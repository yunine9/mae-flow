#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lean phase guidance and test-only harness contracts."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from unittest import mock


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.orchestration.models import (  # noqa: E402
    CommitPace,
    DeliveryPath,
    FlowState,
    Phase,
    StartupConfig,
)
from mae_flow_core.orchestration.guidance import render_guidance  # noqa: E402
from mae_flow_core import state_store  # noqa: E402
import lean_harness  # noqa: E402


HARNESS = os.path.join(os.path.dirname(__file__), "lean_harness.py")


def state_for(phase):
    return FlowState(
        ticket="REQ-42",
        path=DeliveryPath.FULL,
        phase=phase,
        commit_pace=CommitPace.STAGED,
        current_cp="CP2",
        artifacts=(
            ("request", "docs/requests/REQ-42.md"),
            ("spec", "openspec/changes/req-42/change.md"),
            ("story", "docs/story/STORY-REQ-42.md"),
        ),
        decisions=(("private.detail", "must not be rendered"),),
        risks=("database migration remains unresolved",),
    )


class LeanGuidanceTests(unittest.TestCase):
    def test_recovery_keeps_the_confirmed_operational_configuration_visible(self):
        state = replace(
            state_for(Phase.QUALITY),
            decisions=(("startup.confirmation", "用户已确认完整配置。"),),
            startup_config=StartupConfig(
                worker="zhangsan",
                ticket_type="fix",
                requirement_source="requirements/query.md",
                base_branch="main",
                working_branch="main_zhangsan_REQ-42",
                build_method="build-fix",
                ut_method="ut-generator-agent",
                ut_command="ctest --test-dir build",
            ),
        )

        text = render_guidance(state)

        for expected in (
                "已确认的启动配置", "zhangsan", "fix",
                "requirements/query.md", "main_zhangsan_REQ-42",
                "build-fix", "ut-generator-agent", "ctest --test-dir build"):
            self.assertIn(expected, text)

    def test_phase_guidance_connects_behavior_baseline_to_delivery(self):
        startup = render_guidance(state_for(Phase.STARTUP))
        spec = render_guidance(state_for(Phase.SPEC))
        story = render_guidance(state_for(Phase.STORY))
        delivery = render_guidance(state_for(Phase.DELIVERY))

        self.assertIn("docs/specs/index.md", startup)
        self.assertIn("业务领域", startup)
        self.assertIn("相关行为基线", spec)
        self.assertIn(".mae-flow-work", spec)
        self.assertIn("独立交给开发和测试", story)
        for action in ("新增", "更新", "不变"):
            self.assertIn(action, delivery)
        self.assertIn("精确清单", delivery)

    def test_each_phase_renders_outcome_focused_recovery_guidance(self):
        for phase in Phase:
            with self.subTest(phase=phase):
                text = render_guidance(state_for(phase))
                self.assertIn("工单: REQ-42", text)
                self.assertIn("交付路径: 完整流程（Full）", text)
                self.assertIn("当前阶段:", text)
                self.assertIn("当前开发批次: CP2", text)
                self.assertIn("## 目标", text)
                self.assertIn("## 当前要做", text)
                self.assertIn("## 何时询问用户", text)
                self.assertIn("## 本阶段产出", text)
                self.assertIn("## 下一步", text)
                self.assertIn("docs/requests/REQ-42.md", text)
                self.assertIn("database migration remains unresolved", text)

    def test_guidance_omits_legacy_ritual_and_irrelevant_state(self):
        forbidden = (
            "done --ack",
            "证据令牌",
            "任务卡",
            "report-hash",
            "exact ACK",
            "sleep",
            "poll",
            "must not be rendered",
        )
        for phase in Phase:
            with self.subTest(phase=phase):
                text = render_guidance(state_for(phase))
                for term in forbidden:
                    self.assertNotIn(term, text)

    def test_phase_ownership_and_quality_retry_policy_are_explicit(self):
        spec = render_guidance(state_for(Phase.SPEC))
        story = render_guidance(state_for(Phase.STORY))
        construction = render_guidance(state_for(Phase.CONSTRUCTION))
        quality = render_guidance(state_for(Phase.QUALITY))
        self.assertIn("WHAT", spec)
        self.assertIn("实现边界", story)
        self.assertIn("累计 UT 交接", construction)
        self.assertIn("最多一次", quality)
        self.assertIn("用户决定", quality)
        self.assertIn("当前语义位置", quality)
        self.assertIn("新的阶段或开发批次", quality)

    def test_empty_artifacts_render_as_none(self):
        text = render_guidance(FlowState.new(
            "REQ-EMPTY", DeliveryPath.FULL, CommitPace.CONTINUOUS))
        self.assertIn("流程产物: 无", text)

    def test_spec_and_story_render_one_shot_review_policy(self):
        spec = render_guidance(state_for(Phase.SPEC))
        story = render_guidance(state_for(Phase.STORY))
        self.assertIn("调用一次 `grill-critic-agent`", spec)
        self.assertIn("CLEAR 不增加", spec)
        self.assertIn("调用一次 `story-generator-agent`", story)
        self.assertIn("失败只记录，不自动重试", story)
        self.assertIn("真实设计取舍", story)

    def test_recovery_guidance_names_exact_phase_capabilities(self):
        expected = {
            Phase.SPEC: ("grill-critic-agent",),
            Phase.STORY: ("story-generator-agent", "craft-reviewer-agent"),
            Phase.CONSTRUCTION: ("craft-reviewer-agent", "build-fix"),
            Phase.QUALITY: ("codecheck-advisor-agent", "ut-generator-agent"),
        }
        for phase, names in expected.items():
            with self.subTest(phase=phase):
                guidance = render_guidance(state_for(phase))
                for name in names:
                    self.assertIn(name, guidance)

    def test_construction_plans_testability_without_running_formal_ut(self):
        construction = render_guidance(state_for(Phase.CONSTRUCTION))
        self.assertIn("可测性边界", construction)
        self.assertIn("累计 UT 交接", construction)
        self.assertIn("不正式编写或运行 UT", construction)
        self.assertIn("已配置的 `build-fix`", construction)
        self.assertNotIn("tests leading each behavior change", construction)

    def test_focused_recovery_from_full_only_phases_never_demands_full_reviews(self):
        for phase in (Phase.SPEC, Phase.STORY):
            with self.subTest(phase=phase):
                state = FlowState(
                    ticket="DTS-RECOVER",
                    path=DeliveryPath.FOCUSED,
                    phase=phase,
                    commit_pace=CommitPace.CONTINUOUS,
                )
                text = render_guidance(state)
                self.assertIn("聚焦流程恢复说明", text)
                self.assertIn("编码实现", text)
                self.assertIn("upgrade-to-full", text)
                self.assertNotIn("exactly once", text)
                self.assertNotIn("完整 Story", text)


class LeanHarnessTests(unittest.TestCase):
    def run_harness(self, state_path, *arguments):
        return subprocess.run(
            [sys.executable, HARNESS, "--state", state_path, *arguments],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )

    def test_end_to_end_commands_persist_direct_orchestration_results(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "flow.json")
            started = self.run_harness(
                path, "start", "REQ-9", "focused", "continuous")
            advanced = self.run_harness(
                path, "advance", "startup-confirmed", "--value",
                "The user confirmed the Focused route.")
            decided = self.run_harness(
                path, "decision", "construction.scope", "Keep the fix local.")
            current = self.run_harness(path, "current")
            exited = self.run_harness(path, "exit")

            self.assertEqual(0, started.returncode, started.stderr)
            self.assertEqual(0, advanced.returncode, advanced.stderr)
            self.assertEqual(0, decided.returncode, decided.stderr)
            self.assertEqual(0, current.returncode, current.stderr)
            self.assertEqual(0, exited.returncode, exited.stderr)
            self.assertIn("当前阶段: 编码实现（Construction）", current.stdout)
            with open(path, encoding="utf-8") as stream:
                persisted = json.load(stream)
            self.assertEqual("exited", persisted["status"])
            self.assertEqual("construction", persisted["phase"])
            self.assertIn(
                {"key": "construction.scope", "value": "Keep the fix local."},
                persisted["decisions"],
            )

    def test_exit_succeeds_from_every_phase(self):
        with tempfile.TemporaryDirectory() as root:
            for phase in Phase:
                with self.subTest(phase=phase):
                    path = os.path.join(root, "%s.json" % phase.value)
                    with open(path, "w", encoding="utf-8") as stream:
                        json.dump(state_for(phase).to_dict(), stream)
                    result = self.run_harness(path, "exit")
                    self.assertEqual(0, result.returncode, result.stderr)
                    with open(path, encoding="utf-8") as stream:
                        persisted = json.load(stream)
                    self.assertEqual("exited", persisted["status"])
                    self.assertEqual(phase.value, persisted["phase"])

    def test_invalid_command_does_not_rewrite_caller_state(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "flow.json")
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(state_for(Phase.SPEC).to_dict(), stream)
            with open(path, "rb") as stream:
                before = stream.read()

            result = self.run_harness(path, "advance", "")

            self.assertEqual(2, result.returncode)
            self.assertIn("error:", result.stderr)
            with open(path, "rb") as stream:
                self.assertEqual(before, stream.read())

    def test_encoding_failure_preserves_state_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "flow.json")
            seeded = b'{"known":"recovery cursor"}\n'
            with open(path, "wb") as stream:
                stream.write(seeded)
            state = state_for(Phase.CONSTRUCTION).with_decision(
                "construction.note", "invalid surrogate: \ud800")

            with self.assertRaises(UnicodeEncodeError):
                lean_harness._save(path, state)

            with open(path, "rb") as stream:
                self.assertEqual(seeded, stream.read())
            self.assertEqual(["flow.json"], os.listdir(root))

    def test_save_retries_windows_replace_in_the_caller_directory(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "flow.json")
            real_replace = os.replace
            calls = []

            def flaky_replace(source, destination):
                calls.append((source, destination))
                if len(calls) == 1:
                    raise PermissionError("temporary Windows file lock")
                real_replace(source, destination)

            with mock.patch.object(
                    state_store.os, "replace", side_effect=flaky_replace), \
                    mock.patch.object(state_store.time, "sleep"):
                lean_harness._save(path, state_for(Phase.QUALITY))

            self.assertEqual(2, len(calls))
            for temporary, destination in calls:
                self.assertEqual(root, os.path.dirname(temporary))
                self.assertEqual(path, destination)
            self.assertEqual(["flow.json"], os.listdir(root))


if __name__ == "__main__":
    unittest.main()
