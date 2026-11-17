# -*- coding: utf-8 -*-
"""
VeriFlow Defect Repair（闭环修复层）
===================================
职责边界：
  * **只根据形式化验证的结论生成修复建议**，不做独立的启发式扫描——
    缺陷从哪来、修完是否真的消失，都由重验证回答；
  * 建议必须由用户确认后才 apply；apply 逐条做结构合法性校验，
    非法改动整条回滚，并给出**语义差异摘要**（不是"改完就说干净了"）；
  * 不存在"改标签式修复"：凡是无法在网结构上造成可验证变化的动作，
    一律降级为人工复核，不再以自动修复的名义出现。

动作 → 语义效果：
  connect_false_branch  if 的 false 分支接上汇合点 → p_else 的残留 token 消失
  enable_exit           while 具备出口 → t_exit 存在，p_out 可达
  reconnect_to_tail     孤立/不可达节点接回主链 → 其变迁在可达图中触发
  manual_review         需要人判断语义的动作，系统不自动改
"""
from __future__ import annotations

import copy
import os
from typing import Any, Dict, List, Optional, Tuple

from verification import verify_workflow

VALID_BRANCHES = (None, "true", "false", "loop", "exit")


# ---------------------------------------------------------------------------
# 图结构辅助
# ---------------------------------------------------------------------------
def _in_deg(wf: Dict[str, Any]) -> Dict[str, int]:
    d = {n["id"]: 0 for n in wf.get("nodes", [])}
    for e in wf.get("edges", []):
        d[e["to"]] = d.get(e["to"], 0) + 1
    return d


def _out_deg(wf: Dict[str, Any]) -> Dict[str, int]:
    d = {n["id"]: 0 for n in wf.get("nodes", [])}
    for e in wf.get("edges", []):
        d[e["from"]] = d.get(e["from"], 0) + 1
    return d


def _last_node(wf: Dict[str, Any]) -> Optional[str]:
    out = _out_deg(wf)
    cand = [n["id"] for n in wf.get("nodes", [])
            if n.get("type") in ("task", "message") and out.get(n["id"], 0) == 0]
    return cand[-1] if cand else (wf["nodes"][-1]["id"] if wf.get("nodes") else None)


def _true_branch_merge_point(wf: Dict[str, Any], if_id: str) -> Optional[str]:
    """沿 if 的 true 分支走，找汇合点（入度≥2 或出度为 0 的节点）。"""
    succ: Dict[str, List[str]] = {}
    for e in wf.get("edges", []):
        succ.setdefault(e["from"], []).append(e["to"])
    nxt = [e["to"] for e in wf.get("edges", [])
           if e["from"] == if_id and e.get("branch") == "true"]
    if not nxt:
        return None
    cur = nxt[0]
    seen = {cur}
    while True:
        outs = succ.get(cur, [])
        if not outs:
            return cur
        indeg = sum(1 for e in wf.get("edges", [])
                    if e["to"] == cur and e["from"] != if_id)
        if indeg >= 2:
            return cur
        cur = outs[0]
        if cur in seen:
            return cur
        seen.add(cur)


def _reachable_from(wf: Dict[str, Any], start: str) -> set:
    succ: Dict[str, List[str]] = {}
    for e in wf.get("edges", []):
        succ.setdefault(e["from"], []).append(e["to"])
    seen, stack = set(), [start]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(succ.get(cur, []))
    return seen


# ---------------------------------------------------------------------------
# 结构合法性校验
# ---------------------------------------------------------------------------
NESTED_KEYS = ("then", "else", "body")


def _iter_nodes(nodes: List[dict]):
    """深度优先展开节点树（嵌套 then/else/body 也是合法节点）。"""
    for n in nodes:
        if not isinstance(n, dict):
            continue
        yield n
        for key in NESTED_KEYS:
            child = n.get(key)
            if isinstance(child, dict):
                yield from _iter_nodes([child])
            elif isinstance(child, list):
                yield from _iter_nodes(child)


def validate_workflow_structure(wf: Dict[str, Any]) -> List[str]:
    """返回结构错误清单；空列表表示该工作流结构合法。"""
    errors: List[str] = []
    nodes = list(_iter_nodes(wf.get("nodes", [])))
    edges = wf.get("edges", [])

    ids = [n.get("id") for n in nodes]
    if len(ids) != len(set(ids)):
        errors.append("duplicate node ids")
    id_set = set(ids)

    seen_edges: Dict[Tuple[str, str, Any], int] = {}
    for e in edges:
        u, v, b = e.get("from"), e.get("to"), e.get("branch")
        if u not in id_set:
            errors.append(f"edge source '{u}' does not exist")
        if v not in id_set:
            errors.append(f"edge target '{v}' does not exist")
        if u == v:
            errors.append(f"self loop on '{u}'")
        if b not in VALID_BRANCHES:
            errors.append(f"invalid branch tag '{b}' on {u}->{v}")
        key = (u, v, b)
        seen_edges[key] = seen_edges.get(key, 0) + 1
        if seen_edges[key] > 1:
            errors.append(f"duplicate edge {u}->{v} (branch={b})")
    return errors


def _edge_exists(wf: Dict[str, Any], u: str, v: str, branch=None) -> bool:
    return any(e.get("from") == u and e.get("to") == v
               and e.get("branch") == branch for e in wf.get("edges", []))


# ---------------------------------------------------------------------------
# 修复建议
# ---------------------------------------------------------------------------
def suggest_repairs(wf: Dict[str, Any],
                    verify_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """由验证结果生成修复建议。缺陷 → 动作由缺陷类型与 μ 定位决定。"""
    node_kind = {n["id"]: n.get("type") for n in wf.get("nodes", [])}
    last = _last_node(wf)
    repairs: List[Dict[str, Any]] = []
    seen: set = set()
    rid = 0

    def push(dtype, source_id, action, desc, conf, auto, evidence=None):
        nonlocal rid
        key = (action, source_id)
        if key in seen:
            return
        seen.add(key)
        rid += 1
        repairs.append({
            "repair_id": f"r{rid}", "defect_type": dtype,
            "source_id": source_id, "action": action,
            "description": desc, "confidence": round(conf, 2),
            "auto": auto, "evidence": evidence or {},
        })

    for d in verify_result.get("defects", []):
        dtype = d["type"]
        if dtype == "analysis_incomplete":
            continue
        src = d.get("source_id")
        if not src:
            srcs = d.get("sources") or []
            src = srcs[0] if srcs else "workflow"

        if dtype == "missing_branch":
            mp = _true_branch_merge_point(wf, src) or last
            push("missing_branch", src, "connect_false_branch",
                 f"条件节点「{src}」的 false 分支没有落点（残留条件 token）："
                 f"把 false 分支接到汇合点「{mp}」", 0.9, True, d)
        elif dtype in ("unexpected_deadlock", "non_termination_risk"):
            if node_kind.get(src) == "while":
                push("abnormal_loop", src, "enable_exit",
                     f"循环节点「{src}」没有出口：置 exit=true 并补 exit 边，"
                     "使循环存在终止路径", 0.85, True, d)
            else:
                push(dtype, src, "manual_review",
                     f"「{src}」处出现无法自动判定的死锁/非终止：需人工核对控制流",
                     0.0, False, d)
        elif dtype == "broken_message":
            push("broken_message", src, "manual_review",
                 f"消息节点「{src}」发送后没有接收方（消息 token 无人消费）："
                 "请补接收节点，或确认该交互在业务上允许单向发送", 0.0, False, d)
        elif dtype in ("unreachable_node", "isolated_node"):
            if last and last != src:
                push(dtype, src, "reconnect_to_tail",
                     f"节点「{src}」不在任何可达路径上：接到流程末尾「{last}」之后",
                     0.6, True, d)
            else:
                push(dtype, src, "manual_review",
                     f"节点「{src}」不可达且无法安全接到主链末尾：需人工判断其归属",
                     0.0, False, d)
        elif dtype == "variable_constraint":
            push("variable_constraint", src, "manual_review",
                 f"节点「{src}」的数据类型约束不一致：需人工核对字段类型与依赖",
                 0.0, False, d)

    _llm_explain(wf, repairs, verify_result.get("defects", []))
    return repairs


# ---------------------------------------------------------------------------
# 应用
# ---------------------------------------------------------------------------
def _apply_one(wf: Dict[str, Any], r: Dict[str, Any]) -> Optional[str]:
    """应用单条动作；成功返回 None，失败返回原因（此时 wf 未被修改）。"""
    src = r["source_id"]
    action = r["action"]
    ids = {n["id"] for n in wf.get("nodes", [])}

    if src not in ids and action != "manual_review":
        return f"unknown source node '{src}'"

    if action == "connect_false_branch":
        mp = _true_branch_merge_point(wf, src) or _last_node(wf)
        if not mp or mp == src:
            return "no merge point available"
        if _edge_exists(wf, src, mp, "false"):
            return "false branch already present"
        wf["edges"].append({"from": src, "to": mp, "branch": "false"})
        return None

    if action == "enable_exit":
        node = next((n for n in wf["nodes"] if n["id"] == src), None)
        if node is None or node.get("type") != "while":
            return "source is not a while node"
        node["exit"] = True
        target = next((e["to"] for e in wf["edges"]
                       if e["from"] == src and e.get("branch") is None), None)
        target = target or _last_node(wf)
        if not target:
            return "no exit target available"
        if target == src:
            return "refusing to create a self loop"
        if not _edge_exists(wf, src, target, "exit"):
            wf["edges"].append({"from": src, "to": target, "branch": "exit"})
        return None

    if action == "reconnect_to_tail":
        last = _last_node(wf)
        if not last:
            return "no tail node"
        if last == src:
            return "refusing to create a self loop"
        if _edge_exists(wf, last, src, None):
            return "edge already present"
        if last in _reachable_from(wf, src):
            return "would create a cycle back to the tail"
        wf["edges"].append({"from": last, "to": src})
        return None

    return "no structural effect defined for action"


def apply_repairs(wf: Dict[str, Any],
                  repairs: List[Dict[str, Any]],
                  accepted_ids: List[str]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """应用用户确认的修复。每条改动都过结构校验；非法改动回滚并记录原因。

    返回 (新工作流, 应用记录)。应用记录里 status ∈ {applied, skipped}，
    skipped 带 reason —— 不做"静默失败"。
    """
    w = copy.deepcopy(wf)
    by_id = {r["repair_id"]: r for r in repairs}
    records: List[Dict[str, Any]] = []

    for rid in accepted_ids:
        r = by_id.get(rid)
        if r is None:
            records.append({"repair_id": rid, "status": "skipped",
                            "reason": "unknown repair id"})
            continue
        if not r.get("auto"):
            records.append({"repair_id": rid, "status": "skipped",
                            "reason": "manual review required"})
            continue

        snapshot = copy.deepcopy(w)
        reason = _apply_one(w, r)
        if reason is None:
            errs = validate_workflow_structure(w)
            if errs:
                w = snapshot
                reason = "structure validation failed: " + "; ".join(errs[:3])
        if reason is not None:
            records.append({"repair_id": rid, "source_id": r["source_id"],
                            "action": r["action"], "status": "skipped",
                            "reason": reason})
            continue

        records.append({"repair_id": rid, "source_id": r["source_id"],
                        "action": r["action"], "status": "applied",
                        "delta": _workflow_delta(snapshot, w)})

    return w, records


def _workflow_delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """结构层面的差异摘要（节点/边的增删，以及被修改的节点字段）。"""
    b_nodes = {n["id"]: n for n in before.get("nodes", [])}
    a_nodes = {n["id"]: n for n in after.get("nodes", [])}
    changed = []
    for nid in sorted(set(a_nodes) & set(b_nodes)):
        diff = {k: (b_nodes[nid].get(k), a_nodes[nid].get(k))
                for k in a_nodes[nid]
                if b_nodes[nid].get(k) != a_nodes[nid].get(k)}
        if diff:
            changed.append({"id": nid, "fields": diff})

    def _key(e):
        return (e.get("from"), e.get("to"), e.get("branch"))

    b_edges = {_key(e) for e in before.get("edges", [])}
    a_edges = {_key(e) for e in after.get("edges", [])}
    return {
        "nodes_added": sorted(set(a_nodes) - set(b_nodes)),
        "nodes_removed": sorted(set(b_nodes) - set(a_nodes)),
        "nodes_changed": changed,
        "edges_added": [f"{u}->{v}[{b}]" if b else f"{u}->{v}"
                        for (u, v, b) in sorted(a_edges - b_edges, key=str)],
        "edges_removed": [f"{u}->{v}[{b}]" if b else f"{u}->{v}"
                          for (u, v, b) in sorted(b_edges - a_edges, key=str)],
    }


def _verify_delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """两次验证的语义差异：缺陷数、可达图规模、缺陷类型变化。"""
    def _types(v):
        return sorted({d["type"] for d in v.get("defects", [])})

    return {
        "defects_before": len(before.get("defects", [])),
        "defects_after": len(after.get("defects", [])),
        "types_before": _types(before),
        "types_after": _types(after),
        "rg_before": before.get("stats", {}).get("|RG|"),
        "rg_after": after.get("stats", {}).get("|RG|"),
        "truncated": after.get("stats", {}).get("truncated", False),
    }


def repair_and_reverify(wf: Dict[str, Any],
                        accepted_ids: List[str]) -> Dict[str, Any]:
    """闭环入口：验证 → 建议 → 应用已确认项 → 重验证 → 语义差异。"""
    first = verify_workflow(wf)
    repairs = suggest_repairs(wf, first)
    if not accepted_ids:
        return {"workflow": wf, "verify": first, "repairs": repairs,
                "applied": [], "clean": not first["defective"],
                "delta": None}
    w2, applied = apply_repairs(wf, repairs, accepted_ids)
    v2 = verify_workflow(w2)
    return {"workflow": w2, "verify": v2, "repairs": repairs,
            "applied": applied, "clean": not v2["defective"],
            "delta": _verify_delta(first, v2)}


# ---------------------------------------------------------------------------
# 可选：把机械描述改写成自然语言（只改 description，不影响任何判定）
# ---------------------------------------------------------------------------
def _llm_explain(wf: Dict[str, Any], repairs: List[Dict[str, Any]],
                 defects: List[Dict[str, Any]]) -> None:
    """需显式开启（VERIFLOW_LLM_EXPLAIN=1）；失败静默，绝不影响修复动作。"""
    if os.environ.get("VERIFLOW_LLM_EXPLAIN") != "1":
        return
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key or not repairs:
        return
    try:
        import json as _json
        import re
        import urllib.request
        endpoint = os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1"
        model = os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat"
        auto = [r for r in repairs if r["auto"]]
        if not auto:
            return
        body = _json.dumps({
            "model": model,
            "messages": [
                {"role": "system",
                 "content": "把给定的工作流修复动作改写成不超过 60 字的中文说明，"
                            "只输出 JSON：{repair_id: 说明}。"},
                {"role": "user",
                 "content": _json.dumps({
                     "nodes": [n.get("name") for n in wf.get("nodes", [])],
                     "defects": [{"type": d["type"], "sources": d.get("sources", [])}
                                 for d in defects[:5]],
                     "repairs": [{"id": r["repair_id"], "action": r["action"],
                                  "node": r["source_id"]} for r in auto],
                 }, ensure_ascii=False)},
            ],
            "temperature": 0.3, "max_tokens": 300,
        }).encode("utf-8")
        req = urllib.request.Request(
            endpoint.rstrip("/") + "/chat/completions", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = _json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            notes = _json.loads(m.group(0))
            for r in repairs:
                if r["repair_id"] in notes:
                    r["llm_note"] = notes[r["repair_id"]]
    except Exception:
        return


if __name__ == "__main__":
    # 自测 1：缺 false 分支 → 补分支 → 重验证干净
    wf = {"name": "t", "nodes": [
        {"id": "n1", "type": "task", "name": "开始"},
        {"id": "n2", "type": "if", "name": "判断", "condition": "x",
         "then": {"id": "n3", "type": "task", "name": "通过"}},
        {"id": "n4", "type": "task", "name": "结束"},
    ], "edges": [
        {"from": "n1", "to": "n2"},
        {"from": "n2", "to": "n3", "branch": "true"},
        {"from": "n3", "to": "n4"},
    ]}
    r1 = verify_workflow(wf)
    print("before:", r1["defective"], [d["type"] for d in r1["defects"]])
    repairs = suggest_repairs(wf, r1)
    print("repairs:", [(r["repair_id"], r["defect_type"], r["action"], r["auto"])
                       for r in repairs])
    out = repair_and_reverify(wf, [r["repair_id"] for r in repairs if r["auto"]])
    print("after: clean=", out["clean"],
          [d["type"] for d in out["verify"]["defects"]],
          "delta=", out["delta"])

    # 自测 2：不可达节点 → 接回末尾 → 重验证干净
    wf2 = {"name": "t2", "nodes": [
        {"id": "a", "type": "task", "name": "开始"},
        {"id": "b", "type": "task", "name": "中间"},
        {"id": "c", "type": "task", "name": "孤儿"},
        {"id": "d", "type": "task", "name": "结束"},
    ], "edges": [
        {"from": "a", "to": "b"},
        {"from": "b", "to": "d"},
    ]}
    r2 = verify_workflow(wf2)
    print("before2:", r2["defective"], [d["type"] for d in r2["defects"]])
    repairs2 = suggest_repairs(wf2, r2)
    print("repairs2:", [(r["repair_id"], r["defect_type"], r["action"])
                        for r in repairs2])
    out2 = repair_and_reverify(wf2, [r["repair_id"] for r in repairs2 if r["auto"]])
    print("after2: clean=", out2["clean"],
          [d["type"] for d in out2["verify"]["defects"]])
