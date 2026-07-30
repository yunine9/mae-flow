#!/usr/bin/env python3
"""Spec2Code 生产流程串联回归，不引入质量评分门禁。"""

import hashlib
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core.application.delivery.checkpoint_quality import (  # noqa: E402
    PLAN_CONTINUE_ACK,
    CheckpointQualityPorts,
    decide_checkpoint_plan,
    prepare_checkpoint_plan,
    record_craft_review,
)
from mae_flow_core.application.delivery.checkpoints import (  # noqa: E402
    CheckpointPlanPorts,
    plan_checkpoint,
)
from mae_flow_core.application.quality.role_task_documents import (  # noqa: E402
    ArtifactRef,
    RoleTaskContext,
    build_role_task_document,
)
from mae_flow_core.delivery.models import thaw  # noqa: E402
from mae_flow_core.quality.spec2code_artifacts import (  # noqa: E402
    blueprint_scenario_ids,
)
from test_spec2code_artifacts import (  # noqa: E402
    BLUEPRINT,
    PLAN,
    ROADMAP,
    TASK_CARD_SHA,
    review,
)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Spec2CodeQualityFlowTests(unittest.TestCase):
    def ports(self, files):
        return CheckpointQualityPorts(
            is_file=lambda path: path in files,
            read_text=lambda path: files[path],
            normalize_path=lambda path: path,
            digest=digest,
            ack_cursor=lambda: ("before-user-review",),
            verify_ack=lambda _receipt, _expected: (True, ""),
            role_task_sha=lambda _role, _checkpoint: TASK_CARD_SHA,
            now=lambda: "2026-07-30 16:00:00",
        )

    def test_artifacts_checkpoint_roles_reviews_and_ut_blueprint_connect(self):
        roadmap = ROADMAP.replace(
            "## CP1：创建核心对象",
            "## CP1：创建核心对象",
        )
        planned = plan_checkpoint(
            current="build_pace",
            workflow="full",
            moonlight=False,
            raw_items=(),
            ports=CheckpointPlanPorts(
                dirty_paths=lambda: (),
                task_structure=lambda: ("task-sha", ("Task CP1-T1",)),
                head=lambda: "base-head",
                ack_cursor=lambda: ("before-pace",),
                now=lambda: "2026-07-30 15:00:00",
                process_artifacts=lambda: {
                    "roadmap": {
                        "path": ".mae-flow-work/roadmap-REQ-1.md",
                        "sha256": digest(roadmap),
                        "text": roadmap,
                    },
                    "plan": {
                        "path": ".mae-flow-work/plan-REQ-1.md",
                        "sha256": digest(PLAN),
                        "text": PLAN,
                    },
                },
            ),
        )
        checkpoint_state = thaw(planned.effects[0].payload)
        checkpoint_state.update({
            "status": "active",
            "mode": "staged",
            "current_index": 0,
        })
        checkpoint_state["checkpoints"][0].update({
            "status": "planned",
            "fixed_base": "base-head",
        })
        files = {
            ".mae-flow-work/plan-REQ-1.md": PLAN,
            ".mae-flow-work/reviews/REQ-1/CP1-plan.md": review(
                mode="PLAN",
                target_sha=digest(PLAN),
            ),
            ".mae-flow-work/reviews/REQ-1/CP1-code.md": review(
                target_sha="d" * 64,
            ),
        }
        prepared = prepare_checkpoint_plan(
            checkpoint_state,
            "CP1",
            ".mae-flow-work/plan-REQ-1.md",
            ".mae-flow-work/reviews/REQ-1/CP1-plan.md",
            "REQ-1",
            self.ports(files),
        )
        coding = decide_checkpoint_plan(
            thaw(prepared.effects[0].payload),
            "continue",
            PLAN_CONTINUE_ACK,
            self.ports(files),
        )
        coding_state = thaw(coding.effects[0].payload)
        self.assertEqual(
            "coding", coding_state["checkpoints"][0]["status"])

        refs = {
            "blueprint": ArtifactRef("blueprint.md", digest(BLUEPRINT)),
            "roadmap": ArtifactRef("roadmap.md", digest(roadmap)),
            "plan": ArtifactRef("plan.md", digest(PLAN)),
        }
        implement_card = build_role_task_document(
            role="cp-implement",
            project_root="/repo",
            ticket="REQ-1",
            checkpoint="CP1",
            context=RoleTaskContext(
                artifacts=refs,
                files=("src/service.py",),
                context_paths=("survey.md", "src/service.py"),
            ),
        ).body()
        self.assertIn("Comment Standard v1", implement_card)
        self.assertIn("src/service.py", implement_card)

        coding_state["checkpoints"][0].update({
            "status": "craft_pending",
            "compile_source_sha256": "d" * 64,
        })
        crafted = record_craft_review(
            coding_state,
            "CP1",
            ".mae-flow-work/reviews/REQ-1/CP1-code.md",
            "REQ-1",
            "d" * 64,
            self.ports(files),
        )
        self.assertEqual(
            "review_pending",
            thaw(crafted.effects[0].payload)["checkpoints"][0]["status"],
        )
        self.assertEqual(("SC-1",), blueprint_scenario_ids(BLUEPRINT))

    def test_process_artifacts_are_git_ignored(self):
        with open(os.path.join(ROOT, ".gitignore"), encoding="utf-8") as stream:
            ignored = stream.read().splitlines()
        self.assertIn(".mae-flow-work/", ignored)


if __name__ == "__main__":
    unittest.main()
