#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Release scenarios for the lean Full/Focused operating model."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace


TESTS = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(TESTS, "..", ".."))
SCRIPTS = os.path.abspath(os.path.join(TESTS, ".."))
CLI = os.path.join(SCRIPTS, "mae-flow.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.adapters.lean_exit import valid_exit_pointer  # noqa: E402
from mae_flow_core.adapters.lean_hook import LeanHookAdapter  # noqa: E402
from mae_flow_core.application.hooks.capability_observation import (  # noqa: E402
    observe_return,
)
from mae_flow_core.guard.manifest import (  # noqa: E402
    DeliveryManifest,
    authorize_delivery,
)
from mae_flow_core.orchestration import (  # noqa: E402
    AdvanceRequest,
    CommitPace,
    DeliveryPath,
    FlowState,
    MoonlightAuthorization,
    Phase,
    advance_flow,
)
from mae_flow_core.orchestration.capabilities import (  # noqa: E402
    AttemptContext,
    CapabilityKind,
    flow_attempt_context,
    record_attempt,
    record_flow_attempt,
    retry_decision_key,
    retry_options,
)
from mae_flow_core.orchestration.delivery import plan_delivery  # noqa: E402
from mae_flow_core.orchestration.guidance import render_user_card  # noqa: E402
from mae_flow_core.orchestration.moonlight_policy import (  # noqa: E402
    apply_moonlight_policy,
)
from mae_flow_core.orchestration.toolbox import (  # noqa: E402
    ToolboxRequest,
    run_toolbox_request,
)


def advance(state, kind, key="", value=""):
    return advance_flow(state, AdvanceRequest(kind, key, value))


def full_at(phase, pace=CommitPace.CONTINUOUS, **changes):
    state = FlowState(
        ticket="REQ-42",
        path=DeliveryPath.FULL,
        phase=phase,
        commit_pace=pace,
    )
    return replace(state, **changes)


def run_cli(root, *arguments):
    env = dict(os.environ)
    env["PYTHONPYCACHEPREFIX"] = os.path.join(root, "pycache")
    return subprocess.run(
        [sys.executable, CLI] + list(arguments),
        cwd=root,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=20,
    )


class FullWorkflowScenarioTests(unittest.TestCase):
    def test_small_full_stops_only_at_startup_spec_story_each_cp_and_delivery(self):
        state = FlowState.new(
            "REQ-SMALL", DeliveryPath.FULL, CommitPace.CONTINUOUS)

        self.assertTrue(advance(state, "startup-ready").needs_user)
        state = advance(
            state, "startup-confirmed", value="用户确认进入 Full Spec。").state
        self.assertEqual(Phase.SPEC, state.phase)
        self.assertTrue(advance(state, "spec-ready").needs_user)

        question = json.dumps({
            "parent": "",
            "evidence": "Current behavior covers only the primary carrier.",
            "impact": "SUL selection remains ambiguous.",
            "recommendation": "Select SUL only when it is configured.",
        }, sort_keys=True, separators=(",", ":"))
        convergence = json.dumps({
            "answer_count": 1,
            "grill_sha256": "a" * 64,
        }, sort_keys=True, separators=(",", ":"))
        critic = json.dumps({
            "grill_sha256": "a" * 64,
            "input_coverage": "complete",
            "spec_sha256": "b" * 64,
        }, sort_keys=True, separators=(",", ":"))
        state = advance(
            state, "grill-question", "GQ-001", question).state
        state = advance(
            state, "grill-answer", "GQ-001",
            "用户确认推荐的 SUL 边界。").state
        state = advance(
            state, "grill-converged", value=convergence).state
        state = record_flow_attempt(
            state,
            flow_attempt_context(state, CapabilityKind.GRILL),
            "returned",
            "opaque grill return",
        )
        state = advance(state, "grill-clear", value=critic).state
        state = advance(
            state, "spec-confirmed", value="用户确认 Spec 行为边界。").state
        self.assertEqual(Phase.STORY, state.phase)
        self.assertTrue(advance(state, "story-ready").needs_user)

        state = record_flow_attempt(
            state,
            flow_attempt_context(state, CapabilityKind.REVIEWER),
            "returned",
            "opaque design review return",
        )
        state = advance(state, "design-review-clear").state
        state = advance(
            state, "story-confirmed", value="用户确认 Story 实现设计。").state
        self.assertEqual(Phase.CONSTRUCTION, state.phase)
        state = record_flow_attempt(
            state,
            flow_attempt_context(state, CapabilityKind.BUILD),
            "returned",
            "opaque CP build return",
        )
        self.assertTrue(advance(state, "cp-ready").needs_user)
        state = advance(state, "cp-ready").state
        state = advance(
            state, "cp-confirmed", value="用户确认 CP1 结果。").state
        self.assertFalse(advance(state, "cp-progress").needs_user)
        state = advance(state, "construction-complete").state
        self.assertEqual(Phase.QUALITY, state.phase)
        state = advance(
            state, "final-conformance",
            value="最终实现和覆盖符合确认的 Spec 与 Story。",
        ).state
        state = advance(state, "quality-complete").state
        self.assertEqual(Phase.DELIVERY, state.phase)
        self.assertTrue(advance(state, "delivery-ready").needs_user)

    def test_complex_full_keeps_every_cp_visible_without_size_thresholds(self):
        state = full_at(
            Phase.CONSTRUCTION,
            pace=CommitPace.CONTINUOUS,
            current_cp="CP1",
        )

        observed = []
        for checkpoint in ("CP1", "CP2", "CP3"):
            state = record_flow_attempt(
                state,
                flow_attempt_context(state, CapabilityKind.BUILD),
                "returned",
                "opaque %s build return" % checkpoint,
            )
            ready = advance(state, "cp-ready", checkpoint)
            observed.append((ready.state.current_cp, ready.needs_user))
            state = advance(
                ready.state, "cp-confirmed",
                value="用户确认 %s 结果。" % checkpoint).state
            if checkpoint != "CP3":
                next_checkpoint = "CP%d" % (int(checkpoint[2:]) + 1)
                state = advance(
                    state, "cp-opened", next_checkpoint).state

        integration = advance(
            state,
            "cp-progress",
            "checkpoint.interface_change",
            "The interface is shared by CP2 and CP3.",
        )
        self.assertEqual(
            [("CP1", True), ("CP2", True), ("CP3", True)], observed)
        self.assertFalse(integration.needs_user)
        self.assertIn("interface change", integration.reason)


class FocusedAndOpaqueCapabilityScenarioTests(unittest.TestCase):
    def test_focused_review_fix_stops_at_startup_and_delivery_only(self):
        state = FlowState.new(
            "REQ-REVIEW-FIX", DeliveryPath.FOCUSED, CommitPace.CONTINUOUS)
        self.assertTrue(advance(state, "startup-ready").needs_user)
        state = advance(
            state, "startup-confirmed", value="用户确认局部修复范围。").state
        self.assertEqual(Phase.CONSTRUCTION, state.phase)

        first = AttemptContext(
            CapabilityKind.CODECHECK, "focused-source-v1", "host-env-v1")
        state = record_flow_attempt(
            state, first, "returned", "review reported an opaque concern")
        self.assertFalse(advance(state, "reviewer-clear").needs_user)

        changed = AttemptContext(
            CapabilityKind.CODECHECK, "focused-source-v2", "host-env-v1")
        self.assertFalse(retry_options(state.capabilities, changed).allowed)
        state = state.with_decision(
            retry_decision_key(changed),
            "用户确认在新的代码检视语义槽位再尝试一次。",
        )
        state = record_flow_attempt(
            state, changed, "returned", "opaque return after the user fix")
        state = record_flow_attempt(
            state,
            flow_attempt_context(state, CapabilityKind.BUILD),
            "returned",
            "opaque focused CP build return",
        )
        state = advance(state, "construction-complete").state
        state = advance(
            state, "final-conformance",
            value="最终实现和覆盖符合确认的局部范围。",
        ).state
        state = advance(state, "quality-complete").state
        self.assertEqual(Phase.DELIVERY, state.phase)
        self.assertTrue(advance(state, "delivery-ready").needs_user)

    def test_semantic_risk_upgrades_focused_to_full_without_counting_files(self):
        focused = replace(
            FlowState.new(
                "REQ-RISK", DeliveryPath.FOCUSED, CommitPace.CONTINUOUS),
            phase=Phase.CONSTRUCTION,
        )

        upgraded = advance(
            focused,
            "upgrade-to-full",
            value="The compatibility contract has two valid meanings.",
        )

        self.assertEqual(DeliveryPath.FULL, upgraded.state.path)
        self.assertEqual(Phase.SPEC, upgraded.state.phase)
        self.assertFalse(upgraded.needs_user)
        self.assertIn(
            ("workflow.path", "The compatibility contract has two valid meanings."),
            upgraded.state.decisions,
        )

    def test_weak_cpp_gtest_ut_is_one_shot_and_its_return_stays_opaque(self):
        request = ToolboxRequest(
            "ut",
            "Create the weakest useful C++ gtest seam; do not invent coverage.",
            (r"src\weak_component.cpp",),
        )
        rendered = run_toolbox_request(request)
        context = AttemptContext(
            CapabilityKind.UT, "weak-cpp-v1", "gtest-unknown-v1")
        attempts = record_attempt(
            (), context, "returned",
            "gtest runner returned but identified no executed case count",
        )

        self.assertEqual(("src/weak_component.cpp",), rendered.artifacts)
        self.assertEqual((), rendered.effects)
        self.assertIn("weakest useful C++ gtest seam", rendered.guidance)
        self.assertIn("at most once", rendered.guidance)
        self.assertEqual("returned", attempts[0].outcome)
        self.assertIn("no executed case count", attempts[0].summary)

    def test_unknown_codecheck_output_is_observed_without_a_verdict(self):
        raw = {"status": "???", "warnings": 17, "private_format": [1, 2]}
        observation = observe_return({"tool_response": raw})
        context = AttemptContext(
            CapabilityKind.CODECHECK, "source-v7", "scanner-v3")
        attempts = record_attempt(
            (), context, "returned", observation.summary)

        self.assertTrue(observation.return_present)
        self.assertEqual(
            '{"private_format":[1,2],"status":"???","warnings":17}',
            attempts[0].summary,
        )
        self.assertEqual("returned", attempts[0].outcome)

    def test_workflow_records_one_opaque_synchronous_host_return(self):
        with tempfile.TemporaryDirectory() as root:
            initialized = subprocess.run(
                ["git", "init", "-q"], cwd=root,
                capture_output=True, timeout=10)
            self.assertEqual(0, initialized.returncode)
            started = run_cli(
                root,
                "start", "--ticket", "REQ-BUILD-HOOK",
                "--path", "focused", "--pace", "continuous",
            )
            self.assertEqual(0, started.returncode)
            recorded = run_cli(
                root,
                "advance", "capability-returned",
                "--key", "build",
                "--decision", "host returned opaque data",
            )

            self.assertEqual(0, recorded.returncode, recorded.stderr)
            with open(os.path.join(root, ".mae-flow.json"),
                      encoding="utf-8") as stream:
                persisted = json.load(stream)
            self.assertEqual(1, len(persisted["capabilities"]))
            attempt = persisted["capabilities"][0]
            self.assertEqual("build", attempt["kind"])
            self.assertEqual("returned", attempt["outcome"])
            self.assertEqual("host returned opaque data", attempt["summary"])

    def test_same_result_is_reused_and_never_automatically_retried(self):
        state = full_at(Phase.QUALITY)
        context = AttemptContext(
            CapabilityKind.BUILD, "quality-source-v1", "fake-host-v1")
        state = record_flow_attempt(
            state, context, "timed-out", "bounded host timeout")

        option = retry_options(state.capabilities, context)
        recovered = FlowState.from_dict(state.to_dict())

        self.assertFalse(option.allowed)
        self.assertTrue(option.needs_user)
        self.assertEqual(state.capabilities, recovered.capabilities)
        with self.assertRaisesRegex(ValueError, "自然语言重试决定"):
            record_flow_attempt(
                recovered, context, "returned", "must not be reached")


class WorkspaceRecoveryAndDeliveryScenarioTests(unittest.TestCase):
    def test_dirty_workspace_requires_exact_adoption_before_delivery(self):
        state = full_at(
            Phase.DELIVERY,
            initial_dirty=("src/existing.cpp", "notes/private.txt"),
            delivery_files=("src/new.cpp", "src/existing.cpp"),
            decisions=((
                "delivery.commit_message",
                "[REQ-42][fix]adopt the reviewed source change",
            ),),
        )
        with self.assertRaisesRegex(ValueError, "adoption"):
            plan_delivery(state)

        manifest = DeliveryManifest.from_paths(
            state.delivery_files, adopted_dirty=("src/existing.cpp",))
        adopted = authorize_delivery(state, manifest)
        delivery = plan_delivery(adopted)

        self.assertEqual(state.delivery_files, delivery.commits[0].manifest.files)
        self.assertEqual(
            ("src/existing.cpp",),
            delivery.commits[0].manifest.adopted_dirty,
        )
        self.assertNotIn("notes/private.txt", delivery.commits[0].manifest.files)

    def test_story_is_local_unless_explicitly_selected_for_exact_manifest(self):
        story = "docs/specs/requirements/REQ-42/story.md"
        decisions = ((
            "delivery.commit_message",
            "[REQ-42][feat]deliver the reviewed behavior",
        ),)
        state = full_at(
            Phase.DELIVERY,
            delivery_files=("src/a.cpp", story),
            decisions=decisions,
        )

        with self.assertRaisesRegex(ValueError, "explicit delivery selection"):
            plan_delivery(state)

        selected = replace(
            state,
            decisions=decisions + (("delivery.conditional_document", story),),
        )
        delivery = plan_delivery(selected)
        self.assertEqual(("src/a.cpp", story), delivery.commits[0].manifest.files)
        self.assertEqual(
            "[REQ-42][feat]deliver the reviewed behavior",
            delivery.commits[0].message,
        )

    def test_resume_corrupt_state_and_explicit_exit_keep_control_recoverable(self):
        with tempfile.TemporaryDirectory() as root:
            state_path = os.path.join(root, ".mae-flow.json")
            marker_root = os.path.join(root, "markers")
            state = full_at(
                Phase.QUALITY,
                current_cp="CP2",
                risks=("The external dependency remains unknown.",),
            )
            with open(state_path, "w", encoding="utf-8") as stream:
                json.dump(state.to_dict(), stream, ensure_ascii=False)

            adapter = LeanHookAdapter(root, marker_root=marker_root)
            resumed = adapter.handle(
                "SessionStart", {"session_id": "semantic-resume"})
            self.assertIn("Phase: quality", resumed.stdout)
            self.assertIn("CP: CP2", resumed.stdout)

            with open(state_path, "wb") as stream:
                stream.write(b"corrupt-flow-state")
            corrupt = adapter.handle(
                "SessionStart", {"session_id": "corrupt-resume"})
            self.assertIn("corrupt", corrupt.stdout.casefold())

            exited = adapter.handle(
                "UserPromptSubmit",
                {"session_id": "exit", "prompt": "退出 Mae-Flow"},
            )
            pointer_path = state_path + ".exited"
            snapshot_dir = os.path.join(root, ".mae-flow-work", "exited")
            self.assertEqual(0, exited.exit_code)
            self.assertFalse(os.path.exists(state_path))
            self.assertIsNotNone(valid_exit_pointer(
                root, pointer_path, snapshot_dir))

    def test_moonlight_exact_authorization_never_hides_delivery_card(self):
        story = "docs/specs/requirements/REQ-42/story.md"
        state = full_at(
            Phase.DELIVERY,
            delivery_files=("src/a.cpp", story),
            decisions=(("delivery.conditional_document", story),),
        )

        outside = apply_moonlight_policy(
            state,
            MoonlightAuthorization(True, ("SRC\\A.CPP",), True, True),
        )
        exact = apply_moonlight_policy(
            state,
            MoonlightAuthorization(
                True, ("SRC\\A.CPP", story), True, True),
        )

        self.assertTrue(outside.safe_stop)
        self.assertFalse(outside.authorization.allow_commit)
        self.assertFalse(exact.safe_stop)
        self.assertTrue(exact.authorization.allow_commit)
        self.assertTrue(exact.authorization.allow_push)
        self.assertIn("交付", render_user_card(exact.state))

    def test_current_renders_exact_moonlight_delivery_authorization(self):
        story = "docs/specs/requirements/REQ-42/story.md"
        message = "[REQ-42][feat]deliver the reviewed behavior"
        state = full_at(
            Phase.DELIVERY,
            delivery_files=("src/a.cpp", story),
            decisions=(
                ("delivery.conditional_document", story),
                ("delivery.commit_message", message),
            ),
        )
        state = apply_moonlight_policy(
            state,
            MoonlightAuthorization(
                True, state.delivery_files, True, False),
        ).state

        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, ".mae-flow.json"), "w",
                      encoding="utf-8") as stream:
                json.dump(state.to_dict(), stream, ensure_ascii=False)
            current = run_cli(root, "current")

        self.assertEqual(0, current.returncode, current.stderr)
        expected_card = "\n".join((
            "需要用户介入: 交付（精确文件、提交说明和是否推送）",
            "最终 Spec/Story/代码对照: 未记录",
            "精确文件:",
            "- src/a.cpp",
            "- %s" % story,
            "提交说明: %s" % message,
            "Moonlight requested: allow_commit=true, allow_push=false",
            "Moonlight effective: allow_commit=true, allow_push=false",
            "Moonlight block reason: none",
        ))
        self.assertIn(expected_card, current.stdout)

    def test_current_renders_staged_cp_messages_in_state_order(self):
        first_message = "[REQ-42][feat]deliver CP1 query entry"
        second_message = "[REQ-42][feat]deliver CP2 result mapping"
        state = full_at(
            Phase.DELIVERY,
            pace=CommitPace.STAGED,
            current_cp="CP2",
            delivery_files=("src/a.cpp", "src/b.cpp"),
            decisions=(
                ("delivery.cp.CP1.file", "src/a.cpp"),
                ("delivery.cp.CP1.message", first_message),
                ("delivery.cp.CP1.source_sha", "a" * 40),
                ("delivery.cp.CP1.confirmation", "CP1 reviewed."),
                ("delivery.cp.CP2.file", "src/b.cpp"),
                ("delivery.cp.CP2.message", second_message),
                ("delivery.cp.CP2.source_sha", "b" * 40),
                ("delivery.cp.CP2.confirmation", "CP2 reviewed."),
                ("delivery.staged_final_file", "src/a.cpp"),
                ("delivery.staged_final_file", "src/b.cpp"),
            ),
        )
        state = apply_moonlight_policy(
            state,
            MoonlightAuthorization(
                True, state.delivery_files, True, True),
        ).state

        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, ".mae-flow.json"), "w",
                      encoding="utf-8") as stream:
                json.dump(state.to_dict(), stream, ensure_ascii=False)
            current = run_cli(root, "current")

        self.assertEqual(0, current.returncode, current.stderr)
        expected_card = "\n".join((
            "需要用户介入: 交付（精确文件、提交说明和是否推送）",
            "最终 Spec/Story/代码对照: 未记录",
            "精确文件:",
            "- src/a.cpp",
            "- src/b.cpp",
            "提交说明（按 CP 顺序）:",
            "- CP1: %s" % first_message,
            "- CP2: %s" % second_message,
            "Moonlight requested: allow_commit=true, allow_push=true",
            "Moonlight effective: allow_commit=true, allow_push=true",
            "Moonlight block reason: none",
        ))
        self.assertIn(expected_card, current.stdout)
        self.assertNotIn("尚未选择", current.stdout)


class ProductDocumentationContractTests(unittest.TestCase):
    CURRENT_DOCS = (
        "README.md",
        "MAINTAINERS.md",
        "FIELD-TEST.md",
        "CLEAN-ROOM-TEST.md",
    )
    PHILOSOPHY = "高效率、高质量；在需要人介入时聪明地让人介入"
    HISTORY_MARKER = "## 历史发布（非当前操作指南）"

    def read(self, relative):
        with open(os.path.join(ROOT, relative), encoding="utf-8") as stream:
            return stream.read()

    def current_changelog(self):
        text = self.read("CHANGELOG.md")
        self.assertIn(self.HISTORY_MARKER, text)
        return text.split(self.HISTORY_MARKER, 1)[0]

    def test_current_docs_publish_one_operating_model(self):
        documents = {
            path: self.read(path) for path in self.CURRENT_DOCS
        }
        documents["CHANGELOG.md"] = self.current_changelog()
        required = (
            self.PHILOSOPHY,
            "Full",
            "Focused",
            "Intake → Spec → Design → Construction → Quality → Delivery",
        )
        for path, text in documents.items():
            with self.subTest(path=path):
                self.assertLess(text.find(self.PHILOSOPHY), 500)
                for term in required:
                    self.assertIn(term, text)

    def test_current_docs_define_one_shot_capabilities_hooks_and_local_docs(self):
        text = "\n".join(self.read(path) for path in self.CURRENT_DOCS)
        for capability in (
                "Build", "UT", "CodeCheck", "Grill", "Story", "Reviewer"):
            self.assertIn(capability, text)
        for event in (
                "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"):
            self.assertIn(event, text)
        self.assertIn("工作流命令是 capability 事实的唯一写者", text)
        self.assertIn("默认保留在本地", text)
        self.assertIn("[ticket][feat|fix]description", text)

    def test_public_stage_and_retry_terms_match_skill_and_cli(self):
        public_sequence = (
            "Intake → Spec → Design → Construction → Quality → Delivery")
        guides = {
            path: self.read(path)
            for path in ("README.md", "MAINTAINERS.md", "skills/mae-flow/SKILL.md")
        }
        for path, text in guides.items():
            with self.subTest(path=path):
                self.assertIn(public_sequence, text)
                self.assertIn("同一语义 slot", text)
                self.assertIn("新的阶段", text)
        cli_source = self.read(
            "scripts/mae_flow_core/orchestration/guidance.py")
        self.assertIn("需要用户介入: Intake（启动选择", cli_source)
        self.assertIn("需要用户介入: Design（Story", cli_source)
        self.assertNotIn("需要用户介入: 启动选择", cli_source)
        self.assertNotIn("需要用户介入: Story（", cli_source)

    def test_public_ci_is_fake_host_proof_not_internal_tool_execution(self):
        workflow = self.read(".github/workflows/selftest.yml")
        for private_selector in (
                "build-fix", "ut-generator-agent", "codecheck-advisor-agent"):
            self.assertNotIn(private_selector, workflow)
        self.assertIn(
            "CI 不调用真实内部 Build、UT 或 CodeCheck", self.read("README.md"))
        self.assertIn(
            "语义场景不能调用内部 Build、UT 或 CodeCheck",
            self.read("MAINTAINERS.md"),
        )
        self.assertIn(
            "不调用真实内部 Build、UT 或 CodeCheck", self.read("FIELD-TEST.md"))
        self.assertIn(
            "CI 不安装或调用真实内部 Build、UT、CodeCheck",
            self.read("CLEAN-ROOM-TEST.md"),
        )

    def test_retired_current_guidance_is_absent_but_history_is_non_operational(self):
        current = "\n".join(
            [self.read(path) for path in self.CURRENT_DOCS]
            + [self.current_changelog()]
        )
        forbidden = (
            "exact ACK",
            "done --ack",
            "任务卡",
            "evidence ledger",
            "证据账本",
            "Hotfix",
            "Tweak",
            "Review 模式",
            "archive command",
            "反复质量链",
        )
        for term in forbidden:
            with self.subTest(term=term):
                self.assertNotIn(term, current)

        history = self.read("CHANGELOG.md").split(
            self.HISTORY_MARKER, 1)[1]
        self.assertIn("过去式", history)
        self.assertIn("不构成当前操作说明", history)
        self.assertEqual(
            34,
            sum(line.startswith("## ") for line in history.splitlines()),
        )
        self.assertGreaterEqual(len(history.splitlines()), 858)
        self.assertIn(
            "## 2026-07-31：长编译只做一次，修复分阶段风险出口",
            history,
        )
        self.assertIn(
            "## 2026-07-25：Windows 与确认流程修正",
            history,
        )
        self.assertIn(
            "固定内嵌 OpenSpec 1.6.0、Comet 0.3.9、Superpowers 和 Ponytail",
            history,
        )


if __name__ == "__main__":
    unittest.main()
