# -*- coding: utf-8 -*-
"""
VeriFlow: 形式化验证模块（对应论文 §3.5）
==========================================
基于 JCPN 可达图（Definition 3-5/3-6）检测：
  1. 不可达活动（unreachable node）       —— 某源节点的全部变迁从未触发
  2. 意外死锁（unexpected deadlock）      —— 无后继状态且不含完成库所 P_f 的 token
  3. 非终止风险（non-termination risk）   —— 可达 SCC 中无路径到达完成状态
  4. 消息交互断裂（broken message）       —— n8n 消息未配对（适配器语义，§3.3.2）

抽象约定（对应论文 §3.3.4 的有限抽象）：
  - Θ_cond = {true, false}：决策点（if.t_cond / while.p_judge）触发时对
    两个条件值非确定性分裂；缺失的分支产生无后继状态（死锁）。
  - 循环出口依赖数据更新（data_dependent）时，抽象下 false 分支不可达，
    验证器保守报告 non-termination 风险（论文明确此抽象可能过近似）。
异常经 provenance 映射 μ 回溯到源 JSON 节点（localize_defect）。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

from jcpn_builder import JCPNModel, TRUE_GUARD, FALSE_GUARD, localize_defect, transform
from preprocess import preprocess


# ===========================================================================
# 1. 可达图构建
# ===========================================================================

class ReachabilityGraph:
    """RG = (M, →)。状态为规范化标识（place → token 数）。"""

    def __init__(self) -> None:
        self.state_keys: List[Tuple[Tuple[str, int], ...]] = []
        self.state_id: Dict[Tuple[Tuple[str, int], ...], int] = {}
        self.succ: List[List[Tuple[int, str]]] = []   # 状态 → [(后继, 标签)]
        self.parent: List[Tuple[Optional[int], str]] = []  # (父状态, 触发变迁)
        self.fired: Set[str] = set()                 # 可达图中触发过的变迁

    @staticmethod
    def canon(mark: Dict[str, int]) -> Tuple[Tuple[str, int], ...]:
        return tuple(sorted((p, n) for p, n in mark.items() if n > 0))

    def add_state(self, key) -> int:
        if key not in self.state_id:
            sid = len(self.state_keys)
            self.state_keys.append(key)
            self.state_id[key] = sid
            self.succ.append([])
            self.parent.append((None, ""))
        return self.state_id[key]

    def add_edge(self, src: int, dst: int, label: str) -> None:
        self.succ[src].append((dst, label))


def build_reachability_graph(model: JCPNModel,
                             max_states: int = 100_000) -> ReachabilityGraph:
    """
    从 M₀ 出发构建可达图。
    转移类型：
      a) 普通变迁：输入库所均有 token → 消费输入、产出输出；
      b) 决策变迁（if.t_cond ∈ _split_transitions）：按输出弧条件标记
         c=true / c=false 分裂；缺失的分支 → 死锁后继；
      c) 决策库所（while.p_judge ∈ _cond_places）：按输出变迁守卫
         [c=true] / [c=false] 分裂；缺失或 data_dependent 的分支 → 死锁后继。
    """
    rg = ReachabilityGraph()
    P, T, A, X = model.P, model.T, model.A, model.X
    G = model.G

    # 预计算：普通变迁输入/输出库所；决策弧
    t_inputs: Dict[str, Set[str]] = {t: set() for t in T}
    t_outputs: Dict[str, Set[str]] = {t: set() for t in T}
    cond_arcs: Dict[str, Dict[str, str]] = {t: {} for t in T}  # t → {条件: 目标place}
    for (u, v) in A:
        if u in P and v in T:
            t_inputs[v].add(u)
        elif u in T and v in P:
            t_outputs[u].add(v)
    for (t, p), expr in X.items():
        if expr in ("c=true", "c=false"):
            cond_arcs.setdefault(t, {})[expr] = p

    # data_dependent 判定辅助：cond place 归属哪个 while 子网（μ 遍历，
    # 避免合并库所的反向索引歧义——如回边合并后的 p_judge）
    def _data_dependent(p: str) -> bool:
        for _src, entry in model.mu.items():
            if entry["kind"] == "while" and p in entry["places"]:
                return bool(entry["source_node"].get("data_dependent"))
        return False

    # 初始状态
    mark0: Dict[str, int] = {}
    for p, toks in model.M0.items():
        if toks:
            mark0[p] = mark0.get(p, 0) + 1
    start = rg.add_state(rg.canon(mark0))

    # BFS
    queue = [start]
    visited = [False] * 0
    visited = [False] * (max_states + 1)
    while queue:
        sid = queue.pop(0)
        if visited[sid]:
            continue
        visited[sid] = True
        if len(rg.state_keys) > max_states:
            break
        mark = dict(rg.state_keys[sid])
        successors = []

        # a) 普通变迁 + b) 决策变迁
        for t in T:
            if t in model._split_transitions:
                # 决策变迁：枚举两个条件值
                if not all(mark.get(p, 0) >= 1 for p in t_inputs[t]):
                    continue
                for cond, label in (("c=true", "true"), ("c=false", "false")):
                    nxt = dict(mark)
                    for p in t_inputs[t]:
                        nxt[p] -= 1
                    target = cond_arcs[t].get(cond)
                    if target is not None:
                        nxt[target] = nxt.get(target, 0) + 1
                        rg.fired.add(t)
                        successors.append((rg.add_state(rg.canon(nxt)), t))
                    else:
                        # 分支缺失 → 死锁后继（无使能变迁）
                        rg.fired.add(t)
                        successors.append((rg.add_state(rg.canon(nxt)), t))
            else:
                # 带条件守卫的变迁（[c=true]/[c=false]）只由决策库所分裂处理，
                # 普通枚举跳过，避免绕过守卫直接触发（如 t_loop / t_exit）。
                if G.get(t, "true") != "true":
                    continue
                if not all(mark.get(p, 0) >= 1 for p in t_inputs[t]):
                    continue
                nxt = dict(mark)
                for p in t_inputs[t]:
                    nxt[p] -= 1
                for p in t_outputs[t]:
                    nxt[p] = nxt.get(p, 0) + 1
                rg.fired.add(t)
                successors.append((rg.add_state(rg.canon(nxt)), t))

        # c) 决策库所（while.p_judge）
        for p in model._cond_places:
            if mark.get(p, 0) < 1:
                continue
            for guard, label in ((TRUE_GUARD, "true"), (FALSE_GUARD, "false")):
                nxt = dict(mark)
                nxt[p] -= 1
                # 找到该库所输出且守卫匹配的变迁
                cand = [t for t in T
                        if (p, t) in A and G.get(t) == guard]
                if cand and not (label == "false" and _data_dependent(p)):
                    t_sel = cand[0]
                    for po in t_outputs[t_sel]:
                        nxt[po] = nxt.get(po, 0) + 1
                    rg.fired.add(t_sel)
                    successors.append((rg.add_state(rg.canon(nxt)), t_sel))
                else:
                    # 无 exit 变迁 或 抽象下 false 分支不可达 → 死锁后继
                    successors.append((rg.add_state(rg.canon(nxt)), f"split[{label}]"))

        # 去重后继并记录
        seen = set()
        for (d, lbl) in successors:
            if d not in seen:
                seen.add(d)
                rg.add_edge(sid, d, lbl)
                if rg.parent[d][0] is None and d != start:
                    rg.parent[d] = (sid, lbl)
            if not visited[d] and d not in queue:
                queue.append(d)

    return rg


# ===========================================================================
# 2. 缺陷检测
# ===========================================================================

def _marking_to_sources(model: JCPNModel, mark_key) -> List[str]:
    """标记中的库所经 μ 反向回溯到源节点 id（用于定位）。"""
    srcs = []
    for (p, n) in mark_key:
        if n <= 0:
            continue
        s = model.reverse_lookup(p)
        if s and s not in srcs:
            srcs.append(s)
    return srcs


def _path_labels(rg: ReachabilityGraph, sid: int) -> List[str]:
    """从初始状态到 sid 的触发路径标签。"""
    labels = []
    cur = sid
    while rg.parent[cur][0] is not None:
        labels.append(rg.parent[cur][1])
        cur = rg.parent[cur][0]
    labels.reverse()
    return labels


def detect_unreachable_nodes(rg: ReachabilityGraph,
                             model: JCPNModel) -> List[Dict[str, Any]]:
    """
    某源节点的全部 JCPN 变迁在可达图中从未触发 → 不可达活动
    （覆盖 isolated node / 无入边路径缺陷）。
    """
    findings = []
    for src, entry in model.mu.items():
        if entry["kind"] not in ("task", "message", "if", "while"):
            continue
        # 平台适配层豁免：独立备用入口分支（n8n 附加 manual trigger 等）不在
        # 主流程分析范围内，不构成不可达缺陷。
        if entry.get("source_node", {}).get("is_alt_entry"):
            continue
        trans = set(entry["transitions"])
        if not trans:
            continue
        if not (trans & rg.fired):
            findings.append({
                "type": "unreachable_node",
                "source_id": src,
                "kind": entry["kind"],
                "detail": f"activities {sorted(trans)} never fired in the reachable state space",
            })
    return findings


def detect_deadlocks(rg: ReachabilityGraph,
                     model: JCPNModel) -> List[Dict[str, Any]]:
    """
    无后继状态 且 标识不含任何完成库所 P_f 的 token → 意外死锁
    （Definition 3-6；正常终止因 P_f token 而豁免）。
    """
    findings = []
    for sid, key in enumerate(rg.state_keys):
        if rg.succ[sid]:
            continue
        mark = dict(key)
        if any(mark.get(p, 0) >= 1 for p in model.P_f):
            continue                      # 正常完成
        sources = _marking_to_sources(model, key)
        findings.append({
            "type": "unexpected_deadlock",
            "state": key,
            "sources": sources,
            "path": _path_labels(rg, sid),
            "detail": f"marking {key} has no enabled transition and no completion token",
        })
    return findings


def detect_non_termination(rg: ReachabilityGraph,
                           model: JCPNModel) -> List[Dict[str, Any]]:
    """
    Tarjan SCC 分析：可达 SCC 含环（|SCC|>1 或自环）且从其中任何状态
    都无法到达「含 P_f token 的完成状态」→ 报告为潜在非终止风险
    （论文 §3.3.4：循环风险而非确定结论）。
    """
    n = len(rg.state_keys)
    if n == 0:
        return []
    index = 0
    indices = [-1] * n
    lowlink = [0] * n
    on_stack = [False] * n
    stack: List[int] = []
    sccs: List[List[int]] = []

    def strongconnect(v: int) -> None:
        nonlocal index
        indices[v] = lowlink[v] = index
        index += 1
        stack.append(v)
        on_stack[v] = True
        for (w, _lbl) in rg.succ[v]:
            if indices[w] == -1:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif on_stack[w]:
                lowlink[v] = min(lowlink[v], indices[w])
        if lowlink[v] == indices[v]:
            comp = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                comp.append(w)
                if w == v:
                    break
            sccs.append(comp)

    for v in range(n):
        if indices[v] == -1:
            strongconnect(v)

    # 完成状态集合
    complete = [sid for sid, key in enumerate(rg.state_keys)
                if any(dict(key).get(p, 0) >= 1 for p in model.P_f)]

    # SCC 压缩图 + 反向可达标记（哪些 SCC 能到达完成状态）
    scc_id = [-1] * n
    for i, comp in enumerate(sccs):
        for v in comp:
            scc_id[v] = i
    can_finish = [False] * len(sccs)
    for c in complete:
        can_finish[scc_id[c]] = True
    changed = True
    while changed:
        changed = False
        for i, comp in enumerate(sccs):
            if can_finish[i]:
                continue
            for v in comp:
                for (w, _lbl) in rg.succ[v]:
                    if can_finish[scc_id[w]]:
                        can_finish[i] = True
                        changed = True
                        break
                if can_finish[i]:
                    break

    findings = []
    for i, comp in enumerate(sccs):
        is_cyclic = len(comp) > 1 or any(
            (w == v) for v in comp for (w, _lbl) in rg.succ[v])
        if not is_cyclic or can_finish[i]:
            continue
        sources = []
        for v in comp:
            for s in _marking_to_sources(model, rg.state_keys[v]):
                if s not in sources:
                    sources.append(s)
        findings.append({
            "type": "non_termination_risk",
            "scc_size": len(comp),
            "sources": sources,
            "detail": "reachable cycle with no path to a completion marking "
                      "(P_f token); reported as a risk under the current abstraction",
        })
    return findings


def detect_broken_message(model: JCPNModel) -> List[Dict[str, Any]]:
    """
    消息适配器语义（§3.3.2）：n8n 消息节点未配对（pairing=unpaired）
    → 只映射 t_send，不合成 t_recv → broken-message 候选。
    Dify/Coze 出站消息（send_only）为平台正常语义，不报。
    """
    findings = []
    for src, entry in model.mu.items():
        if entry["kind"] != "message":
            continue
        sn = entry.get("source_node", {})
        if sn.get("pairing") == "unpaired" and sn.get("platform") == "n8n":
            findings.append({
                "type": "broken_message",
                "source_id": src,
                "kind": "message",
                "detail": "n8n message node has no paired receive: "
                          "t_recv not synthesized (send-only interaction)",
            })
    return findings


def detect_variable_constraint(workflow: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Θ_data 颜色集一致性检查（§3.2.3 / Definition 3-3 的 C:P→Θ 颜色分配）：
    沿控制流边，上游任务输出的数据颜色（output_type）必须与下游任务声明的
    输入颜色（input_type）匹配；不匹配即变量约束缺陷（variable-constraint error）。
    仅在节点显式标注类型时检查（平台未标注则不臆测）；当前为轻量类型检查，
    不建模完整的数据域传播与变量作用域。
    """
    findings = []
    by_id = {n.get("id"): n for n in workflow.get("nodes", [])}
    for e in workflow.get("edges", []):
        u, v = e.get("from"), e.get("to")
        nu, nv = by_id.get(u), by_id.get(v)
        if not nu or not nv:
            continue
        ot = nu.get("output_type")
        it = nv.get("input_type")
        if ot and it and ot != it:
            findings.append({
                "type": "variable_constraint",
                "source_id": v,
                "kind": "task",
                "detail": f"data color mismatch: '{u}' produces {ot} "
                          f"while '{v}' requires {it}",
            })
    return findings


# ===========================================================================
# 3. 验证主入口
# ===========================================================================

def verify_workflow(raw_workflow: Dict[str, Any],
                    max_states: int = 100_000) -> Dict[str, Any]:
    """
    完整验证流水线：preprocess → transform → 可达图 → 四类缺陷检测。
    返回 dict：{defective, defects, model, rg, stats}
    """
    t0 = time.perf_counter()

    norm = preprocess(raw_workflow)
    workflow = norm["workflow"]

    model = transform(workflow)
    rg = build_reachability_graph(model, max_states=max_states)

    findings = (detect_unreachable_nodes(rg, model)
                + detect_deadlocks(rg, model)
                + detect_non_termination(rg, model)
                + detect_broken_message(model)
                + detect_variable_constraint(workflow))

    elapsed = time.perf_counter() - t0
    stats = {
        "preprocess_errors": len(norm["errors"]),
        "anomalies": norm["anomalies"],
        "|P|": len(model.P),
        "|T|": len(model.T),
        "|A|": len(model.A),
        "|RG|": len(rg.state_keys),
        "fired_transitions": len(rg.fired),
        "time_s": round(elapsed, 4),
    }
    return {
        "defective": bool(findings),
        "defects": findings,
        "model": model,
        "rg": rg,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# CLI 自检
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys
    cid = sys.argv[1] if len(sys.argv) > 1 else "wf_001"
    wf = json.load(open(f"test_cases/{cid}.json", encoding="utf-8"))
    res = verify_workflow(wf)
    print(f"[{cid}] defective={res['defective']} stats={res['stats']}")
    for d in res["defects"]:
        print("  -", d["type"], "| src:", d.get("source_id") or d.get("sources"),
              "|", d["detail"][:80])
