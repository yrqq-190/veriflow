# -*- coding: utf-8 -*-
"""
VeriFlow: 缺陷注入器（真实平台工作流 → 受控缺陷负样本）
==========================================================
在标准 JSON 层对真实（正常）工作流注入论文 5 类缺陷，构造有标注的负样本。
每类注入函数返回 (workflow', defect_label)。注入保持 JSON 语法有效，
仅破坏控制流/消息/数据语义 —— 与论文"语法正常、语义缺陷"的实验设计一致。

注意：variable_constraint 注入在当前 Θ 抽象（不建模数据域）下为已知局限，
评估中将如实呈现为 FN（与论文 §4.3.2 报告一致）。
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


def inject_missing_branch(wf: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """删除 if 的 false 边 + 嵌套 else 字段 → 条件为假时无后继"""
    w = _clone(wf)
    for n in w["nodes"]:
        if n.get("type") != "if":
            continue
        e = _find_edge(w, n["id"], branch="false")
        if e is not None:
            w["edges"] = [x for x in w["edges"] if x is not e]
            n.pop("else", None)
            return w, "missing_branch"
        if n.get("else") is not None:
            n.pop("else", None)
            return w, "missing_branch"
    raise ValueError("no if node with a false branch edge to remove")


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
    """插入 while{exit:false}（无出口循环）到流程中部"""
    w = _clone(wf)
    nodes = w["nodes"]
    if not nodes:
        return w, "abnormal_loop"
    # 在第一个非入口 task 前插入无出口 while
    anchor = None
    for n in nodes:
        if n.get("type") == "task" and not n.get("is_entry") and not n.get("is_alt_entry"):
            anchor = n["id"]
            break
    if anchor is None:
        anchor = nodes[-1]["id"]
    loop_id = "loop_injected_1"
    # 断开 anchor 的入边，插入 loop → anchor
    w["nodes"].append({"id": loop_id, "type": "while", "name": "injected loop",
                       "exit": False, "body": None})
    for e in list(w["edges"]):
        if e["to"] == anchor:
            w["edges"].remove(e)
            w["edges"].append({"from": e["from"], "to": loop_id})
    w["edges"].append({"from": loop_id, "to": anchor})
    return w, "abnormal_loop"


def inject_broken_message(wf: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """消息发送后无配对接收 → broken-message 候选。
    优先把已有 n8n 消息节点改为 unpaired；若工作流无消息节点，则插入一个
    有入边/出边但 pairing=unpaired 的 n8n 消息节点（图检查器只看有无出边，
    检测不到；JCPN 检测配对语义，可检出——体现两者差异）。"""
    w = _clone(wf)
    # 1) 已有 n8n 消息节点：直接改 unpaired
    for n in w["nodes"]:
        if n.get("type") == "message" and n.get("platform") == "n8n":
            n["pairing"] = "unpaired"
            return w, "broken_message"
    # 2) 无消息节点：找一个有出边的中间 task，在其后插入 unpaired 消息节点
    out_edges = {}
    for e in w["edges"]:
        out_edges.setdefault(e["from"], []).append(e)
    anchor_edge = None
    for n in w["nodes"]:
        if n.get("type") == "task" and not n.get("is_entry") and n["id"] in out_edges:
            anchor_edge = out_edges[n["id"]][0]
            break
    if anchor_edge is None:
        raise ValueError("no suitable edge to insert broken message")
    msg_id = "msg_injected_1"
    w["nodes"].append({
        "id": msg_id, "type": "message", "name": "injected send (no receive)",
        "sender": "system", "pairing": "unpaired",
        "platform": "n8n", "direction": "out"})
    nxt = anchor_edge["to"]
    w["edges"] = [e for e in w["edges"] if e is not anchor_edge]
    w["edges"].append({"from": anchor_edge["from"], "to": msg_id})
    w["edges"].append({"from": msg_id, "to": nxt})
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
