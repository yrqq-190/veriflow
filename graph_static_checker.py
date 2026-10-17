# -*- coding: utf-8 -*-
"""
VeriFlow: 图结构静态检查器（Baseline）
=====================================
仅基于工作流图结构（节点 / 边 / 字段存在性）做缺陷检测，
不构建状态空间、不分析执行行为。作为论文 §4.2 对比基线之一。

检查项（与 JCPN 可达图分析形成对照，体现形式化方法的增益）：
  1. isolated_node     节点无入边且无出边
  2. unreachable_node  从入口（无入边节点）不可达
  3. missing_branch    条件节点缺少 else 分支
  4. abnormal_loop     循环节点无出口（无出边）
  5. broken_message    消息节点无出边（发送后流程无后继）

局限：无法检测"消息已发送但无对应接收节点"（有出边的 unpaired 消息）、
数据依赖约束等语义缺陷 —— 这正是 JCPN 形式化验证的增益所在。
"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple


def _tarjan_scc(succ: Dict[str, List[str]], nodes: List[str]) -> List[List[str]]:
    """Tarjan 强连通分量（迭代栈，避免递归深度问题）。"""
    index, low, onstack = {}, {}, set()
    stack: List[str] = []
    sccs: List[List[str]] = []
    counter = [0]
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(succ.get(root, [])))]
        index[root] = low[root] = counter[0]; counter[0] += 1
        stack.append(root); onstack.add(root)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]; counter[0] += 1
                    stack.append(w); onstack.add(w)
                    work.append((w, iter(succ.get(w, []))))
                    advanced = True
                    break
                elif w in onstack:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop(); onstack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                sccs.append(comp)
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
    return sccs


def graph_based_static_checker(workflow: dict) -> set:
    """
    结构-only 检查。返回缺陷集合，元素为 (defect_type, node_id)。
    不修改输入工作流。
    """
    defects: Set[Tuple[str, str]] = set()
    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", [])

    # 节点全集 = 顶层节点 ∪ 边引用的端点（嵌套分支节点可能被边直接引用）
    top_ids: Set[str] = {n["id"] for n in nodes}
    edge_ids: Set[str] = {e.get("from") for e in edges} | {e.get("to") for e in edges}
    node_ids: Set[str] = top_ids | edge_ids

    in_deg: Dict[str, int] = {nid: 0 for nid in node_ids}
    out_deg: Dict[str, int] = {nid: 0 for nid in node_ids}
    succ: Dict[str, List[str]] = {nid: [] for nid in node_ids}
    for e in edges:
        u, v = e.get("from"), e.get("to")
        if u in out_deg and v in in_deg:
            out_deg[u] += 1
            in_deg[v] += 1
            succ[u].append(v)

    # 平台适配层豁免：独立备用入口 / 非 main 连线节点（n8n 工具·模型连线等）
    alt = {n["id"] for n in nodes if n.get("is_alt_entry")}

    # 1. 孤立节点（无入边且无出边）
    for nid in node_ids:
        if nid in alt:
            continue
        if in_deg[nid] == 0 and out_deg[nid] == 0:
            defects.add(("isolated_node", nid))

    # 2. 不可达节点：从"主入口"（覆盖节点最多的入口）出发 BFS
    #    不能从所有入度=0 节点出发——注入 unreachable_node 后被断开的节点
    #    也会变成入度=0，若把它当合法入口就会漏报（审稿意见 #2）。
    entries = [n for n in node_ids
               if n not in alt and in_deg[n] == 0 and out_deg[n] != 0]

    def _bfs(start):
        seen = set()
        st = [start]
        while st:
            cur = st.pop()
            if cur in seen:
                continue
            seen.add(cur)
            st.extend(succ.get(cur, []))
        return seen

    if entries:
        best_entry = entries[0]
        best_count = -1
        for e in entries:
            cnt = len(_bfs(e))
            if cnt > best_count:
                best_count = cnt
                best_entry = e
        reachable = _bfs(best_entry)
    else:
        reachable = set()
    for nid in node_ids:
        if nid in alt:
            continue
        if nid not in reachable:
            defects.add(("unreachable_node", nid))

    # 3. 缺失分支（if 无 else 键 且 无扁平 false 分支边 —— 平台适配器语义）
    for n in nodes:
        if n.get("type") == "if":
            has_false_edge = any(e.get("from") == n["id"] and e.get("branch") == "false"
                                 for e in edges)
            if "else" not in n and not has_false_edge:
                defects.add(("missing_branch", n["id"]))

    # 4. 无出口循环
    # 4a. 显式声明：while 节点未标注 exit（节点级控制流声明）
    for n in nodes:
        if n.get("type") == "while" and n.get("exit") is not True:
            defects.add(("abnormal_loop", n["id"]))
    # 4b. SCC 分析：存在环且该强连通分量无出边到外部 → 非终止循环风险
    ordered = list(node_ids)
    for comp in _tarjan_scc(succ, ordered):
        self_loop = len(comp) == 1 and comp[0] in succ.get(comp[0], [])
        is_cycle = len(comp) > 1 or self_loop
        if not is_cycle:
            continue
        compset = set(comp)
        has_exit = any(w not in compset for v in comp for w in succ.get(v, []))
        if not has_exit:
            defects.add(("abnormal_loop", comp[0]))

    # 5. 消息配对检查（加强版，不再是稻草人）：
    #    a) message 节点无出边（发送后流程终止）
    #    b) message 节点显式标注 pairing=unpaired（发送后无对应接收）
    #    c) n8n 配对模式：发送端 message 若声明了 receiver 但图中找不到对应接收节点
    #    公平性修正：send_only/out（向用户回复）合法，不报。
    #    局限：需要可达图才能判断"发送端是否在接收端的所有前驱路径上"，
    #    纯结构检查只能做局部配对，跨分支/异步消息仍可能漏报 —— 这是 JCPN 的增益。
    for n in nodes:
        if n.get("type") != "message":
            continue
        nid = n["id"]
        # send_only/out 是终端回复，合法结束
        if n.get("pairing") == "send_only" and n.get("direction") == "out":
            continue
        # a) 无出边
        if out_deg[nid] == 0:
            defects.add(("broken_message", nid))
            continue
        # b) 显式 unpaired
        if n.get("pairing") == "unpaired":
            defects.add(("broken_message", nid))
            continue
        # c) 声明了 receiver 但图中无对应接收节点（按 receiver id 匹配）
        receiver = n.get("receiver")
        if receiver and receiver not in node_ids:
            defects.add(("broken_message", nid))

    return defects


# ---------------------------------------------------------------------------
# JSON Schema 基线（字段 / 引用 / 类型约束）
# ---------------------------------------------------------------------------

# 标准化中间表示采用扁平边模式（分支/循环体由 edges.branch 表达），
# 故 B1 只要求节点自身的最小字段；分支完整性、循环出口等行为结构不在此检查。
REQUIRED_FIELDS: Dict[str, List[str]] = {
    "task":    ["id", "type", "name"],
    "message": ["id", "type", "name", "sender"],
    "if":      ["id", "type", "name"],
    "while":   ["id", "type", "name"],
}
VALID_TYPES = {"task", "message", "if", "while"}


def json_schema_checker(workflow: dict) -> set:
    """
    纯 JSON Schema 基线（B1）：仅必填字段、节点类型枚举、ID 唯一性、边引用
    完整性等语法/字段约束。不含分支完整性、while 出口、可达性、消息配对等行为
    约束（属 B2 / JCPN）。注入缺陷保持 JSON 语法有效，故该基线对语义缺陷为 FN。
    """
    defects: Set[Tuple[str, str]] = set()
    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", [])

    def _walk(node_list):
        for n in node_list:
            yield n
            for key in ("then", "else", "body"):
                child = n.get(key)
                if isinstance(child, dict):
                    yield from _walk([child])
                elif isinstance(child, list):
                    yield from _walk(child)

    seen: Set[str] = set()
    for n in _walk(nodes):
        nid = n.get("id")
        ntype = n.get("type")
        if nid is None:
            defects.add(("schema_missing_id", nid or ""))
            continue
        if nid in seen:
            defects.add(("schema_duplicate_id", nid))
        seen.add(nid)

        if ntype not in VALID_TYPES:
            defects.add(("schema_bad_type", nid))
            continue
        for f in REQUIRED_FIELDS.get(ntype, []):
            if f not in n:
                defects.add(("schema_missing_field", f"{nid}.{f}"))

        # 纯 JSON Schema 基线只做字段/枚举/引用约束；
        # if 分支完整性、while 出口等行为约束属于 B2 图检查器 / JCPN，不在此检查。

    for e in edges:
        if e.get("from") not in seen:
            defects.add(("schema_dangling_edge", e.get("from", "")))
        if e.get("to") not in seen:
            defects.add(("schema_dangling_edge", e.get("to", "")))

    return defects
