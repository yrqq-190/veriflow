# -*- coding: utf-8 -*-
"""
VeriFlow 预处理模块（对应论文 §2.2(2) JSON preprocessing）
=============================================================
只做语法规范化，不修复语义缺陷。语义缺陷（缺失分支、无出口循环、
断开连接等）被检测并标记后原样保留，交由验证阶段处理。

与论文定义的对应关系：
  - Definition 3-1: 规范化工作流 ζ = (S, E, O)
  - 三平台字段别名归一化（n8n / Dify / Coze）
  - 入口/终点节点三层判定（Appendix A）由 jcpn_builder._assign_boundary_markings 负责

模块接口（用户任务要求）：
  validate_required_fields(workflow)     检查必填字段，只报错不补全
  validate_identifiers(workflow)         检查 ID 唯一性和边引用完整性
  validate_structure(workflow)           检测 4 类结构异常，只标记不修复
  normalize_workflow_syntax(workflow)    字段名重命名、字符串清洗
  preprocess(raw_workflow)               主入口，返回 {workflow, errors, anomalies}
"""

import json
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

REQUIRED_NODE_FIELDS: Dict[str, List[str]] = {
    "task":    ["id", "type", "name"],
    # message: sender/receiver 允许缺省（unpaired 消息无对应接收方），
    #          由适配器语义在验证阶段判定 broken-message 候选
    "message": ["id", "type", "name", "sender"],
    # if: else 键不做必填 —— 缺失即 missing_branch 缺陷，只报告不修复
    "if":      ["id", "type", "condition", "then"],
    "while":   ["id", "type", "condition", "body"],
}

VALID_NODE_TYPES = {"task", "message", "if", "while"}

# 平台字段名 → 规范字段名（n8n/Dify/Coze 混合来源归一化）
FIELD_ALIASES = {
    "nodeId": "id", "node_id": "id",
    "nodeType": "type", "node_type": "type",
    "label": "name", "title": "name",
    "from": "from", "source": "from", "src": "from",
    "to": "to", "target": "to", "dst": "to",
    "cond": "condition", "predicate": "condition", "guard": "condition",
    "ifTrue": "then", "ifFalse": "else", "thenBranch": "then", "elseBranch": "else",
    "loopBody": "body", "loop_body": "body",
    "senderId": "sender", "receiverId": "receiver",
    "platformName": "platform", "sourcePlatform": "platform",
}

NESTED_KEYS = ("then", "else", "body")


# ---------------------------------------------------------------------------
# 遍历辅助：递归展开全部节点（含嵌套 then/else/body）
# ---------------------------------------------------------------------------

def _iter_all_nodes(nodes: List[dict]):
    """深度优先遍历节点树，产出每个节点字典。"""
    for node in nodes:
        yield node
        for key in NESTED_KEYS:
            child = node.get(key)
            if isinstance(child, dict):
                yield from _iter_all_nodes([child])
            elif isinstance(child, list):
                yield from _iter_all_nodes(child)


# ---------------------------------------------------------------------------
# 1. 必填字段校验（存在性检查，不自动补全）
# ---------------------------------------------------------------------------

def validate_required_fields(workflow: dict) -> list:
    """
    检查每个节点（含嵌套）是否包含必填字段。
    缺失字段只报告，绝不补全。
    """
    errors = []
    for node in _iter_all_nodes(workflow.get("nodes", [])):
        nid = node.get("id", "<unknown>")
        ntype = node.get("type")
        if ntype not in VALID_NODE_TYPES:
            errors.append(f"Node '{nid}': unknown or missing type '{ntype}'.")
            continue
        for field in REQUIRED_NODE_FIELDS[ntype]:
            if field not in node:
                errors.append(
                    f"Node '{nid}' (type={ntype}): missing required field "
                    f"'{field}'. NOT auto-completed."
                )
    return errors


# ---------------------------------------------------------------------------
# 2. 标识符校验（ID 唯一性 + 边引用完整性）
# ---------------------------------------------------------------------------

def validate_identifiers(workflow: dict) -> list:
    """
    检查：(a) 全部节点（含嵌套）ID 唯一；
          (b) 边端点引用存在的节点。
    不创建缺失节点或边。
    """
    errors = []
    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", [])

    seen: set = set()
    for node in _iter_all_nodes(nodes):
        nid = node.get("id")
        if nid is None:
            continue
        if nid in seen:
            errors.append(f"Duplicate node id: '{nid}'.")
        seen.add(nid)

    for edge in edges:
        src, dst = edge.get("from"), edge.get("to")
        if src not in seen:
            errors.append(f"Edge references unknown source node: '{src}'.")
        if dst not in seen:
            errors.append(f"Edge references unknown target node: '{dst}'.")
    return errors


# ---------------------------------------------------------------------------
# 3. 结构校验（4 类结构异常，只标记不修复）
# ---------------------------------------------------------------------------

def validate_structure(workflow: dict) -> dict:
    """
    检测 4 类结构异常并标记：
      missing_else_branch      条件节点缺少 else 分支
      missing_loop_exit        循环节点无出口边
      isolated_nodes           节点既无入边也无出边
      unreachable_from_entry   从入口不可达的节点
    所有异常原样保留 —— 输出工作流的控制流语义不变。
    """
    anomalies = {
        "missing_else_branch":    [],
        "missing_loop_exit":      [],
        "isolated_nodes":         [],
        "unreachable_from_entry": [],
    }

    nodes = workflow.get("nodes", [])
    edges = workflow.get("edges", [])

    # 结构检查的节点集合：顶层节点 ∪ 被边引用的嵌套节点。
    # 嵌套节点若只在父结构内组合（then/else/body 顺序），不参与孤立/可达性检查。
    all_ids = {n["id"] for n in _iter_all_nodes(nodes)}
    edge_endpoints = {e["from"] for e in edges} | {e["to"] for e in edges}
    check_ids = {n["id"] for n in nodes} | (edge_endpoints & all_ids)

    node_ids = check_ids
    incoming: Dict[str, list] = {nid: [] for nid in node_ids}
    outgoing: Dict[str, list] = {nid: [] for nid in node_ids}
    for e in edges:
        if e["from"] in incoming and e["to"] in incoming:
            outgoing[e["from"]].append(e["to"])
            incoming[e["to"]].append(e["from"])

    # 3a. 缺失 else 分支（含嵌套条件节点）
    for node in _iter_all_nodes(nodes):
        if node.get("type") == "if" and "else" not in node:
            anomalies["missing_else_branch"].append(node["id"])

    # 3b. 循环无出口：while 无任何出边且未声明结构出口（exit != True）。
    #     嵌套 while 的出口由父结构组合承担，故以其 exit 字段为准。
    for node in _iter_all_nodes(nodes):
        if (node.get("type") == "while"
                and node.get("exit") is not True
                and not outgoing.get(node["id"])):
            anomalies["missing_loop_exit"].append(node["id"])

    # 3c. 孤立节点（无入边且无出边）
    for nid in node_ids:
        if not incoming[nid] and not outgoing[nid]:
            anomalies["isolated_nodes"].append(nid)

    # 3d. 从入口不可达（入口 = 所有无入边节点，论文 Appendix A.2 结构规则）
    entry_candidates = [nid for nid in node_ids if not incoming[nid]]
    reachable: set = set()
    stack = list(entry_candidates)
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        stack.extend(outgoing.get(cur, []))
    for nid in node_ids:
        if nid not in reachable:
            anomalies["unreachable_from_entry"].append(nid)

    return anomalies


# ---------------------------------------------------------------------------
# 4. 语法规范化（纯外观调整，不改变控制流）
# ---------------------------------------------------------------------------

def normalize_field_names(obj: Any) -> Any:
    """递归重命名平台特有字段为规范名称。"""
    if isinstance(obj, dict):
        return {FIELD_ALIASES.get(k, k): normalize_field_names(v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_field_names(x) for x in obj]
    return obj


def normalize_strings(obj: Any) -> Any:
    """去首尾空白、压缩内部连续空白、统一引号。"""
    if isinstance(obj, dict):
        return {k: normalize_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_strings(x) for x in obj]
    if isinstance(obj, str):
        s = obj.strip()
        s = re.sub(r"\s+", " ", s)          # 压缩连续空白（原 deepseek 版存在转义 bug）
        return s
    return obj


def normalize_workflow_syntax(workflow: dict) -> dict:
    """
    仅应用外观规范化。本函数绝不增删或重连任何控制流元素。
    """
    wf = deepcopy(workflow)
    wf = normalize_field_names(wf)
    wf = normalize_strings(wf)
    return wf


# ---------------------------------------------------------------------------
# 5. 主入口
# ---------------------------------------------------------------------------

def preprocess(raw_workflow: dict, strict: bool = False) -> dict:
    """
    预处理主入口。

    参数
    ----
    raw_workflow : dict    LLM 生成的原始 JSON 工作流
    strict       : bool    True 时校验失败抛异常；False（默认）收集错误继续

    返回
    ----
    dict:
        'workflow'  : 规范化工作流（控制流语义不变）
        'errors'    : 校验错误消息列表（已报告，未修复）
        'anomalies' : 检测到的语义异常（已标记，未修复）
    """
    wf = normalize_workflow_syntax(raw_workflow)

    field_errors = validate_required_fields(wf)
    id_errors = validate_identifiers(wf)
    anomalies = validate_structure(wf)

    errors = field_errors + id_errors
    if strict and errors:
        raise ValueError("Preprocessing validation failed:\n" + "\n".join(errors))

    return {
        "workflow": wf,
        "errors": errors,
        "anomalies": anomalies,
    }


# ---------------------------------------------------------------------------
# CLI（可复现性检查）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python preprocess.py <workflow.json>")
        sys.exit(1)
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        raw = json.load(f)
    result = preprocess(raw)
    print(json.dumps(result, indent=2, ensure_ascii=False))
