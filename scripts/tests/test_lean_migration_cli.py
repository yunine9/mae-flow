#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Subprocess contracts for safe schema-v2 to lean schema-v3 cutover."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.abspath(os.path.join(SCRIPTS, ".."))
CLI = os.path.join(SCRIPTS, "mae-flow.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def legacy(current="build", workflow="full", **extra):
    state = {
        "schema_version": 2,
        "revision": 7,
        "current": current,
        "config": {"单号": "REQ-42"},
        "choices": {"workflow": workflow},
        "history": [],
    }
    state.update(extra)
    return state


class LeanMigrationCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.state_path = os.path.join(self.root, ".mae-flow.json")
        self.tokens_path = self.state_path + ".tokens"
        self.env = dict(os.environ)
        self.env["PYTHONPYCACHEPREFIX"] = os.path.join(
            self.root, "pycache")

    def tearDown(self):
        self.temp.cleanup()

    def write_state(self, state):
        raw = (json.dumps(
            state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        with open(self.state_path, "wb") as stream:
            stream.write(raw)
        return raw

    def run_cli(self, command="current"):
        return subprocess.run(
            [sys.executable, CLI, command],
            cwd=self.root,
            env=self.env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=20,
        )

    def backups(self):
        prefix = ".mae-flow.json.v2-backup."
        return sorted(
            os.path.join(self.root, name)
            for name in os.listdir(self.root)
            if name.startswith(prefix)
        )

    def read_state(self):
        with open(self.state_path, encoding="utf-8") as stream:
            return json.load(stream)

    def read_state_bytes(self):
        with open(self.state_path, "rb") as stream:
            return stream.read()

    def assert_backup(self, original):
        backups = self.backups()
        self.assertEqual(1, len(backups))
        self.assertRegex(
            os.path.basename(backups[0]),
            r"^\.mae-flow\.json\.v2-backup\.\d{8}-\d{6}"
            r"\.\d+\.\d+(?:\.\d+)?$",
        )
        self.assertNotRegex(os.path.basename(backups[0]), r"[:*?\"<>|]")
        with open(backups[0], "rb") as stream:
            self.assertEqual(original, stream.read())

    def test_current_migrates_active_full_before_legacy_dispatch(self):
        original = self.write_state(legacy(
            current="build",
            config={
                "单号": "REQ-42",
                "需求文档": "docs/request.md",
                "SPEC路径": "docs/spec.md",
                "基线分支": "main",
            },
            choices={"workflow": "full", "grill": "yes"},
        ))

        result = self.run_cli()

        self.assertEqual(0, result.returncode, result.stderr)
        state = self.read_state()
        self.assertEqual(3, state["schema_version"])
        self.assertEqual("lean-v1", state["engine"])
        self.assertEqual("full", state["path"])
        self.assertEqual("construction", state["phase"])
        self.assertIn("阶段: construction", result.stdout)
        self.assertIn("request: docs/request.md", result.stdout)
        self.assertIn("config.基线分支: main", result.stdout)
        self.assertIn("风险:", result.stdout)
        self.assertNotIn("当前步骤 build", result.stdout)
        self.assert_backup(original)

    def test_current_consumes_real_token_sidecar_without_persisting_ledgers(self):
        original = self.write_state(legacy(
            current="build",
            agent_tasks={
                "COMPILE": {
                    "step": "build",
                    "head": "a" * 40,
                    "sha256": "task-digest",
                    "issuance_id": "build-issuance-1",
                },
            },
        ))
        tokens = {
            "COMPILE": {
                "step": "build",
                "head": "b" * 40,
                "status": "OK",
                "task_sha256": "task-digest",
                "task_issuance_id": "build-issuance-1",
            },
        }
        with open(self.tokens_path, "w", encoding="utf-8") as stream:
            json.dump(tokens, stream)

        result = self.run_cli()

        self.assertEqual(0, result.returncode, result.stderr)
        state = self.read_state()
        self.assertEqual(1, len(state["capabilities"]))
        self.assertEqual("build", state["capabilities"][0]["kind"])
        self.assertEqual("returned", state["capabilities"][0]["outcome"])
        self.assertNotIn("agent_tasks", state)
        self.assertNotIn("tokens", state)
        self.assertIn("build | returned", result.stdout)
        with open(self.tokens_path, encoding="utf-8") as stream:
            self.assertEqual(tokens, json.load(stream))
        self.assert_backup(original)

    def test_corrupt_token_sidecar_is_preserved_and_becomes_a_recovery_risk(self):
        original = self.write_state(legacy(current="verify_ut"))
        sidecar = b'{"UT": broken-token-sidecar'
        with open(self.tokens_path, "wb") as stream:
            stream.write(sidecar)

        result = self.run_cli()

        self.assertEqual(0, result.returncode, result.stderr)
        state = self.read_state()
        self.assertEqual([], state["capabilities"])
        self.assertTrue(any(
            "token sidecar is unreadable" in risk
            for risk in state["risks"]))
        with open(self.tokens_path, "rb") as stream:
            self.assertEqual(sidecar, stream.read())
        self.assert_backup(original)

    def test_internal_command_maps_each_focused_legacy_family(self):
        cases = (
            ("hotfix", "hf_open", "spec"),
            ("tweak", "tw_change", "construction"),
            ("review", "rf_fix", "construction"),
        )
        for index, (workflow, current, phase) in enumerate(cases):
            with self.subTest(workflow=workflow):
                if index:
                    os.remove(self.state_path)
                    for backup in self.backups():
                        os.remove(backup)
                original = self.write_state(legacy(
                    current=current, workflow=workflow))

                result = self.run_cli("migrate-flow")

                self.assertEqual(0, result.returncode, result.stderr)
                state = self.read_state()
                self.assertEqual("focused", state["path"])
                self.assertEqual(phase, state["phase"])
                self.assertIn("阶段: %s" % phase, result.stdout)
                self.assert_backup(original)

    def test_terminal_state_remains_complete_and_is_summarized(self):
        original = self.write_state(legacy(current="end"))

        result = self.run_cli()

        self.assertEqual(0, result.returncode, result.stderr)
        state = self.read_state()
        self.assertEqual("complete", state["status"])
        self.assertEqual("delivery", state["phase"])
        self.assertIn("状态: complete", result.stdout)
        self.assert_backup(original)

    def test_ambiguous_state_revokes_all_delivery_authorization(self):
        original = self.write_state(legacy(
            current="verify_future_tool",
            config={
                "单号": "REQ-42",
                "automation": {"allow_push": True},
            },
            choices={
                "workflow": "full",
                "delivery": {"automatic_push": True},
                "moonlight": {"allow_commit": True, "allow_push": True},
            },
            decisions={
                "moonlight.enabled": "true",
                "moonlight.allow_commit": "true",
                "moonlight.allow_push": "true",
                "moonlight.business_file": "src/a.cpp",
                "delivery.commit_message": "[REQ-42][fix]repair",
                "delivery.confirmation": "approved",
                "policy": {"moonlight": {"allow_commit": True}},
                "business.rule": "keep this decision",
            },
            delivery_files=["src/a.cpp"],
        ))

        result = self.run_cli()

        self.assertEqual(0, result.returncode, result.stderr)
        state = self.read_state()
        self.assertEqual([], state["delivery_files"])
        decision_keys = [item["key"] for item in state["decisions"]]
        self.assertIn("business.rule", decision_keys)
        self.assertNotIn("config.automation", decision_keys)
        self.assertNotIn("policy", decision_keys)
        self.assertFalse(any(
            key == "delivery" or key.startswith("delivery.")
            or key == "moonlight" or key.startswith("moonlight.")
            for key in decision_keys
        ))
        self.assertTrue(state["risks"])
        self.assertIn("natural-language", state["risks"][-1])
        self.assertIn("风险:", result.stdout)
        self.assertIn("natural-language", result.stdout)
        self.assertNotIn("allow_push", result.stdout)
        self.assert_backup(original)

    def test_next_current_is_idempotent_and_repeats_unresolved_warning(self):
        self.write_state(legacy(current="future_delivery_step"))
        first = self.run_cli()
        self.assertEqual(0, first.returncode, first.stderr)
        first_bytes = self.read_state_bytes()
        first_backups = self.backups()

        second = self.run_cli()

        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(first_bytes, self.read_state_bytes())
        self.assertEqual(first_backups, self.backups())
        self.assertIn("natural-language", second.stdout)
        self.assertNotIn("迁移完成", second.stdout)

    def test_migrated_ambiguity_must_be_resolved_before_delivery(self):
        from mae_flow_core.orchestration import (  # noqa: E402
            AdvanceRequest,
            FlowState,
            Phase,
            advance_flow,
        )

        self.write_state(legacy(current="verify_future_tool"))
        migrated = self.run_cli()
        self.assertEqual(0, migrated.returncode, migrated.stderr)
        state = FlowState.from_dict(self.read_state())
        migration_risk = state.risks[-1]

        blocked = advance_flow(
            state, AdvanceRequest("quality-complete"))
        resolved = advance_flow(blocked.state, AdvanceRequest(
            "risk-resolved",
            decision_key=migration_risk,
            decision_value="用户确认该旧步骤属于质量阶段，可以进入交付。",
        ))
        conformance = advance_flow(resolved.state, AdvanceRequest(
            "final-conformance",
            decision_value="迁移后的最终实现与确认范围一致。",
        ))
        advanced = advance_flow(
            conformance.state, AdvanceRequest("quality-complete"))

        self.assertIs(state, blocked.state)
        self.assertEqual(Phase.QUALITY, blocked.state.phase)
        self.assertTrue(blocked.needs_user)
        self.assertEqual((), resolved.state.risks)
        self.assertFalse(resolved.needs_user)
        self.assertIn(
            (
                "risk.resolution",
                "用户确认该旧步骤属于质量阶段，可以进入交付。 "
                "Resolved risk: %s" % migration_risk,
            ),
            resolved.state.decisions,
        )
        self.assertEqual(Phase.DELIVERY, advanced.state.phase)
        self.assertFalse(advanced.needs_user)

    def test_existing_schema_v3_current_is_read_only(self):
        from mae_flow_core.orchestration import (  # noqa: E402
            CommitPace,
            DeliveryPath,
            FlowState,
        )

        raw = self.write_state(FlowState.new(
            "REQ-42", DeliveryPath.FULL, CommitPace.CONTINUOUS).to_dict())

        result = self.run_cli()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(raw, self.read_state_bytes())
        self.assertEqual([], self.backups())
        self.assertIn("阶段: startup", result.stdout)

    def test_corrupt_json_is_backed_up_and_never_overwritten(self):
        original = b'{"schema_version": 2, "current": "build", broken'
        with open(self.state_path, "wb") as stream:
            stream.write(original)

        result = self.run_cli("migrate-flow")

        self.assertNotEqual(0, result.returncode)
        self.assertEqual(original, self.read_state_bytes())
        self.assert_backup(original)
        self.assertNotIn("迁移完成", result.stdout + result.stderr)

    def test_unsupported_schema_fails_safe_without_rewriting(self):
        original = self.write_state({"schema_version": 99, "current": "build"})

        result = self.run_cli("migrate-flow")

        self.assertNotEqual(0, result.returncode)
        self.assertEqual(original, self.read_state_bytes())
        self.assertEqual([], self.backups())
        self.assertNotIn("迁移完成", result.stdout + result.stderr)

    def test_atomic_write_failure_keeps_original_and_complete_backup(self):
        from mae_flow_core.cli_commands import lean_migration  # noqa: E402

        original = self.write_state(legacy(current="build"))
        stdout = io.StringIO()
        with mock.patch.object(
                lean_migration, "atomic_write_json",
                side_effect=PermissionError("locked")):
            with contextlib.redirect_stdout(stdout):
                with self.assertRaises(PermissionError):
                    lean_migration.migrate_state_file(
                        self.state_path, project_root=self.root)

        self.assertEqual("", stdout.getvalue())
        self.assertEqual(original, self.read_state_bytes())
        self.assert_backup(original)

    def test_summary_omits_legacy_evidence_internals(self):
        original = self.write_state(legacy(
            current="verify_ut",
            tokens={"UT": "secret-token"},
            receipts={"review": "secret-receipt"},
            agent_tasks={"UT": {"report_hash": "secret-hash"}},
            decisions={"scope": "keep semantic decision"},
        ))

        result = self.run_cli()

        self.assertEqual(0, result.returncode, result.stderr)
        for forbidden in (
                "secret-token", "secret-receipt", "secret-hash",
                "tokens", "receipts", "agent_tasks", "report_hash"):
            self.assertNotIn(forbidden, result.stdout)
        self.assertIn("scope: keep semantic decision", result.stdout)
        self.assert_backup(original)


if __name__ == "__main__":
    unittest.main()
