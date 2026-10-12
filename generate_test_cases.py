# -*- coding: utf-8 -*-
"""
VeriFlow 测试数据生成器
=======================
按论文 Table 2 的缺陷分布生成 50 个合成 JSON 工作流：
  - wf_001 ~ wf_025 : 25 个含缺陷工作流
        missing_branch         × 8   （条件节点缺少 else 分支）
        isolated_node          × 6   （节点无入边和出边）
        abnormal_loop          × 5   （循环无法到达出口）
        broken_message         × 4   （消息发送后无接收，n8n 未配对）
        variable_constraint    × 2   （节点间数据依赖不一致，JCPN 已知局限→FN）
  - wf_026 ~ wf_050 : 25 个正常工作流
        wf_026 为带"数据依赖退出条件"的循环（模拟论文中 JCPN 唯一 FP 的成因）
        wf_034 以 Dify/Coze 出站消息结尾（图结构基线会将其误判为 broken_message）

所有注入均保持 JSON 语法有效，满足"只报告不修复"的评估前提。
"""

import json
import os

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_cases")


# ---------------------------------------------------------------------------
# 节点 / 边构造辅助
# ---------------------------------------------------------------------------

def task(nid, name=None):
    return {"id": nid, "type": "task", "name": name or f"execute {nid}"}


def msg(nid, name, sender, receiver, platform, pairing):
    """message 节点：pairing ∈ {paired, unpaired, send_only}"""
    return {
        "id": nid, "type": "message", "name": name,
        "sender": sender, "receiver": receiver,
        "platform": platform, "pairing": pairing,
    }


def ifn(nid, cond, then, else_=None, condition=None):
    """
    if 节点：then / else 可为单节点 dict 或节点列表。
    else_=None 表示缺失 else 分支（missing_branch 缺陷）。
    """
    node = {"id": nid, "type": "if", "condition": condition or cond, "then": then}
    if else_ is not None:
        node["else"] = else_
    return node


def whilen(nid, cond, body, exit_=True, data_dependent=False, condition=None):
    """
    while 节点：
      exit_=True          生成退出变迁（结构上有合法出口）
      exit_=False         无出口（abnormal_loop 缺陷）
      data_dependent=True 出口条件依赖数据更新（抽象下不可达 → JCPN 保守报告）
    """
    node = {
        "id": nid, "type": "while", "condition": condition or cond,
        "body": body, "exit": exit_, "data_dependent": data_dependent,
    }
    return node


def edge(u, v):
    return {"from": u, "to": v}


def build(cid, name, platform, nodes, edges):
    return {"id": cid, "name": name, "platform": platform,
            "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# 1. 缺陷用例 wf_001 ~ wf_025
# ---------------------------------------------------------------------------

def defect_missing_branch(idx):
    """if 节点只有 then 无 else：false 分支无后继 → 死锁"""
    n = idx % 3 + 3                     # 链长变化
    nodes, edges = [], []
    prev = None
    for i in range(n):
        nid = f"t{idx}_{i}"
        nodes.append(task(nid, f"step {i + 1}"))
        if prev:
            edges.append(edge(prev, nid))
        prev = nid
    dec = f"dec{idx}"
    then_t = f"then{idx}"
    nodes.append(ifn(dec, f"check_{idx} == ok", task(then_t, "then action")))
    edges.append(edge(prev, dec))
    last = f"end{idx}"
    nodes.append(task(last, "finalize"))
    edges.append(edge(then_t, last))
    platform = ["n8n", "dify", "coze"][idx % 3]
    return build(f"wf_{idx:03d}", f"conditional without else #{idx}", platform, nodes, edges)


def defect_isolated(idx):
    """正常链之外挂一个孤立节点（无入边无出边）；链长 4 → 总节点 5"""
    names = ["start task", "fetch record", "validate fields", "update state",
             "orphaned activity"]                                   # 最后一项孤立
    nodes = [task(f"a{idx}_{i}", names[i]) for i in range(5)]
    edges = [edge(f"a{idx}_{i}", f"a{idx}_{i + 1}") for i in range(3)]
    platform = ["n8n", "dify", "coze"][idx % 3]
    return build(f"wf_{idx:03d}", f"workflow with isolated node #{idx}",
                 platform, nodes, edges)


def defect_abnormal_loop(idx):
    """while 无出口（exit=false），且 while 无出边：循环无法到达出口；前置链 3 任务"""
    nodes = [task(f"pre{idx}_{i}", f"prepare step {i + 1}") for i in range(4)]
    nodes.append(whilen(f"loop{idx}", f"retry_{idx} < max", task(f"body{idx}", "retry body"),
                        exit_=False))
    edges = ([edge(f"pre{idx}_{i}", f"pre{idx}_{i + 1}") for i in range(3)]
             + [edge(f"pre{idx}_3", f"loop{idx}")])
    platform = ["n8n", "dify", "coze"][idx % 3]
    return build(f"wf_{idx:03d}", f"non-exiting loop #{idx}", platform, nodes, edges)


def defect_broken_message(idx):
    """n8n 消息节点未配对（unpaired）：发送后无对应接收，流程继续 → 结构性缺陷"""
    nodes = [task(f"p{idx}_0", "prepare payload"),
             task(f"p{idx}_1", "validate payload"),
             msg(f"m{idx}", "send notification", "service", "customer", "n8n", "unpaired"),
             task(f"q{idx}_0", "continue pipeline"),
             task(f"q{idx}_1", "finalize")]
    edges = [edge(f"p{idx}_0", f"p{idx}_1"), edge(f"p{idx}_1", f"m{idx}"),
             edge(f"m{idx}", f"q{idx}_0"), edge(f"q{idx}_0", f"q{idx}_1")]
    return build(f"wf_{idx:03d}", f"unpaired message interaction #{idx}",
                 "n8n", nodes, edges)


def defect_variable_constraint(idx):
    """相邻任务数据类型不一致（integer → string），JCPN 当前抽象无法检测 → 预期 FN"""
    out_node = task(f"oa{idx}", "compute result")
    out_node["output"] = {"type": "integer", "name": "result_value"}
    in_node = task(f"ib{idx}", "consume result")
    in_node["input"] = {"type": "string", "name": "result_value"}
    nodes = [task(f"ok{idx}", "kickoff"), out_node, in_node,
             task(f"oc{idx}", "archive"), task(f"od{idx}", "report")]
    edges = [edge(f"ok{idx}", f"oa{idx}"), edge(f"oa{idx}", f"ib{idx}"),
             edge(f"ib{idx}", f"oc{idx}"), edge(f"oc{idx}", f"od{idx}")]
    platform = ["n8n", "dify"][idx % 2]
    return build(f"wf_{idx:03d}", f"variable type mismatch #{idx}",
                 platform, nodes, edges)


DEFECT_GENERATORS = [
    ("missing_branch", defect_missing_branch, 8),
    ("isolated_node", defect_isolated, 6),
    ("abnormal_loop", defect_abnormal_loop, 5),
    ("broken_message", defect_broken_message, 4),
    ("variable_constraint", defect_variable_constraint, 2),
]


def gen_defective():
    cases = {}
    labels = {}
    idx = 1
    for kind, gen, count in DEFECT_GENERATORS:
        for i in range(count):
            wf = gen(idx)
            cases[wf["id"]] = wf
            labels[wf["id"]] = kind
            idx += 1
    return cases, labels


# ---------------------------------------------------------------------------
# 2. 正常用例 wf_026 ~ wf_050
# ---------------------------------------------------------------------------

def gen_normal():
    cases = {}
    labels = {}

    def add(wf):
        cases[wf["id"]] = wf
        labels[wf["id"]] = "none"

    # wf_026: 循环退出条件依赖数据更新（counter 抽象）→ JCPN 保守报告（预期 FP）
    add(build("wf_026", "loop with data-dependent exit", "dify",
              [task("t0", "warm up"),
               task("t1", "init counter"),
               whilen("lp", "counter < 10", task("t2", "increment counter"),
                      exit_=True, data_dependent=True,
                      condition="counter < 10"),
               task("t3", "finalize")],
              [edge("t0", "t1"), edge("t1", "lp"), edge("lp", "t3")]))

    # wf_027: 纯线性
    add(build("wf_027", "linear pipeline 5", "n8n",
              [task(f"s{i}", f"stage {i}") for i in range(5)],
              [edge(f"s{i}", f"s{i + 1}") for i in range(4)]))

    # wf_028: 完整 if-else
    add(build("wf_028", "complete decision", "n8n",
              [task("a", "read input"),
               ifn("d", "ok == true", task("tb", "approve path"), task("eb", "reject path")),
               task("z", "close")],
              [edge("a", "d"), edge("tb", "z"), edge("eb", "z")]))

    # wf_029: 完整 if-else（coze）
    add(build("wf_029", "decision with both branches", "coze",
              [task("p", "load order"),
               ifn("chk", "paid == true", task("s1", "ship order"), task("s2", "notify payment")),
               task("e", "record")],
              [edge("p", "chk"), edge("s1", "e"), edge("s2", "e")]))

    # wf_030: 正常循环（布尔出口，exit 可达）
    add(build("wf_030", "normal loop with exit", "coze",
              [task("i", "open session"),
               whilen("lp2", "session active", task("b", "poll message"), exit_=True),
               task("f", "close session"),
               task("f2", "cleanup session")],
              [edge("i", "lp2"), edge("lp2", "f"), edge("f", "f2")]))

    # wf_031: 线性 5
    add(build("wf_031", "linear pipeline 5", "dify",
              [task(f"x{i}", f"stage {i}") for i in range(5)],
              [edge(f"x{i}", f"x{i + 1}") for i in range(4)]))

    # wf_032: n8n 配对消息
    add(build("wf_032", "paired message exchange", "n8n",
              [task("p0", "initialize"),
               task("p1", "build request"),
               msg("m1", "send api request", "workflow", "webhook", "n8n", "paired"),
               task("p2", "process response"),
               task("p3", "store result")],
              [edge("p0", "p1"), edge("p1", "m1"), edge("m1", "p2"), edge("p2", "p3")]))

    # wf_033: dify 出站消息（send_only，有后继 → 正常）
    add(build("wf_033", "dify outbound notification", "dify",
              [task("a0", "load batch"),
               task("a1", "collect results"),
               msg("n1", "notify user", "bot", "user", "dify", "send_only"),
               task("a2", "log delivery"),
               task("a3", "cleanup")],
              [edge("a0", "a1"), edge("a1", "n1"), edge("n1", "a2"), edge("a2", "a3")]))

    # wf_034: coze 出站消息作为流程终点 → 图基线误报 broken_message（预期 FP）
    add(build("wf_034", "terminal notification message", "coze",
              [task("c0", "init order"),
               task("c1", "finalize order"),
               task("c2", "update ledger"),
               task("c3", "issue invoice"),
               msg("n2", "send receipt", "bot", "user", "coze", "send_only")],
              [edge("c0", "c1"), edge("c1", "c2"), edge("c2", "c3"), edge("c3", "n2")]))

    # wf_035: 嵌套 if（then 分支内嵌循环）
    add(build("wf_035", "nested loop in then branch", "n8n",
              [task("s0", "start"),
               ifn("d1", "mode == auto",
                   [task("s1", "run first pass"),
                    whilen("lp3", "queue not empty", task("s2", "drain queue"), exit_=True)],
                   task("s3", "manual mode")),
               task("s4", "finish")],
              [edge("s0", "d1"), edge("s1", "lp3"), edge("lp3", "s4"), edge("s3", "s4")]))

    # wf_036: 双消息（n8n 配对 + dify 出站）
    add(build("wf_036", "two message interactions", "n8n",
              [task("k0", "start"),
               msg("k1", "call external api", "workflow", "api", "n8n", "paired"),
               task("k2", "handle response"),
               msg("k3", "notify user", "bot", "user", "dify", "send_only"),
               task("k4", "done")],
              [edge("k0", "k1"), edge("k1", "k2"), edge("k2", "k3"), edge("k3", "k4")]))

    # wf_037: 循环体内嵌决策
    add(build("wf_037", "decision inside loop body", "dify",
              [task("m0", "init"),
               whilen("m1", "items remain", ifn("m2", "item valid",
                                                task("m3", "process item"),
                                                task("m4", "skip item")),
                      exit_=True),
               task("m5", "report")],
              [edge("m0", "m1"), edge("m1", "m5")]))

    # wf_038: 线性 8
    add(build("wf_038", "long linear pipeline", "coze",
              [task(f"n{i}", f"step {i}") for i in range(8)],
              [edge(f"n{i}", f"n{i + 1}") for i in range(7)]))

    # wf_039: then 分支含多任务
    add(build("wf_039", "multi-task then branch", "n8n",
              [task("h0", "start"),
               ifn("h1", "eligible == true",
                   [task("h2", "check docs"), task("h3", "score"), task("h4", "rank")],
                   task("h5", "not eligible")),
               task("h6", "output")],
              [edge("h0", "h1"), edge("h2", "h3"), edge("h3", "h4"),
               edge("h4", "h6"), edge("h5", "h6")]))

    # wf_040: 消息 + 决策
    add(build("wf_040", "message then decision", "n8n",
              [task("g0", "start"),
               msg("g1", "request review", "workflow", "reviewer", "n8n", "paired"),
               task("g2", "collect feedback"),
               ifn("g3", "approved == true", task("g4", "publish"), task("g5", "revise")),
               task("g6", "close")],
              [edge("g0", "g1"), edge("g1", "g2"), edge("g2", "g3"),
               edge("g4", "g6"), edge("g5", "g6")]))

    # wf_041: 循环 + coze 出站消息（有后继）
    add(build("wf_041", "loop then notify", "coze",
              [task("r0", "seed"),
               whilen("r1", "pending tasks", task("r2", "consume task"), exit_=True),
               msg("r3", "broadcast result", "bot", "channel", "coze", "send_only"),
               task("r4", "archive")],
              [edge("r0", "r1"), edge("r1", "r3"), edge("r3", "r4")]))

    # wf_042: 线性 10
    add(build("wf_042", "linear pipeline 10", "dify",
              [task(f"u{i}", f"stage {i}") for i in range(10)],
              [edge(f"u{i}", f"u{i + 1}") for i in range(9)]))

    # wf_043: else 分支内嵌循环
    add(build("wf_043", "loop in else branch", "coze",
              [task("v0", "start"),
               ifn("v1", "fast path",
                   task("v2", "quick fix"),
                   whilen("v3", "slow retries", task("v4", "retry"), exit_=True)),
               task("v5", "finish")],
              [edge("v0", "v1"), edge("v2", "v5"), edge("v3", "v5")]))

    # wf_044: dify 出站消息（有后继）
    add(build("wf_044", "dify notify in middle", "dify",
              [task("w0", "start"),
               msg("w1", "progress update", "bot", "user", "dify", "send_only"),
               task("w2", "continue"), task("w3", "finish"),
               task("w4", "audit trail")],
              [edge("w0", "w1"), edge("w1", "w2"), edge("w2", "w3"), edge("w3", "w4")]))

    # wf_045: 复杂嵌套（then 含消息+任务，else 多任务）
    add(build("wf_045", "complex nested branch", "n8n",
              [task("y0", "start"),
               ifn("y1", "mode == auto",
                   [msg("y2", "call classifier", "workflow", "classifier", "n8n", "paired"),
                    task("y3", "apply result")],
                   [task("y4", "manual classify"), task("y5", "store")]),
               task("y6", "report")],
              [edge("y0", "y1"), edge("y2", "y3"), edge("y3", "y6"),
               edge("y4", "y5"), edge("y5", "y6")]))

    # wf_046: 线性 6
    add(build("wf_046", "linear pipeline 6", "coze",
              [task(f"z{i}", f"step {i}") for i in range(6)],
              [edge(f"z{i}", f"z{i + 1}") for i in range(5)]))

    # wf_047: 循环(双任务体) + 配对消息
    add(build("wf_047", "loop with two-step body", "n8n",
              [task("q0", "start"),
               whilen("q1", "buffer not empty", [task("q2", "read buffer"),
                                                 task("q3", "write sink")], exit_=True),
               msg("q4", "report completion", "workflow", "dashboard", "n8n", "paired"),
               task("q5", "finish")],
              [edge("q0", "q1"), edge("q1", "q4"), edge("q4", "q5")]))

    # wf_048: 决策 + 循环 + 消息
    add(build("wf_048", "decision loop message", "dify",
              [task("e0", "start"),
               ifn("e1", "dry run", task("e2", "simulate"), task("e3", "execute")),
               whilen("e4", "needs cleanup", task("e5", "cleanup"), exit_=True),
               msg("e6", "summary", "bot", "user", "dify", "send_only"),
               task("e7", "exit")],
              [edge("e0", "e1"), edge("e2", "e4"), edge("e3", "e4"),
               edge("e4", "e6"), edge("e6", "e7")]))

    # wf_049: 线性 12
    add(build("wf_049", "long linear pipeline 12", "n8n",
              [task(f"f{i}", f"stage {i}") for i in range(12)],
              [edge(f"f{i}", f"f{i + 1}") for i in range(11)]))

    # wf_050: 配对消息 + 出站消息（均有后继）
    add(build("wf_050", "mixed messages", "n8n",
              [task("b0", "start"),
               msg("b1", "fetch remote", "workflow", "remote", "n8n", "paired"),
               task("b2", "merge"),
               msg("b3", "notify owner", "bot", "owner", "coze", "send_only"),
               task("b4", "done")],
              [edge("b0", "b1"), edge("b1", "b2"), edge("b2", "b3"), edge("b3", "b4")]))

    return cases, labels


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    cases, labels = {}, {}
    d_cases, d_labels = gen_defective()
    n_cases, n_labels = gen_normal()
    cases.update(d_cases)
    cases.update(n_cases)
    labels.update(d_labels)
    labels.update(n_labels)

    # 逐用例写盘
    for cid, wf in sorted(cases.items()):
        with open(os.path.join(OUT_DIR, f"{cid}.json"), "w", encoding="utf-8") as f:
            json.dump(wf, f, ensure_ascii=False, indent=2)

    with open(os.path.join(OUT_DIR, "labels.json"), "w", encoding="utf-8") as f:
        json.dump(labels, f, ensure_ascii=False, indent=2)

    # 统计
    from collections import Counter
    kind_count = Counter(labels.values())
    node_count = [len(wf["nodes"]) for wf in cases.values()]
    print(f"total cases : {len(cases)}")
    print("labels      :", dict(kind_count))
    print(f"node range  : {min(node_count)} ~ {max(node_count)}")
    print(f"output dir  : {OUT_DIR}")


if __name__ == "__main__":
    main()
