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
from typing import Iterable, Any, Dict, List, Optional, Tuple


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

TEMPLATE_EN = {
    "leave": "Student leave approval",
    "order": "Order exception handling",
    "content": "Content publishing approval",
    "report": "Daily report generation",
    "ticket": "Ticket handling",
    "notify": "Customer message notification",
    "customs": "Integrated customs clearance",
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


def resolve_topic(topic: str) -> Optional[str]:
    """自由主题 → 模板 id。

    先按模板 id / 模板名精确匹配，再按关键字与名称包含匹配。匹配不上返回 None，
    由调用方走"主题骨架"路径——绝不把用户给的主题当成歧义再问一遍。
    """
    if not topic:
        return None
    t = topic.strip().lower()
    if not t:
        return None
    for tid, tmpl in TEMPLATES.items():
        name = str(tmpl.get("name", "")).lower()
        if t == tid or (name and t == name):
            return tid
        if any(str(kw).lower() in t for kw in tmpl.get("keywords", [])):
            return tid
    return None


def detect_intent(text: str, slots: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """意图识别：返回 {template_id?, topic?, steps, has_cond, has_loop, has_msg, ambiguity}

    slots 是澄清阶段的结构化回答（topic / action / else / msg_platform）。
    主题槽位一旦给出：即便原文是"你帮我生成一个流程"，也不再判为缺主题。
    """
    slots = slots or {}
    intent: Dict[str, Any] = {"steps": [], "has_cond": False, "has_loop": False,
                              "has_msg": False, "template_id": None, "ambiguity": [],
                              "self_generate": False, "topic": None,
                              "template_source": None}
    t = text.strip()
    topic = str(slots.get("topic") or "").strip()
    if topic:
        intent["topic"] = topic
        tid = resolve_topic(topic)
        if tid:
            intent["template_id"] = tid
            intent["template_source"] = "clarification"
        intent["self_generate"] = False
    # 0) “AI 自生成”指令标记（用户没想好 → 由主题词导向模板，否则澄清主题）
    if _SELF_GEN_RE.search(t):
        intent["self_generate"] = True
    # 1) 模板命中（主题词优先）
    if intent["template_id"] is None:
        for tid, tmpl in TEMPLATES.items():
            if any(kw in t for kw in tmpl["keywords"]):
                intent["template_id"] = tid
                intent["template_source"] = "text_keyword"
                break
    if (intent.get("self_generate") and intent["template_id"] is None
            and not intent.get("topic")):
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


def clarify_questions(text: str, slots: Optional[Dict[str, Any]] = None,
                      asked: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """需求歧义时返回澄清问题（必要处确认，而非一次性盲目生成）。

    两条收敛保证：
    - 已经有结构化回答的问题不再问（slot 已填）；
    - 同一个 question id 只问一次（asked 预算），第二轮强制生成。
    """
    slots = slots or {}
    asked_set = set(asked or ())
    intent = detect_intent(text, slots)
    topic_options = [TEMPLATES[k]["name"] for k in TEMPLATES]
    topic_options_en = [TEMPLATE_EN[k] for k in TEMPLATES]
    # 同一轮内按 id 去重：一个 id 只对应一个问法（vague 与自生成两条规则可能同时命中）
    cand: Dict[str, Dict[str, Any]] = {}
    if (intent["template_id"] is None and not intent.get("topic")
            and "no_action" in intent["ambiguity"]
            and not slots.get("action") and "q_action" not in asked_set):
        cand["q_action"] = {
            "id": "q_action", "phase": "requirements_clarification",
            "question": "请补充工作流要完成的动作（如：提交申请→审批→通知）",
            "question_en": "Which actions should the workflow perform? (e.g. submit → approve → notify)",
            "options": None, "options_en": None}
    if (intent["template_id"] is None and not intent.get("topic")
            and "too_vague" in intent["ambiguity"] and "q_topic" not in asked_set):
        cand["q_topic"] = {
            "id": "q_topic", "phase": "requirements_clarification",
            "question": "请补充工作流主题（如：请假审批 / 订单处理 / 内容发布 / 数据日报 / 工单处理 / 消息通知）",
            "question_en": "Which scenario should the workflow model? (e.g. leave approval / order handling / daily report)",
            "options": topic_options, "options_en": topic_options_en}
    if (intent.get("self_generate") and "need_topic" in intent["ambiguity"]
            and "q_topic" not in asked_set):
        # 自生成场景的问法更具体，覆盖 vague 版本（同一个 id 只保留一条）
        cand["q_topic"] = {
            "id": "q_topic", "phase": "requirements_clarification",
            "question": "你想让我生成哪个场景的工作流？我会根据主题自动补齐完整步骤并验证（如：海关一体化通关 / 请假审批 / 订单处理 / 数据日报）",
            "question_en": "Which scenario should I build? I will fill in the steps from that topic and verify them (e.g. customs clearance / leave approval / order handling / daily report).",
            "options": topic_options, "options_en": topic_options_en}
    if (intent["has_cond"] and not _ELSE_RE.search(text)
            and not intent["template_id"] and not slots.get("else")
            and "q_else" not in asked_set):
        cand["q_else"] = {
            "id": "q_else", "phase": "requirements_clarification",
            "question": "条件不满足时如何处理？系统将默认生成 else 分支连接正常终点（missing-branch 缺陷修复策略）。",
            "question_en": "What happens when the condition is false? A default else branch to the normal end is generated (the missing-branch repair strategy).",
            "options": ["默认生成 else", "不需要 else 分支"],
            "options_en": ["Generate a default else branch", "No else branch needed"]}
    if (intent["has_msg"] and intent["template_id"] is None
            and not slots.get("msg_platform") and "q_msg_platform" not in asked_set):
        cand["q_msg_platform"] = {
            "id": "q_msg_platform", "phase": "requirements_clarification",
            "question": "消息通过哪个平台发送？（影响适配器语义：n8n/Dify/Coze）",
            "question_en": "Which platform sends the message? (affects adapter semantics: n8n / Dify / Coze)",
            "options": ["n8n", "Dify", "Coze", "内部系统"],
            "options_en": ["n8n", "Dify", "Coze", "Internal system"]}
    order = ["q_action", "q_topic", "q_else", "q_msg_platform"]
    return [cand[k] for k in order if k in cand]


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


def build_topic_skeleton(intent: Dict[str, Any], text: str) -> Dict[str, Any]:
    """主题已确定、但不在模板库时的最小骨架。

    只有三步，且在 assumptions 里显式声明"步骤是骨架、业务细节未补齐"——
    宁可交一个标注清楚的粗工作流，也不假装读懂了用户没说的动作。
    """
    topic = intent.get("topic") or "业务流程"
    steps = [f"受理{topic}的业务请求", f"执行{topic}的核心业务处理",
             "归档处理结果并向用户反馈"]
    nodes = [{"id": _make_id(i), "type": "task", "name": name}
             for i, name in enumerate(steps)]
    edges = [{"from": _make_id(i), "to": _make_id(i + 1)} for i in range(len(steps) - 1)]
    return {
        "name": f"{topic}工作流（骨架）",
        "description": text.strip(),
        "version": "1.0",
        "source": "nl2json_topic_skeleton",
        "assumptions": [
            "主题由用户澄清阶段给出，未命中内置模板",
            "步骤为最小骨架（受理/执行/归档），具体业务动作需要用户补充",
        ],
        "nodes": nodes,
        "edges": edges,
    }


_ALLOWED_NODE_TYPES = {"task", "message", "if", "while"}


def _node_id_set(nodes: List[Any], edges: List[Any]) -> set:
    """收集合法节点 id（含 if/while 内联的 then/else/body 子节点）。

    LLM 可能把分支子节点写成内联对象而不在 nodes 里重复列出；只要边引用的 id
    能在任何一处找到，就认为引用是完整的。
    """
    ids: set = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        nid = node.get("id")
        if isinstance(nid, str) and nid:
            ids.add(nid)
        for key in ("then", "else", "body"):
            walk(node.get(key))

    for n in nodes:
        walk(n)
    return ids


def _validate_llm_workflow(wf: Any) -> None:
    """校验 LLM 输出是否可以安全送入 preprocess → JCPN。

    只做必要约束（类型合法、id 唯一、if/while 带条件、边不悬空），
    不通过就抛 ValueError，由调用方回退规则引擎——错误不会被静默吞掉。
    """
    if not isinstance(wf, dict):
        raise ValueError("llm_not_object")
    nodes = wf.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("llm_nodes_empty")
    edges = wf.get("edges") or []
    if not isinstance(edges, list):
        raise ValueError("llm_edges_not_list")
    seen: set = set()

    def check(node: Any) -> None:
        if not isinstance(node, dict):
            raise ValueError("llm_node_not_object")
        nid = node.get("id")
        ntype = node.get("type")
        if not isinstance(nid, str) or not nid:
            raise ValueError("llm_node_without_id")
        if nid in seen:
            raise ValueError(f"llm_duplicate_node_id:{nid}")
        seen.add(nid)
        if ntype not in _ALLOWED_NODE_TYPES:
            raise ValueError(f"llm_bad_node_type:{ntype}")
        if ntype == "if":
            if not str(node.get("condition") or "").strip():
                raise ValueError(f"llm_if_without_condition:{nid}")
            for key in ("then", "else"):
                if node.get(key) is not None:
                    check(node[key])
        if ntype == "while":
            if not str(node.get("condition") or "").strip():
                raise ValueError(f"llm_while_without_condition:{nid}")
            if not isinstance(node.get("body"), dict):
                raise ValueError(f"llm_while_without_body:{nid}")

    for n in nodes:
        check(n)
    ids = _node_id_set(nodes, edges)
    for e in edges:
        if not isinstance(e, dict):
            raise ValueError("llm_edge_not_object")
        src, dst = e.get("from"), e.get("to")
        if src not in ids or dst not in ids:
            raise ValueError(f"llm_edge_dangling:{src}->{dst}")


def nl2json(text: str, slots: Optional[Dict[str, Any]] = None,
            asked: Optional[Iterable[str]] = None,
            allow_questions: bool = True) -> Tuple[Dict[str, Any], List[Dict[str, Any]], str]:
    """
    主入口：自然语言 → (标准化JSON, 澄清问题列表, 阶段说明)。
    优先级：LLM（DeepSeek，需 DEEPSEEK_API_KEY）→ 规则模板 → 通用解析。
    返回的 JSON 是标准形式（与 adapters 输出同构），可直接送入 preprocess → JCPN。
    """
    import os
    slots = slots or {}
    parse_text = text
    if slots.get("action"):
        parse_text = f"{text}。{slots['action']}"
    intent = detect_intent(parse_text, slots)
    questions = (clarify_questions(parse_text, slots, asked)
                 if allow_questions else [])

    # 1) LLM 优先（如果配了 key）；主题槽位一并告诉模型
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    wf: Optional[Dict[str, Any]] = None
    stage = "rule"
    if api_key:
        try:
            llm_text = parse_text
            if intent.get("topic"):
                llm_text = f"{parse_text}（工作流主题：{intent['topic']}）"
            candidate = llm_json(llm_text)
            _validate_llm_workflow(candidate)   # 先校验，通过后才采用
            wf = candidate
            stage = "llm"
        except Exception as e:  # noqa: BLE001
            # LLM 失败，回退规则引擎；把原因记在 stage 里方便调试
            stage = f"llm_fallback({type(e).__name__})"

    # 2) 规则引擎兜底：模板 → 主题骨架 → 通用解析
    if wf is None:
        if intent["template_id"]:
            wf = build_from_template(intent["template_id"], parse_text)
            stage = stage if "fallback" in stage else "template"
        elif intent.get("topic"):
            wf = build_topic_skeleton(intent, parse_text)
            stage = stage if "fallback" in stage else "generic_from_topic"
        else:
            wf = build_generic(intent, parse_text)
            stage = stage if "fallback" in stage else "generic"

    # 消息平台槽位：显式写到消息节点上（不覆盖已有声明）
    if slots.get("msg_platform"):
        for n in wf.get("nodes", []):
            if n.get("type") == "message":
                n.setdefault("platform", str(slots["msg_platform"]))

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
