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

    # 2. 不可达节点（从非孤立的无入边入口出发）
    entries = [n for n in node_ids
               if n not in alt and in_deg[n] == 0 and out_deg[n] != 0]
    reachable: Set[str] = set()
    stack = list(entries)
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        stack.extend(succ.get(cur, []))
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

    # 4. 无出口循环（while 无出边）
    for n in nodes:
        if n.get("type") == "while" and out_deg[n["id"]] == 0:
            defects.add(("abnormal_loop", n["id"]))

    # 5. 消息断裂（消息节点无出边：发送后流程无后继）
    for n in nodes:
        if n.get("type") == "message" and out_deg[n["id"]] == 0:
            defects.add(("broken_message", n["id"]))

    return defects


# ---------------------------------------------------------------------------
# JSON Schema 基线（字段 / 引用 / 类型约束）
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: Dict[str, List[str]] = {
    "task":    ["id", "type", "name"],
    "message": ["id", "type", "name", "sender"],
    "if":      ["id", "type", "condition", "then"],
    "while":   ["id", "type", "condition", "body"],
}
VALID_TYPES = {"task", "message", "if", "while"}


def json_schema_checker(workflow: dict) -> set:
    """
    JSON Schema 风格验证：必填字段、节点类型枚举、ID 唯一性、边引用完整性，
    以及平台 schema 级约束：if 必须声明 else 分支、while 必须声明有效出口。
    递归覆盖嵌套节点（then/else/body）。缺陷注入的用例保持 JSON 语法有效，
    因此该基线只捕获字段层面的缺口。
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

        # 平台 schema 级约束（字段完整性，非执行语义）
        if ntype == "if" and "else" not in n:
            defects.add(("schema_missing_else", nid))
        if ntype == "while" and not (n.get("exit") is True):
            defects.add(("schema_missing_exit", nid))

    for e in edges:
        if e.get("from") not in seen:
            defects.add(("schema_dangling_edge", e.get("from", "")))
        if e.get("to") not in seen:
            defects.add(("schema_dangling_edge", e.get("to", "")))

    return defects
