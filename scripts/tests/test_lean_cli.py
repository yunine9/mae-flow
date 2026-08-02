#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Production CLI contracts for the lean Mae-Flow workflow."""

import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CLI = os.path.join(ROOT, "scripts", "mae-flow.py")


class LeanCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = self.temporary.name
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.env = dict(os.environ)
        self.env["PYTHONPYCACHEPREFIX"] = os.path.join(
            self.root, "pycache")

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, CLI] + list(arguments),
            cwd=self.root,
            env=self.env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=20,
        )

    def state(self):
        with open(os.path.join(self.root, ".mae-flow.json"),
                  encoding="utf-8") as stream:
            return json.load(stream)

    def assert_success(self, result):
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_full_flow_surfaces_only_five_high_value_user_stops(self):
        started = self.run_cli(
            "start", "--ticket", "REQ-42", "--path", "full",
            "--pace", "continuous")
        self.assert_success(started)
        self.assertIn("需要用户介入: 启动选择", started.stdout)

        startup = self.run_cli(
            "decision", "startup-confirmed", "按完整开发和一次交付继续。")
        self.assert_success(startup)
        self.assertIn("需要用户介入: Spec", startup.stdout)

        self.assert_success(self.run_cli(
            "capability-record", "grill", "returned",
            "--source", "spec-v1", "--environment", "critic-v1"))
        self.assert_success(self.run_cli(
            "decision", "grill-clear", "只读质询未发现待决分支。"))
        spec = self.run_cli(
            "decision", "spec-confirmed", "可观察行为和范围已确认。")
        self.assert_success(spec)
        self.assertIn("需要用户介入: Story", spec.stdout)

        self.assert_success(self.run_cli(
            "capability-record", "story", "returned",
            "--source", "spec-v1", "--environment", "story-v1"))
        self.assert_success(self.run_cli(
            "capability-record", "reviewer", "returned",
            "--source", "story-v1", "--environment", "design-review"))
        self.assert_success(self.run_cli(
            "decision", "design-review-approved", "设计检视无待裁决项。"))
        story = self.run_cli(
            "decision", "story-confirmed", "实现边界和可测性设计已确认。")
        self.assert_success(story)
        self.assertIn("需要用户介入: CP", story.stdout)

        cp = self.run_cli(
            "decision", "cp-confirmed", "本 CP 的结果和后续节奏已确认。")
        self.assert_success(cp)
        self.assertNotIn("需要用户介入", cp.stdout)
        self.assert_success(self.run_cli("advance", "construction-complete"))
        self.assert_success(self.run_cli(
            "capability-record", "codecheck", "returned",
            "--source", "final-diff-v1", "--environment", "codecheck-v1"))
        self.assert_success(self.run_cli(
            "capability-record", "build", "returned",
            "--source", "production-v1", "--environment", "build-v1"))
        self.assert_success(self.run_cli(
            "capability-record", "ut", "returned",
            "--source", "final-diff-v1", "--environment", "ut-v1"))
        delivery = self.run_cli("advance", "quality-complete")
        self.assert_success(delivery)
        self.assertIn("需要用户介入: 交付", delivery.stdout)

        state = self.state()
        self.assertEqual("delivery", state["phase"])
        self.assertEqual(6, len(state["capabilities"]))
        story_paths = [
            item["path"] for item in state["artifacts"]
            if item["kind"] == "story"
        ]
        self.assertEqual(1, len(story_paths))
        self.assertIn(".mae-flow-work", story_paths[0].replace("\\", "/"))

    def test_focused_stops_at_startup_and_delivery_and_can_upgrade_semantically(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "DTS-9", "--path", "focused",
            "--pace", "continuous"))
        construction = self.run_cli(
            "decision", "startup-confirmed", "已定位局部修复，直接实现。")
        self.assert_success(construction)
        self.assertIn("Phase: construction", construction.stdout)
        self.assertNotIn("需要用户介入", construction.stdout)

        upgraded = self.run_cli(
            "decision", "upgrade-to-full",
            "发现跨模块兼容性风险，升级完整开发。")
        self.assert_success(upgraded)
        self.assertIn("Path: full", upgraded.stdout)
        self.assertIn("Phase: spec", upgraded.stdout)
        self.assertIn("需要用户介入: Spec", upgraded.stdout)

    def test_focused_migrated_spec_and_story_render_recovery_not_full_reviews(self):
        from pathlib import Path
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from mae_flow_core.orchestration import (  # noqa: E402
            CommitPace,
            DeliveryPath,
            FlowState,
            Phase,
        )

        state_path = Path(self.root) / ".mae-flow.json"
        for phase in (Phase.SPEC, Phase.STORY):
            with self.subTest(phase=phase):
                state = FlowState(
                    ticket="DTS-9",
                    path=DeliveryPath.FOCUSED,
                    phase=phase,
                    commit_pace=CommitPace.CONTINUOUS,
                )
                state_path.write_text(
                    json.dumps(state.to_dict(), ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                current = self.run_cli("current")
                self.assert_success(current)
                self.assertIn("Focused 恢复路径", current.stdout)
                self.assertIn("Construction", current.stdout)
                self.assertIn("upgrade-to-full", current.stdout)
                self.assertNotIn("exactly once", current.stdout)
                self.assertNotIn("必须确认", current.stdout)

    def test_duplicate_capability_needs_and_consumes_natural_language_retry(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-7", "--path", "focused",
            "--pace", "continuous"))
        first = self.run_cli(
            "capability-record", "build", "timed-out",
            "--source", "production-v1", "--environment", "build-v1")
        self.assert_success(first)

        rejected = self.run_cli(
            "capability-record", "build", "returned",
            "--source", "production-v1", "--environment", "build-v1")
        self.assertEqual(2, rejected.returncode)
        self.assertIn("自然语言重试决定", rejected.stderr)
        self.assertEqual(1, len(self.state()["capabilities"]))

        authorized = self.run_cli(
            "decision", "capability.retry.build",
            "构建环境已恢复，用户决定再尝试一次。")
        self.assert_success(authorized)
        retried = self.run_cli(
            "capability-record", "build", "returned",
            "--source", "production-v1", "--environment", "build-v1")
        self.assert_success(retried)
        self.assertEqual(2, len(self.state()["capabilities"]))

        consumed = self.run_cli(
            "capability-record", "build", "returned",
            "--source", "production-v1", "--environment", "build-v1")
        self.assertEqual(2, consumed.returncode)
        self.assertEqual(2, len(self.state()["capabilities"]))

    def test_capability_slot_is_state_derived_not_caller_controlled(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-SLOT", "--path", "focused",
            "--pace", "continuous"))
        self.assert_success(self.run_cli(
            "decision", "startup-confirmed", "已定位局部修复。"))
        first = self.run_cli(
            "capability-record", "build", "returned",
            "--source", "caller-a", "--environment", "env-a")
        changed_labels = self.run_cli(
            "capability-record", "build", "returned",
            "--source", "caller-b", "--environment", "env-b")

        self.assert_success(first)
        self.assertEqual(2, changed_labels.returncode)
        self.assertIn("自然语言重试决定", changed_labels.stderr)
        self.assertEqual(
            "build:construction:CP1",
            self.state()["capabilities"][0]["source_revision"],
        )

        self.assert_success(self.run_cli(
            "decision", "capability.retry.build",
            "用户确认构建环境恢复，再试一次。"))
        self.assert_success(self.run_cli(
            "capability-record", "build", "returned",
            "--source", "caller-c", "--environment", "env-c"))

    def test_design_and_new_cp_reviewer_use_distinct_state_slots(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-REVIEW-SLOT", "--path", "full",
            "--pace", "staged"))
        state = self.state()
        state["phase"] = "story"
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        self.assert_success(self.run_cli(
            "capability-record", "reviewer", "returned",
            "--source", "caller-design", "--environment", "same"))

        state = self.state()
        state["phase"] = "construction"
        state["current_cp"] = "CP2"
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        cp = self.run_cli(
            "capability-record", "reviewer", "returned",
            "--source", "caller-cp", "--environment", "same")

        self.assert_success(cp)
        self.assertEqual(
            ["reviewer:design", "reviewer:cp:CP2"],
            [item["source_revision"]
             for item in self.state()["capabilities"]],
        )

    def test_nonreturned_capability_is_visible_as_risk_until_a_returned_retry(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-CAP-RISK", "--path", "focused",
            "--pace", "continuous"))
        self.assert_success(self.run_cli(
            "decision", "startup-confirmed", "已定位局部修复。"))
        failed = self.run_cli(
            "capability-record", "build", "timed-out",
            "--source", "ignored", "--environment", "ignored")
        self.assert_success(failed)
        self.assertTrue(self.state()["risks"])

        self.assert_success(self.run_cli(
            "decision", "capability.retry.build",
            "用户确认环境恢复，重试一次。"))
        returned = self.run_cli(
            "capability-record", "build", "returned",
            "--source", "still-ignored", "--environment", "still-ignored")

        self.assert_success(returned)
        self.assertEqual([], self.state()["risks"])

    def test_successful_review_retry_clears_both_old_failure_risks(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-REVIEW-RETRY", "--path", "full",
            "--pace", "continuous"))
        self.assert_success(self.run_cli(
            "decision", "startup-confirmed", "用户确认进入 Full Spec。"))
        self.assert_success(self.run_cli(
            "capability-record", "grill", "timed-out",
            "--source", "ignored", "--environment", "ignored"))
        self.assert_success(self.run_cli(
            "decision", "grill-failed", "Grill 本轮超时，不自动重试。"))
        risks = self.state()["risks"]
        self.assertEqual(2, len(risks))
        self.assertTrue(any(
            risk.startswith("Capability grill did not return in slot")
            for risk in risks))
        self.assertTrue(any(
            risk.startswith("Review capability grill did not return in slot")
            for risk in risks))

        self.assert_success(self.run_cli(
            "decision", "capability.retry.grill",
            "用户确认环境恢复，授权 Grill 再尝试一次。"))
        self.assert_success(self.run_cli(
            "capability-record", "grill", "returned",
            "--source", "still-ignored", "--environment", "still-ignored"))
        self.assert_success(self.run_cli(
            "decision", "grill-clear", "Grill 已返回，未发现待决分支。"))

        self.assertEqual([], self.state()["risks"])
        state = self.state()
        state["phase"] = "quality"
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        quality = self.run_cli("advance", "quality-complete")
        self.assert_success(quality)
        self.assertEqual("delivery", self.state()["phase"])

    def test_generic_decisions_cannot_forge_reserved_authorization_facts(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-AUTH", "--path", "focused",
            "--pace", "continuous"))
        for key in (
                "moonlight.allow_push",
                "delivery.cp.CP1.file",
                "delivery.commit_message",
                "delivery.receipt",
                "delivery.adopted_dirty",
                "startup.confirmation",
                "focused.scope_approved",
                "construction.repair",
                "quality.selection",
                "capability.retry.used.build"):
            with self.subTest(key=key):
                result = self.run_cli(
                    "decision", key, "用户普通说明不能伪造保留事实。")
                self.assertEqual(2, result.returncode)
                self.assertIn("保留", result.stderr)

    def test_advance_cannot_self_sign_a_user_owned_transition(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-OWNER", "--path", "focused",
            "--pace", "continuous"))
        before = self.state()

        rejected = self.run_cli(
            "advance", "startup-confirmed", "--decision",
            "This must not self-sign the user stop.")

        self.assertEqual(2, rejected.returncode)
        self.assertIn("decision", rejected.stderr.lower())
        self.assertEqual(before, self.state())
        accepted = self.run_cli(
            "decision", "startup-confirmed", "用户确认精确修改范围。")
        self.assert_success(accepted)

    def test_semantic_confirmation_rejects_reserved_key_override(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-SEMANTIC", "--path", "focused",
            "--pace", "continuous"))
        before = self.state()

        rejected = self.run_cli(
            "decision", "startup-confirmed", "继续局部修复。",
            "--key", "moonlight.enabled")

        self.assertEqual(2, rejected.returncode)
        self.assertIn("不接受 --key", rejected.stderr)
        self.assertEqual(before, self.state())

    def test_manifest_is_exact_and_inactive_execution_is_rejected_but_exit_is_immediate(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-8", "--path", "focused",
            "--pace", "continuous"))
        manifest = self.run_cli(
            "manifest", "--file", "src/order.cpp", "--file",
            "tests/order_test.cpp")
        self.assert_success(manifest)
        self.assertEqual(
            ["src/order.cpp", "tests/order_test.cpp"],
            self.state()["delivery_files"],
        )
        broad = self.run_cli("manifest", "--file", ".")
        self.assertEqual(2, broad.returncode)
        self.assertEqual(
            ["src/order.cpp", "tests/order_test.cpp"],
            self.state()["delivery_files"],
        )

        exited = self.run_cli("exit", "--reason", "切换为直接开发")
        self.assert_success(exited)
        self.assertEqual("exited", self.state()["status"])
        blocked = self.run_cli("advance", "startup-confirmed")
        self.assertEqual(2, blocked.returncode)
        self.assertIn("流程未激活", blocked.stderr)
        again = self.run_cli("exit", "--reason", "保持退出")
        self.assert_success(again)
        self.assertEqual("exited", self.state()["status"])

    def test_manifest_change_clears_prior_delivery_confirmation_and_result(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-REBIND", "--path", "focused",
            "--pace", "continuous"))
        state = self.state()
        state["phase"] = "delivery"
        state["delivery_files"] = ["src/a.cpp"]
        state["decisions"].extend((
            {"key": "delivery.confirmation", "value": "Deliver A."},
            {"key": "delivery.confirmed_file", "value": "src/a.cpp"},
            {"key": "delivery.result", "value": "Pushed A."},
        ))
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)

        changed = self.run_cli("manifest", "--file", "src/b.cpp")

        self.assert_success(changed)
        keys = [item["key"] for item in self.state()["decisions"]]
        self.assertNotIn("delivery.confirmation", keys)
        self.assertNotIn("delivery.confirmed_file", keys)
        self.assertNotIn("delivery.result", keys)

    def test_manifest_binds_commit_and_explicit_push_target_before_confirmation(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-RECEIPT", "--path", "focused",
            "--pace", "continuous"))
        self.assert_success(self.run_cli(
            "decision", "startup-confirmed", "用户确认局部修改范围。"))
        state = self.state()
        state["phase"] = "delivery"
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)

        planned = self.run_cli(
            "manifest", "--file", "src/a.cpp", "--commit-message",
            "[REQ-RECEIPT][fix]绑定交付票据", "--remote", "origin",
            "--destination-ref", "refs/heads/fix/receipt",
            "--expected-destination-sha", "a" * 40)
        self.assert_success(planned)
        confirmed = self.run_cli(
            "decision", "delivery-confirmed",
            "用户确认精确文件、提交信息和远端目标。")
        self.assert_success(confirmed)

        decisions = {
            item["key"]: item["value"]
            for item in self.state()["decisions"]
        }
        receipt = json.loads(decisions["delivery.receipt"])
        self.assertEqual("origin", receipt["remote"])
        self.assertEqual(
            "refs/heads/fix/receipt", receipt["destination_ref"])
        self.assertEqual(["add", "commit", "push"],
                         receipt["requested_actions"])

    def test_toolbox_alias_is_stateless_and_never_calls_external_capability(self):
        result = self.run_cli(
            "codecheck", "--request", "检查本次查询修复", "--file",
            "src/query.cpp")
        self.assert_success(result)
        self.assertIn("one-shot", result.stdout.lower())
        self.assertIn("src/query.cpp", result.stdout)
        self.assertFalse(os.path.exists(os.path.join(
            self.root, ".mae-flow.json")))

    def test_moonlight_start_is_reachable_but_grants_no_git_without_manifest(self):
        started = self.run_cli(
            "start", "--ticket", "REQ-ML", "--path", "full",
            "--pace", "continuous", "--moonlight", "--allow-commit",
            "--allow-push")
        self.assert_success(started)
        decisions = {
            item["key"]: item["value"] for item in self.state()["decisions"]
        }
        self.assertEqual("true", decisions["moonlight.enabled"])
        self.assertEqual("false", decisions["moonlight.allow_commit"])
        self.assertEqual("false", decisions["moonlight.allow_push"])
        self.assertNotIn("需要用户介入: 启动选择", started.stdout)

        refreshed = self.run_cli(
            "manifest", "--file", "src/service.cpp",
            "--moonlight-refresh", "--allow-commit", "--allow-push",
            "--decision", "用户授权当前精确清单的提交与推送。")
        self.assert_success(refreshed)
        refreshed_decisions = {}
        for item in self.state()["decisions"]:
            refreshed_decisions.setdefault(item["key"], []).append(
                item["value"])
        self.assertEqual(["src/service.cpp"], refreshed_decisions[
            "moonlight.business_file"])
        self.assertEqual(["true"], refreshed_decisions[
            "moonlight.allow_commit"])
        self.assertEqual(["true"], refreshed_decisions[
            "moonlight.allow_push"])

    def test_moonlight_refresh_requires_existing_mode_and_manifest_decision(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-NORMAL", "--path", "focused",
            "--pace", "continuous"))
        ordinary = self.run_cli(
            "manifest", "--file", "src/a.cpp", "--moonlight-refresh",
            "--allow-commit", "--allow-push", "--decision",
            "用户只授权当前精确文件。")
        self.assertEqual(2, ordinary.returncode)
        self.assertIn("未启用 Moonlight", ordinary.stderr)
        self.assert_success(self.run_cli("exit", "--reason", "切换测试流。"))

        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-MOON", "--path", "focused",
            "--pace", "continuous", "--moonlight"))
        missing_decision = self.run_cli(
            "manifest", "--file", "src/a.cpp", "--moonlight-refresh",
            "--allow-commit", "--allow-push")
        self.assertEqual(2, missing_decision.returncode)
        self.assertIn("自然语言", missing_decision.stderr)

        accepted = self.run_cli(
            "manifest", "--file", "src/a.cpp", "--moonlight-refresh",
            "--allow-commit", "--allow-push", "--decision",
            "用户授权当前精确清单的提交与推送。")
        self.assert_success(accepted)
        decisions = self.state()["decisions"]
        self.assertIn({
            "key": "moonlight.authorization_decision",
            "value": "用户授权当前精确清单的提交与推送。",
        }, decisions)
        self.assertIn({
            "key": "moonlight.business_file",
            "value": "src/a.cpp",
        }, decisions)

    def test_lightcheck_is_a_fail_open_internal_utility_not_a_flow_transition(self):
        source = os.path.join(self.root, "service.cpp")
        with open(source, "w", encoding="utf-8") as stream:
            stream.write("int lookup(int id) { return id + 42; }\n")
        before = None
        state_path = os.path.join(self.root, ".mae-flow.json")
        result = self.run_cli("lightcheck", "--file", "service.cpp")
        self.assert_success(result)
        self.assertIn("轻量编码预检", result.stdout + result.stderr)
        self.assertNotIn("两轮", result.stdout + result.stderr)
        self.assertEqual(before, None if not os.path.exists(state_path)
                         else self.state())

    def test_lightcheck_without_exact_changed_scope_skips_instead_of_scanning_dirty(self):
        with open(os.path.join(self.root, "inherited.cpp"),
                  "w", encoding="utf-8") as stream:
            stream.write("int inherited() { return 42; }\n")
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-LIGHT", "--path", "focused",
            "--pace", "continuous"))
        before = self.state()

        result = self.run_cli("lightcheck")

        self.assert_success(result)
        self.assertIn("未提供精确本次修改文件", result.stdout)
        self.assertEqual(before, self.state())

    def test_terminal_state_is_rotated_byte_for_byte_before_a_new_ticket(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-OLD", "--path", "focused",
            "--pace", "continuous"))
        self.assert_success(self.run_cli("exit", "--reason", "旧单结束"))
        state_path = os.path.join(self.root, ".mae-flow.json")
        with open(state_path, "rb") as stream:
            old_bytes = stream.read()

        started = self.run_cli(
            "start", "--ticket", "REQ-NEW", "--path", "full",
            "--pace", "continuous")
        self.assert_success(started)
        backups = [
            name for name in os.listdir(self.root)
            if name.startswith(".mae-flow.json.terminal-backup.")
        ]
        self.assertEqual(1, len(backups))
        with open(os.path.join(self.root, backups[0]), "rb") as stream:
            self.assertEqual(old_bytes, stream.read())
        self.assertEqual("REQ-NEW", self.state()["ticket"])

    def test_non_current_command_does_not_silently_migrate_legacy_state(self):
        state_path = os.path.join(self.root, ".mae-flow.json")
        original = (json.dumps({
            "schema_version": 2,
            "revision": 1,
            "current": "build",
            "config": {"单号": "REQ-OLD"},
            "choices": {"workflow": "full"},
            "history": [],
        }, ensure_ascii=False) + "\n").encode("utf-8")
        with open(state_path, "wb") as stream:
            stream.write(original)

        rejected = self.run_cli(
            "decision", "construction.scope", "普通决定不应暗中迁移。")

        self.assertEqual(2, rejected.returncode)
        self.assertIn("先执行 migrate-flow", rejected.stderr)
        with open(state_path, "rb") as stream:
            self.assertEqual(original, stream.read())
        self.assertFalse(any(
            name.startswith(".mae-flow.json.v2-backup.")
            for name in os.listdir(self.root)))

    def test_legacy_exit_is_immediate_without_ack_or_migration(self):
        state_path = os.path.join(self.root, ".mae-flow.json")
        original = (json.dumps({
            "schema_version": 2,
            "revision": 1,
            "current": "build",
            "config": {"单号": "REQ-OLD"},
            "choices": {"workflow": "full"},
            "history": [],
        }, ensure_ascii=False) + "\n").encode("utf-8")
        with open(state_path, "wb") as stream:
            stream.write(original)

        exited = self.run_cli("exit", "--reason", "立即退出旧流程。")

        self.assert_success(exited)
        self.assertFalse(os.path.exists(state_path))
        backups = [
            name for name in os.listdir(self.root)
            if name.startswith(".mae-flow.json.exited-backup.")
        ]
        self.assertEqual(1, len(backups))
        with open(os.path.join(self.root, backups[0]), "rb") as stream:
            self.assertEqual(original, stream.read())
        self.assertFalse(any(
            name.startswith(".mae-flow.json.v2-backup.")
            for name in os.listdir(self.root)))

    def test_every_conditional_document_in_manifest_needs_independent_selection(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-DOC", "--path", "focused",
            "--pace", "continuous"))
        story = "docs/mae-flow/requirements/REQ-DOC/story.md"
        rejected = self.run_cli(
            "manifest", "--file", "src/a.cpp", "--file", story)
        self.assertEqual(2, rejected.returncode)
        self.assertIn("条件文档", rejected.stderr)
        accepted = self.run_cli(
            "manifest", "--file", "src/a.cpp", "--file", story,
            "--conditional-document", story)
        self.assert_success(accepted)

    def test_manifest_rejects_flow_controls_and_requires_dirty_ownership(self):
        os.makedirs(os.path.join(self.root, "src"), exist_ok=True)
        with open(os.path.join(self.root, "src", "existing.cpp"),
                  "w", encoding="utf-8") as stream:
            stream.write("int existing() { return 1; }\n")
        started = self.run_cli(
            "start", "--ticket", "REQ-OWN", "--path", "focused",
            "--pace", "continuous")
        self.assert_success(started)
        self.assertIn("启动时已有改动", started.stdout)
        for path in (
                ".mae-flow-history.jsonl",
                ".mae-flow/session.json",
                ".codecheckcli/result.json"):
            with self.subTest(path=path):
                rejected = self.run_cli("manifest", "--file", path)
                self.assertEqual(2, rejected.returncode)
                self.assertIn("控制文件", rejected.stderr)

        unowned = self.run_cli(
            "manifest", "--file", "src/existing.cpp")
        self.assertEqual(2, unowned.returncode)
        self.assertIn("归属", unowned.stderr)
        owned = self.run_cli(
            "manifest", "--file", "src/existing.cpp",
            "--adopt-dirty",
            "src/existing.cpp=用户确认该启动时改动属于本单。")
        self.assert_success(owned)
        self.assertIn("本单已接管", owned.stdout)
        self.assertIn({
            "key": "delivery.adopted_dirty",
            "value": "src/existing.cpp",
        }, self.state()["decisions"])
        self.assertIn({
            "key": "delivery.adopted_dirty_reason",
            "value": "src/existing.cpp\t用户确认该启动时改动属于本单。",
        }, self.state()["decisions"])

    def test_staged_cp_manifests_allow_same_file_then_require_final_union(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-STAGE", "--path", "full",
            "--pace", "staged"))
        state = self.state()
        state["phase"] = "construction"
        state["current_cp"] = "CP1"
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        cp1 = self.run_cli(
            "manifest", "--checkpoint", "CP1", "--file", "src/a.cpp",
            "--commit-message", "[REQ-STAGE][feat]完成查询入口")
        self.assert_success(cp1)
        self.assert_success(self.run_cli(
            "decision", "cp-confirmed", "用户检视并确认 CP1。"))
        self.assert_success(self.run_cli(
            "advance", "cp-ready", "--key", "CP2"))
        cp2 = self.run_cli(
            "manifest", "--checkpoint", "CP2", "--file", "src/a.cpp",
            "--file", "src/b.cpp",
            "--commit-message", "[REQ-STAGE][feat]完成结果映射")
        self.assert_success(cp2)
        self.assert_success(self.run_cli(
            "decision", "cp-confirmed", "用户检视并确认 CP2。"))
        bad_final = self.run_cli(
            "manifest", "--final", "--file", "src/a.cpp")
        self.assertEqual(2, bad_final.returncode)
        final = self.run_cli(
            "manifest", "--final", "--file", "src/a.cpp", "--file",
            "src/b.cpp")
        self.assert_success(final)
        self.assertEqual(["src/a.cpp", "src/b.cpp"],
                         self.state()["delivery_files"])

    def test_next_full_checkpoint_gets_a_new_user_card_and_confirmation(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-CP", "--path", "full",
            "--pace", "staged"))
        state = self.state()
        state["phase"] = "construction"
        state["current_cp"] = "CP1"
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        self.assert_success(self.run_cli(
            "manifest", "--checkpoint", "CP1", "--file", "src/a.cpp",
            "--commit-message", "[REQ-CP][feat]完成 CP1"))
        first = self.run_cli(
            "decision", "cp-confirmed", "CP1 已检视。")
        self.assert_success(first)
        self.assertNotIn("需要用户介入: CP", first.stdout)

        second_ready = self.run_cli("advance", "cp-ready", "--key", "CP2")

        self.assert_success(second_ready)
        self.assertIn("需要用户介入: CP", second_ready.stdout)
        self.assertEqual("CP2", self.state()["current_cp"])
        self.assert_success(self.run_cli(
            "manifest", "--checkpoint", "CP2", "--file", "src/b.cpp",
            "--commit-message", "[REQ-CP][feat]完成 CP2"))
        second = self.run_cli(
            "decision", "cp-confirmed", "CP2 已检视。")
        self.assert_success(second)
        decisions = self.state()["decisions"]
        self.assertIn({
            "key": "construction.cp.CP1.confirmation",
            "value": "CP1 已检视。",
        }, decisions)
        self.assertIn({
            "key": "construction.cp.CP2.confirmation",
            "value": "CP2 已检视。",
        }, decisions)

    def test_staged_manifest_precedes_independent_checkpoint_confirmation(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-CP-MANIFEST", "--path", "full",
            "--pace", "staged"))
        state = self.state()
        state["phase"] = "construction"
        state["current_cp"] = "CP1"
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        arguments = (
            "manifest", "--checkpoint", "CP1", "--file", "src/a.cpp",
            "--commit-message", "[REQ-CP-MANIFEST][feat]完成 CP1",
        )

        planned = self.run_cli(*arguments)
        self.assert_success(planned)
        self.assert_success(self.run_cli(
            "decision", "cp-confirmed", "用户确认 CP1 结果。"))
        decisions = self.state()["decisions"]
        self.assertTrue(any(
            item["key"] == "delivery.cp.CP1.receipt"
            for item in decisions))
        wrong_cp = self.run_cli(
            "manifest", "--checkpoint", "CP2", "--file", "src/a.cpp",
            "--commit-message", "[REQ-CP-MANIFEST][feat]完成 CP2")
        self.assertEqual(2, wrong_cp.returncode)
        self.assertIn("当前 CP", wrong_cp.stderr)

    def test_delivery_card_uses_effective_moonlight_authorization(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-ML2", "--path", "focused",
            "--pace", "continuous", "--moonlight"))
        self.assert_success(self.run_cli(
            "manifest", "--file", "src/a.cpp", "--moonlight-refresh",
            "--allow-commit", "--allow-push", "--decision",
            "用户授权当前精确清单的提交与推送。"))
        state = self.state()
        state["phase"] = "delivery"
        state_path = os.path.join(self.root, ".mae-flow.json")
        with open(state_path, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        authorized = self.run_cli("current")
        self.assert_success(authorized)
        self.assertIn("需要用户介入: 交付", authorized.stdout)
        self.assertIn("src/a.cpp", authorized.stdout)

        state["risks"] = ["远端权限仍不明确"]
        with open(state_path, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        blocked = self.run_cli("current")
        self.assert_success(blocked)
        self.assertIn("需要用户介入: 交付", blocked.stdout)


if __name__ == "__main__":
    unittest.main()
