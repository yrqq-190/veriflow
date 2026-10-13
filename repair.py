# -*- coding: utf-8 -*-
"""
VeriFlow Defect Repair
======================
基于形式化验证结果（defects + provenance μ）生成**可修复建议**，
修复动作必须经用户确认后应用（必要时处确认，而非静默修改）。
应用后重新验证，直至缺陷清零或存在不可自动修复项（variable_constraint）。

缺陷类型 → 修复策略映射：
  - unexpected_deadlock（sources 含 if）→ connect_false_branch（补 else 分支）
  - non_termination_risk（sources 含 while）→ enable_exit（置 exit=true 并补出口）
  - unreachable_node / isolated_node      → reconnect_to_tail（接回主链末尾）
  - broken_message（n8n unpaired）        → downgrade_send_only（平台语义放行）
  - variable_constraint 等                → manual_review（人工处理）
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from verification import verify_workflow


def _in_deg(wf: Dict[str, Any]) -> Dict[str, int]:
    d: Dict[str, int] = {}
    for n in wf["nodes"]:
        d[n["id"]] = 0
    for e in wf["edges"]:
        d[e["to"]] = d.get(e["to"], 0) + 1
    return d


def _out_deg(wf: Dict[str, Any]) -> Dict[str, int]:
    d: Dict[str, int] = {}
    for n in wf["nodes"]:
        d[n["id"]] = 0
    for e in wf["edges"]:
        d[e["from"]] = d.get(e["from"], 0) + 1
    return d


def _entry_ids(wf: Dict[str, Any]) -> List[str]:
    d = _in_deg(wf)
    return [nid for nid, deg in d.items() if deg == 0]


def _last_node(wf: Dict[str, Any]) -> Optional[str]:
    """主链终点：无出边的 task/message 节点（按出现顺序取最后一个）。"""
    out = _out_deg(wf)
    cand = [n["id"] for n in wf["nodes"]
            if n.get("type") in ("task", "message") and out.get(n["id"], 0) == 0]
    return cand[-1] if cand else (wf["nodes"][-1]["id"] if wf["nodes"] else None)


def _true_branch_merge_point(wf: Dict[str, Any], if_id: str) -> Optional[str]:
    """沿 if 的 true 分支最长链，找汇合点（入度≥2 或 出度 0 的节点）。"""
    succ: Dict[str, List[str]] = {}
    for e in wf["edges"]:
        succ.setdefault(e["from"], []).append(e["to"])
    nxt = [e["to"] for e in wf["edges"]
           if e["from"] == if_id and e.get("branch") == "true"]
    if not nxt:
        return None
    cur = nxt[0]
    seen = {cur}
    while True:
        outs = succ.get(cur, [])
        if not outs:
            return cur
        indeg = sum(1 for e in wf["edges"]
                    if e["to"] == cur and e["from"] != if_id)
        if indeg >= 2:
            return cur
        cur = outs[0]
        if cur in seen:
            return cur
        seen.add(cur)


def _llm_explain(wf: Dict[str, Any], repairs: List[Dict[str, Any]],
                 defects: List[Dict[str, Any]]) -> None:
    """用 LLM 把机械的修复建议改成人话（仅改 description，不改 action）。失败静默。"""
    import os
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key or not repairs:
        return
    try:
        import json as _json
        import urllib.request
        endpoint = os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1"
        model = os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat"
        # 只解释 auto=True 的修复，manual 的跳过
        auto_repairs = [r for r in repairs if r["auto"]]
        if not auto_repairs:
            return
        defect_brief = [{"type": d["type"], "sources": d.get("sources", []),
                         "path": d.get("path", [])[:5]} for d in defects[:5]]
        repair_brief = [{"id": r["repair_id"], "defect": r["defect_type"],
                          "action": r["action"], "node": r["source_id"]}
                         for r in auto_repairs]
        system = (
            "你是工作流修复助手。基于形式化验证发现的缺陷，把系统给出的机械修复动作"
            "改写成一段对用户友好的中文解释（不超过 60 字），说明：为什么这个节点有问题、"
            "系统将怎么修、修完之后流程会怎样。直接输出 JSON，key 是 repair_id，value 是解释文本。"
        )
        user = f"工作流节点：{[n['name'] for n in wf['nodes']]}\n缺陷：{defect_brief}\n修复：{repair_brief}"
        body = _json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0.3,
        }).encode("utf-8")
        req = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions",
                                     data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        import re
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            explanations = _json.loads(m.group(0))
            for r in repairs:
                if r["repair_id"] in explanations:
                    r["llm_note"] = explanations[r["repair_id"]]
    except Exception:
        # LLM 解释失败不影响主流程
        pass


def suggest_repairs(wf: Dict[str, Any],
                    verify_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """由验证结果生成修复建议列表（绝不直接修改 wf，应用由 apply_repairs 完成）。"""
    node_kind = {n["id"]: n.get("type") for n in wf["nodes"]}
    repairs: List[Dict[str, Any]] = []
    seen: set = set()
    rid = 0

    def push(dtype, source_id, action, desc, conf, auto):
        nonlocal rid
        rid += 1
        repairs.append({"repair_id": f"r{rid}", "defect_type": dtype,
                        "source_id": source_id, "action": action,
                        "description": desc, "confidence": round(conf, 2),
                        "auto": auto})

    last = _last_node(wf)

    for d in verify_result["defects"]:
        dtype = d["type"]

        # --- 死锁：sources / 触发路径定位卡住的 if / message / while ---
        if dtype == "unexpected_deadlock":
            srcs = d.get("sources") or []
            if_srcs = [s for s in srcs if node_kind.get(s) == "if" and s not in seen]
            if not if_srcs:
                # 触发路径含 t_cond_<if_id> 变迁 → 反推决策节点
                for lbl in d.get("path") or []:
                    if lbl.startswith("t_cond_"):
                        cand = lbl[len("t_cond_"):]
                        if cand not in seen:
                            if_srcs.append(cand)
            if if_srcs:
                s = if_srcs[0]
                seen.add(s)
                mp = _true_branch_merge_point(wf, s) or last
                push("missing_branch", s, "connect_false_branch",
                     f"条件节点「{s}」缺少 false 分支导致死锁：补充 false 分支连接到"
                     f"汇合点「{mp}」，使条件不满足时流程继续", 0.9, True)
                continue
            # 死锁若与循环相关（t_loop_X 卡在无出口循环）
            loop_srcs = [s for s in srcs
                         if node_kind.get(s) == "while" and s not in seen]
            if not loop_srcs:
                for lbl in d.get("path") or []:
                    if lbl.startswith("t_loop_"):
                        cand = lbl[len("t_loop_"):]
                        if cand not in seen:
                            loop_srcs.append(cand)
            if loop_srcs:
                s = loop_srcs[0]
                seen.add(s)
                push("abnormal_loop", s, "enable_exit",
                     f"循环节点「{s}」所在环路无出口导致流程无法继续："
                     "将 exit 置为 true 并补 exit 分支边，使循环具备终止路径",
                     0.85, True)
                continue
            # 死锁若与消息节点相关（t_recv 缺失）
            msg_srcs = [s for s in srcs
                        if node_kind.get(s) == "message" and s not in seen]
            if msg_srcs:
                s = msg_srcs[0]
                seen.add(s)
                push("broken_message", s, "downgrade_send_only",
                     f"消息节点「{s}」导致流程阻塞：在平台语义下调整为 send-only"
                     "（仅发送不等待接收），或人工补充接收节点", 0.7, True)
                continue
            s0 = srcs[0] if srcs else "workflow"
            if s0 not in seen:
                seen.add(s0)
                push("deadlock", s0, "manual_review",
                     f"意外死锁（涉及「{s0}」）：需人工检查条件与消息交互", 0.0, False)
            continue

        # --- 非终止风险：sources 含 while → 补出口 ---
        if dtype == "non_termination_risk":
            srcs = d.get("sources") or ["workflow"]
            while_srcs = [s for s in srcs
                          if node_kind.get(s) == "while" and s not in seen]
            if while_srcs:
                s = while_srcs[0]
                seen.add(s)
                push("abnormal_loop", s, "enable_exit",
                     f"循环节点「{s}」所在环路无出口（exit=false 或条件数据依赖）："
                     "将其 exit 置为 true 并补一条 exit 分支边，使循环具备终止路径",
                     0.85, True)
                continue
            # sources 缺失时从触发路径提取 t_loop_<while_id>
            loop_srcs = []
            for lbl in d.get("path") or []:
                if lbl.startswith("t_loop_"):
                    cand = lbl[len("t_loop_"):]
                    if cand not in seen:
                        loop_srcs.append(cand)
            if loop_srcs:
                s = loop_srcs[0]
                seen.add(s)
                push("abnormal_loop", s, "enable_exit",
                     f"循环节点「{s}」所在环路无出口（exit=false 或条件数据依赖）："
                     "将其 exit 置为 true 并补一条 exit 分支边，使循环具备终止路径",
                     0.85, True)
                continue
            s0 = srcs[0] if srcs else "workflow"
            if s0 not in seen:
                seen.add(s0)
                push("non_termination", s0, "manual_review",
                     f"非终止风险（涉及「{s0}」）：需人工检查循环退出条件", 0.0, False)
            continue

        # --- 其余：带 source_id 的缺陷 ---
        src = d.get("source_id", "workflow")
        if src in seen:
            continue
        seen.add(src)

        if dtype == "unreachable_node":
            push("unreachable_node", src, "reconnect_to_tail",
                 f"节点「{src}」不可达：将其重新接入流程末尾（{last} 之后），"
                 "恢复其可达性；若该节点应属独立入口分支请人工核对",
                 0.6, True)

        elif dtype == "isolated_node":
            push("isolated_node", src, "reconnect_to_tail",
                 f"节点「{src}」孤立（无入边无出边）：建议接入流程末尾恢复可达；"
                 "或人工删除该节点", 0.5, True)

        elif dtype == "broken_message":
            push("broken_message", src, "downgrade_send_only",
                 f"消息节点「{src}」发送后无配对接收：在平台语义下将其调整为 "
                 "send-only（仅发送不等待接收），或人工补充接收节点", 0.8, True)

        elif dtype == "variable_constraint":
            push("variable_constraint", src, "manual_review",
                 f"节点「{src}」存在数据域不一致：需要人工核对字段类型/依赖关系，"
                 "系统不自动修复", 0.0, False)

    # --- 兜底结构扫描：验证异常但无法从 sources/path 精确定位时 ---
    # 覆盖 while 无出口（exit≠true）与 if 无 false 分支两类可自动修复项。
    if verify_result["defective"]:
        for n in wf["nodes"]:
            nid = n["id"]
            if nid in seen:
                continue
            if n.get("type") == "if":
                has_false = any(e["from"] == nid and e.get("branch") == "false"
                                for e in wf["edges"])
                if not has_false:
                    seen.add(nid)
                    mp = _true_branch_merge_point(wf, nid) or last
                    push("missing_branch", nid, "connect_false_branch",
                         f"条件节点「{nid}」缺少 false 分支（结构扫描定位）：补充分支"
                         f"连接到汇合点「{mp}」，消除死锁路径", 0.8, True)
            elif n.get("type") == "while" and n.get("exit") is not True:
                seen.add(nid)
                push("abnormal_loop", nid, "enable_exit",
                     f"循环节点「{nid}」无出口（exit≠true，结构扫描定位）：置 "
                     "exit=true 并补 exit 分支边，使循环具备终止路径", 0.8, True)

    # LLM 润色修复建议（可选，失败静默）
    _llm_explain(wf, repairs, verify_result.get("defects", []))

    return repairs


def apply_repairs(wf: Dict[str, Any], repairs: List[Dict[str, Any]],
                  accepted_ids: List[str]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """应用用户确认的修复（accepted_ids 是 repair_id 列表）。返回 (新工作流, 已应用列表)。"""
    w = copy.deepcopy(wf)
    applied: List[Dict[str, Any]] = []
    by_id = {r["repair_id"]: r for r in repairs}
    for rid in accepted_ids:
        r = by_id.get(rid)
        if r is None or not r["auto"]:
            continue
        src = r["source_id"]
        if r["action"] == "connect_false_branch":
            mp = _true_branch_merge_point(w, src) or _last_node(w)
            if mp and not any(e["from"] == src and e.get("branch") == "false"
                              for e in w["edges"]):
                w["edges"].append({"from": src, "to": mp, "branch": "false"})
                applied.append(r)

        elif r["action"] == "reconnect_to_tail":
            last = _last_node(w)
            if last and not any(e["to"] == src for e in w["edges"]):
                w["edges"].append({"from": last, "to": src})
                applied.append(r)

        elif r["action"] == "enable_exit":
            for n in w["nodes"]:
                if n["id"] == src and n.get("type") == "while":
                    n["exit"] = True
                    succ = [e["to"] for e in w["edges"]
                            if e["from"] == src and e.get("branch") is None]
                    target = succ[0] if succ else _last_node(w)
                    if target and not any(e["from"] == src and e.get("branch") == "exit"
                                          for e in w["edges"]):
                        w["edges"].append({"from": src, "to": target, "branch": "exit"})
                    applied.append(r)
                    break

        elif r["action"] == "downgrade_send_only":
            for n in w["nodes"]:
                if n["id"] == src and n.get("type") == "message":
                    n["pairing"] = "send_only"
                    applied.append(r)
                    break

    return w, applied


def repair_and_reverify(wf: Dict[str, Any],
                        accepted_ids: List[str]) -> Dict[str, Any]:
    """闭环入口：验证 → 生成建议 → 应用已确认修复 → 重新验证。"""
    first = verify_workflow(wf)
    repairs = suggest_repairs(wf, first)
    if not accepted_ids:
        return {"workflow": wf, "verify": first, "repairs": repairs,
                "applied": [], "clean": not first["defective"]}
    w2, applied = apply_repairs(wf, repairs, accepted_ids)
    v2 = verify_workflow(w2)
    return {"workflow": w2, "verify": v2, "repairs": repairs,
            "applied": applied, "clean": not v2["defective"]}


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
    print("repairs:", [(r["repair_id"], r["defect_type"], r["action"], r["auto"]) for r in repairs])
    out = repair_and_reverify(wf, [r["repair_id"] for r in repairs if r["auto"]])
    print("after: clean=", out["clean"], [d["type"] for d in out["verify"]["defects"]])

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
    print("repairs2:", [(r["repair_id"], r["defect_type"], r["action"]) for r in repairs2])
    out2 = repair_and_reverify(wf2, [r["repair_id"] for r in repairs2 if r["auto"]])
    print("after2: clean=", out2["clean"], [d["type"] for d in out2["verify"]["defects"]])
