# -*- coding: utf-8 -*-
"""健壮性回归：澄清去重、LLM 校验回退、会话上限、错误边界、样本缓存。"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app as A  # noqa: E402
import nl2json as N  # noqa: E402
from flask import session  # noqa: E402


class ClarifyDedupe(unittest.TestCase):
    def test_unique_ids_per_round(self):
        for text in ("帮我设计一个流程", "帮我生成一个工作流", "流程", "随便设计一个东西"):
            qs = N.clarify_questions(text)
            ids = [q["id"] for q in qs]
            self.assertEqual(len(ids), len(set(ids)), (text, ids))

    def test_bilingual_fields(self):
        qs = N.clarify_questions("帮我生成一个工作流")
        self.assertEqual(len(qs), 1)
        q = qs[0]
        self.assertTrue(q["question_en"])
        self.assertEqual(len(q["options"]), len(q["options_en"]))


class LlmValidation(unittest.TestCase):
    def test_valid_workflow_passes(self):
        wf = {"nodes": [{"id": "n1", "type": "task", "name": "a"},
                        {"id": "n2", "type": "if", "name": "c", "condition": "x>0",
                         "then": {"id": "n3", "type": "task", "name": "t"}}],
              "edges": [{"from": "n1", "to": "n2"},
                        {"from": "n2", "to": "n3", "branch": "true"}]}
        N._validate_llm_workflow(wf)

    def test_invalid_shapes_rejected(self):
        bad = [
            [],
            {"nodes": []},
            {"nodes": [{"id": "n1", "type": "cron"}]},
            {"nodes": [{"id": "n1", "type": "task"},
                       {"id": "n1", "type": "task"}]},
            {"nodes": [{"id": "n1", "type": "task"}],
             "edges": [{"from": "n1", "to": "n9"}]},
            {"nodes": [{"id": "n1", "type": "if", "name": "no-condition"}]},
            {"nodes": [{"id": "n1", "type": "while", "condition": "x"}]},
        ]
        for wf in bad:
            with self.assertRaises(ValueError):
                N._validate_llm_workflow(wf)

    def test_llm_failure_falls_back_to_rules(self):
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}):
            with mock.patch.object(N, "llm_json", side_effect=RuntimeError("boom")):
                wf, qs, stage = N.nl2json("学生请假审批流程，三天以内辅导员审批")
        self.assertIn("llm_fallback", stage)
        self.assertEqual(stage, "llm_fallback(RuntimeError)")
        self.assertTrue(wf["nodes"])

    def test_bad_llm_json_falls_back(self):
        bad = {"nodes": [{"id": "n1", "type": "cron"}], "edges": []}
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}):
            with mock.patch.object(N, "llm_json", return_value=bad):
                wf, qs, stage = N.nl2json("学生请假审批流程，三天以内辅导员审批")
        self.assertIn("llm_fallback", stage)
        self.assertEqual(wf["nodes"][0]["type"], "task")


class SessionBudget(unittest.TestCase):
    def test_store_session_caps_growth(self):
        old = A.MAX_SESSIONS
        A.SESSIONS.clear()
        A.MAX_SESSIONS = 2
        try:
            with A.app.test_request_context():
                for sid in ("a", "b", "c"):
                    session["_sid"] = sid
                    A._store_session({"sid": sid})
            self.assertEqual(len(A.SESSIONS), 2)
            self.assertNotIn("a", A.SESSIONS)
            self.assertIn("c", A.SESSIONS)
        finally:
            A.MAX_SESSIONS = old
            A.SESSIONS.clear()


class ErrorBoundary(unittest.TestCase):
    def test_pipeline_error_returns_structured_500(self):
        c = A.app.test_client()
        with mock.patch.object(A, "run_pipeline", side_effect=ValueError("bad model")):
            r = c.post("/api/generate", json={"text": "随便"})
        self.assertEqual(r.status_code, 500)
        body = r.get_json()
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["error"], "pipeline_error")
        self.assertIn("ValueError", body["message"])


class SamplesCache(unittest.TestCase):
    def test_payload_is_cached(self):
        first = A._samples_payload()
        second = A._samples_payload()
        self.assertIs(first, second)
        self.assertTrue(first["samples"])
        self.assertEqual(len(first["checklist"]), 9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
