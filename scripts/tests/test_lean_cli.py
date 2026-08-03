#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Production CLI contracts for the lean Mae-Flow workflow."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CLI = os.path.join(ROOT, "scripts", "mae-flow.py")
STATUSLINE = os.path.join(ROOT, "scripts", "statusline.py")
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.adapters.lean_hook import LeanHookAdapter  # noqa: E402
from mae_flow_core.adapters.lean_exit import (  # noqa: E402
    exclusive_backup_bytes,
)


class LeanCliTests(unittest.TestCase):
    def test_confirmed_start_places_the_exact_working_branch_and_quality_plan(self):
        base = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"], cwd=self.root,
            text=True, encoding="utf-8", capture_output=True, check=True,
        ).stdout.strip()
        working = base + "_alice_REQ-BRANCH"
        started = self.run_cli(
            "start", "--ticket", "REQ-BRANCH", "--ticket-type", "feat",
            "--worker", "alice", "--base-branch", base,
            "--working-branch", working,
            "--build-method", "mvn compile -q",
            "--ut-method", "java-autout", "--ut-command", "mvn test",
            "--quality-plan",
            "每个 CP 用 Maven 编译一次；正式 CodeCheck 一次；UT 一次。",
            "--path", "focused", "--pace", "continuous",
            "--decision", "用户确认完整配置。",
        )

        self.assert_success(started)
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=self.root,
            text=True, encoding="utf-8", capture_output=True, check=True,
        ).stdout.strip()
        self.assertEqual(working, branch)
        self.assertIn("mvn compile -q", started.stdout)
        self.assertIn("每个 CP 用 Maven 编译一次", started.stdout)

    def test_confirmed_start_switches_to_an_existing_working_branch(self):
        subprocess.run(
            ["git", "config", "user.email", "mae-flow@example.invalid"],
            cwd=self.root, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Mae Flow Test"],
            cwd=self.root, check=True)
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "initial"],
            cwd=self.root, check=True, capture_output=True)
        base = subprocess.run(
            ["git", "branch", "--show-current"], cwd=self.root,
            text=True, encoding="utf-8", capture_output=True, check=True,
        ).stdout.strip()
        working = base + "_alice_REQ-EXISTING"
        subprocess.run(["git", "branch", working], cwd=self.root, check=True)

        started = self.run_cli(
            "start", "--ticket", "REQ-EXISTING", "--ticket-type", "feat",
            "--worker", "alice", "--base-branch", base,
            "--working-branch", working, "--build-method", "mvn compile -q",
            "--path", "focused", "--pace", "continuous",
            "--decision", "用户确认使用已有工作分支。",
        )

        self.assert_success(started)
        branch = subprocess.run(
            ["git", "branch", "--show-current"], cwd=self.root,
            text=True, encoding="utf-8", capture_output=True, check=True,
        ).stdout.strip()
        self.assertEqual(working, branch)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = self.temporary.name
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.env = dict(os.environ)
        self.env["PYTHONPYCACHEPREFIX"] = os.path.join(
            self.root, "pycache")
        self.capability_invocations = 0

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, *arguments):
        if len(arguments) >= 3 and arguments[0] == "decision":
            self.submit_user_prompt(arguments[2])
        if (arguments and arguments[0] == "manifest"
                and "--moonlight-refresh" in arguments
                and "--decision" in arguments):
            index = arguments.index("--decision")
            if index + 1 < len(arguments):
                self.submit_user_prompt(arguments[index + 1])
        return self.run_cli_raw(*arguments)

    def run_cli_raw(self, *arguments):
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

    def submit_user_prompt(self, text, session_id="cli-user-session"):
        result = LeanHookAdapter(self.root).handle(
            "UserPromptSubmit",
            {"session_id": session_id, "prompt": text},
        )
        self.assertEqual(0, result.exit_code, result.stderr)
        return result

    def run_statusline(self):
        return subprocess.run(
            [sys.executable, STATUSLINE],
            cwd=self.root,
            env=self.env,
            input=json.dumps({"cwd": self.root}),
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

    def observe_checkpoint_commit(self, checkpoint):
        state = self.state()
        receipt = next(
            item["value"] for item in state["decisions"]
            if item["key"] == "delivery.cp.%s.receipt" % checkpoint)
        state["decisions"].append({
            "key": "delivery.git.commit_observation",
            "value": json.dumps({
                "receipt_digest": json.loads(receipt)["digest"],
                "sha": "c" * 40,
            }, sort_keys=True, separators=(",", ":")),
        })
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)

    def test_user_owned_decision_consumes_one_current_codeagent_prompt(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-USER-EVENT", "--path", "focused",
            "--pace", "continuous"))
        prompt = "可以，按刚才展示的解析边界继续。"
        decision = "用户确认只修改已展示的解析边界。"

        fabricated = self.run_cli_raw(
            "decision", "startup-confirmed", decision)

        self.assertEqual(2, fabricated.returncode)
        self.assertEqual("startup", self.state()["phase"])

        self.submit_user_prompt(prompt)
        accepted = self.run_cli_raw(
            "decision", "startup-confirmed", decision)
        reused = self.run_cli_raw(
            "decision", "upgrade-to-full", decision)

        self.assert_success(accepted)
        self.assertEqual("construction", self.state()["phase"])
        self.assertEqual(2, reused.returncode)
        consumed = [
            item for item in self.state()["decisions"]
            if item["key"] == "user.event.consumed"
        ]
        self.assertEqual(1, len(consumed))

    def test_user_owned_decision_consumes_current_askuser_answer(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-ASKUSER", "--path", "focused",
            "--pace", "continuous"))
        answer = "确认按已展示的范围继续。"

        captured = LeanHookAdapter(self.root).handle(
            "PostToolUse",
            {
                "tool_name": "AskUserQuestion",
                "tool_input": {
                    "questions": [{"question": "是否确认当前范围？"}],
                },
                "tool_response": answer,
            },
        )
        accepted = self.run_cli_raw(
            "decision", "startup-confirmed", "用户确认当前范围。")

        self.assertEqual(0, captured.exit_code, captured.stderr)
        self.assert_success(accepted)
        self.assertEqual("construction", self.state()["phase"])
        consumed = [
            item for item in self.state()["decisions"]
            if item["key"] == "user.event.consumed"
        ]
        self.assertEqual(1, len(consumed))
        receipt = json.loads(consumed[0]["value"])
        self.assertEqual("startup-confirmed", receipt["semantic_event"])

    def test_user_owned_decision_rejects_an_event_from_an_older_state(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-STALE-EVENT", "--path", "focused",
            "--pace", "continuous"))
        self.submit_user_prompt("按当前范围继续。")
        self.assert_success(self.run_cli_raw(
            "decision", "notes.context", "补充一条机器已查证的上下文。"))

        stale = self.run_cli_raw(
            "decision", "startup-confirmed", "用户确认当前范围。")

        self.assertEqual(2, stale.returncode)
        self.assertEqual("startup", self.state()["phase"])

    def run_capability(self, kind, outcome="returned"):
        self.capability_invocations += 1
        return self.run_cli_raw(
            "advance", "capability-" + outcome,
            "--key", kind,
            "--decision", "opaque synchronous CodeAgent return %d" %
            self.capability_invocations,
        )

    def assert_success(self, result):
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_start_persists_and_renders_the_complete_confirmed_configuration(self):
        started = self.run_cli(
            "start",
            "--ticket", "REQ-CONFIG",
            "--ticket-type", "feat",
            "--worker", "zhangsan",
            "--requirement", "requirements/query.md",
            "--base-branch", "main",
            "--build-method", "build-fix",
            "--ut-method", "ut-generator-agent",
            "--ut-command", "ctest --test-dir build",
            "--path", "full",
            "--pace", "continuous",
        )

        self.assert_success(started)
        self.assertEqual({
            "worker": "zhangsan",
            "ticket_type": "feat",
            "requirement_source": "requirements/query.md",
            "base_branch": "main",
            "working_branch": "main_zhangsan_REQ-CONFIG",
            "build_method": "build-fix",
            "ut_method": "ut-generator-agent",
            "ut_command": "ctest --test-dir build",
        }, self.state()["startup_config"])
        for expected in (
                "完整启动配置", "zhangsan", "requirements/query.md",
                "main_zhangsan_REQ-CONFIG", "build-fix",
                "ut-generator-agent", "ctest --test-dir build"):
            self.assertIn(expected, started.stdout)
        self.assertIn("Proposed startup configuration", started.stdout)
        self.assertNotIn("Confirmed startup configuration", started.stdout)

    def test_start_can_atomically_consume_the_one_startup_card_decision(self):
        started = self.run_cli_raw(
            "start", "--ticket", "REQ-ONE-CARD",
            "--ticket-type", "feat", "--worker", "zhangsan",
            "--requirement", "用户消息中的需求",
            "--base-branch", "main",
            "--working-branch", "main_zhangsan_REQ-ONE-CARD",
            "--build-method", "build-fix",
            "--ut-method", "ut-generator-agent",
            "--ut-command", "ctest --test-dir build",
            "--path", "full", "--pace", "continuous",
            "--decision", "用户确认这张完整配置卡并进入 Spec。",
        )

        self.assert_success(started)
        state = self.state()
        self.assertEqual("spec", state["phase"])
        self.assertIn(
            {"key": "startup.confirmation",
             "value": "用户确认这张完整配置卡并进入 Spec。"},
            state["decisions"],
        )
        self.assertIn("Confirmed startup configuration", started.stdout)
        self.assertNotIn("需要用户介入: Intake", started.stdout)

    def test_repository_defaults_prefill_startup_and_cli_values_override_them(self):
        with open(os.path.join(self.root, ".mae-flow-defaults.json"),
                  "w", encoding="utf-8-sig") as stream:
            json.dump({
                "工号": "default-user",
                "单号类型": "fix",
                "基线分支": "develop",
                "编译方式": "repository-build-skill",
                "UT生成方式": "repository-ut-agent",
                "UT运行命令": "repository-test-command",
            }, stream, ensure_ascii=False)

        started = self.run_cli(
            "start", "--ticket", "REQ-DEFAULTS",
            "--ticket-type", "feat",
            "--worker", r"DOMAIN\actual-user",
            "--path", "focused", "--pace", "staged",
        )

        self.assert_success(started)
        config = self.state()["startup_config"]
        self.assertEqual("actual-user", config["worker"])
        self.assertEqual("feat", config["ticket_type"])
        self.assertEqual("develop", config["base_branch"])
        self.assertEqual(
            "develop_actual-user_REQ-DEFAULTS", config["working_branch"])
        self.assertEqual("repository-build-skill", config["build_method"])
        self.assertEqual("repository-ut-agent", config["ut_method"])
        self.assertEqual("repository-test-command", config["ut_command"])

    def test_malformed_repository_defaults_are_visible_but_nonblocking(self):
        with open(os.path.join(self.root, ".mae-flow-defaults.json"),
                  "w", encoding="utf-8") as stream:
            stream.write("{broken-json")

        started = self.run_cli(
            "start", "--ticket", "REQ-BAD-DEFAULTS",
            "--ticket-type", "fix", "--worker", "zhangsan",
            "--base-branch", "main", "--path", "focused",
            "--pace", "continuous",
        )

        self.assert_success(started)
        state = self.state()
        self.assertFalse(any(
            "defaults" in risk.lower() for risk in state["risks"]))
        warnings = [
            item["value"] for item in state["decisions"]
            if item["key"] == "startup.defaults_warning"
        ]
        self.assertEqual(1, len(warnings))
        self.assertIn("预设读取提示", started.stdout)

    def test_current_recovers_selected_domains_and_final_reconciliation(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-DOMAIN", "--path", "focused",
            "--pace", "continuous"))
        domain = "docs/specs/order-query.md"

        self.assert_success(self.run_cli_raw(
            "advance", "domain-selected", "--key", domain,
            "--decision", "本次只涉及订单查询业务能力。"))
        self.assert_success(self.run_cli_raw(
            "advance", "domain-updated", "--key", domain,
            "--decision", "查询过滤规则已按交付后的当前行为更新。"))
        current = self.run_cli_raw("current")

        self.assert_success(current)
        self.assertIn("Selected behavior domains", current.stdout)
        self.assertIn(domain, current.stdout)
        self.assertIn("updated", current.stdout)
        self.assertIn("查询过滤规则", current.stdout)

    def test_full_spec_and_story_artifacts_are_grouped_locally_by_default(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-LOCAL-DESIGN", "--path", "full",
            "--pace", "continuous"))

        artifacts = {
            item["kind"]: item["path"] for item in self.state()["artifacts"]}
        self.assertTrue(artifacts["spec"].startswith(".mae-flow-work/"))
        self.assertTrue(artifacts["spec"].endswith("/spec.md"))
        self.assertTrue(artifacts["story"].startswith(".mae-flow-work/"))
        self.assertTrue(artifacts["story"].endswith("/story.md"))

    def test_cp_card_combines_actual_review_ut_intent_and_next_brief(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-CP-CARD", "--path", "full",
            "--pace", "continuous"))
        state = self.state()
        state["phase"] = "construction"
        state["current_cp"] = "CP1"
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        facts = (
            ("cp-brief", "CP1", "提取可测试的查询条件构造。"),
            ("cp-result", "CP1", "查询构造已从数据库框架中分离。"),
            ("cp-review", "CP1", "Reviewer 未发现阻塞问题。"),
            ("cp-ut-intent", "CP1", "覆盖条件组合，不 Mock 数据库连接。"),
            ("cp-brief", "CP2", "接入结果映射并保持旧接口。"),
        )
        for event, checkpoint, text in facts:
            self.assert_success(self.run_cli_raw(
                "advance", event, "--key", checkpoint,
                "--decision", text))
        self.assert_success(self.run_capability("build"))
        self.assert_success(self.run_cli_raw(
            "advance", "cp-ready", "--key", "CP1"))

        current = self.run_cli_raw("current")

        self.assert_success(current)
        for expected in (
                "原简报", "查询构造已从数据库框架中分离",
                "Reviewer 未发现阻塞问题", "不 Mock 数据库连接",
                "下一 CP: CP2", "接入结果映射"):
            self.assertIn(expected, current.stdout)

    def test_exclusive_backups_never_replace_a_name_collision(self):
        base = os.path.join(self.root, ".mae-flow.json")
        patches = (
            mock.patch(
                "mae_flow_core.adapters.lean_exit.time.strftime",
                return_value="20260802-010203"),
            mock.patch(
                "mae_flow_core.adapters.lean_exit.time.time_ns",
                return_value=456),
            mock.patch(
                "mae_flow_core.adapters.lean_exit.os.getpid",
                return_value=123),
        )
        with patches[0], patches[1], patches[2]:
            first = exclusive_backup_bytes(
                base, b"first", "terminal-backup")
            second = exclusive_backup_bytes(
                base, b"second", "terminal-backup")

        self.assertNotEqual(first, second)
        with open(first, "rb") as stream:
            self.assertEqual(b"first", stream.read())
        with open(second, "rb") as stream:
            self.assertEqual(b"second", stream.read())

    def test_full_flow_surfaces_only_five_high_value_user_stops(self):
        started = self.run_cli(
            "start", "--ticket", "REQ-42", "--path", "full",
            "--pace", "continuous")
        self.assert_success(started)
        self.assertIn("需要用户介入: Intake（启动选择", started.stdout)

        startup = self.run_cli(
            "decision", "startup-confirmed", "按完整开发和一次交付继续。")
        self.assert_success(startup)
        self.assertIn("需要用户介入: Spec", startup.stdout)

        question = json.dumps({
            "parent": "",
            "evidence": "当前行为只覆盖主载波。",
            "impact": "SUL 资源选择仍不明确。",
            "recommendation": "仅在配置 SUL 时使用 SUL 资源。",
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        convergence = json.dumps({
            "answer_count": 1,
            "grill_sha256": "a" * 64,
        }, sort_keys=True, separators=(",", ":"))
        critic = json.dumps({
            "grill_sha256": "a" * 64,
            "input_coverage": "complete",
            "spec_sha256": "b" * 64,
        }, sort_keys=True, separators=(",", ":"))
        self.assert_success(self.run_cli_raw(
            "advance", "grill-question", "--key", "GQ-001",
            "--decision", question))
        self.assert_success(self.run_cli(
            "decision", "grill-answer", "用户确认推荐的 SUL 边界。",
            "--key", "GQ-001"))
        self.assert_success(self.run_cli_raw(
            "advance", "grill-converged", "--decision", convergence))
        self.assert_success(self.run_capability("grill"))
        self.assert_success(self.run_cli_raw(
            "advance", "grill-clear", "--decision", critic))
        spec = self.run_cli(
            "decision", "spec-confirmed", "可观察行为和范围已确认。")
        self.assert_success(spec)
        self.assertIn("需要用户介入: Design（Story", spec.stdout)

        self.assert_success(self.run_capability("story"))
        self.assert_success(self.run_capability("reviewer"))
        self.assert_success(self.run_cli(
            "decision", "design-review-approved", "设计检视无待裁决项。"))
        story = self.run_cli(
            "decision", "story-confirmed", "实现边界和可测性设计已确认。")
        self.assert_success(story)
        self.assertNotIn("需要用户介入: CP", story.stdout)

        for event, text in (
                ("cp-brief", "完成缓存删除边界。"),
                ("cp-result", "缓存删除逻辑已经实现。"),
                ("cp-review", "CODE Reviewer 未发现阻塞问题。"),
                ("cp-ut-intent", "覆盖删除成功和缓存不存在场景。")):
            self.assert_success(self.run_cli_raw(
                "advance", event, "--key", "CP1", "--decision", text))
        self.assert_success(self.run_capability("build"))
        ready = self.run_cli_raw("advance", "cp-ready", "--key", "CP1")
        self.assert_success(ready)
        self.assertIn("需要用户介入: CP", ready.stdout)

        cp = self.run_cli(
            "decision", "cp-confirmed", "本 CP 的结果和后续节奏已确认。")
        self.assert_success(cp)
        self.assertNotIn("需要用户介入", cp.stdout)
        self.assert_success(self.run_cli("advance", "construction-complete"))
        self.assert_success(self.run_capability("codecheck"))
        self.assert_success(self.run_capability("ut"))
        self.assert_success(self.run_cli_raw(
            "advance", "final-conformance", "--decision",
            "最终代码、覆盖与确认的 Spec/Story 一致。"))
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
        self.assertEqual([], self.state()["artifacts"])
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
        artifacts = self.state()["artifacts"]
        self.assertEqual(
            ["spec", "story", "ut-handoff"],
            [item["kind"] for item in artifacts],
        )
        self.assertTrue(artifacts[0]["path"].endswith("/spec.md"))
        self.assertIn(".mae-flow-work", artifacts[1]["path"])
        self.assertTrue(artifacts[2]["path"].endswith("/ut-handoff.md"))

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
        first = self.run_capability("build", "not-observed")
        self.assert_success(first)

        rejected = self.run_capability("build")
        self.assertEqual(2, rejected.returncode)
        self.assertIn("自然语言重试决定", rejected.stderr)
        self.assertEqual(1, len(self.state()["capabilities"]))

        authorized = self.run_cli(
            "decision", "capability.retry.build",
            "构建环境已恢复，用户决定再尝试一次。")
        self.assert_success(authorized)
        recovered = self.run_cli("current")
        self.assert_success(recovered)
        self.assertIn(
            "build: 已授权一次重试（尚未消费）", recovered.stdout)
        retried = self.run_capability("build")
        self.assert_success(retried)
        self.assertEqual(2, len(self.state()["capabilities"]))
        consumed_status = self.run_cli("current")
        self.assert_success(consumed_status)
        self.assertIn(
            "build: 再次调用前需要用户决定", consumed_status.stdout)

        consumed = self.run_capability("build")
        self.assertEqual(2, consumed.returncode)
        self.assertEqual(2, len(self.state()["capabilities"]))

    def test_capability_slot_is_derived_from_workflow_state(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-SLOT", "--path", "focused",
            "--pace", "continuous"))
        self.assert_success(self.run_cli(
            "decision", "startup-confirmed", "已定位局部修复。"))
        first = self.run_capability("build")
        changed_labels = self.run_capability("build")

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
        self.assert_success(self.run_capability("build"))

    def test_new_cp_is_shown_as_planned_work_not_an_authorized_retry(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-NEW-SLOT", "--path", "focused",
            "--pace", "continuous"))
        self.assert_success(self.run_cli(
            "decision", "startup-confirmed", "已定位局部修复。"))
        self.assert_success(self.run_capability("build"))

        next_cp = self.run_cli("advance", "cp-opened", "--key", "CP2")

        self.assert_success(next_cp)
        self.assertIn(
            "build: 当前新语义 slot 尚未调用；仅按阶段计划调用",
            next_cp.stdout,
        )
        self.assertNotIn(
            "build: 已授权一次重试（尚未消费）", next_cp.stdout)

    def test_public_cli_cannot_forge_a_capability_record(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-NO-FORGE", "--path", "focused",
            "--pace", "continuous"))
        before = self.state()

        rejected = self.run_cli(
            "capability-record", "build", "returned",
            "--source", "forged", "--environment", "forged")

        self.assertEqual(2, rejected.returncode)
        self.assertIn("invalid choice", rejected.stderr)
        self.assertEqual(before, self.state())

    def test_design_and_new_cp_reviewer_use_distinct_state_slots(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-REVIEW-SLOT", "--path", "full",
            "--pace", "staged"))
        state = self.state()
        state["phase"] = "story"
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        self.assert_success(self.run_capability("reviewer"))

        state = self.state()
        state["phase"] = "construction"
        state["current_cp"] = "CP2"
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        self.assert_success(self.run_cli(
            "decision", "capability.retry.reviewer",
            "用户确认在 CP2 的精确检视槽位再尝试一次。"))
        cp = self.run_capability("reviewer")

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
        failed = self.run_capability("build", "not-observed")
        self.assert_success(failed)
        self.assertTrue(self.state()["risks"])

        self.assert_success(self.run_cli(
            "decision", "capability.retry.build",
            "用户确认环境恢复，重试一次。"))
        returned = self.run_capability("build")

        self.assert_success(returned)
        self.assertEqual([], self.state()["risks"])

    def test_review_nonreturn_is_visible_without_blocking_progress(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-REVIEW-RETRY", "--path", "full",
            "--pace", "continuous"))
        self.assert_success(self.run_cli(
            "decision", "startup-confirmed", "用户确认进入 Full Spec。"))
        self.assert_success(self.run_capability("grill", "not-observed"))
        self.assert_success(self.run_cli(
            "decision", "grill-failed", "Grill 本轮超时，不自动重试。"))
        self.assertEqual([], self.state()["risks"])

        self.assert_success(self.run_cli(
            "decision", "capability.retry.grill",
            "用户确认环境恢复，授权 Grill 再尝试一次。"))
        self.assert_success(self.run_capability("grill"))
        self.assert_success(self.run_cli(
            "decision", "grill-clear", "Grill 已返回，未发现待决分支。"))

        self.assertEqual([], self.state()["risks"])
        state = self.state()
        state["phase"] = "quality"
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        self.assert_success(self.run_cli_raw(
            "advance", "final-conformance", "--decision",
            "最终实现与确认范围一致。"))
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
        state_path = os.path.join(self.root, ".mae-flow.json")
        pointer_path = state_path + ".exited"
        self.assertFalse(os.path.exists(state_path))
        with open(pointer_path, encoding="utf-8") as stream:
            pointer = json.load(stream)
        self.assertEqual("exited", pointer["status"])
        self.assertRegex(pointer["state_sha256"], r"^[0-9a-f]{64}$")
        current = self.run_cli("current")
        self.assert_success(current)
        self.assertIn("状态: exited", current.stdout)
        blocked = self.run_cli("advance", "startup-confirmed")
        self.assertEqual(2, blocked.returncode)
        self.assertIn("已退出", blocked.stderr)
        again = self.run_cli("exit", "--reason", "保持退出")
        self.assert_success(again)
        with open(pointer_path, encoding="utf-8") as stream:
            self.assertEqual(pointer, json.load(stream))

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
        with open(os.path.join(self.root, "baseline.txt"),
                  "w", encoding="utf-8") as stream:
            stream.write("baseline\n")
        subprocess.run(["git", "add", "baseline.txt"],
                       cwd=self.root, check=True)
        subprocess.run([
            "git", "-c", "user.name=Mae Flow Test",
            "-c", "user.email=mae-flow@example.invalid",
            "commit", "-q", "-m", "baseline",
        ], cwd=self.root, check=True)
        source_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root,
            text=True).strip()
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
            "--expected-destination-sha", source_sha)
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
        self.assertNotIn("需要用户介入: Intake（启动选择", started.stdout)

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

        fabricated = self.run_cli_raw(
            "manifest", "--file", "src/a.cpp", "--moonlight-refresh",
            "--allow-commit", "--allow-push", "--decision",
            "用户授权当前精确清单的提交与推送。")
        self.assertEqual(2, fabricated.returncode)

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

    def test_new_start_rotates_old_exit_pointer_without_overwrite(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-OLD", "--path", "focused",
            "--pace", "continuous"))
        self.assert_success(self.run_cli("exit", "--reason", "旧单结束"))
        state_path = os.path.join(self.root, ".mae-flow.json")
        pointer_path = state_path + ".exited"
        with open(pointer_path, "rb") as stream:
            old_pointer = stream.read()

        started = self.run_cli(
            "start", "--ticket", "REQ-NEW", "--path", "full",
            "--pace", "continuous")
        self.assert_success(started)
        backups = [
            name for name in os.listdir(self.root)
            if name.startswith(".mae-flow.json.exited-backup.")
        ]
        self.assertEqual(1, len(backups))
        with open(os.path.join(self.root, backups[0]), "rb") as stream:
            self.assertEqual(old_pointer, stream.read())
        self.assertFalse(os.path.exists(pointer_path))
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
        with open(state_path + ".exited", encoding="utf-8") as stream:
            pointer = json.load(stream)
        snapshot = os.path.join(
            self.root, *pointer["snapshot"].split("/"))
        with open(snapshot, "rb") as stream:
            self.assertEqual(original, stream.read())
        self.assertFalse(any(
            name.startswith(".mae-flow.json.v2-backup.")
            for name in os.listdir(self.root)))

    def test_statusline_distinguishes_active_complete_exited_and_corrupt_v3(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-STATUS", "--path", "focused",
            "--pace", "continuous"))
        active = self.run_statusline()
        self.assertEqual(0, active.returncode, active.stderr)
        self.assertIn("REQ-STATUS", active.stdout)
        self.assertIn("startup", active.stdout.casefold())
        self.assertIn("focused", active.stdout.casefold())

        state = self.state()
        state["status"] = "complete"
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream)
        complete = self.run_statusline()
        self.assertIn("complete", complete.stdout.casefold())

        state["status"] = "active"
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "w", encoding="utf-8") as stream:
            json.dump(state, stream)
        self.assert_success(self.run_cli("exit", "--reason", "状态栏退出"))
        exited = self.run_statusline()
        self.assertIn("已退出", exited.stdout)

        os.remove(os.path.join(self.root, ".mae-flow.json.exited"))
        with open(os.path.join(self.root, ".mae-flow.json"),
                  "wb") as stream:
            stream.write(b"corrupt-v3-state")
        corrupt = self.run_statusline()
        self.assertIn("状态异常", corrupt.stdout)

    def test_every_conditional_document_in_manifest_needs_independent_selection(self):
        self.assert_success(self.run_cli(
            "start", "--ticket", "REQ-DOC", "--path", "focused",
            "--pace", "continuous"))
        story = "docs/specs/requirements/REQ-DOC/story.md"
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
        self.assert_success(self.run_capability("build"))
        self.assert_success(self.run_cli_raw(
            "advance", "cp-ready", "--key", "CP1"))
        self.assert_success(self.run_cli(
            "decision", "cp-confirmed", "用户检视并确认 CP1。"))
        self.observe_checkpoint_commit("CP1")
        self.assert_success(self.run_cli(
            "advance", "cp-opened", "--key", "CP2"))
        self.assert_success(self.run_capability("build"))
        cp2 = self.run_cli(
            "manifest", "--checkpoint", "CP2", "--file", "src/a.cpp",
            "--file", "src/b.cpp",
            "--commit-message", "[REQ-STAGE][feat]完成结果映射")
        self.assert_success(cp2)
        self.assert_success(self.run_cli_raw(
            "advance", "cp-ready", "--key", "CP2"))
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
        self.assert_success(self.run_capability("build"))
        self.assert_success(self.run_cli_raw(
            "advance", "cp-ready", "--key", "CP1"))
        first = self.run_cli(
            "decision", "cp-confirmed", "CP1 已检视。")
        self.assert_success(first)
        self.assertNotIn("需要用户介入: CP", first.stdout)
        self.observe_checkpoint_commit("CP1")

        second_opened = self.run_cli(
            "advance", "cp-opened", "--key", "CP2")

        self.assert_success(second_opened)
        self.assertNotIn("需要用户介入: CP", second_opened.stdout)
        self.assertEqual("CP2", self.state()["current_cp"])
        self.assert_success(self.run_capability("build"))
        self.assert_success(self.run_cli(
            "manifest", "--checkpoint", "CP2", "--file", "src/b.cpp",
            "--commit-message", "[REQ-CP][feat]完成 CP2"))
        second_ready = self.run_cli_raw(
            "advance", "cp-ready", "--key", "CP2")
        self.assert_success(second_ready)
        self.assertIn("需要用户介入: CP", second_ready.stdout)
        self.assertIn("本批精确提交计划", second_ready.stdout)
        self.assertIn("src/b.cpp", second_ready.stdout)
        self.assertIn("[REQ-CP][feat]完成 CP2", second_ready.stdout)
        self.assertEqual("CP2", self.state()["current_cp"])
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
        self.assert_success(self.run_capability("build"))
        self.assert_success(self.run_cli_raw(
            "advance", "cp-ready", "--key", "CP1"))
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
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
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
        self.assertIn(
            "Moonlight requested: allow_commit=true, allow_push=true",
            authorized.stdout,
        )
        self.assertIn(
            "Moonlight effective: allow_commit=true, allow_push=true",
            authorized.stdout,
        )
        self.assertIn("Moonlight block reason: none", authorized.stdout)

        state["risks"] = ["远端权限仍不明确"]
        with open(state_path, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
        blocked = self.run_cli("current")
        self.assert_success(blocked)
        self.assertIn("需要用户介入: 交付", blocked.stdout)
        self.assertIn(
            "Moonlight requested: allow_commit=true, allow_push=true",
            blocked.stdout,
        )
        self.assertIn(
            "Moonlight effective: allow_commit=false, allow_push=false",
            blocked.stdout,
        )
        self.assertIn(
            "Moonlight block reason: Unresolved workflow risk requires a "
            "safe stop.",
            blocked.stdout,
        )


if __name__ == "__main__":
    unittest.main()
