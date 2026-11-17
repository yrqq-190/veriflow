# -*- coding: utf-8 -*-
"""澄清阶段收敛性回归：同一问题不得重复追问，预算用尽必须继续生成。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nl2json import clarify_questions, nl2json, resolve_topic  # noqa: E402
from app import run_pipeline  # noqa: E402

LOOP_TEXT = "生成一个超级复杂的工作流，检测一下这个网页的最高能力。补充说明：机场人员和旅客的管理系统"


class ClarifyConvergence(unittest.TestCase):
    def test_initial_question_is_topic(self):
        _, qs, _ = nl2json(LOOP_TEXT)
        self.assertEqual([q["id"] for q in qs], ["q_topic"])

    def test_topic_answer_stops_reasking(self):
        wf, qs, stage = nl2json(LOOP_TEXT, {"topic": "机场人员和旅客的管理系统"}, ["q_topic"])
        self.assertEqual(qs, [])
        self.assertEqual(stage, "generic_from_topic")
        self.assertTrue(wf["name"].startswith("机场人员和旅客的管理系统"))
        self.assertTrue(wf.get("assumptions"), "骨架工作流必须显式声明假设")

    def test_topic_answer_resolves_template_by_name(self):
        wf, qs, stage = nl2json(LOOP_TEXT, {"topic": "海关一体化通关流程"}, ["q_topic"])
        self.assertEqual(qs, [])
        self.assertEqual(stage, "template")
        self.assertIn("海关", wf["name"])

    def test_asked_budget_suppresses_same_id(self):
        self.assertEqual(len(clarify_questions(LOOP_TEXT, {}, [])), 1)
        self.assertEqual(clarify_questions(LOOP_TEXT, {}, ["q_topic"]), [])

    def test_budget_forces_generation(self):
        res = run_pipeline(LOOP_TEXT, {}, ["q_topic"])
        self.assertNotEqual(res["status"], "awaiting_clarification")
        self.assertTrue(res["clarification_exhausted"])

    def test_pipeline_clarify_once_then_generate(self):
        first = run_pipeline(LOOP_TEXT, {}, [])
        self.assertEqual(first["status"], "awaiting_clarification")
        second = run_pipeline(LOOP_TEXT,
                              {"topic": "机场人员和旅客的管理系统"},
                              ["q_topic"])
        self.assertIn(second["status"], ("clean", "awaiting_repair"))
        self.assertNotEqual(second["status"], "awaiting_clarification")

    def test_resolve_topic_unknown_returns_none(self):
        self.assertIsNone(resolve_topic("机场人员和旅客的管理系统"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
