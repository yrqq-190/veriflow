# -*- coding: utf-8 -*-
"""
形式化内核回归测试
==================
把审计阶段用到的四个反例固化为测试，另加修复闭环与截断语义的用例。
运行：python -m unittest discover -s tests -v   （或在仓库根目录执行本文件）
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jcpn_builder import F_COND, F_DATA, ANY_TYPE, transform  # noqa: E402
from repair import (apply_repairs, repair_and_reverify,  # noqa: E402
                    suggest_repairs, validate_workflow_structure)
from verification import verify_workflow  # noqa: E402


def task(nid, **kw):
    d = {"id": nid, "type": "task", "name": nid}
    d.update(kw)
    return d


def wf(nodes, edges):
    return {"name": "test", "nodes": nodes, "edges": edges}


def find(model, prefix):
    return sorted(t for t in model.T if t.startswith(prefix))


def finding_types(result):
    return {d["type"] for d in result["defects"]}


class WhileSemantics(unittest.TestCase):
    """CASE A：while 的出口与循环体不能被合并掉。"""

    def setUp(self):
        self.w = wf(
            [task("a"), {"id": "w", "type": "while", "name": "w",
                         "condition": "c", "exit": True, "body": [task("b")]},
             task("c")],
            [{"from": "a", "to": "w"},
             {"from": "w", "to": "c"},
             {"from": "w", "to": "b", "branch": "loop"}])
        self.model = transform(self.w)
        self.result = verify_workflow(self.w)

    def test_exit_transition_exists(self):
        self.assertIn("t_exit_w", self.model.T)

    def test_body_place_separate_from_exit(self):
        # 循环体入口与循环出口必须是不同库所：t_loop 只能进 body，t_exit 只能进 p_out
        loop_targets = {v for (u, v) in self.model.A if u == "t_loop_w"}
        exit_targets = {v for (u, v) in self.model.A if u == "t_exit_w"}
        self.assertTrue(loop_targets, "t_loop must feed the body")
        self.assertTrue(exit_targets, "t_exit must feed the continuation")
        self.assertNotIn("p_out_w", loop_targets)
        self.assertNotIn("p_judge_w", loop_targets)
        self.assertFalse(loop_targets & exit_targets)

    def test_downstream_reachable_through_exit(self):
        self.assertIn("t_c", self.result["rg"].fired)
        self.assertIn("t_exit_w", self.result["rg"].fired)

    def test_clean_workflow_has_no_defect(self):
        self.assertFalse(self.result["defective"], self.result["defects"])


class FanOutSemantics(unittest.TestCase):
    """CASE B：一个节点多个后继必须是 AND-split。"""

    def setUp(self):
        self.w = wf([task("a"), task("b"), task("c"), task("d")],
                    [{"from": "a", "to": "b"}, {"from": "a", "to": "c"},
                     {"from": "b", "to": "d"}, {"from": "c", "to": "d"}])
        self.model = transform(self.w)
        self.result = verify_workflow(self.w)

    def test_single_fork_transition(self):
        forks = find(self.model, "t_fork_")
        self.assertEqual(len(forks), 1)
        self.assertEqual(len([1 for (u, v) in self.model.A if u == forks[0]
                              and v.startswith("p_in_")]), 2)

    def test_both_branches_fire(self):
        fired = self.result["rg"].fired
        self.assertIn("t_b", fired)
        self.assertIn("t_c", fired)

    def test_join_is_concurrent_not_xor(self):
        # 两条分支各持一个 token，汇合点先后被两个 token 消费
        self.assertGreaterEqual(self.result["stats"]["|RG|"], 8)
        self.assertFalse(self.result["defective"], self.result["defects"])


class ColorSemantics(unittest.TestCase):
    """CASE C：消息 token 的颜色不能被数据变迁吞掉。"""

    def setUp(self):
        self.w = wf([task("a"),
                     {"id": "m", "type": "message", "name": "m",
                      "sender": "bot", "pairing": "send_only"},
                     task("z")],
                    [{"from": "a", "to": "m"}, {"from": "m", "to": "z"}])
        self.model = transform(self.w)

    def test_message_place_has_message_family(self):
        self.assertIn("Θ_msg", self.model.C["p_msg_m"])
        self.assertIn("msg_m", self.model.Theta_msg)

    def test_only_message_transition_consumes_message_place(self):
        consumers = {v for (u, v) in self.model.A if u == "p_msg_m"}
        self.assertEqual(consumers, {"t_deliver_m"})

    def test_flow_reaches_end(self):
        r = verify_workflow(self.w)
        self.assertIn("t_z", r["rg"].fired)
        self.assertFalse(r["defective"], r["defects"])


class IfBranchSemantics(unittest.TestCase):
    """CASE D：两分支汇到同一节点时，弧与颜色都不能互相覆盖。"""

    def setUp(self):
        self.w = wf([task("a"),
                     {"id": "i", "type": "if", "name": "i", "condition": "x",
                      "then": [task("x")], "else": [task("y")]},
                     task("c")],
                    [{"from": "a", "to": "i"},
                     {"from": "i", "to": "x", "branch": "true"},
                     {"from": "i", "to": "y", "branch": "false"},
                     {"from": "x", "to": "c"}, {"from": "y", "to": "c"}])

    def test_two_decision_transitions(self):
        m = transform(self.w)
        self.assertEqual(find(m, "t_cond_then_"), ["t_cond_then_i"])
        self.assertEqual(find(m, "t_cond_else_"), ["t_cond_else_i"])

    def test_branch_colors_distinct(self):
        m = transform(self.w)
        produced = {e.text() for (u, _v) in m.A if u == "t_cond_then_i"
                    for e in m.arcs[(u, _v)]}
        produced_else = {e.text() for (u, _v) in m.A if u == "t_cond_else_i"
                         for e in m.arcs[(u, _v)]}
        self.assertTrue(any("c=true" in p for p in produced), produced)
        self.assertTrue(any("c=false" in p for p in produced_else), produced_else)

    def test_no_fabricated_deadlock(self):
        r = verify_workflow(self.w)
        self.assertFalse(r["defective"], r["defects"])


class MissingBranchDetection(unittest.TestCase):
    """缺 false 分支的双口径。

    - 默认（平台语义）：条件为假且未连边 = 实例结束，该分支并入 P_f，不算缺陷；
    - 严格读法（VERIFLOW_STRICT_BRANCH=1）：在非终点处提前终止 = missing_branch。
    两种读法都写进 model.notes，不允许一种语义悄悄覆盖另一种。
    """

    def setUp(self):
        self.w = wf([task("n1"),
                     {"id": "n2", "type": "if", "name": "cond", "condition": "x",
                      "then": {"id": "n3", "type": "task", "name": "pass"}},
                     task("n4")],
                    [{"from": "n1", "to": "n2"},
                     {"from": "n2", "to": "n3", "branch": "true"},
                     {"from": "n3", "to": "n4"}])

    def test_platform_semantics_is_clean_and_recorded(self):
        r = verify_workflow(self.w)
        self.assertFalse(r["defective"], r["defects"])
        self.assertTrue(any("implicit_termination" in n for n in r["model"].notes),
                        r["model"].notes)
        self.assertIn("p_else_n2", r["model"].P_f)

    def test_strict_reading_reports_missing_branch(self):
        import jcpn_builder as jb
        old = jb.IMPLICIT_BRANCH_TERMINATION
        jb.IMPLICIT_BRANCH_TERMINATION = False
        try:
            r = verify_workflow(self.w)
            self.assertIn("missing_branch", finding_types(r))
            hit = [d for d in r["defects"] if d["type"] == "missing_branch"][0]
            self.assertEqual(hit["source_id"], "n2")
            self.assertTrue(hit["residual"])
        finally:
            jb.IMPLICIT_BRANCH_TERMINATION = old

    def test_strict_reading_repair_closes_the_loop(self):
        import jcpn_builder as jb
        old = jb.IMPLICIT_BRANCH_TERMINATION
        jb.IMPLICIT_BRANCH_TERMINATION = False
        try:
            r = verify_workflow(self.w)
            repairs = suggest_repairs(self.w, r)
            auto = [x["repair_id"] for x in repairs if x["auto"]]
            self.assertTrue(auto, repairs)
            out = repair_and_reverify(self.w, auto)
            self.assertTrue(out["clean"], out["verify"]["defects"])
            self.assertEqual(out["delta"]["defects_after"], 0)
        finally:
            jb.IMPLICIT_BRANCH_TERMINATION = old


class MultiCaseBranches(unittest.TestCase):
    """Dify if-else 是 n 路分支，不能降维成 true/false 两路。"""

    def _wf(self):
        return wf([task("a"),
                   {"id": "i", "type": "if", "name": "classify", "condition": "x"},
                   task("p"), task("q"), task("r")],
                  [{"from": "a", "to": "i"},
                   {"from": "i", "to": "p", "branch": "case_a"},
                   {"from": "i", "to": "q", "branch": "case_b"},
                   {"from": "i", "to": "r", "branch": "case_c"}])

    def test_three_cases_get_distinct_colors(self):
        m = transform(self._wf())
        cases = find(m, "t_cond_case")
        self.assertEqual(len(cases), 3, m.T)
        conds = set()
        for t in cases:
            for (u, v) in [x for x in m.A if x[0] == t]:
                conds |= {e.cond for e in m.arcs[(u, v)] if e.cond}
        self.assertEqual(conds, {"case_a", "case_b", "case_c"})

    def test_three_cases_all_reach_targets(self):
        r = verify_workflow(self._wf())
        self.assertTrue({"t_p", "t_q", "t_r"} <= r["rg"].fired, r["rg"].fired)
        self.assertTrue(any("implicit_termination" in n for n in r["model"].notes))


class BrokenMessageSemantics(unittest.TestCase):
    """unpaired 消息：消息 token 残留 → broken_message，且只允许人工复核。"""

    def setUp(self):
        self.w = wf([task("a"),
                     {"id": "m", "type": "message", "name": "m", "sender": "bot",
                      "platform": "n8n", "pairing": "unpaired"},
                     task("z")],
                    [{"from": "a", "to": "m"}, {"from": "m", "to": "z"}])
        self.r = verify_workflow(self.w)

    def test_detected_by_state_space(self):
        self.assertIn("broken_message", finding_types(self.r))
        hit = [d for d in self.r["defects"] if d["type"] == "broken_message"][0]
        self.assertTrue(all(x["color"].startswith("msg(") for x in hit["residual"]))

    def test_repair_is_manual_only(self):
        repairs = suggest_repairs(self.w, self.r)
        bm = [r for r in repairs if r["defect_type"] == "broken_message"]
        self.assertTrue(bm)
        self.assertFalse(any(r["auto"] for r in bm),
                         "改标签式假修复必须不存在")


class TruncationSemantics(unittest.TestCase):
    """状态空间截断时不得给出"不可达/干净"的结论。"""

    def test_truncated_suppresses_claims(self):
        nodes = [task(f"t{i}") for i in range(12)]
        edges = [{"from": f"t{i}", "to": f"t{i + 1}"} for i in range(11)]
        w = wf(nodes, edges)
        r = verify_workflow(w, max_states=4)
        self.assertTrue(r["stats"]["truncated"])
        types = finding_types(r)
        self.assertIn("analysis_incomplete", types)
        self.assertNotIn("unreachable_node", types)


class RepairGuardrails(unittest.TestCase):
    """修复不得制造自环、重复边或悬空端点。"""

    def test_structure_validator(self):
        bad = wf([task("a")], [{"from": "a", "to": "a"}])
        self.assertIn("self loop on 'a'", validate_workflow_structure(bad))
        dup = wf([task("a"), task("b")],
                 [{"from": "a", "to": "b"}, {"from": "a", "to": "b"}])
        self.assertTrue(any("duplicate edge" in e
                            for e in validate_workflow_structure(dup)))

    def test_reconnect_refuses_self_loop(self):
        w = wf([task("a"), task("b")],
               [{"from": "a", "to": "b"}])
        r = verify_workflow(w)
        self.assertFalse(r["defective"])
        # 人为给一条"最后节点接回自己"的建议，apply 必须拒绝
        rec = [{"repair_id": "x", "source_id": "b", "action": "reconnect_to_tail",
                "auto": True}]
        w2, applied = apply_repairs(w, rec, ["x"])
        self.assertEqual(applied[0]["status"], "skipped")
        self.assertIn("self loop", applied[0]["reason"])


class MarkingWellFormed(unittest.TestCase):
    """任何终止标识的残留都非空：不存在"空标识"这种伪状态。"""

    def test_no_empty_terminal_findings(self):
        w = wf([task("a"),
                {"id": "i", "type": "if", "name": "i", "condition": "x",
                 "then": [task("b")]},
                task("c")],
               [{"from": "a", "to": "i"},
                {"from": "i", "to": "b", "branch": "true"},
                {"from": "b", "to": "c"}])
        r = verify_workflow(w)
        for d in r["defects"]:
            self.assertTrue(d.get("residual"), d)


if __name__ == "__main__":
    unittest.main(verbosity=2)
