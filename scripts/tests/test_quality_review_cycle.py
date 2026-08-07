#!/usr/bin/env python3
"""Semantic quality review and resume policy regressions."""

import os
import json
import sys
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.workflow import transitions  # noqa: E402


class QualityReviewCycleTests(unittest.TestCase):
    def test_every_compile_to_review_bridge_declares_recovery_context(self):
        root = os.path.abspath(os.path.join(SCRIPTS, ".."))
        with open(os.path.join(root, "flow", "flow.json"),
                  encoding="utf-8") as stream:
            flow = json.load(stream)
        for step_id, step in flow["steps"].items():
            if step.get("next") != "quality_review":
                continue
            with self.subTest(step=step_id):
                self.assertTrue(step.get("quality_review_origin"))
                self.assertTrue(step.get("quality_review_resume"))
                self.assertTrue(step.get("quality_review_rework"))

    def test_quality_context_records_semantic_resume_without_document_digest(self):
        factory = getattr(transitions, "quality_review_context", None)
        self.assertTrue(callable(factory))
        context = factory(
            "ut-source", ["src/a.cpp", "tests/a_test.cpp"], "a" * 40)
        self.assertEqual("verify_codecheck", context["resume"])
        self.assertEqual("quality_recompile", context["rework"])
        self.assertEqual(
            ["src/a.cpp", "tests/a_test.cpp"], context["changed_files"])
        self.assertNotIn("digest", context)

    def test_test_only_context_returns_to_ut_for_rework_and_verify_for_commit(self):
        factory = getattr(transitions, "quality_review_context", None)
        self.assertTrue(callable(factory))
        context = factory("ut-test", ["tests/a_test.cpp"], "b" * 40)
        self.assertEqual("verify_comet", context["resume"])
        self.assertEqual("verify_ut", context["rework"])

    def test_focused_paths_may_supply_their_real_resume_nodes(self):
        context = transitions.quality_review_context(
            "codecheck-source", ["src/a.cpp"], "b" * 40,
            resume="tw_codecheck",
        )
        self.assertEqual("tw_codecheck", context["resume"])
        self.assertEqual("quality_recompile", context["rework"])

    def test_dynamic_next_reads_only_declared_quality_context_field(self):
        state = {
            "quality_review": {
                "resume": "verify_codecheck",
                "rework": "quality_recompile",
            }
        }
        self.assertEqual(
            "verify_codecheck",
            transitions.next_step(
                {"next_from_state": "quality_review.resume"}, state),
        )
        self.assertEqual(
            "quality_recompile",
            transitions.next_step(
                {"next_from_state": "quality_review.rework"}, state),
        )

    def test_unknown_origin_is_rejected_instead_of_guessing(self):
        factory = getattr(transitions, "quality_review_context", None)
        self.assertTrue(callable(factory))
        with self.assertRaisesRegex(ValueError, "unknown quality review origin"):
            factory("mystery", ["src/a.cpp"], "c" * 40)

    def test_deferred_steps_do_not_open_their_own_review_round(self):
        """精简与规范修复只重新编译;检视留到质量链末尾一次做完。

        逐步各拉一轮人工检视，最坏要把用户叫四次，还会让 CodeCheck 反复重跑。
        """
        root = os.path.abspath(os.path.join(SCRIPTS, ".."))
        with open(os.path.join(root, "flow", "flow.json"),
                  encoding="utf-8") as stream:
            flow = json.load(stream)
        steps = flow["steps"]
        for step_id, compile_step, resume in (
                ("verify_ponytail", "verify_post_ponytail_compile",
                 "verify_codecheck"),
                ("verify_codecheck", "verify_codecheck_compile",
                 "verify_ut")):
            with self.subTest(step=step_id):
                step = steps[step_id]
                self.assertTrue(step["source_change_defer_review"])
                self.assertEqual(compile_step, step["source_change_next"])
                # 延后检视的步骤不得再声明自己的检视游标，否则会写出一个
                # 没人消费的游标，后续恢复逻辑会照它跳转。
                for key in ("quality_review_origin", "quality_review_resume",
                            "quality_review_rework"):
                    self.assertNotIn(key, step)
                self.assertEqual(resume, steps[compile_step]["next"])
                self.assertNotEqual(
                    "quality_review", steps[compile_step]["next"])

    def test_engine_skips_the_cursor_for_deferred_source_changes(self):
        """真调 done 的路由:延后检视的步骤不得写出检视游标。"""
        from unittest import mock
        from mae_flow_core.cli_commands import done_status

        def route(step):
            state = {"current": "x", "step_heads": {"x": "a" * 40}}
            calls = []
            with mock.patch.object(
                    done_status, "_set_quality_review_context",
                    side_effect=lambda *a, **k: calls.append(a)):
                with mock.patch.object(
                        done_status, "_done_transition_to_recheck",
                        return_value=True):
                    # api 的属性在 _values 里late-bind,只能替换该字典。
                    with mock.patch.dict(done_status.api._values, {
                            "_ensure_step_entry_head":
                                lambda *a, **k: ("a" * 40, ""),
                            "_source_changed_since":
                                lambda *a, **k: (["src/a.cpp"], ""),
                    }):
                        handled = done_status._done_source_change(
                            {}, state, "x", step)
            return handled, calls

        deferred, deferred_calls = route({
            "source_change_next": "verify_codecheck_compile",
            "source_change_defer_review": True,
        })
        self.assertTrue(deferred)
        self.assertEqual([], deferred_calls, "延后检视不应写游标")

        immediate, immediate_calls = route({
            "source_change_next": "quality_recompile",
        })
        self.assertTrue(immediate)
        self.assertEqual(1, len(immediate_calls), "未声明延后的仍立即建立游标")

    def test_ut_unlock_source_still_reruns_codecheck(self):
        """UT 经用户裁决改的被测源码没过 CodeCheck，必须单独回流重跑。"""
        root = os.path.abspath(os.path.join(SCRIPTS, ".."))
        with open(os.path.join(root, "flow", "flow.json"),
                  encoding="utf-8") as stream:
            steps = json.load(stream)["steps"]
        ut = steps["verify_ut"]
        self.assertEqual("quality_recompile", ut["source_change_recheck"])
        self.assertEqual("verify_codecheck", ut["quality_review_resume"])
        self.assertEqual("quality_review", steps["quality_recompile"]["next"])
        # 而测试改动只做一次统一检视，通过后直接继续。
        self.assertEqual("verify_comet", ut["test_change_review_resume"])


if __name__ == "__main__":
    unittest.main()
