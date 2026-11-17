# -*- coding: utf-8 -*-
"""
VeriFlow: 形式化验证模块（对应论文 §4.4 / Definition 4-4 ~ 4-6）
=================================================================
在颜色化 JCPN 的可达图上判定：

  完成（proper completion）  终止标识中**全部** token 位于 P_f
  意外死锁                   终止标识中仍有 P_f 之外的残留 token
  不可达活动                 源节点对应的变迁在整张可达图中从未触发
  非终止风险                 可达强连通分量无路径通向完成标识
  消息交互断裂               终止标识中残留未被消费的消息 token
  分支缺失                   终止标识中残留带条件颜色的 token

语义要点（与初版的差别，均可在可达图上复核）：
  * 标识是「库所 → 颜色多重集」，canon 保留颜色，`(M, t, M')` 为带标签的发生关系，
    同一对状态经不同变迁到达不会被合并；
  * 使能取 CPN 绑定语义：为每条输入弧选一个满足弧表达式颜色的 token，
    守卫在绑定上求值；`[c = true]` 一类守卫在绑定 token 无颜色取值时是 open
    （两种结果都可能），既不假装判定，也不阻塞；
  * 截断是一等结果：状态数超限时置 truncated，抑制"无缺陷/不可达"这类
    需要完整状态空间才能成立的结论，并显式输出 analysis_incomplete。
"""

from __future__ import annotations

import time
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from jcpn_builder import (ANY_TYPE, G_COND, G_FALSE, G_OPEN, G_TRUE, JCPNModel,
                          PASS, Color, Expr, data_color, localize_defect,
                          msg_color, transform)
from preprocess import preprocess

Marking = Dict[str, Tuple[Color, ...]]

MAX_BINDINGS = 64          # 单变迁绑定枚举上限，超出则截断该变迁的分支（记入 stats）


# ===========================================================================
# 1. 标识与可达图
# ===========================================================================

def canon(mark: Marking) -> Tuple[Tuple[str, Tuple[Color, ...]], ...]:
    """规范化标识：颜色参与键，token 顺序按颜色文本排序。"""
    items = []
    for p in sorted(mark):
        toks = mark[p]
        if toks:
            items.append((p, tuple(sorted(toks, key=lambda c: c.text()))))
    return tuple(items)


def marking_from_key(key) -> Marking:
    return {p: list(toks) for p, toks in key}


def _place_of(key) -> Dict[str, Tuple[Color, ...]]:
    return {p: toks for p, toks in key}


class ReachabilityGraph:
    """RG = (M, →)，→ ⊆ M × T × M 为带标签的发生关系。"""

    def __init__(self) -> None:
        self.state_keys: List[Tuple[Tuple[str, Tuple[Color, ...]], ...]] = []
        self.state_id: Dict[Any, int] = {}
        self.succ: List[List[Tuple[int, str]]] = []
        self.parent: List[Tuple[Optional[int], str]] = []
        self.fired: Set[str] = set()
        self.truncated: bool = False
        self.open_guard_firings: int = 0
        self.binding_capped: int = 0

    def add_state(self, key) -> int:
        sid = self.state_id.get(key)
        if sid is None:
            sid = len(self.state_keys)
            self.state_keys.append(key)
            self.state_id[key] = sid
            self.succ.append([])
            self.parent.append((None, ""))
        return sid

    def add_edge(self, src: int, dst: int, label: str) -> bool:
        for (d, lbl) in self.succ[src]:
            if d == dst and lbl == label:
                return False
        self.succ[src].append((dst, label))
        return True


# ===========================================================================
# 2. 变迁的输入 / 输出
# ===========================================================================

def _transition_io(model: JCPNModel):
    tin: Dict[str, List[Tuple[str, Expr]]] = {t: [] for t in model.T}
    tout: Dict[str, List[Tuple[str, Expr]]] = {t: [] for t in model.T}
    for (u, v), exprs in model.arcs.items():
        if u in model.P and v in model.T:
            for e in exprs:
                if e.op == "consume":
                    tin[v].append((u, e))
        elif u in model.T and v in model.P:
            for e in exprs:
                if e.op == "produce":
                    tout[u].append((v, e))
    return tin, tout


def _compatible(expr: Expr, color: Color) -> bool:
    if expr.kind != color.kind:
        return False
    if color.kind == "msg":
        return expr.arg == color.mid
    if expr.arg == ANY_TYPE or color.dtype == ANY_TYPE:
        return True
    return expr.arg == color.dtype


def _bindings(mark: Marking, arcs: List[Tuple[str, Expr]]) -> List[List[Color]]:
    """为输入弧枚举 token 绑定。"""
    result: List[List[Color]] = []
    used: Dict[str, Set[int]] = {}

    def walk(i: int, acc: List[Color]) -> None:
        if len(result) >= MAX_BINDINGS:
            return
        if i == len(arcs):
            result.append(list(acc))
            return
        p, expr = arcs[i]
        toks = mark.get(p, ())
        taken = used.setdefault(p, set())
        for idx, c in enumerate(toks):
            if idx in taken:
                continue
            if not _compatible(expr, c):
                continue
            taken.add(idx)
            acc.append(c)
            walk(i + 1, acc)
            acc.pop()
            taken.discard(idx)

    walk(0, [])
    return result


def _guard_ok(spec: Tuple[str, Any], bound: Sequence[Color]) -> Tuple[bool, bool]:
    """返回 (是否使能, 是否为开放判定)。"""
    kind, val = spec
    if kind == G_TRUE:
        return True, False
    if kind == G_FALSE:
        return False, False
    if kind == G_COND:
        vals = [c.cond for c in bound if c.kind == "data" and c.cond is not None]
        if not vals:
            return True, True
        if any(v == val for v in vals):
            return True, False
        return False, False
    if kind == G_OPEN:
        return True, True
    return False, False


def _produce(expr: Expr, bound: Sequence[Color]) -> Color:
    if expr.kind == "msg":
        return msg_color(expr.arg)

    if expr.arg == PASS:
        dtype = next((c.dtype for c in bound if c.kind == "data"), ANY_TYPE)
    else:
        dtype = expr.arg
    return data_color(dtype, expr.cond)


def _fire(mark: Marking, tin: List[Tuple[str, Expr]],
          tout: List[Tuple[str, Expr]], bound: List[Color]) -> Marking:
    nxt: Dict[str, List[Color]] = {p: list(t) for p, t in mark.items()}
    for (p, _e), c in zip(tin, bound):
        bucket = nxt.get(p)
        if bucket:
            for k, x in enumerate(bucket):
                if x is c or x == c:
                    bucket.pop(k)
                    break
    for (p, e) in tout:
        nxt.setdefault(p, []).append(_produce(e, bound))
    return {p: tuple(sorted(v, key=lambda c: c.text())) for p, v in nxt.items() if v}


def build_reachability_graph(model: JCPNModel,
                             max_states: int = 100_000) -> ReachabilityGraph:
    rg = ReachabilityGraph()
    tin, tout = _transition_io(model)

    mark0: Dict[str, List[Color]] = {}
    for p, toks in model.M0.items():
        for c in (toks or ()):
            mark0.setdefault(p, []).append(c)
    start = rg.add_state(canon({p: tuple(v) for p, v in mark0.items()}))

    queue: List[int] = [start]
    head = 0
    processed: Set[int] = set()

    while head < len(queue):
        sid = queue[head]
        head += 1
        if sid in processed:
            continue
        if len(rg.state_keys) >= max_states:
            rg.truncated = True
            break
        processed.add(sid)
        mark = marking_from_key(rg.state_keys[sid])

        successors: List[Tuple[int, str]] = []
        for t in model.T:
            arcs_in = tin.get(t, [])
            if any(mark.get(p, ()) == () for (p, _e) in arcs_in):
                continue
            binds = _bindings(mark, arcs_in)
            if len(binds) >= MAX_BINDINGS:
                rg.binding_capped += 1
            spec = model.guard_of.get(t, (G_TRUE, None))
            for bound in binds:
                ok, actual_open = _guard_ok(spec, bound)
                if not ok:
                    continue
                if actual_open:
                    rg.open_guard_firings += 1
                nxt = _fire(mark, arcs_in, tout.get(t, []), bound)
                rg.fired.add(t)
                sid_next = rg.add_state(canon(nxt))
                successors.append((sid_next, t))

        seen: Set[Tuple[int, str]] = set()
        for (d, lbl) in successors:
            if (d, lbl) in seen:
                continue
            seen.add((d, lbl))
            rg.add_edge(sid, d, lbl)
            if d != start and rg.parent[d][0] is None:
                rg.parent[d] = (sid, lbl)
            if d not in processed and d not in queue:
                queue.append(d)

    return rg


# ===========================================================================
# 3. 终止标识分析
# ===========================================================================

def _path_labels(rg: ReachabilityGraph, sid: int) -> List[str]:
    labels: List[str] = []
    cur = sid
    guard = 0
    while rg.parent[cur][0] is not None and guard < 10_000:
        labels.append(rg.parent[cur][1])
        cur = rg.parent[cur][0]
        guard += 1
    labels.reverse()
    return labels


def _residual(key, model: JCPNModel) -> List[Tuple[str, Color]]:
    """终止标识中位于 P_f 之外的 token。"""
    out = []
    for p, toks in key:
        if p in model.P_f:
            continue
        for c in toks:
            out.append((p, c))
    return out


def _classify_residual(residual: List[Tuple[str, Color]]) -> str:
    """按残留 token 的颜色族给出缺陷类别。"""
    if any(c.kind == "msg" for _p, c in residual):
        return "broken_message"
    if any(c.kind == "data" and c.cond is not None for _p, c in residual):
        return "missing_branch"
    return "unexpected_deadlock"


def _residual_sources(residual: List[Tuple[str, Color]],
                      model: JCPNModel) -> List[str]:
    srcs: List[str] = []
    for p, _c in residual:
        s = model.reverse_lookup(p)
        if s and s not in srcs:
            srcs.append(s)
    return srcs


def analyze_terminals(rg: ReachabilityGraph,
                      model: JCPNModel) -> Tuple[List[Dict[str, Any]], int, int]:
    """返回 (findings, 完成标识数, 终止标识数)。

    同一个缺陷会在多个终止标识里重现（例如分支 token 在循环中反复残留）。
    一个源节点的一个缺陷只报一条，附见证状态数与若干代表性路径。
    """
    agg: Dict[Tuple[str, str], Dict[str, Any]] = {}
    completed = 0
    terminals = 0

    for sid, key in enumerate(rg.state_keys):
        if rg.succ[sid]:
            continue
        terminals += 1
        residual = _residual(key, model)
        if not residual:
            completed += 1
            continue

        dtype = _classify_residual(residual)
        sources = _residual_sources(residual, model)
        src_key = sources[0] if sources else "<unmapped>"
        entry = agg.get((dtype, src_key))
        if entry is None:
            detail = {
                "broken_message": "terminal marking still holds an unconsumed message token "
                                  "(send side without a receive side)",
                "missing_branch": "terminal marking still holds a branch token whose target "
                                  "node does not exist",
                "unexpected_deadlock": "terminal marking holds a token outside the completion "
                                       "set P_f and no transition is enabled",
            }[dtype]
            entry = {
                "type": dtype,
                "source_id": sources[0] if sources else None,
                "sources": sources,
                "kind": "message" if dtype == "broken_message" else "task",
                "residual": [{"place": p_, "color": c.text()} for p_, c in residual],
                "path": _path_labels(rg, sid),
                "detail": detail,
                "witness_states": 0,
                "witness_paths": [],
            }
            agg[(dtype, src_key)] = entry
        entry["witness_states"] += 1
        if len(entry["witness_paths"]) < 3:
            entry["witness_paths"].append(_path_labels(rg, sid))

    return list(agg.values()), completed, terminals


def _static_reachability(model: JCPNModel) -> Tuple[Set[str], Set[str]]:
    """网结构上的可达库所集与可达变迁集（不动点）。

    忽略守卫、颜色与弧多重性，只走 P→T→P 的结构通路。这是真实可达集的上近似：
    判为不可达一定可靠，判为可达只说明结构上有可能。
    """
    reach: Set[str] = {p for p, tokens in model.M0.items() if tokens}
    pre: Dict[str, Set[str]] = {}
    post: Dict[str, Set[str]] = {}
    for (u, v) in model.arcs:
        if u in model.P and v in model.T:
            pre.setdefault(v, set()).add(u)
        elif u in model.T and v in model.P:
            post.setdefault(u, set()).add(v)
    fired: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for t in model.T:
            if t in fired:
                continue
            if all(x in reach for x in pre.get(t, ())):
                fired.add(t)
                changed = True
                for p in post.get(t, ()):
                    if p not in reach:
                        reach.add(p)
    return reach, fired


def detect_unreachable_nodes(rg: ReachabilityGraph,
                             model: JCPNModel) -> List[Dict[str, Any]]:
    """不可达节点。

    先做结构判定（可靠，与截断无关）：入口库所结构上不可达 ⇒ 该节点永远
    拿不到令牌。只有在可达图完整时，才补充"结构可达但从未触发"的情形，
    并注明 mechanism，避免把"守卫长期阻塞"说成"结构不可达"。
    """
    findings = []
    reach, structurally_firable = _static_reachability(model)
    for src, entry in model.mu.items():
        if entry["kind"] not in ("task", "message", "if", "while"):
            continue
        if entry.get("source_node", {}).get("is_alt_entry"):
            continue
        trans = set(entry["transitions"])
        if not trans:
            continue
        structurally_ok = bool(trans & structurally_firable)
        if not structurally_ok:
            findings.append({
                "type": "unreachable_node",
                "source_id": src,
                "kind": entry["kind"],
                "mechanism": "no_structural_path",
                "detail": (f"activities {sorted(trans)} have no structural path "
                           f"from the initial marking"),
            })
            continue
        if rg.truncated:
            continue          # 未探索完，不能断言"从未触发"
        if not (trans & rg.fired):
            findings.append({
                "type": "unreachable_node",
                "source_id": src,
                "kind": entry["kind"],
                "mechanism": "never_fired_in_complete_rg",
                "detail": (f"activities {sorted(trans)} never fired although the "
                           f"complete reachability graph was explored"),
            })
    return findings


def detect_non_termination(rg: ReachabilityGraph,
                           model: JCPNModel) -> List[Dict[str, Any]]:
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

    complete = [sid for sid, key in enumerate(rg.state_keys)
                if not _residual(key, model)]

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

    findings: List[Dict[str, Any]] = []
    by_src: Dict[str, Dict[str, Any]] = {}
    for i, comp in enumerate(sccs):
        is_cyclic = len(comp) > 1 or any(
            (w == v) for v in comp for (w, _lbl) in rg.succ[v])
        if not is_cyclic or can_finish[i]:
            continue
        # 定位优先取「循环结构本身」：环上的变迁若属于某个 while/if 子网，用它做源；
        # 否则退化为该 SCC 内被 token 占据的库所所属节点。
        trans_in_comp = {lbl for v in comp for (_w, lbl) in rg.succ[v]}
        sources: List[str] = []
        for src, entry in model.mu.items():
            if entry["kind"] == "while" and (set(entry["transitions"]) & trans_in_comp):
                sources.append(src)
        if not sources:
            for v in comp:
                for s in _residual_sources(_residual(rg.state_keys[v], model), model):
                    if s not in sources:
                        sources.append(s)
        if not sources:
            for v in comp:
                for p, _toks in rg.state_keys[v]:
                    s = model.reverse_lookup(p)
                    if s and s not in sources:
                        sources.append(s)
        key = sources[0] if sources else "<unmapped>"
        if key in by_src:
            by_src[key]["scc_count"] += 1
            by_src[key]["states"] += len(comp)
            continue
        entry = {
            "type": "non_termination_risk",
            "scc_size": len(comp),
            "scc_count": 1,
            "states": len(comp),
            "sources": sources,
            "source_id": sources[0] if sources else None,
            "detail": "reachable cycle with no path to a completion marking "
                      "(all tokens inside P_f); reported as a risk under the "
                      "current abstraction",
        }
        by_src[key] = entry
        findings.append(entry)
    return findings


def detect_variable_constraint(workflow: Dict[str, Any]) -> List[Dict[str, Any]]:
    """静态类型规则：上游 output_type 与下游 input_type 不一致。

    这不是可达图结论（这条弧上没有类型冲突也会被报），因此在文档与评估中
    单列为 static rule，不与状态空间结论混算。
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
                "mechanism": "static_type_rule",
                "detail": f"data color mismatch: '{u}' produces {ot} "
                          f"while '{v}' requires {it}",
            })
    return findings


def detect_typed_consumption_stall(model: JCPNModel) -> List[Dict[str, Any]]:
    """声明了输入类型、却没有任何生产侧能提供该类型 → 该变迁结构性不可使能。

    只在两侧都显式标注类型时成立；任一侧未标注（any）就不臆测。
    """
    producers: Dict[str, Set[str]] = {}
    for (u, v), exprs in model.arcs.items():
        if u in model.T and v in model.P:
            for e in exprs:
                if e.op == "produce" and e.kind == "data" and e.arg not in (PASS, ANY_TYPE):
                    producers.setdefault(v, set()).add(e.arg)

    findings = []
    tin, _tout = _transition_io(model)
    for t, arcs in tin.items():
        for (p, e) in arcs:
            if e.kind != "data" or e.arg in (PASS, ANY_TYPE):
                continue
            if producers.get(p) and e.arg not in producers[p]:
                src = model.reverse_lookup(t)
                findings.append({
                    "type": "variable_constraint",
                    "source_id": src,
                    "kind": "task",
                    "mechanism": "typed_consumption_stall",
                    "detail": f"transition '{t}' consumes {e.arg} from '{p}' "
                              f"but only {sorted(producers[p])} can be produced there",
                })
    return findings


# ===========================================================================
# 4. 主入口
# ===========================================================================

# ---------------------------------------------------------------------------
# 检测清单：每条性质的形式化依据、判定方式与可靠性边界
# ---------------------------------------------------------------------------
# method="state_space" 的结论依赖完整可达图；一旦截断即降级为未证实，绝不硬报。
# method="static" 的结论只依赖网结构/类型规则，与状态空间规模无关。
CHECKLIST = [
    {
        "id": "P1",
        "title": "option to complete",
        "title_zh": "选项可完成性（不存在无出路的状态）",
        "formal": "WF-net soundness (van der Aalst): 从任一可达标识都能到达完成标识 O",
        "types": ["unexpected_deadlock"],
        "method": "state_space",
        "how": "遍历可达图，找终态标识；终态 ≠ 完成标识即死锁，按 (类型, 源节点) 聚合，附见证路径",
    },
    {
        "id": "P2",
        "title": "proper completion",
        "title_zh": "正确完成性（完成时只有 O 有令牌）",
        "formal": "完成标识 O 之外不得残留 token；残留按颜色族分类",
        "types": ["missing_branch", "broken_message", "unexpected_deadlock"],
        "method": "state_space",
        "how": "终态中剔除完成后仍持有的 token，按条件/消息/数据族归类并回溯源节点",
    },
    {
        "id": "P3",
        "title": "no dead transitions",
        "title_zh": "无死变迁（不存在永远无法执行的节点）",
        "formal": "结构可达性上近似 + 完整可达图的 fired 集",
        "types": ["unreachable_node"],
        "method": "static+state_space",
        "how": "先在 P→T→P 结构图上做不动点（可靠但保守）；可达图完整时再补'结构可达却从未触发'并标 mechanism",
    },
    {
        "id": "P4",
        "title": "termination / no livelock",
        "title_zh": "终止性（不存在必然无限的循环）",
        "formal": "可达图的非平凡 SCC；只在无法离开的循环上成立",
        "types": ["non_termination_risk"],
        "method": "state_space",
        "how": "Tarjan SCC + 出口可达性判定，按 SCC 去重并优先定位到循环节点",
    },
    {
        "id": "P5",
        "title": "branch totality",
        "title_zh": "分支完整性",
        "formal": "条件节点的每个分支恰好有一条后继；未连边分支按平台语义=实例结束",
        "types": ["missing_branch"],
        "method": "static+state_space",
        "how": "n 路分支各自建模为独立决策变迁与分支库所；悬空分支并入 P_f 并记录 implicit_termination",
    },
    {
        "id": "P6",
        "title": "message pairing",
        "title_zh": "消息配对（send/receive 一致）",
        "formal": "每条 send 必须有同 id 的 receive；unpaired 消息 token 残留即断裂",
        "types": ["broken_message"],
        "method": "static+state_space",
        "how": "消息颜色按 message id 配对；paired 走 t_send/t_recv，send_only 走 t_deliver，unpaired 残留",
    },
    {
        "id": "P7",
        "title": "typed data flow",
        "title_zh": "类型化数据流（不消费不兼容的颜色）",
        "formal": "弧表达式声明类型域；any 与任意域兼容，不兼容即阻塞",
        "types": ["variable_constraint", "typed_consumption_stall"],
        "method": "static",
        "how": "颜色域与弧表达式做静态类型检查，与状态空间规模无关（消融实验里唯一不掉的召回来源）",
    },
    {
        "id": "P8",
        "title": "structural sanity",
        "title_zh": "结构合法性（孤立节点/自环/重复边）",
        "formal": "规范化工作流的边端点存在、无自环、无重复边、无末节点回接",
        "types": ["isolated_node"],
        "method": "static",
        "how": "预处理与 repair.validate_workflow_structure 双向校验，修复只允许满足前提的改动",
    },
    {
        "id": "P9",
        "title": "honest truncation",
        "title_zh": "截断诚实性（探索不完就不下结论）",
        "formal": "有界探索只给出下近似；'不存在某状态'类结论一律不可证",
        "types": ["analysis_incomplete"],
        "method": "meta",
        "how": "max_states 超限时把 P1/P2/P4/P5 的结论降级为未证实，只报 analysis_incomplete 并列出被抑制项",
    },
]

DEFAULT_MAX_STATES = 20_000


def verify_workflow(raw_workflow: Dict[str, Any],
                    max_states: int = DEFAULT_MAX_STATES) -> Dict[str, Any]:
    t0 = time.perf_counter()

    norm = preprocess(raw_workflow)
    workflow = norm["workflow"]

    model = transform(workflow)
    rg = build_reachability_graph(model, max_states=max_states)

    terminal_findings, completed, terminals = analyze_terminals(rg, model)
    cycle_findings = detect_non_termination(rg, model)

    findings: List[Dict[str, Any]] = []
    if rg.truncated:
        # 截断 = 只探索了状态空间的一部分。此时"某状态不可达""必然死锁"
        # 都没有证明力（未探索的 frontier 之后可能还有路径），因此一律
        # 降级为未证实，不计入缺陷；静态可判的性质继续上报。
        suppressed: Dict[str, int] = {}
        for d in terminal_findings + cycle_findings:
            suppressed[d["type"]] = suppressed.get(d["type"], 0) + 1
        findings.append({
            "type": "analysis_incomplete",
            "source_id": None,
            "uncertain": True,
            "suppressed": suppressed,
            "detail": (f"state space exceeded max_states={max_states} "
                       f"({len(rg.state_keys)} states explored); "
                       f"state-space conclusions are withheld as unproven "
                       f"({suppressed or 'none'})"),
        })
    else:
        findings.extend(terminal_findings)
        findings.extend(cycle_findings)

    findings.extend(detect_typed_consumption_stall(model))
    findings.extend(detect_variable_constraint(workflow))
    findings.extend(detect_unreachable_nodes(rg, model))

    elapsed = time.perf_counter() - t0
    stats = {
        "preprocess_errors": len(norm["errors"]),
        "anomalies": norm["anomalies"],
        "|P|": len(model.P),
        "|T|": len(model.T),
        "|A|": len(model.A),
        "|RG|": len(rg.state_keys),
        "|RG_edges|": sum(len(s) for s in rg.succ),
        "fired_transitions": len(rg.fired),
        "terminal_markings": terminals,
        "completed_markings": completed,
        "truncated": rg.truncated,
        "open_guard_firings": rg.open_guard_firings,
        "binding_capped": rg.binding_capped,
        "model_warnings": len(model.warnings),
        "time_s": round(elapsed, 4),
    }
    return {
        "defective": bool(findings),
        "defects": findings,
        "model": model,
        "rg": rg,
        "stats": stats,
    }


if __name__ == "__main__":
    import json
    import sys
    cid = sys.argv[1] if len(sys.argv) > 1 else "wf_001"
    wf = json.load(open(f"test_cases/{cid}.json", encoding="utf-8"))
    res = verify_workflow(wf)
    print(f"[{cid}] defective={res['defective']} stats={res['stats']}")
    for d in res["defects"]:
        print("  -", d["type"], "| src:", d.get("source_id") or d.get("sources"),
              "|", d["detail"][:90])
