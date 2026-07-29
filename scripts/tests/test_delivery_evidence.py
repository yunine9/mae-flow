#!/usr/bin/env python3
"""Unit tests for Delivery Evidence policies."""

import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.delivery.evidence import (  # noqa: E402
    DeliveryEvidencePorts,
    DeliveryEvidenceRules,
)


def make_ports(**overrides):
    values = {
        "moonlight": lambda _state: False,
        "development_review": lambda state: state.get("development_review"),
        "source_changed_since": lambda _head, _state: ([], ""),
        "review_before_commit": lambda data: bool(
            data.get("review_before_commit")),
        "final_review_delta": lambda _state: ([], ""),
        "archive_delivery_paths": lambda state: (
            (state.get("spec") or {}).get("archive_paths") or []),
        "shell_output": lambda command: {
            "git branch --show-current": "feature/x",
            "git rev-parse --verify HEAD": "a" * 40,
            "git rev-parse --verify @{u}": "a" * 40,
            "git log -1 --pretty=%s": "[REQ-7][fix] done",
        }.get(command, ""),
        "argv_output": lambda _arguments: "",
        "committed_initial_carryover": lambda _state: ([], ""),
        "committed_delivery_paths": lambda _state: ([], ""),
        "trusted_harness_commit_path": lambda _path, _state: True,
        "dirty_paths": lambda: [],
        "path_fingerprint": lambda _path: "same",
        "repo_path_identity": lambda path: path,
        "agent_written_paths": lambda: set(),
        "read_text_replace": lambda _path: "",
        "agent_ran": lambda _spec, _state: (True, ""),
    }
    values.update(overrides)
    return DeliveryEvidencePorts(**values)


class DeliveryEvidenceRuleTests(unittest.TestCase):
    def test_checkpoint_plan_and_completion_boundaries(self):
        rules = DeliveryEvidenceRules(make_ports())
        state = {"current": "tw_pace"}
        self.assertIn(
            "尚未生成开发检查点方案",
            rules.checkpoint_plan({}, state).reason,
        )
        state["development_review"] = {
            "status": "plan_pending",
            "plan_step": "tw_pace",
            "plan_head": "a" * 40,
            "checkpoints": [{"id": "CP1"}],
        }
        self.assertTrue(rules.checkpoint_plan({}, state).passed)
        state["development_review"].update({
            "status": "active",
            "mode": "continuous",
            "checkpoints": [{"id": "CP1", "status": "coding"}],
        })
        result = rules.checkpoint_plan_complete({}, state)
        self.assertFalse(result.passed)
        self.assertIn("检查点尚未闭环: CP1", result.reason)

    def test_final_review_and_archive_outputs_must_be_clean(self):
        rules = DeliveryEvidenceRules(make_ports(
            final_review_delta=lambda _state: (["src/main.py"], ""),
            argv_output=lambda arguments: (
                " M archive" if arguments[-1] == "archive" else ""),
        ))
        state = {
            "development_review": {"status": "active"},
            "spec": {"archive_paths": ["archive"]},
        }
        self.assertIn(
            "质量链后仍有未检视代码增量",
            rules.final_review_clear({}, state).reason,
        )
        self.assertEqual(
            (
                False,
                "本次定稿产物尚未提交: archive(M)。"
                "只精确 git add 上述路径并提交；不要 git add openspec/，"
                "它可能卷入上一单遗留文件",
            ),
            tuple(rules.archive_paths_clean({}, state)),
        )

    def test_commit_must_be_tagged_and_created_after_entry(self):
        bad = DeliveryEvidenceRules(make_ports(
            shell_output=lambda command: (
                "plain commit" if command == "git log -1 --pretty=%s"
                else "a" * 40),
            argv_output=lambda arguments: (
                "commit" if arguments[1] == "cat-file" else
                "b" * 40 if arguments[1] == "log" else ""),
        ))
        state = {
            "current": "tw_change",
            "config": {"单号": "REQ-7"},
            "step_heads": {"tw_change": "a" * 40},
        }
        self.assertIn(
            "不符合 [REQ-7][feat|fix]描述 格式",
            bad.commit_tagged_after_entry({}, state).reason,
        )

    def test_push_requires_upstream_and_rejects_dirty_delivery_candidate(self):
        no_upstream = DeliveryEvidenceRules(make_ports(
            shell_output=lambda command: {
                "git branch --show-current": "feature/x",
                "git rev-parse --verify HEAD": "a" * 40,
                "git rev-parse --verify @{u}": "",
            }.get(command, ""),
        ))
        state = {
            "config": {"分支名": "feature/x", "单号": "REQ-7"},
            "initial_dirty": [],
        }
        self.assertIn(
            "分支无上游跟踪",
            no_upstream.pushed({}, state).reason,
        )
        dirty = DeliveryEvidenceRules(make_ports(
            dirty_paths=lambda: ["src/main.py"],
            agent_written_paths=lambda: {"src/main.py"},
        ))
        self.assertIn(
            "仍有 Agent 实际写入或流程明确维护的交付候选未处理",
            dirty.pushed({}, state).reason,
        )
        self.assertTrue(
            DeliveryEvidenceRules(make_ports()).pushed({}, state).passed)


if __name__ == "__main__":
    unittest.main()
