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
            _authorization_message=mock.Mock(return_value=(
                True, "确认按该清单提交", {"message_id": "msg-1"}, "")),
        )

        first = confirm_delivery_manifest(state, "msg-1", api)
        second = confirm_delivery_manifest(first, "msg-1", api)

        self.assertTrue(first["delivery_manifest"]["confirmed"])
        self.assertIs(first, second)
        api._authorization_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
