# -*- coding: utf-8 -*-
"""
VeriFlow: 缺陷注入器（真实平台工作流 → 受控缺陷负样本）
==========================================================
在标准 JSON 层对真实（正常）工作流注入论文 5 类缺陷，构造有标注的负样本。
每类注入函数返回 (workflow', defect_label)。注入保持 JSON 语法有效，
仅破坏控制流/消息/数据语义 —— 与论文"语法正常、语义缺陷"的实验设计一致。

variable_constraint 注入通过改写相邻任务的 output_type / input_type 声明制造
数据颜色冲突，由 verification.detect_variable_constraint 的 Θ_data 颜色一致性
静态检查检出（与论文 Table 6 / §4.3 报告一致）。
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Optional, Tuple


def _clone(wf: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(wf)


def _find(wf: Dict[str, Any], type_: str, exclude: Optional[set] = None) -> Optional[dict]:
    cand = [n for n in wf["nodes"] if n.get("type") == type_]
    if exclude:
        cand = [n for n in cand if n["id"] not in exclude]
    return cand[0] if cand else None


def _find_edge(wf: Dict[str, Any], from_: str, branch: Optional[str] = None) -> Optional[dict]:
    for e in wf["edges"]:
        if e["from"] == from_ and (branch is None or e.get("branch") == branch):
            return e
    return None


def _degrees(wf: Dict[str, Any]):
    in_deg = {n["id"]: 0 for n in wf["nodes"]}
    out_deg = {n["id"]: 0 for n in wf["nodes"]}
    for e in wf["edges"]:
        in_deg[e["to"]] = in_deg.get(e["to"], 0) + 1
        out_deg[e["from"]] = out_deg.get(e["from"], 0) + 1
    return in_deg, out_deg


def _entries(wf: Dict[str, Any]) -> set:
    in_deg, _ = _degrees(wf)
    return {nid for nid, d in in_deg.items() if d == 0}


def _primary_entry(wf: Dict[str, Any]) -> Optional[str]:
    """主入口：与建模阶段一致（有显式 start 则用它，否则取字典序最小的人无入边节点）。"""
    for n in wf["nodes"]:
        if n.get("type") in ("start", "Start"):
            return n["id"]
    cands = sorted(_entries(wf))
    return cands[0] if cands else None


def _reachable(wf: Dict[str, Any]) -> set:
    outs = {}
    for e in wf["edges"]:
        outs.setdefault(e["from"], []).append(e["to"])
    start = _primary_entry(wf)
    seen, stack = set(), [start] if start else []
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(outs.get(cur, []))
    return seen


def _insertable_edge(wf: Dict[str, Any]) -> Optional[dict]:
    """挑一条「两端可达、目标只有这一条入边」的边，用于在流程中部插入结构。"""
    in_deg, _ = _degrees(wf)
    reach = _reachable(wf)
    for e in wf["edges"]:
        u, v = e["from"], e["to"]
        if u == v or e.get("branch"):
            continue
        if u not in reach or v not in reach:
            continue
        if in_deg.get(v, 0) != 1:
            continue
        if v in _entries(wf):
            continue
        return e
    return None


def inject_missing_branch(wf: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """删掉一条条件分支的连线，让该分支的整段子图脱离执行路径。

    语义说明：在 n8n / Dify 里「条件不满足且该分支没连边」是合法的实例终止，
    所以单纯删边、不留子图并不构成可检出缺陷（建模阶段已按平台语义把悬空分支
    并入 P_f）。真正属于缺陷的是「该分支原本有要做的工作，现在这段工作再也
    跑不到」——因此这里只删边、保留子图，缺陷的可观察后果是子图节点不可达。
    """
    w = _clone(wf)
    indeg, _ = _degrees(w)
    by_id = {n["id"]: n for n in w["nodes"]}
    for n in w["nodes"]:
        if n.get("type") != "if":
            continue
        outs = [e for e in w["edges"] if e["from"] == n["id"] and e.get("branch")]
        for e in outs:
            tgt = e["to"]
            if tgt not in by_id:
                continue
            if indeg.get(tgt, 0) != 1:      # 目标还有其他入边，删了也不会孤立
                continue
            w["edges"] = [x for x in w["edges"] if not (x["from"] == e["from"]
                                                        and x["to"] == tgt
                                                        and x.get("branch") == e.get("branch"))]
            return w, "missing_branch"
    raise ValueError("no removable branch edge with a private target subtree")


def inject_isolated_node(wf: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """断开中间 task 的入边与出边 → 孤立节点（无入边无出边）"""
    w = _clone(wf)
    in_deg = {n["id"]: 0 for n in w["nodes"]}
    out_deg = {n["id"]: 0 for n in w["nodes"]}
    for e in w["edges"]:
        in_deg[e["to"]] = in_deg.get(e["to"], 0) + 1
        out_deg[e["from"]] = out_deg.get(e["from"], 0) + 1
    for n in w["nodes"]:
        if n.get("type") != "task" or n.get("is_entry") or n.get("is_alt_entry"):
            continue
        if in_deg.get(n["id"], 0) >= 1 and out_deg.get(n["id"], 0) >= 1:
            w["edges"] = [e for e in w["edges"]
                          if e["from"] != n["id"] and e["to"] != n["id"]]
            return w, "isolated_node"
    raise ValueError("no interior task node to isolate")


def inject_unreachable_node(wf: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """删除中间 task 的入边（保留出边）→ 不可达节点（与孤立区分）"""
    w = _clone(wf)
    in_deg = {n["id"]: 0 for n in w["nodes"]}
    for e in w["edges"]:
        in_deg[e["to"]] = in_deg.get(e["to"], 0) + 1
    for n in w["nodes"]:
        if n.get("type") != "task" or n.get("is_entry") or n.get("is_alt_entry"):
            continue
        if in_deg.get(n["id"], 0) >= 1:
            w["edges"] = [e for e in w["edges"] if e["to"] != n["id"]]
            return w, "unreachable_node"
    raise ValueError("no interior task node to disconnect")


def inject_abnormal_loop(wf: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """在一次正常流转的中间插入 while{exit:false}（无出口循环）。

    插入点必须是一条「两端可达、目标唯一入边」的边，否则缺陷会落在不可达区域，
    评估时只能观察到 unreachable_node，无法检验循环终止性的判定能力。
    """
    w = _clone(wf)
    e = _insertable_edge(w)
    if e is None:
        raise ValueError("no insertable interior edge for abnormal loop")
    loop_id = "loop_injected_1"
    u, v = e["from"], e["to"]
    w["nodes"].append({"id": loop_id, "type": "while", "name": "injected loop",
                       "condition": "loop", "exit": False, "body": None})
    w["edges"] = [x for x in w["edges"] if not (x["from"] == u and x["to"] == v)]
    w["edges"].append({"from": u, "to": loop_id})
    w["edges"].append({"from": loop_id, "to": v})
    return w, "abnormal_loop"


def inject_broken_message(wf: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """消息发送后无配对接收 → broken-message 候选。

    优先把已有 n8n 消息节点改为 unpaired；否则在一条可执行的内部边上插入
    `pairing=unpaired` 的消息节点（有入边有出边，图检查器看不到问题）。
    """
    w = _clone(wf)
    for n in w["nodes"]:
        if n.get("type") == "message" and n.get("platform") == "n8n":
            n["pairing"] = "unpaired"
            n.pop("receiver", None)
            return w, "broken_message"

    e = _insertable_edge(w)
    if e is None:
        raise ValueError("no insertable interior edge for broken message")
    msg_id = "msg_injected_1"
    u, v = e["from"], e["to"]
    w["nodes"].append({
        "id": msg_id, "type": "message", "name": "injected send (no receive)",
        "sender": "system", "pairing": "unpaired",
        "platform": "n8n", "direction": "out"})
    w["edges"] = [x for x in w["edges"] if not (x["from"] == u and x["to"] == v)]
    w["edges"].append({"from": u, "to": msg_id})
    w["edges"].append({"from": msg_id, "to": v})
    return w, "broken_message"


def inject_variable_constraint(wf: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """在有直接边相连的两个任务上注入数据颜色冲突（上游 integer→下游 string）。
    优先选相邻任务，保证缺陷落在真实数据依赖边上；退化为任意两个内部任务。"""
    w = _clone(wf)
    by_id = {n["id"]: n for n in w["nodes"]}
    for e in w["edges"]:
        nu, nv = by_id.get(e["from"]), by_id.get(e["to"])
        if (nu and nv and nu.get("type") == "task" and nv.get("type") == "task"
                and not nu.get("is_entry") and not nv.get("is_entry")
                and not nu.get("is_alt_entry") and not nv.get("is_alt_entry")):
            nu["output_type"] = "integer"
            nv["input_type"] = "string"
            return w, "variable_constraint"
    tasks = [n for n in w["nodes"] if n.get("type") == "task" and not n.get("is_entry") and not n.get("is_alt_entry")]
    if len(tasks) >= 2:
        tasks[0]["output_type"] = "integer"
        tasks[1]["input_type"] = "string"
        return w, "variable_constraint"
    raise ValueError("need >=2 interior task nodes for data-domain conflict")


INJECTORS = {
    "missing_branch": inject_missing_branch,
    "isolated_node": inject_isolated_node,
    "unreachable_node": inject_unreachable_node,
    "abnormal_loop": inject_abnormal_loop,
    "broken_message": inject_broken_message,
    "variable_constraint": inject_variable_constraint,
}


def build_defective_set(real_normal: Dict[str, Dict[str, Any]]) -> Dict[str, Tuple[Dict[str, Any], str]]:
    """
    对真实正常样本注入缺陷。输入 {case_id: standard_workflow}。
    返回 {case_id#variant: (workflow', defect_label)}。
    每类缺陷取一个可注入样本生成一个变体；失败则跳过（如实记录）。
    """
    out: Dict[str, Tuple[Dict[str, Any], str]] = {}
    report: Dict[str, list] = {}
    for defect, inj in INJECTORS.items():
        report[defect] = []
        for cid, wf in real_normal.items():
            try:
                w2, label = inj(wf)
            except Exception as ex:  # 注入失败跳过
                report[defect].append(f"{cid}: fail({ex})")
                continue
            out[f"{cid}#{defect}"] = (w2, label)
            report[defect].append(cid)
    return out, report
