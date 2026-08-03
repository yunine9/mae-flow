#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Production CLI contracts for the recoverable Chain workflow."""

import json
import os
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CLI = os.path.join(ROOT, "scripts", "mae-flow.py")
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.adapters.lean_hook import LeanHookAdapter  # noqa: E402


class LeanChainCliTests(unittest.TestCase):
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

    def assert_success(self, result):
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    @property
    def pointer_path(self):
        return os.path.join(
            self.root, ".mae-flow-work", "chain-current.json")

    def pointer(self):
        with open(self.pointer_path, encoding="utf-8") as stream:
            return json.load(stream)

    def state_path(self):
        return os.path.join(self.root, *self.pointer()["state"].split("/"))

    def state(self):
        with open(self.state_path(), encoding="utf-8") as stream:
            return json.load(stream)

    def start(self, ticket="REQ-CHAIN"):
        return self.run_cli(
            "chain", "start", "--ticket", ticket,
            "--request", "梳理两个仓库的接口变更",
            "--requirement", "requirements/chain.md",
        )

    def submit_user_prompt(self, text):
        result = LeanHookAdapter(self.root).handle(
            "UserPromptSubmit", {"prompt": text, "session_id": "chain-cli"})
        self.assertEqual(0, result.exit_code, result.stderr)
        with open(os.path.join(
                self.root, ".mae-flow-work", "lean-hook-user-events.json"),
                encoding="utf-8") as stream:
            captured = json.load(stream)[-1]
        self.assertEqual(text, captured["payload"]["prompt"])
        with open(self.state_path(), "rb") as stream:
            expected = __import__("hashlib").sha256(stream.read()).hexdigest()
        self.assertEqual(expected, captured["state_sha256"])

    def record(self, kind, key, value):
        return self.run_cli(
            "chain", "record", kind, "--key", key,
            "--value", json.dumps(value, ensure_ascii=False),
        )

    def test_start_current_and_second_active_chain(self):
        started = self.start("REQ:CHAIN")
        current = self.run_cli("chain", "current")
        duplicate = self.start("REQ-OTHER")

        self.assert_success(started)
        self.assert_success(current)
        self.assertIn("REQ:CHAIN", current.stdout)
        self.assertEqual(1, self.pointer()["schema_version"])
        self.assertFalse(os.path.isabs(self.pointer()["state"]))
        self.assertEqual(2, duplicate.returncode)
        self.assertIn("Chain", duplicate.stderr)

    def test_active_delivery_rejects_chain_start(self):
        flow = self.run_cli(
            "start", "--ticket", "REQ-FLOW", "--path", "focused",
            "--pace", "continuous",
        )
        chain = self.start()

        self.assert_success(flow)
        self.assertEqual(2, chain.returncode)
        self.assertIn("活动", chain.stderr)

    def test_corrupt_pointer_and_state_fail_without_guessing(self):
        os.makedirs(os.path.dirname(self.pointer_path), exist_ok=True)
        with open(self.pointer_path, "w", encoding="utf-8") as stream:
            json.dump({"schema_version": 1, "state": "../escape.json"}, stream)

        traversal = self.run_cli("chain", "current")
        self.assertEqual(2, traversal.returncode)
        self.assertIn("指针", traversal.stderr)

        os.remove(self.pointer_path)
        self.assert_success(self.start())
        path = self.state_path()
        with open(path, "w", encoding="utf-8") as stream:
            stream.write("{broken")

        corrupt = self.run_cli("chain", "current")
        self.assertEqual(2, corrupt.returncode)
        self.assertIn("状态", corrupt.stderr)

    def test_question_answer_requires_the_current_question(self):
        self.assert_success(self.start())
        question = self.run_cli(
            "chain", "question", "--key", "CQ-001", "--value",
            json.dumps({
                "evidence": "两个仓库对同一错误码定义不同",
                "impact": "调用方无法稳定重试",
                "recommendation": "统一为显式错误枚举",
                "parent": "",
            }, ensure_ascii=False),
        )
        wrong = self.run_cli(
            "chain", "answer", "--key", "CQ-999", "不是这个问题")
        self.submit_user_prompt("采用统一错误枚举")
        answered = self.run_cli(
            "chain", "answer", "--key", "CQ-001", "采用统一错误枚举")

        self.assert_success(question)
        self.assertEqual(2, wrong.returncode)
        self.assert_success(answered)
        answers = [
            item for item in self.state()["records"]
            if item["kind"] == "answer"
        ]
        self.assertEqual(["CQ-001"], [item["key"] for item in answers])

    def test_complete_chain_verifies_renders_confirms_and_exits(self):
        self.assert_success(self.start())
        os.makedirs(os.path.join(self.root, "repo-b"))
        for repository, directory, symbol in (
                ("anchor", self.root, "AnchorSymbol"),
                ("service", os.path.join(self.root, "repo-b"),
                 "ServiceSymbol")):
            with open(os.path.join(directory, "evidence.txt"),
                      "w", encoding="utf-8") as stream:
                stream.write(symbol + "\n")
            self.assert_success(self.record("repository", repository, {
                "path": "." if repository == "anchor" else "repo-b",
                "language_build": "Python / unittest",
                "responsibility": repository + " responsibility",
            }))
            for index, angle in enumerate(
                    ("keyword", "interface", "config-routing"), 1):
                self.assert_success(self.record(
                    "touchpoint", "%s-%s" % (repository, index), {
                        "repository": repository,
                        "file": "evidence.txt",
                        "symbol": symbol,
                        "why": angle + " evidence",
                        "confidence": "high",
                        "angle": angle,
                    }))

        self.assert_success(self.record("contract", "CONTRACT-1", {
            "repositories": ["anchor", "service"],
            "shape": "request -> response",
            "fields": "id:string,result:string,error:enum",
            "error_semantics": "typed error; caller retries timeout only",
        }))
        self.assert_success(self.record("dependency", "DEP-1", {
            "from": "anchor", "to": "service",
            "order": "service contract first, anchor integration second",
            "parallel": "implement adapters in parallel after contract freeze",
            "integration": "merge service, then run anchor integration tests",
        }))
        for repository in ("anchor", "service"):
            self.assert_success(self.record("reverse-check", repository, {
                "independent": True,
                "reason": "launch card contains exact scope and contract",
            }))

        verified = self.run_cli("chain", "verify")
        self.assert_success(verified)
        document = self.state()["document_path"]
        absolute_document = os.path.join(self.root, *document.split("/"))
        with open(absolute_document, "w", encoding="utf-8") as stream:
            stream.write("# Chain\n\nComplete launch cards.\n")
        rendered = self.run_cli("chain", "rendered")
        self.submit_user_prompt("确认触点完整且错误语义准确")
        confirmed = self.run_cli(
            "chain", "confirm", "确认触点完整且错误语义准确")
        exited = self.run_cli("chain", "exit", "--reason", "handoff complete")

        self.assert_success(rendered)
        self.assert_success(confirmed)
        self.assert_success(exited)
        self.assertFalse(os.path.exists(self.pointer_path))
        archive = os.path.join(
            self.root, ".mae-flow-work", "chain-exited")
        self.assertEqual(1, len(os.listdir(archive)))

    def test_answer_requires_one_current_unconsumed_user_input(self):
        self.assert_success(self.start())
        question = json.dumps({
            "evidence": "e", "impact": "i", "recommendation": "r",
            "parent": "",
        })
        self.assert_success(self.run_cli(
            "chain", "question", "--key", "CQ-001", "--value", question))

        fabricated = self.run_cli(
            "chain", "answer", "--key", "CQ-001", "伪造回答")
        self.submit_user_prompt("真实回答")
        accepted = self.run_cli(
            "chain", "answer", "--key", "CQ-001", "真实回答")
        self.assert_success(self.run_cli(
            "chain", "question", "--key", "CQ-002", "--value",
            json.dumps({
                "evidence": "e2", "impact": "i2", "recommendation": "r2",
                "parent": "CQ-001",
            })))
        reused = self.run_cli(
            "chain", "answer", "--key", "CQ-002", "复用旧回答")

        self.assertEqual(2, fabricated.returncode)
        self.assert_success(accepted)
        self.assertEqual(2, reused.returncode)
        consumed = [
            item for item in self.state()["decisions"]
            if item["key"] == "user.event.consumed"
        ]
        self.assertEqual(1, len(consumed))

    def test_answer_rejects_user_input_bound_to_an_older_chain_state(self):
        self.assert_success(self.start())
        self.assert_success(self.run_cli(
            "chain", "question", "--key", "CQ-001", "--value",
            json.dumps({
                "evidence": "e", "impact": "i", "recommendation": "r",
                "parent": "",
            })))
        self.submit_user_prompt("这个输入将变旧")
        self.assert_success(self.record("repository", "anchor", {
            "path": ".", "language_build": "Python",
            "responsibility": "anchor",
        }))

        stale = self.run_cli(
            "chain", "answer", "--key", "CQ-001", "这个输入将变旧")
        self.assertEqual(2, stale.returncode)
        self.assertIn("用户输入", stale.stderr)


if __name__ == "__main__":
    unittest.main()
