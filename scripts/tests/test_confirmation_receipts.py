#!/usr/bin/env python3
"""Confirmation receipt integration regressions."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MAE = os.path.join(ROOT, "scripts", "mae-flow.py")
HOOK = os.path.join(ROOT, "hooks", "dispatch.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core import cli_runtime as mf  # noqa: E402
from mae_flow_core.cli_parser import parse_args  # noqa: E402
from mae_flow_core.state_store import (  # noqa: E402
    read_json,
    save_versioned_json,
)


def run(cwd, argv, payload=None):
    env = dict(os.environ)
    env["PYTHONPYCACHEPREFIX"] = os.path.join(cwd, "pycache")
    return subprocess.run(
        argv,
        cwd=cwd,
        input=payload,
        text=True,
        capture_output=True,
        env=env,
        timeout=20,
    )


class ConfirmationReceiptTests(unittest.TestCase):
    def make_repo(self):
        temp = tempfile.TemporaryDirectory()
        root = temp.name
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "receipts@test.invalid"],
            cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.name", "Receipt Tests"],
            cwd=root, check=True)
        with open(os.path.join(root, "biz.cpp"), "w", encoding="utf-8") as stream:
            stream.write("int answer() { return 42; }\n")
        subprocess.run(["git", "add", "biz.cpp"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
        return temp, root

    def action(self, root, scope_sha="scope-v1"):
        work = os.path.join(
            root, ".mae-flow-work", "standalone", "receipt-ut")
        action = {
            "id": "receipt-ut",
            "kind": "ut",
            "status": "awaiting_scope_confirmation",
            "created_at": "2026-07-31 12:00:00",
            "expires_epoch": time.time() + 3600,
            "work_dir": work,
            "request": "补充边界测试",
            "config": {
                "UT生成方式": "AutoUT",
                "UT运行命令": "test",
            },
            "check_only": False,
            "base_head": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True,
                text=True, capture_output=True).stdout.strip(),
            "commit_policy": "forbid",
            "tokens": {},
            "rejections": {},
            "quality": {},
            "sources": [],
            "files": ["biz.cpp"],
            "scope_source": "explicit",
            "scope_proposed_at": "2026-07-31 12:00:00",
            "scope_proposed_epoch": time.time() - 1,
            "scope_sha256": scope_sha,
            "user_messages": [],
        }
        save_versioned_json(
            os.path.join(root, ".mae-flow-work", "standalone-action.json"),
            action,
            "action",
            project_root=root,
        )

    def capture_answer(self, root, answer):
        payload = json.dumps({
            "cwd": root,
            "tool_name": "AskUserQuestion",
            "tool_input": {
                "questions": [{
                    "question": "是否确认以上范围？",
                    "options": [
                        {"label": "确认以上范围"},
                        {"label": "需要调整范围"},
                    ],
                }],
            },
            "tool_response": {
                "answers": {"UT覆盖范围确认": answer},
            },
        }, ensure_ascii=False) + "\n"
        return run(root, [sys.executable, HOOK, "posttooluse"], payload)

    def test_natural_scope_confirmation_needs_no_copied_ack(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        self.action(root)
        captured = self.capture_answer(
            root, "范围没问题，优先覆盖大量行缺失的文件")
        self.assertEqual(0, captured.returncode, captured.stderr)

        confirmed = run(
            root,
            [sys.executable, MAE, "action", "confirm-scope"],
        )

        self.assertEqual(
            0, confirmed.returncode, confirmed.stdout + confirmed.stderr)
        state = read_json(os.path.join(
            root, ".mae-flow-work", "standalone-action.json"))
        self.assertEqual("active", state["status"])
        receipt = state["scope_confirmation_receipt"]
        self.assertEqual("scope-v1", receipt["scope_sha256"])
        self.assertTrue(receipt["message_id"])
        self.assertNotIn("scope_confirmed_ack", state)

    def test_negative_or_question_scope_answers_do_not_confirm(self):
        for answer in (
                "范围需要调整",
                "确认以上范围是什么意思？",
                "我还没确认这个范围"):
            with self.subTest(answer=answer):
                temp, root = self.make_repo()
                try:
                    self.action(root)
                    self.capture_answer(root, answer)
                    confirmed = run(
                        root,
                        [sys.executable, MAE, "action", "confirm-scope"],
                    )
                    self.assertEqual(2, confirmed.returncode)
                    state = read_json(os.path.join(
                        root, ".mae-flow-work",
                        "standalone-action.json"))
                    self.assertEqual(
                        "awaiting_scope_confirmation", state["status"])
                finally:
                    temp.cleanup()

    def test_scope_answer_cannot_confirm_a_changed_scope(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        self.action(root)
        self.capture_answer(root, "确认以上范围")
        path = os.path.join(
            root, ".mae-flow-work", "standalone-action.json")
        state = read_json(path)
        state["scope_sha256"] = "scope-v2"
        save_versioned_json(
            path, state, "action", project_root=root,
            expected_revision=state["revision"])

        confirmed = run(
            root,
            [sys.executable, MAE, "action", "confirm-scope"],
        )

        self.assertEqual(2, confirmed.returncode)
        self.assertIn("范围", confirmed.stdout + confirmed.stderr)

    def test_authorization_message_uses_trusted_answer_not_option_metadata(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        old_cwd = os.getcwd()
        os.chdir(root)
        self.addCleanup(os.chdir, old_cwd)
        state = {
            "current": "verify_ut",
            "started": "2026-07-31 11:00:00",
            "history": [],
        }
        with open(
                os.path.join(root, ".mae-flow.json.usermsg"),
                "w", encoding="utf-8") as stream:
            json.dump([{
                "id": "risk-answer",
                "at": "2026-07-31 12:00:00",
                "step": "verify_ut",
                "text": json.dumps({
                    "question": "是否授权删除 src/Secret.cpp？",
                    "options": ["授权删除 src/Secret.cpp", "拒绝"],
                    "answers": {"裁决": "拒绝"},
                }, ensure_ascii=False),
            }], stream, ensure_ascii=False)

        resolver = getattr(mf, "_authorization_message", None)
        self.assertIsNotNone(resolver)
        ok, answer, receipt, why = resolver(state, "risk-answer")

        self.assertTrue(ok, why)
        self.assertEqual("拒绝", answer)
        self.assertEqual("risk-answer", receipt["message_id"])
        self.assertEqual(
            hashlib.sha256("拒绝".encode("utf-8")).hexdigest(),
            receipt["answer_sha256"])
        self.assertNotIn("Secret.cpp", answer)

    def test_authorization_message_id_cannot_cross_steps(self):
        temp, root = self.make_repo()
        self.addCleanup(temp.cleanup)
        old_cwd = os.getcwd()
        os.chdir(root)
        self.addCleanup(os.chdir, old_cwd)
        with open(
                os.path.join(root, ".mae-flow.json.usermsg"),
                "w", encoding="utf-8") as stream:
            json.dump([{
                "id": "old-answer",
                "at": "2026-07-31 12:00:00",
                "step": "build",
                "text": "确认承担风险",
            }], stream, ensure_ascii=False)
        resolver = getattr(mf, "_authorization_message", None)
        self.assertIsNotNone(resolver)

        ok, _answer, _receipt, why = resolver({
            "current": "verify_ut",
            "started": "2026-07-31 11:00:00",
            "history": [],
        }, "old-answer")

        self.assertFalse(ok)
        self.assertIn("build", why)
        self.assertIn("verify_ut", why)

    def test_authorization_commands_transport_message_ids_not_user_text(self):
        commands = (
            ["goto", "verify_ut", "--force", "--message-id", "m1"],
            ["unlock", "source", "--reason", "确认缺陷", "--message-id", "m1"],
            ["accept-risk", "ut", "--reason", "环境受限",
             "--message-id", "m1"],
            ["allow", "block-1", "--message-id", "m1"],
            ["codecheck-scope", "--include", "W1,W3",
             "--message-id", "m1"],
            ["codecheck-record", "--count", "0", "--diagnostic", "diag.txt",
             "--reason", "人工核对", "--message-id", "m1"],
            ["approve-exemption", "--rule", "R1", "--file", "biz.cpp",
             "--reason", "仓库约定", "--message-id", "m1"],
        )
        for argv in commands:
            with self.subTest(command=argv[0]):
                parsed = parse_args(argv)
                self.assertEqual("m1", parsed.message_id)
                self.assertFalse(hasattr(parsed, "ack"))


if __name__ == "__main__":
    unittest.main()
