#!/usr/bin/env python3
"""User-readable delivery confirmation and exact staging contracts."""

import os
import sys
import types
import unittest
from unittest import mock


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.cli_parser import parse_args  # noqa: E402
from mae_flow_core.cli_commands.delivery_manifest import (  # noqa: E402
    build_delivery_manifest,
    confirm_delivery_manifest,
)


class DeliveryConfirmationTests(unittest.TestCase):
    def state(self):
        return {
            "current": "delivery_review",
            "config": {"单号": "REQ-42"},
            "initial_dirty": ["docs/user-notes.md"],
        }

    def test_parser_accepts_every_delivery_command_printed_to_agents(self):
        set_args = parse_args([
            "manifest", "set", "--file", "src/a.cpp",
            "--file", "tests/a_test.cpp", "--message", "feat: add A",
            "--target", "main", "--adopt-dirty",
            "docs/user-notes.md=用户确认该文件属于本需求",
        ])
        show_args = parse_args(["manifest", "show"])
        confirm_args = parse_args([
            "manifest", "confirm", "--message-id", "msg-1"])

        self.assertEqual("set", set_args.manifest_action)
        self.assertEqual("show", show_args.manifest_action)
        self.assertEqual("confirm", confirm_args.manifest_action)

    def test_startup_dirty_requires_explicit_natural_language_adoption(self):
        with self.assertRaisesRegex(ValueError, "启动时已有修改"):
            build_delivery_manifest(
                self.state(), ["docs/user-notes.md"], "docs: update", "main",
                (), candidate_paths=("docs/user-notes.md",))

        manifest = build_delivery_manifest(
            self.state(), ["docs/user-notes.md"], "docs: update", "main",
            ("docs/user-notes.md=用户确认属于本需求",),
            candidate_paths=("docs/user-notes.md",))

        self.assertEqual(
            {"docs/user-notes.md": "用户确认属于本需求"},
            manifest["adopted_dirty"])

    def test_manifest_rejects_files_outside_old_candidate_ownership(self):
        with self.assertRaisesRegex(ValueError, "不在当前候选增量"):
            build_delivery_manifest(
                self.state(), ["src/unrelated.cpp"], "feat: unrelated", "main",
                (), candidate_paths=("src/a.cpp",))

    def test_manifest_rejects_every_process_document_family(self):
        forbidden = (
            ".mae-flow-work/REQ-42/spec.md",
            "docs/clarifications-REQ-42.md",
            "docs/review/REVIEW-REQ-42.md",
            "docs/codecheck-exempt-REQ-42.md",
            "docs/delivery-notes.md",
            "docs/story/STORY-REQ-42.md",
            "docs/superpowers/plans/plan.md",
            "openspec/changes/change/change.md",
            "openspec/specs/domain/spec.md",
        )
        for path in forbidden:
            with self.subTest(path=path), self.assertRaisesRegex(
                    ValueError, "过程文件"):
                build_delivery_manifest(
                    self.state(), [path], "docs: process", "main", (),
                    candidate_paths=(path,))

    def test_docs_specs_requires_exact_current_archive_output(self):
        path = "docs/specs/radio.md"
        with self.assertRaisesRegex(ValueError, "领域归档"):
            build_delivery_manifest(
                self.state(), [path], "docs: truth", "main", (),
                candidate_paths=(path,))
        state = self.state()
        state["domain_archive"] = {
            "status": "applied", "result": "changes",
            "applied_paths": [path],
        }
        manifest = build_delivery_manifest(
            state, [path], "docs: truth", "main", (),
            candidate_paths=(path,))
        self.assertEqual([path], manifest["files"])

    def test_change_clears_confirmation_once_and_identical_set_keeps_it(self):
        state = self.state()
        state["delivery_manifest"] = {
            "files": ["src/a.cpp"],
            "commit_message": "feat: A",
            "target_branch": "main",
            "adopted_dirty": {},
            "confirmed": True,
        }

        same = build_delivery_manifest(
            state, ["src/a.cpp"], "feat: A", "main", (),
            candidate_paths=("src/a.cpp",))
        changed = build_delivery_manifest(
            state, ["src/a.cpp"], "feat: A revised", "main", (),
            candidate_paths=("src/a.cpp",))

        self.assertTrue(same["confirmed"])
        self.assertFalse(changed["confirmed"])
        state["delivery_manifest"] = changed
        self.assertFalse(build_delivery_manifest(
            state, ["src/a.cpp"], "feat: A revised", "main", (),
            candidate_paths=("src/a.cpp",))["confirmed"])

    def test_confirmation_is_a_single_semantic_user_decision(self):
        state = self.state()
        state["delivery_manifest"] = build_delivery_manifest(
            state, ["src/a.cpp"], "feat: A", "main", (),
            candidate_paths=("src/a.cpp",))
        api = types.SimpleNamespace(
            _is_positive_confirmation=lambda answer: answer.startswith("确认"),
            _authorization_message=mock.Mock(return_value=(
                True, "确认按该清单提交", {"message_id": "msg-1"}, "")),
        )

        first = confirm_delivery_manifest(state, "msg-1", api)
        second = confirm_delivery_manifest(first, "msg-1", api)

        self.assertTrue(first["delivery_manifest"]["confirmed"])
        self.assertIs(first, second)
        api._authorization_message.assert_called_once()

    def test_negative_user_answer_does_not_confirm_manifest(self):
        state = self.state()
        state["delivery_manifest"] = build_delivery_manifest(
            state, ["src/a.cpp"], "feat: A", "main", (),
            candidate_paths=("src/a.cpp",))
        api = types.SimpleNamespace(
            _is_positive_confirmation=lambda _answer: False,
            _authorization_message=mock.Mock(return_value=(
                True, "不同意，这个清单还要修改",
                {"message_id": "msg-no"}, "")),
        )

        with self.assertRaisesRegex(ValueError, "没有明确批准"):
            confirm_delivery_manifest(state, "msg-no", api)
        self.assertFalse(state["delivery_manifest"]["confirmed"])


if __name__ == "__main__":
    unittest.main()
