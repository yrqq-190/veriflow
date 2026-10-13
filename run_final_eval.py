# -*- coding: utf-8 -*-
"""
VeriFlow 缺陷检测端到端评测
============================
- 3 个干净底版工作流（请假/订单/报销）
- 每个底版注入 6 类缺陷（missing_branch / isolated_node / unreachable_node /
  abnormal_loop / broken_message / variable_constraint）
- 对比 JCPN 形式化验证 vs 图结构 baseline
- 输出 evaluation_report_final.md
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(__file__))

from preprocess import preprocess
from verification import verify_workflow
from graph_static_checker import graph_based_static_checker
from defect_injector import INJECTORS

# ---------- 干净底版 ----------
BASE = {
    "请假审批": {
        "name": "leave",
        "nodes": [
            {"id": "n1", "type": "task", "name": "提交请假申请"},
            {"id": "n2", "type": "if", "name": "天数判断",
             "condition": "days<=3",
             "then": {"id": "n3", "type": "task", "name": "辅导员审批"},
             "else": {"id": "n4", "type": "task", "name": "学院审批"}},
            {"id": "n5", "type": "task", "name": "审批通过"},
            {"id": "n6", "type": "message", "name": "通知学生",
             "sender": "系统", "pairing": "send_only", "platform": "internal"},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3", "branch": "true"},
            {"from": "n2", "to": "n4", "branch": "false"},
            {"from": "n3", "to": "n5"},
            {"from": "n4", "to": "n5"},
            {"from": "n5", "to": "n6"},
        ],
    },
    "订单处理": {
        "name": "order",
        "nodes": [
            {"id": "n1", "type": "task", "name": "接收订单"},
            {"id": "n2", "type": "task", "name": "库存检查"},
            {"id": "n3", "type": "if", "name": "库存充足",
             "condition": "stock>0",
             "then": {"id": "n4", "type": "task", "name": "发货"},
             "else": {"id": "n5", "type": "task", "name": "补货"}},
            {"id": "n6", "type": "message", "name": "物流通知",
             "sender": "系统", "pairing": "send_only", "platform": "internal"},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4", "branch": "true"},
            {"from": "n3", "to": "n5", "branch": "false"},
            {"from": "n4", "to": "n6"},
        ],
    },
    "报销流程": {
        "name": "reimburse",
        "nodes": [
            {"id": "n1", "type": "task", "name": "填写报销单"},
            {"id": "n2", "type": "task", "name": "直属领导审批"},
            {"id": "n3", "type": "while", "name": "发票校验",
             "condition": "unverified>0", "exit": True,
             "body": {"id": "n4", "type": "task", "name": "校验一张发票"}},
            {"id": "n5", "type": "task", "name": "财务打款"},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
            {"from": "n3", "to": "n4", "branch": "loop"},
            {"from": "n4", "to": "n3"},
            {"from": "n3", "to": "n5", "branch": "exit"},
        ],
    },
}

# 刁难案例：手动构造
TRICKY = {
    "嵌套if缺else": {
        "name": "nested_if",
        "nodes": [
            {"id": "n1", "type": "task", "name": "开始"},
            {"id": "n2", "type": "if", "name": "外层判断",
             "condition": "a",
             "then": {"id": "n3", "type": "if", "name": "内层判断",
                      "condition": "b",
                      "then": {"id": "n4", "type": "task", "name": "内层通过"},
                      "else": {"id": "n5", "type": "task", "name": "内层拒绝"}},
             "else": {"id": "n6", "type": "task", "name": "外层拒绝"}},
            {"id": "n7", "type": "task", "name": "结束"},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3", "branch": "true"},
            {"from": "n3", "to": "n4", "branch": "true"},
            {"from": "n3", "to": "n5", "branch": "false"},
            # 故意漏掉 n2 false -> n7 的边（n6 是死节点）
            {"from": "n4", "to": "n7"},
        ],
    },
    "循环里发消息无接收": {
        "name": "loop_msg",
        "nodes": [
            {"id": "n1", "type": "task", "name": "开始"},
            {"id": "n2", "type": "while", "name": "批处理",
             "condition": "batch>0", "exit": True,
             "body": {"id": "n3", "type": "message", "name": "发送通知",
                      "sender": "系统", "pairing": "paired", "platform": "internal"}},
            {"id": "n4", "type": "task", "name": "结束"},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3", "branch": "loop"},
            {"from": "n3", "to": "n2"},
            {"from": "n2", "to": "n4", "branch": "exit"},
        ],
    },
}


def detect_jcpn(wf):
    pp = preprocess(wf)
    v = verify_workflow(pp["workflow"])
    return v


def detect_graph(wf):
    pp = preprocess(wf)
    return graph_based_static_checker(pp["workflow"])


def main():
    rows = []  # 每行: case_name, injected_defect, expected, jcpn_hit, graph_hit, note

    # 1) 干净样本（负例）
    for name, wf in BASE.items():
        v = detect_jcpn(wf)
        g = detect_graph(wf)
        rows.append({
            "case": f"[干净] {name}",
            "injected": "无",
            "expected": "无缺陷",
            "jcpn": "PASS" if not v["defective"] else f"误报:{[d['type'] for d in v['defects']]}",
            "graph": "PASS" if not g else f"误报:{sorted(g)}",
            "rg_size": v["stats"]["|RG|"],
        })

    # 2) 每个底版注入每种缺陷
    for base_name, base_wf in BASE.items():
        for defect_name, inj in INJECTORS.items():
            try:
                wf2, injected_id = inj(json.loads(json.dumps(base_wf)))
            except (ValueError, IndexError, KeyError) as e:
                rows.append({
                    "case": f"[注入] {base_name}",
                    "injected": f"{defect_name} (跳过:{e})",
                    "expected": defect_name,
                    "jcpn": "—",
                    "graph": "—",
                    "rg_size": 0,
                })
                continue
            v = detect_jcpn(wf2)
            g = detect_graph(wf2)
            jcpn_defects = [d["type"] for d in v["defects"]]
            expected = defect_name
            hit = any(expected in d for d in jcpn_defects) or \
                  (expected == "missing_branch" and "unexpected_deadlock" in jcpn_defects) or \
                  (expected == "abnormal_loop" and "non_termination_risk" in jcpn_defects)
            rows.append({
                "case": f"[注入] {base_name}",
                "injected": f"{defect_name} ({injected_id})",
                "expected": expected,
                "jcpn": "✓ 检出" if hit else f"✗ 漏检:{jcpn_defects}",
                "graph": "✓" if g else "✗",
                "rg_size": v["stats"]["|RG|"],
            })

    # 3) 刁难案例
    for name, wf in TRICKY.items():
        v = detect_jcpn(wf)
        g = detect_graph(wf)
        rows.append({
            "case": f"[刁难] {name}",
            "injected": "手动构造",
            "expected": "见说明",
            "jcpn": f"defects={[d['type'] for d in v['defects']]}",
            "graph": f"defects={sorted(g) if g else '[]'}",
            "rg_size": v["stats"]["|RG|"],
        })

    # ---------- 汇总 ----------
    tp = fp = fn = tn = 0
    for r in rows:
        is_defective = not r["injected"].startswith("无")
        jcpn_says_bad = r["jcpn"].startswith("✓") or "defects=[" in r["jcpn"] and "[]" not in r["jcpn"]
        if is_defective and jcpn_says_bad: tp += 1
        elif not is_defective and not jcpn_says_bad: tn += 1
        elif not is_defective and jcpn_says_bad: fp += 1
        else: fn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    # ---------- 输出 markdown ----------
    out = ["# VeriFlow 缺陷检测端到端评测报告\n"]
    out.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    out.append(f"- 测试样本数：{len(rows)}（干净 3 + 注入 18 + 刁难 2）")
    out.append(f"- JCPN 形式化验证：TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    out.append(f"- Precision={precision:.1%}  Recall={recall:.1%}  F1={f1:.1%}\n")
    out.append("## 逐案例结果\n")
    out.append("| 案例 | 注入缺陷 | 预期 | JCPN 结果 | 图结构 baseline | |RG| |")
    out.append("|---|---|---|---|---|---|")
    for r in rows:
        out.append(f"| {r['case']} | {r['injected']} | {r['expected']} | {r['jcpn']} | {r['graph']} | {r['rg_size']} |")

    out.append("\n## 缺陷类型覆盖\n")
    out.append("| 缺陷类型 | 说明 | 注入位置 |")
    out.append("|---|---|---|")
    out.append("| missing_branch | 条件节点缺 else 分支 | 删除 if 的 false 边 |")
    out.append("| isolated_node | 节点无入边无出边 | 新增一个孤立 task |")
    out.append("| unreachable_node | 节点不在主链上 | 新增节点但不连入 |")
    out.append("| abnormal_loop | while 无出口 | 去掉 exit=true 和 exit 边 |")
    out.append("| broken_message | 消息发送无接收 | 设 pairing=paired 但无 recv |")
    out.append("| variable_constraint | 数据依赖不一致 | 改字段名制造不一致 |")

    out.append("\n## 刁难案例说明\n")
    out.append("- **嵌套 if 缺 else**：外层 if 的 false 分支节点 n6 没有出边，形成死节点")
    out.append("- **循环里发消息无接收**：while body 里发 paired 消息但无对应 recv，死锁在循环内")

    with open(os.path.join(os.path.dirname(__file__), "evaluation_report_final.md"),
              "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("\n".join(out[:10]))
    print("...")
    print("saved: evaluation_report_final.md")


if __name__ == "__main__":
    main()
