#!/usr/bin/env python3
"""Reachable stable flow keeps all requirement process artifacts local."""

import json
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.workflow.transitions import workflow_chain  # noqa: E402


class ProcessArtifactBoundaryTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "flow", "flow.json"), encoding="utf-8") as stream:
            self.flow = json.load(stream)

    def test_reachable_steps_never_require_repo_process_documents(self):
        forbidden = (
            "docs/clarifications-", "docs/review/REVIEW-",
            "docs/codecheck-exempt-", "docs/delivery-notes.md",
            "docs/story/", "openspec/changes/",
        )
        reached = set()
        for workflow in ("full", "hotfix", "tweak", "review"):
            reached.update(workflow_chain(self.flow, workflow))
        for step_id in reached:
            serialized = json.dumps(self.flow["steps"][step_id], ensure_ascii=False)
            with self.subTest(step=step_id):
                for marker in forbidden:
                    self.assertNotIn(marker, serialized)

    def test_reachable_guidance_never_commits_process_documents(self):
        reached = set()
        for workflow in ("full", "hotfix", "tweak", "review"):
            reached.update(workflow_chain(self.flow, workflow))
        forbidden = (
            "git add docs/clarifications-", "git add docs/review/",
            "git add docs/codecheck-exempt-", "git add docs/delivery-notes.md",
            "spec new", "spec archive",
        )
        for step_id in reached:
            path = os.path.join(ROOT, "flow", "steps", step_id + ".md")
            with open(path, encoding="utf-8") as stream:
                content = stream.read()
            with self.subTest(step=step_id):
                for marker in forbidden:
                    self.assertNotIn(marker, content)


if __name__ == "__main__":
    unittest.main()
