# -*- coding: utf-8 -*-
"""
VeriFlow NL2JSON Converter
==========================
把用户的自然语言工作流描述转换为标准化 JSON 工作流（节点、边、条件、消息）。
两层策略：
  1. 规则引擎（内置模板库 + 步骤/条件/循环/消息识别）—— 离线可跑通，保证演示闭环；
  2. 可选 LLM 通道（用户配置 API 后启用，规则引擎结果作为 fallback 与校验）。
在必要处返回 clarify 问题（需求歧义确认），而不是一次性盲目生成。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 内置模板库：高质量的通用工作流骨架（按用户描述中的主题词匹配）
# ---------------------------------------------------------------------------
TEMPLATES: Dict[str, Dict[str, Any]] = {
    "leave": {
        "name": "学生请假审批流程",
        "nodes": [
            {"id": "n1", "type": "task", "name": "提交请假申请"},
            {"id": "n2", "type": "if", "name": "请假天数判断", "condition": "days <= 3",
             "then": {"id": "n3", "type": "task", "name": "辅导员审批"},
             "else": {"id": "n4", "type": "task", "name": "学院审批"}},
            {"id": "n5", "type": "message", "name": "通知学生结果", "sender": "系统",
             "pairing": "send_only", "platform": "internal"},
            {"id": "n6", "type": "task", "name": "登记请假记录"},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3", "branch": "true"},
            {"from": "n2", "to": "n4", "branch": "false"},
            {"from": "n3", "to": "n5"},
            {"from": "n4", "to": "n5"},
            {"from": "n5", "to": "n6"},
        ],
        "keywords": ["请假", "审批", "假条", "leave"],
    },
    "order": {
        "name": "订单异常处理流程",
        "nodes": [
            {"id": "n1", "type": "task", "name": "接收订单"},
            {"id": "n2", "type": "if", "name": "库存校验", "condition": "stock >= qty",
             "then": {"id": "n3", "type": "task", "name": "发货"},
             "else": {"id": "n4", "type": "task", "name": "通知补货"}},
            {"id": "n5", "type": "message", "name": "通知客户", "sender": "订单系统",
             "pairing": "send_only", "platform": "internal"},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3", "branch": "true"},
            {"from": "n2", "to": "n4", "branch": "false"},
            {"from": "n3", "to": "n5"},
            {"from": "n4", "to": "n5"},
        ],
        "keywords": ["订单", "库存", "发货", "order"],
    },
    "content": {
        "name": "内容发布审批流程",
        "nodes": [
            {"id": "n1", "type": "task", "name": "编辑起草内容"},
            {"id": "n2", "type": "if", "name": "是否需要审核", "condition": "needs_review",
             "then": {"id": "n3", "type": "task", "name": "主管审核"}},
            {"id": "n4", "type": "message", "name": "发布通知", "sender": "内容系统",
             "pairing": "send_only", "platform": "internal"},
            {"id": "n5", "type": "task", "name": "正式发布"},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3", "branch": "true"},
            {"from": "n3", "to": "n4"},
            {"from": "n2", "to": "n4", "branch": "false"},
            {"from": "n4", "to": "n5"},
        ],
        "keywords": ["内容", "发布", "审核", "文章", "文案", "content"],
    },
    "report": {
        "name": "定时数据日报流程",
        "nodes": [
            {"id": "n1", "type": "while", "name": "每日循环", "condition": "schedule",
             "exit": True,
             "body": {"id": "n2", "type": "task", "name": "拉取业务数据"}},
            {"id": "n3", "type": "task", "name": "生成报表"},
            {"id": "n4", "type": "message", "name": "推送日报", "sender": "数据服务",
             "pairing": "send_only", "platform": "internal"},
        ],
        "edges": [
            {"from": "n1", "to": "n3", "branch": "exit"},
            {"from": "n3", "to": "n4"},
        ],
        "keywords": ["日报", "数据", "定时", "循环", "report", "daily"],
    },
    "ticket": {
        "name": "工单处理流程",
        "nodes": [
            {"id": "n1", "type": "task", "name": "创建工单"},
            {"id": "n2", "type": "if", "name": "优先级判断", "condition": "priority == high",
             "then": {"id": "n3", "type": "task", "name": "立即响应"},
             "else": {"id": "n4", "type": "task", "name": "排队处理"}},
            {"id": "n5", "type": "task", "name": "处理工单"},
            {"id": "n6", "type": "task", "name": "标记完成"},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3", "branch": "true"},
            {"from": "n2", "to": "n4", "branch": "false"},
            {"from": "n3", "to": "n5"},
            {"from": "n4", "to": "n5"},
            {"from": "n5", "to": "n6"},
        ],
        "keywords": ["工单", "ticket", "客服", "故障", "反馈"],
    },
    "notify": {
        "name": "客户消息通知流程",
        "nodes": [
            {"id": "n1", "type": "task", "name": "读取客户事件"},
            {"id": "n2", "type": "message", "name": "发送通知", "sender": "客服系统",
             "pairing": "send_only", "platform": "internal"},
        ],
        "edges": [{"from": "n1", "to": "n2"}],
        "keywords": ["通知", "消息", "提醒", "notify", "alert", "推送"],
    },
    "customs": {
        "name": "海关一体化通关流程",
        "nodes": [
            {"id": "n1", "type": "task", "name": "申报数据接收（单一窗口）"},
            {"id": "n2", "type": "task", "name": "电子审单（系统自动审核单证）"},
            {"id": "n3", "type": "if", "name": "风险布控判定", "condition": "risk_level == high",
             "then": {"id": "n4", "type": "task", "name": "布控查验（人工查验）"},
             "else": {"id": "n5", "type": "task", "name": "系统自动放行"}},
            {"id": "n6", "type": "task", "name": "税费核算（关税与增值税）"},
            {"id": "n7", "type": "message", "name": "放行通知", "sender": "海关系统",
             "pairing": "send_only", "platform": "internal"},
            {"id": "n8", "type": "task", "name": "放行归档与数据回流"},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4", "branch": "true"},
            {"from": "n3", "to": "n5", "branch": "false"},
            {"from": "n4", "to": "n6"},
            {"from": "n5", "to": "n6"},
            {"from": "n6", "to": "n7"},
            {"from": "n7", "to": "n8"},
        ],
        "keywords": ["海关", "报关", "通关", "一体化", "口岸", "查验", "保税", "审单", "放行", "customs"],
    },
}

# 通用解析：步骤 / 条件 / 循环 / 消息 的启发式切分
_STEP_SPLIT = re.compile(r"[，。；;,.、\n]|(?:首先|然后|接着|再|最后|同时|之后|随后)")
_IF_RE = re.compile(r"如果|若|假如|当.*?(?:时|后)|除非|要是")
_ELSE_RE = re.compile(r"否则|不然|要不然|否则的话")
_LOOP_RE = re.compile(r"重复|循环|每天|每周|定时|直到|每隔|批量|分批")
_MSG_RE = re.compile(r"通知|发送|邮件|短信|推送|提醒|钉钉|微信|飞书|消息|公告")
_ACTION_VERB_RE = re.compile(r"(提交|审批|审核|创建|发送|通知|处理|生成|校验|登记|发布|读取|更新|确认|归档|复核|签名|答复)")
# “AI 自己生成”指令（用户没想好时）：不把指令句当作任务名
_SELF_GEN_RE = re.compile(r"(你自己|你来|帮我(?:设计|生成|做|弄)|随便(?:生成|设计|来)|没想好|想不出来|设计一个|生成一个|全权|全面考虑)")


def detect_intent(text: str) -> Dict[str, Any]:
    """意图识别：返回 {template_id?, steps, has_cond, has_loop, has_msg, ambiguity}"""
    intent: Dict[str, Any] = {"steps": [], "has_cond": False, "has_loop": False,
                              "has_msg": False, "template_id": None, "ambiguity": [],
                              "self_generate": False}
    t = text.strip()
    # 0) “AI 自生成”指令标记（用户没想好 → 由主题词导向模板，否则澄清主题）
    if _SELF_GEN_RE.search(t):
        intent["self_generate"] = True
    # 1) 模板命中（主题词优先）
    for tid, tmpl in TEMPLATES.items():
        if any(kw in t for kw in tmpl["keywords"]):
            intent["template_id"] = tid
            break
    if intent.get("self_generate") and intent["template_id"] is None:
        intent["ambiguity"].append("need_topic")
    # 2) 结构启发式
    if _IF_RE.search(t):
        intent["has_cond"] = True
    if _LOOP_RE.search(t):
        intent["has_loop"] = True
    if _MSG_RE.search(t):
        intent["has_msg"] = True
    # 3) 动作步骤提取
    pieces = [p.strip() for p in _STEP_SPLIT.split(t) if p and p.strip()]
    for p in pieces:
        if _ACTION_VERB_RE.search(p):
            intent["steps"].append(p)
    if not intent["steps"] and not intent["template_id"]:
        intent["ambiguity"].append("no_action")
    if len(pieces) == 1 and not intent["template_id"]:
        intent["ambiguity"].append("too_vague")
    return intent


def clarify_questions(text: str) -> List[Dict[str, Any]]:
    """需求歧义时返回澄清问题（必要处确认，而非一次性盲目生成）。"""
    intent = detect_intent(text)
    qs: List[Dict[str, Any]] = []
    if intent["template_id"] is None and "no_action" in intent["ambiguity"]:
        qs.append({
            "id": "q_action", "phase": "requirements_clarification",
            "question": "请补充工作流要完成的动作（如：提交申请→审批→通知）",
            "options": None})
    if intent["template_id"] is None and "too_vague" in intent["ambiguity"]:
        qs.append({
            "id": "q_topic", "phase": "requirements_clarification",
            "question": "请补充工作流主题（如：请假审批 / 订单处理 / 内容发布 / 数据日报 / 工单处理 / 消息通知）",
            "options": list(TEMPLATES.keys())})
    if intent.get("self_generate") and "need_topic" in intent["ambiguity"]:
        qs.append({
            "id": "q_topic", "phase": "requirements_clarification",
            "question": "你想让我生成哪个场景的工作流？我会根据主题自动补齐完整步骤并验证（如：海关一体化通关 / 请假审批 / 订单处理 / 数据日报）",
            "options": list(TEMPLATES.keys())})
    if intent["has_cond"] and not _ELSE_RE.search(text) and not intent["template_id"]:
        qs.append({
            "id": "q_else", "phase": "requirements_clarification",
            "question": "条件不满足时如何处理？系统将默认生成 else 分支连接正常终点（missing-branch 缺陷修复策略）。",
            "options": ["默认生成 else", "不需要 else 分支"]})
    if intent["has_msg"] and intent["template_id"] is None:
        qs.append({
            "id": "q_msg_platform", "phase": "requirements_clarification",
            "question": "消息通过哪个平台发送？（影响适配器语义：n8n/Dify/Coze）",
            "options": ["n8n", "Dify", "Coze", "内部系统"]})
    return qs


def _make_id(i: int) -> str:
    return f"n{i}"


def build_from_template(tid: str, text: str) -> Dict[str, Any]:
    """模板实例化：复制模板并回填用户描述中的关键名词（人名/部门等）。"""
    import copy
    wf = copy.deepcopy(TEMPLATES[tid])
    wf["name"] = f"{wf['name']}（由用户描述生成）"
    wf["description"] = text.strip()
    wf["version"] = "1.0"
    wf["source"] = "nl2json_rule_engine"
    return wf


def build_generic(intent: Dict[str, Any], text: str) -> Dict[str, Any]:
    """通用解析：把提取的步骤拼成顺序链；命中 if/loop/msg 时插入对应节点。"""
    steps = intent["steps"]
    # 过滤“AI 自生成”指令片段（“你自己生成一个工作流”等不是流程步骤）
    if intent.get("self_generate"):
        steps = [s for s in steps if not _SELF_GEN_RE.search(s)]
    if not steps:
        steps = ["开始"]
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    prev_id: Optional[str] = None

    def add_task(name: str, i: int) -> str:
        nid = _make_id(i)
        nodes.append({"id": nid, "type": "task", "name": name})
        return nid

    idx = 0
    for step in steps:
        if prev_id is not None:
            edges.append({"from": prev_id, "to": _make_id(idx)})
        nid = add_task(step, idx)
        prev_id = nid
        idx += 1
    return {"name": "通用工作流", "description": text.strip(), "version": "1.0",
            "source": "nl2json_rule_engine", "nodes": nodes, "edges": edges}


def nl2json(text: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str]:
    """
    主入口：自然语言 → (标准化JSON, 澄清问题列表, 阶段说明)。
    优先级：LLM（DeepSeek，需 DEEPSEEK_API_KEY）→ 规则模板 → 通用解析。
    返回的 JSON 是标准形式（与 adapters 输出同构），可直接送入 preprocess → JCPN。
    """
    import os
    intent = detect_intent(text)
    questions = clarify_questions(text)

    # 1) LLM 优先（如果配了 key）
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    wf: Optional[Dict[str, Any]] = None
    stage = "rule"
    if api_key:
        try:
            wf = llm_json(text)
            stage = "llm"
        except Exception as e:  # noqa: BLE001
            # LLM 失败，回退规则引擎；把原因记在 stage 里方便调试
            stage = f"llm_fallback({type(e).__name__})"

    # 2) 规则引擎兜底
    if wf is None:
        if intent["template_id"]:
            wf = build_from_template(intent["template_id"], text)
            stage = stage if "fallback" in stage else "template"
        else:
            wf = build_generic(intent, text)
            stage = stage if "fallback" in stage else "generic"

    wf.setdefault("version", "1.0")
    wf.setdefault("nodes", [])
    wf.setdefault("edges", [])
    return wf, questions, stage


# ---------------------------------------------------------------------------
# 可选 LLM 通道（配置 OPENAI_API_KEY / 自定义 endpoint 后启用）
# ---------------------------------------------------------------------------
def llm_json(text: str, api_key: Optional[str] = None,
             endpoint: Optional[str] = None,
             model: Optional[str] = None) -> Dict[str, Any]:
    """调用外部 LLM 生成 JSON；失败时抛异常，由调用方回退规则引擎。

    默认走 DeepSeek（OpenAI 兼容协议），从环境变量读配置：
      DEEPSEEK_API_KEY   必填
      DEEPSEEK_BASE_URL  默认 https://api.deepseek.com/v1
      DEEPSEEK_MODEL     默认 deepseek-chat（V3）
    """
    import os
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    endpoint = endpoint or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1"
    model = model or os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat"
    if not api_key:
        raise RuntimeError("no_api_key")
    import urllib.request
    url = endpoint.rstrip("/") + "/chat/completions"
    system = (
        "You are a workflow compiler. Convert the user's natural-language workflow "
        "description into a normalized JSON workflow. Output ONLY a JSON object with keys "
        "{name, nodes, edges}. node.type ∈ {task,message,if,while}. "
        "task node: {id,type,name}. "
        "message node: {id,type,name,sender,pairing:'send_only',platform:'internal'}. "
        "if node: {id,type,name,condition,then:{id,type,name},else:{id,type,name}} (else optional). "
        "while node: {id,type,name,condition,exit:true,body:{id,type,name}}. "
        "edges: [{from,to,branch?}] where branch ∈ {true,false,exit}. "
        "Use ids n1,n2,... sequentially. Build a coherent flow from the user's description; "
        "do NOT copy any template. If the user's description is vague, still produce a "
        "reasonable generic workflow and the clarification questions can be handled separately."
    )
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": text}],
        "temperature": 0.2,
        "max_tokens": 1200,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        raise ValueError("llm_no_json")
    wf = json.loads(m.group(0))
    wf.setdefault("name", "LLM-generated workflow")
    wf.setdefault("nodes", [])
    wf.setdefault("edges", [])
    wf["source"] = "nl2json_llm"
    wf["llm_model"] = model
    return wf


if __name__ == "__main__":
    for sample in ["学生请假审批流程，三天以内辅导员审批，超过三天学院审批，通过后通知学生并登记",
                   "订单来了先校验库存，够就发货，不够通知补货，最后都通知客户",
                   "每天早上拉取业务数据，生成报表，推送日报",
                   "帮我处理个流程"]:
        w, qs, st = nl2json(sample)
        print(f"[{st}] {sample}")
        print("  clarify:", [(q["id"], q["question"]) for q in qs])
        print("  nodes:", [(n["id"], n["type"]) for n in w["nodes"]])
        print("  edges:", w["edges"][:6])
        print()
