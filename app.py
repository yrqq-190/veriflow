# -*- coding: utf-8 -*-
"""
VeriFlow 原型后端（Flask REST）
================================
闭环：自然语言 → (必要时澄清/确认) → NL2JSON → preprocess → JCPN 建模 →
形式化验证 → 缺陷修复（用户确认后应用）→ 重验证 → 输出正确工作流。

API：
  GET  /                 前端页面（webui/）
  GET  /api/health       健康检查
  POST /api/generate     NL → 管道执行；若需澄清返回 awaiting_clarification
  POST /api/clarify      用户澄清后重生成
  POST /api/confirm      确认修复项 → 应用 → 重验证
  POST /api/export       导出最终 JSON
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, Iterable, List, Optional

from flask import Flask, jsonify, request, send_from_directory, session

from nl2json import nl2json, detect_intent
from preprocess import preprocess
from jcpn_builder import transform
from verification import verify_workflow
from repair import suggest_repairs, apply_repairs, verify_workflow as _vw
from adapters import parse_n8n, parse_dify, parse_coze

BASE = os.path.dirname(os.path.abspath(__file__))
WEBUI = os.path.join(BASE, "webui")

app = Flask(__name__, static_folder=WEBUI, static_url_path="")
app.secret_key = os.environ.get("VERIFLOW_SECRET") or os.urandom(16).hex()
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # 部署后前端立即生效

# 内存会话（单用户演示）；生产可换 redis/文件
SESSIONS: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()

# 验证管道阶段（双语 id → 顺序）
PIPELINE_STAGES = [
    "requirements_capture",
    "requirements_analysis",
    "requirements_clarification",
    "requirements_confirmation",
    "workflow_planning",
    "json_intermediate_representation",
    "jcpn_model_construction",
    "formal_verification",
    "defect_repair",
    "workflow_output",
]


def _sid() -> str:
    if "_sid" not in session:
        session["_sid"] = os.urandom(8).hex()
    return session["_sid"]


MAX_SESSIONS = int(os.environ.get("VERIFLOW_MAX_SESSIONS", "200"))


def _store_session(result: Dict[str, Any]) -> None:
    """写入会话，并把总量限制在 MAX_SESSIONS。

    Render 免费实例只有 512MB，演示站被反复访问时会话表会一直增长；
    这里按最近使用顺序淘汰最旧的会话（重新插入以刷新顺序）。
    """
    sid = _sid()
    SESSIONS.pop(sid, None)
    SESSIONS[sid] = result
    overflow = len(SESSIONS) - MAX_SESSIONS
    if overflow > 0:
        for key in list(SESSIONS.keys())[:overflow]:
            if key != sid:
                SESSIONS.pop(key, None)


def _clean_verify(v: Dict[str, Any]) -> Dict[str, Any]:
    """剥离不可 JSON 序列化的对象（JCPNModel / ReachabilityGraph，含 set 等）。"""
    return {k: val for k, val in v.items() if k not in ("model", "rg")}


def _model_digest(model) -> Dict[str, Any]:
    """JCPN 模型 → 可序列化摘要（CPN 图数据源 + μ 溯源展示）。"""
    places = [{"id": p_, "color": model.C.get(p_, "?"),
               "source": model._reverse.get(p_, None), "final": p_ in model.P_f}
              for p_ in sorted(model.P)]
    trans = [{"id": t, "guard": model.G.get(t, "true"),
              "update": model.U.get(t, ""),
              "source": model._reverse.get(t, None)}
             for t in sorted(model.T)]
    arcs = [{"from": a[0], "to": a[1], "expr": model.X.get(a, "1`x")}
            for a in sorted(model.A, key=lambda x: (x[0], x[1]))]
    mu = [{"source": sid, "kind": v.get("kind", "?"),
           "places": list(v.get("places", [])),
           "transitions": list(v.get("transitions", []))}
          for sid, v in sorted(model.mu.items())]
    return {"places": places, "transitions": trans, "arcs": arcs,
            "mu": mu, "|P|": len(model.P), "|T|": len(model.T), "|A|": len(model.A)}


# ---------------------------------------------------------------------------
# 阶段执行器
# ---------------------------------------------------------------------------
def _stage(name: str, ok: bool, note: str) -> Dict[str, Any]:
    return {"stage": name, "status": "done" if ok else "blocked", "note": note}


SLOT_MAP = {"q_topic": "topic", "q_action": "action",
            "q_else": "else", "q_msg_platform": "msg_platform"}


def run_pipeline(text: str, slots: Optional[Dict[str, Any]] = None,
                 asked: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """执行完整管道，返回阶段记录与中间产物。

    slots 是澄清阶段的结构化回答（topic/action/else/msg_platform）；
    asked 是本会话已经问过的问题 id，用于澄清预算：同一问题不再重复提问。
    """
    steps: List[Dict[str, Any]] = []
    text = (text or "").strip()
    if not text:
        return {"status": "error", "error": "empty_input", "steps": []}

    steps.append(_stage("requirements_capture", True, text))

    slots = dict(slots or {})
    asked_list = list(asked or [])

    # --- Requirements analysis + clarification（必要处确认，而非一次性盲目生成）---
    from nl2json import clarify_questions
    intent = detect_intent(text, slots)
    questions = clarify_questions(text, slots, asked_list)
    # 澄清预算是否已经把问题挡住（用于诚实标注"按已知信息生成"）
    suppressed = bool(asked_list) and not questions and bool(
        clarify_questions(text, slots, None))
    if questions:
        steps.append(_stage("requirements_analysis", True,
                            "检测到需求歧义 / 缺省项，需要用户澄清"))
        steps.append(_stage("requirements_clarification", False,
                            "等待用户澄清（question ids: "
                            + ", ".join(q["id"] for q in questions) + ")"))
        steps.append(_stage("requirements_confirmation", False,
                            "待澄清后确认需求"))
        return {"status": "awaiting_clarification", "questions": questions,
                "steps": steps, "text": text, "slots": slots,
                "asked": asked_list}
    if suppressed:
        steps.append(_stage("requirements_analysis", True,
                            "澄清预算已用尽：同一问题不重复提问，按已知信息生成"))
        steps.append(_stage("requirements_clarification", True,
                            "已收到用户回答（question ids: "
                            + ", ".join(asked_list) + "），继续生成"))
    elif slots:
        steps.append(_stage("requirements_analysis", True,
                            "已收到结构化澄清回答（"
                            + "、".join(f"{k}={v}" for k, v in slots.items())
                            + "）"))
        steps.append(_stage("requirements_clarification", True, "澄清完成"))
    else:
        steps.append(_stage("requirements_analysis", True,
                            "意图识别：模板命中或通用解析"))
        steps.append(_stage("requirements_clarification", True, "无需澄清（无歧义）"))
    steps.append(_stage("requirements_confirmation", True,
                        "需求已确认（默认接受；可回退修改）"))

    # --- Workflow planning + JSON IR ---
    wf, _, gen_stage = nl2json(text, slots, asked_list)
    steps.append(_stage("workflow_planning", True,
                        f"工作流规划完成（生成模式: {gen_stage}）"))
    steps.append(_stage("json_intermediate_representation", True,
                        f"JSON IR：{len(wf.get('nodes', []))} 节点 / "
                        f"{len(wf.get('edges', []))} 边"))

    # --- JCPN 建模 + 形式化验证 ---
    pp = preprocess(wf)
    model = transform(pp["workflow"])
    verify = verify_workflow(pp["workflow"])
    verify_out = _clean_verify(verify)
    steps.append(_stage("jcpn_model_construction", True,
                        f"JCPN：|P|={len(model.P)} |T|={len(model.T)} "
                        f"|A|={len(model.A)}，μ 映射 {len(model.mu)} 条"))
    n_defects = len(verify["defects"])
    steps.append(_stage("formal_verification", True,
                        ("验证通过：可达图 "
                         + f"{verify['stats'].get('|RG|', '?')} 状态，无缺陷"
                         if not verify["defective"]
                         else f"发现 {n_defects} 项缺陷："
                              + ", ".join(d["type"] for d in verify["defects"]))))

    # --- Defect repair（建议生成；应用需用户确认）---
    repairs = suggest_repairs(pp["workflow"], verify)
    auto_ids = [r["repair_id"] for r in repairs if r["auto"]]
    manual_ids = [r["repair_id"] for r in repairs if not r["auto"]]
    if repairs:
        steps.append(_stage("defect_repair", False,
                            f"生成 {len(repairs)} 条修复建议（自动 {len(auto_ids)} / "
                            f"人工 {len(manual_ids)}），等待用户确认"))
    else:
        steps.append(_stage("defect_repair", True, "无缺陷，无需修复"))

    # --- Workflow output（输出前确认）---
    steps.append(_stage("workflow_output", not verify["defective"],
                        "工作流输出就绪" if not verify["defective"]
                        else "待修复确认后输出"))

    return {"status": "awaiting_repair" if repairs else "clean",
            "steps": steps, "workflow": pp["workflow"], "verify": verify_out,
            "repairs": repairs, "text": text, "slots": slots,
            "asked": asked_list, "clarification_exhausted": suppressed,
            "gen_stage": gen_stage, "model_digest": _model_digest(model)}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(WEBUI, "index.html")


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "service": "VeriFlow"})


_SAMPLES_CACHE: Dict[str, Any] = {}


@app.route("/api/samples")
def api_samples():
    """真实样本清单 + 逐样本检测结果 + 评估对比（读预计算 JSON，不实时跑，避免 Render OOM）。

    结果按文件 mtime 缓存：这两个文件合计数百 KB，每次请求重读既慢又白耗 IO。
    """
    return jsonify(_samples_payload())


_SAMPLES_CACHE: Dict[str, Any] = {"sig": None, "payload": None}


def _samples_payload() -> Dict[str, Any]:
    base = os.path.dirname(os.path.abspath(__file__))
    pre_path = os.path.join(base, "samples_precomputed.json")
    eval_path = os.path.join(base, "full_experiment_report.json")
    sig = tuple((os.path.getmtime(x) if os.path.exists(x) else 0.0)
                for x in (pre_path, eval_path))
    cached = _SAMPLES_CACHE.get("payload")
    if cached is not None and _SAMPLES_CACHE.get("sig") == sig:
        return cached

    samples = []
    elapsed = 0.0
    if os.path.exists(pre_path):
        with open(pre_path, encoding="utf-8") as fh:
            _d = json.load(fh)
        samples = _d.get("samples", [])
        elapsed = _d.get("elapsed_s", 0.0)
    eval_data = {}
    if os.path.exists(eval_path):
        with open(eval_path, encoding="utf-8") as fh:
            _fe = json.load(fh)
        _g = _fe.get("global", {})
        eval_data = {"results": {
            "JSON Schema": {"precision": _g.get("schema", {}).get("precision", 0), "recall": _g.get("schema", {}).get("recall", 0), "f1": _g.get("schema", {}).get("f1", 0), "accuracy": _g.get("schema", {}).get("accuracy", 0)},
            "Graph static": {"precision": _g.get("graph", {}).get("precision", 0), "recall": _g.get("graph", {}).get("recall", 0), "f1": _g.get("graph", {}).get("f1", 0), "accuracy": _g.get("graph", {}).get("accuracy", 0)},
            "JCPN": {"precision": _g.get("jcpn", {}).get("precision", 0), "recall": _g.get("jcpn", {}).get("recall", 0), "f1": _g.get("jcpn", {}).get("f1", 0), "accuracy": _g.get("jcpn", {}).get("accuracy", 0)},
        },
            "dataset": {"n_bases": _fe.get("n_bases", 0), "n_samples": _fe.get("n_samples", 0)},
            "by_type": _fe.get("by_type", {}),
            "metric_version": _fe.get("metric_version", ""),
            "metric_note": _fe.get("metric_note", ""),
            "clean_false_positives": _fe.get("clean_false_positives", []),
            "clean_fp_counts": _fe.get("clean_fp_counts", {}),
            "clean_inconclusive": _fe.get("clean_inconclusive", []),
            "by_platform": _fe.get("by_platform", {}),
            "semantics": _fe.get("semantics", {}),
        }
    payload = {
        "samples": samples,
        "elapsed_s": elapsed,
        "evaluation": eval_data.get("results", {}),
        "by_type": eval_data.get("by_type", {}),
        "dataset": eval_data.get("dataset", {}),
        "metric_version": eval_data.get("metric_version", ""),
        "metric_note": eval_data.get("metric_note", ""),
        "clean_fp": eval_data.get("clean_false_positives", []),
        "clean_fp_counts": eval_data.get("clean_fp_counts", {}),
        "clean_inconclusive": eval_data.get("clean_inconclusive", []),
        "by_platform": eval_data.get("by_platform", {}),
        "semantics": eval_data.get("semantics", {}),
        "checklist": _checklist_payload(),
    }
    _SAMPLES_CACHE["sig"] = sig
    _SAMPLES_CACHE["payload"] = payload
    return payload


def _checklist_payload() -> List[Dict[str, Any]]:
    """检测清单（形式化性质 + 判定方式 + 可靠性边界）。"""
    try:
        from verification import CHECKLIST
        return CHECKLIST
    except Exception:
        return []


@app.post("/api/generate")
def api_generate():
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text", "")
    try:
        # 计算放在锁外：LLM 最长 45s，不能把其他请求一起堵住
        result = run_pipeline(text, {}, [])
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "error": "pipeline_error",
                        "message": f"{type(e).__name__}: {e}", "steps": []}), 500
    with _lock:
        _store_session(result)
    return jsonify(result)


@app.post("/api/clarify")
def api_clarify():
    """用户回答澄清问题后重新生成。

    answers: {question_id: answer}。按 question id 落进结构化槽位，而不是把答案
    拼回原文再猜——这是"同一问题被反复问"的根治点。同时把问过的 id 计入预算。
    """
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text", "")
    answers = data.get("answers", {}) or {}
    with _lock:
        st = SESSIONS.get(_sid()) or {}
        slots = dict(st.get("slots") or {})
        asked_list = list(st.get("asked") or [])
    for qid, ans in answers.items():
        key = SLOT_MAP.get(qid)
        if key and isinstance(ans, str) and ans.strip():
            slots[key] = ans.strip()
        if qid not in asked_list:
            asked_list.append(qid)
    if not asked_list:
        # 没有会话记录时，至少把本次回答的 id 计入预算，保证不会原地重问
        asked_list = [q for q in answers.keys()]
    try:
        result = run_pipeline(text, slots, asked_list)
    except Exception as e:  # noqa: BLE001
        return jsonify({"status": "error", "error": "pipeline_error",
                        "message": f"{type(e).__name__}: {e}", "steps": []}), 500
    with _lock:
        _store_session(result)
    return jsonify(result)


@app.post("/api/confirm")
def api_confirm():
    """用户确认修复项：accepted: [repair_id, ...] → 应用 → 重验证。"""
    data = request.get_json(force=True, silent=True) or {}
    accepted = data.get("accepted", []) or []
    with _lock:
        st = SESSIONS.get(_sid())
        if not st or "workflow" not in st:
            return jsonify({"status": "error", "error": "no_session"})
        wf = st["workflow"]
        repairs = st.get("repairs", [])
        w2, applied = apply_repairs(wf, repairs, accepted)
        v2 = verify_workflow(w2)
        v2_out = _clean_verify(v2)
        st["workflow"] = w2
        st["verify"] = v2_out
        st["applied"] = applied
        st["clean"] = not v2["defective"]
        # 更新管道阶段：defect_repair / workflow_output
        if st.get("steps"):
            for s in st["steps"]:
                if s["stage"] == "defect_repair":
                    s["status"] = "done"
                    s["note"] = (f"已应用 {len(applied)} 条修复，剩余 "
                                 + f"{len(v2['defects'])} 项缺陷" if v2["defective"]
                                 else f"已应用 {len(applied)} 条修复，验证通过")
                if s["stage"] == "workflow_output":
                    s["status"] = "done" if not v2["defective"] else "blocked"
                    s["note"] = "工作流输出就绪" if not v2["defective"] else "仍有缺陷"
        # 未自动修复项（manual_review）仍存在时给出提示
        pending_manual = [r for r in repairs
                          if r["repair_id"] in accepted and not r["auto"]]
        return jsonify({"status": "clean" if not v2["defective"] else "still_defective",
                        "workflow": w2, "verify": v2_out, "applied": applied,
                        "steps": st.get("steps"),
                        "pending_manual": pending_manual})


@app.post("/api/export")
def api_export():
    data = request.get_json(force=True, silent=True) or {}
    with _lock:
        wf = data.get("workflow") or (SESSIONS.get(_sid()) or {}).get("workflow")
    if not wf:
        return jsonify({"status": "error", "error": "no_workflow"})
    return jsonify({"status": "ok", "workflow": wf,
                    "json": json.dumps(wf, ensure_ascii=False, indent=2)})


@app.route("/webui/<path:filename>")
def webui_static(filename):
    resp = send_from_directory(WEBUI, filename)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"VeriFlow running at http://{host}:{port}  (webui={WEBUI})")
    app.run(host=host, port=port, debug=False, threaded=True)
