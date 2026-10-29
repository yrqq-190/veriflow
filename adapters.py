# -*- coding: utf-8 -*-
"""
VeriFlow: 平台适配器（真实平台工作流 → 标准化 JSON）
========================================================
将 n8n（nodes+connections）、Dify（DSL YAML）、Coze（低代码 JSON）的
真实工作流转换为 VeriFlow 标准 JSON 中间表示：

    {
      "version": "1.0",
      "name": str, "platform": "n8n|dify|coze", "source": str,
      "nodes": [{ "id", "type": "task|message|if|while", "name", ... }],
      "edges": [{ "from", "to", "branch": "true"|"false"|null }]
    }

语义约定（对应论文 §3.3.2 消息适配器）：
  - 触发/入口节点（webhook、manualTrigger 等）→ task 入口（is_entry 标注）
  - 通知类发送节点（gmail/slack/telegram/email…）→ message{pairing:"send_only"}
    —— send-only 交互，验证层按平台语义放行（不判 broken）；
  - 条件节点（n8n if / Dify if-else / Coze condition）→ if
    —— 分支由 edges.branch 表达（扁平模式，true/false），缺失分支即缺陷；
  - 循环节点（Dify iteration / n8n loop / Coze loop）→ while{exit:true}
    —— body 嵌套（若平台 DSL 内嵌子节点）或空体（仅保留结构，标注局限）；
  - 其余执行节点 → task。

缺陷注入的真实负样本由 defect_injector 在标准 JSON 层构造（见 defect_injector.py 与 run_balanced_experiment.py）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

try:
    import yaml  # Dify DSL 解析
except Exception:  # pragma: no cover
    yaml = None


# ===========================================================================
# 1. n8n 适配器
# ===========================================================================

_N8N_IF = {"n8n-nodes-base.if"}
_N8N_SEND_HINTS = (
    "gmail", "slack", "telegram", "smtp", "sendgrid", "twilio",
    "whatsapp", "discord", "email", "sendMessage", "sendEmail",
)
_N8N_TRIGGER_HINTS = ("trigger", "Trigger", "webhook", "Webhook")
_N8N_LOOP = ("splitInBatches", "loopOverItems", "executeWorkflow")


def _n8n_kind(node: Dict[str, Any]) -> str:
    """n8n 节点类型 → 标准类型（task / message / if / while）"""
    t = node.get("type", "")
    if t in _N8N_IF:
        return "if"
    if any(h in t for h in _N8N_SEND_HINTS):
        return "message"
    if any(h in t for h in _N8N_LOOP):
        return "while"
    return "task"


def _n8n_guard(node: Dict[str, Any]) -> str:
    """从 if 节点的 conditions 提取可读守卫描述（真值判定交给 Θ_cond 分裂）"""
    try:
        conds = node["parameters"]["conditions"]["conditions"]
        parts = []
        for c in conds:
            op = c.get("operator", {}).get("operation", "?")
            parts.append(f"{c.get('leftValue', '?')} {op} {c.get('rightValue', '')}")
        return " and ".join(parts) or "cond"
    except Exception:
        return "cond"


def parse_n8n(raw: Dict[str, Any], source: str = "") -> Dict[str, Any]:
    """
    n8n 导出 JSON → 标准 JSON。
    connections 按节点 name 索引：main[0]=true 输出（if），main[1]=false。
    stickyNote 等非执行节点被过滤；悬空引用跳过（保留为 preprocess 检查对象）。
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    name_to_id: Dict[str, str] = {}
    kept: List[Dict[str, Any]] = []
    for n in raw.get("nodes", []):
        if n.get("type") == "n8n-nodes-base.stickyNote":
            continue
        kept.append(n)
        name_to_id[n.get("name", "")] = n.get("id", "")

    # 触发节点判定（入口）
    for n in kept:
        t = n.get("type", "")
        is_trigger = any(h in t for h in _N8N_TRIGGER_HINTS) and "stickyNote" not in t
        if is_trigger and "Trigger" not in t and "trigger" not in t:
            is_trigger = False
        kind = _n8n_kind(n)
        std: Dict[str, Any] = {"id": n["id"], "type": kind, "name": n.get("name", n["id"])}
        if kind == "message":
            std["pairing"] = "send_only"      # 通知型发送，平台正常语义
            std["platform"] = "n8n"
            std["direction"] = "out"
            std["sender"] = n.get("type", "").split(".")[-1]
        elif kind == "if":
            std["guard"] = _n8n_guard(n)
        elif kind == "while":
            std["exit"] = True                # 循环节点自身具备出口语义
            std["loop_hint"] = n.get("type", "")
        if is_trigger:
            std["is_entry"] = True
        nodes.append(std)

    conns = raw.get("connections", {})
    id_to_n8n = {n["id"]: n.get("type", "") for n in kept}
    main_edges: List[Dict[str, Any]] = []
    aux_refs: set = set()
    for src_name, outputs in conns.items():
        src_id = name_to_id.get(src_name)
        if src_id is None:
            continue
        src_kind = _n8n_kind({"type": id_to_n8n.get(src_id, "")})
        for port, groups in outputs.items():
            # n8n 端口输出为数组的数组：main[0]=true 分支、main[1]=false 分支
            for idx, targets in enumerate(groups):
                for tgt in targets:
                    tgt_name = tgt.get("node")
                    tgt_id = name_to_id.get(tgt_name)
                    if tgt_id is None:
                        continue
                    if port == "main":
                        branch = None
                        if src_kind == "if":
                            branch = "true" if idx == 0 else "false"
                        main_edges.append({"from": src_id, "to": tgt_id, "branch": branch})
                    else:
                        # 非 main 端口（ai_languageModel 等）：子模型/配置关系，非流程边
                        aux_refs.add(src_id)
                        aux_refs.add(tgt_id)
    in_main = set()
    for e in main_edges:
        in_main.add(e["from"])
        in_main.add(e["to"])
    # 仅通过非 main 端口被引用、且不在 main 图内的节点 → 配置/子节点，排除
    kept_ids = {n["id"] for n in kept}
    dropped = sorted(aux_refs - in_main)
    nodes = [n for n in nodes if n["id"] not in dropped]
    for n in nodes:
        if n["id"] in dropped:
            pass
    edges = list(main_edges)

    # 多入口分支标记（n8n 常见模式：附加 manual trigger 的独立分支）。
    # 主入口取最小 id（与 jcpn_builder._assign_boundary_markings 同规则），
    # 其余无入边入口出发的连通分量整体标记 is_alt_entry，验证层豁免不可达误报。
    in_deg = {n["id"]: 0 for n in nodes}
    for e in edges:
        if e["to"] in in_deg:
            in_deg[e["to"]] += 1
    entries = [n["id"] for n in nodes if in_deg[n["id"]] == 0]
    if len(entries) > 1:
        main_entry = min(entries)
        adj: Dict[str, List[str]] = {}
        for e in edges:
            adj.setdefault(e["from"], []).append(e["to"])
        node_by_id = {n["id"]: n for n in nodes}
        for alt in entries:
            if alt == main_entry:
                continue
            stack, seen = [alt], set()
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                node_by_id[x]["is_alt_entry"] = True
                stack.extend(adj.get(x, []))

    return {
        "version": "1.0",
        "name": raw.get("name", "n8n workflow"),
        "platform": "n8n",
        "source": source,
        "nodes": nodes,
        "edges": edges,
    }


# ===========================================================================
# 2. Dify 适配器（DSL YAML）
# ===========================================================================

_DIFY_TASK_TYPES = (
    "llm", "code", "http-request", "template-transform", "tool",
    "knowledge-retrieval", "question-classifier", "parameter-extractor",
    "document-extractor", "variable-aggregator", "assigner", "agent",
)
_DIFY_IF = "if-else"
_DIFY_ITERATION = ("iteration", "iteration-start")
_DIFY_ANSWER = "answer"


def _dify_guard(node_data: Dict[str, Any]) -> str:
    try:
        cases = node_data.get("cases", [])
        descs = []
        for c in cases:
            conds = c.get("conditions", [])
            parts = []
            for cc in conds:
                sel = cc.get("variable_selector", [])
                parts.append(f"{sel[-1] if sel else '?'} {cc.get('comparison_operator', '?')} {cc.get('value', '')}")
            descs.append(" AND ".join(parts))
        return " / ".join(descs) or "cond"
    except Exception:
        return "cond"


def parse_dify(dsl_text: str, source: str = "") -> Dict[str, Any]:
    """
    Dify DSL（YAML）→ 标准 JSON。
    graph.edges 按 sourceHandle（true/false/source）表达分支；
    iteration 节点：映射为 while{exit:true}，body 留空（Dify 迭代体内节点
    不在该节点下嵌套，标注局限，见 balanced_experiment_report.md）。
    """
    if yaml is None:
        raise RuntimeError("pyyaml is required to parse Dify DSL")
    data = yaml.safe_load(dsl_text)
    graph = data.get("workflow", {}).get("graph", {})
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    if_node_ids: set = set()

    for n in graph.get("nodes", []):
        d = n.get("data", {})
        nid = str(n.get("id") or d.get("id") or "")
        if not nid:
            continue
        # custom-note 是画布注释/便签，不是可执行节点，跳过
        if n.get("type") == "custom-note" or d.get("type") == "custom-note":
            continue
        t = d.get("type", "")
        title = d.get("title", t)
        if t == "start":
            std: Dict[str, Any] = {"id": nid, "type": "task", "name": title, "is_entry": True}
        elif t == "end":
            std = {"id": nid, "type": "task", "name": title}
        elif t == _DIFY_IF:
            std = {"id": nid, "type": "if", "name": title, "guard": _dify_guard(d)}
            if_node_ids.add(nid)
        elif t in _DIFY_ITERATION:
            std = {"id": nid, "type": "while", "name": title, "exit": True,
                   "loop_hint": t, "body": None}
        elif t == _DIFY_ANSWER:
            std = {"id": nid, "type": "message", "name": title,
                   "sender": "bot", "pairing": "send_only",
                   "platform": "dify", "direction": "out"}
        else:
            std = {"id": nid, "type": "task", "name": title}
        nodes.append(std)

    for e in graph.get("edges", []):
        d = e.get("data", {}) or {}
        src = e.get("source") or d.get("source")
        tgt = e.get("target") or d.get("target")
        if not src or not tgt:
            continue
        sh = e.get("sourceHandle") if e.get("sourceHandle") is not None else d.get("sourceHandle")
        if sh == "true":
            branch = "true"
        elif sh == "false":
            branch = "false"
        elif str(src) in if_node_ids and sh not in (None, "source", ""):
            # Dify if-else 的额外 case 以 case UUID 作为 sourceHandle；
            # 二分支 JCPN 下降维归到 else 侧（c=false 互斥分支）
            branch = "false"
        else:
            branch = None
        edges.append({"from": str(src), "to": str(tgt), "branch": branch})

    return {
        "version": "1.0",
        "name": data.get("app", {}).get("name", "dify workflow"),
        "platform": "dify",
        "source": source,
        "nodes": nodes,
        "edges": edges,
    }


# ===========================================================================
# 3. Coze 适配器（低代码工作流导出 JSON）
# ===========================================================================
# 真实 Coze 导出（Hammer1/cozeworkflows 公开集，191 个官方导出 zip）节点类型编码：
#   '1' 开始  '2' 结束  '3' LLM  '4' 插件  '5' 代码  '8' 选择器(if)
#   '13' 输出(send_only 终端)  '15' 文本处理  '16' 图像生成  '21' 循环(loop)
#   '23' 画板  '28' 批处理(iteration)  '31' 便签(note,跳过)  '32' 变量聚合  '45' HTTP
# 分支由 edges.sourcePortID 表达：'true' / 'false'；循环出口端口 'loop-output' 不分支。
_COZE_NOTE = "31"
_COZE_SELECTOR = "8"
_COZE_OUTPUT = "13"
_COZE_WHILE = {"21", "28"}          # 循环 / 批处理 → while
_COZE_START = "1"
_COZE_END = "2"


def parse_coze(raw: Dict[str, Any], source: str = "") -> Dict[str, Any]:
    """
    Coze 低代码工作流 JSON（导出容器内提取的明文 JSON）→ 标准 JSON。

    节点类型为字符串数字编码（见模块注释）。画布便签（type=31）跳过；
    选择器（type=8）出边按 sourcePortID 分 true/false 分支；循环/批处理节点
    （type=21/28）映射为 while{exit:true}，循环体不嵌套（标注 body=None），
    与 Dify iteration 的扁平处理一致；输出节点（type=13）为 bot 单向 send_only
    终端，豁免消息断裂误报。
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    if_node_ids: set = set()

    for n in raw.get("nodes", []):
        t = str(n.get("type", ""))
        nid = str(n.get("id", ""))
        if not nid:
            continue
        if t == _COZE_NOTE:
            continue                      # 画布便签，非可执行节点
        d = n.get("data") or {}
        nm = d.get("nodeMeta") or {}
        title = nm.get("title") or t

        if t == _COZE_START:
            std: Dict[str, Any] = {"id": nid, "type": "task", "name": title,
                                   "is_entry": True}
        elif t == _COZE_END:
            std = {"id": nid, "type": "task", "name": title}
        elif t == _COZE_SELECTOR:
            std = {"id": nid, "type": "if", "name": title, "guard": "cond"}
            if_node_ids.add(nid)
        elif t in _COZE_WHILE:
            std = {"id": nid, "type": "while", "name": title, "exit": True,
                   "loop_hint": "loop" if t == "21" else "batch", "body": None}
        elif t == _COZE_OUTPUT:
            std = {"id": nid, "type": "message", "name": title,
                   "sender": "bot", "pairing": "send_only",
                   "platform": "coze", "direction": "out"}
        else:
            std = {"id": nid, "type": "task", "name": title}
        nodes.append(std)

    for e in raw.get("edges", []) or []:
        src = str(e.get("sourceNodeID", "") or "")
        tgt = str(e.get("targetNodeID", "") or "")
        if not src or not tgt:
            continue
        port = str(e.get("sourcePortID", "") or "")
        if port == "true":
            branch = "true"
        elif port == "false":
            branch = "false"
        else:
            branch = None                 # '' 或 'loop-output'：普通边
        edges.append({"from": src, "to": tgt, "branch": branch})

    return {
        "version": "1.0",
        "name": raw.get("name", "coze workflow"),
        "platform": "coze",
        "source": source,
        "nodes": nodes,
        "edges": edges,
    }


# ===========================================================================
# 4. 统一入口
# ===========================================================================

def adapt(platform: str, raw: Any, source: str = "") -> Dict[str, Any]:
    """按平台分派；返回标准 JSON（调用方负责 preprocess 校验）。"""
    p = platform.lower()
    if p == "n8n":
        return parse_n8n(raw, source)
    if p == "dify":
        return parse_dify(raw, source)
    if p == "coze":
        return parse_coze(raw, source)
    raise ValueError(f"unsupported platform: {platform}")


if __name__ == "__main__":
    import os, sys
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "real_samples")
    for fn in sorted(os.listdir(base)):
        if not fn.endswith((".json", ".yml")):
            continue
        path = os.path.join(base, fn)
        if fn.endswith(".yml"):
            std = parse_dify(open(path, encoding="utf-8").read(), fn)
        else:
            std = parse_n8n(json.load(open(path, encoding="utf-8")), fn)
        kinds = {}
        for n in std["nodes"]:
            kinds[n["type"]] = kinds.get(n["type"], 0) + 1
        ifs = sum(1 for e in std["edges"] if e["branch"] in ("true", "false"))
        print(f"{fn}: {len(std['nodes'])} nodes {len(std['edges'])} edges "
              f"kinds={kinds} branch_edges={ifs}")
