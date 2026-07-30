#!/usr/bin/env python3
"""Spec2Code 生产流程串联回归，不引入质量评分门禁。"""

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
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
from mae_flow_core import cli_runtime as mf  # noqa: E402
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

with open(
        os.path.join(ROOT, "flow", "flow.json"),
        encoding="utf-8",
) as flow_stream:
    FLOW = json.load(flow_stream)
mf.FLOW = FLOW


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


class Spec2CodeCliSequenceTests(unittest.TestCase):
    def setUp(self):
        self.repository = tempfile.mkdtemp(
            prefix="mae-flow-spec2code-cli-")
        self.previous = os.getcwd()
        os.chdir(self.repository)
        os.makedirs(".mae-flow-work")
        os.makedirs("docs")
        os.makedirs("src")
        self.write("docs/requirement.md", "# Requirement\nCreate object.\n")
        self.write("docs/design.md", "# Design\nService owns orchestration.\n")
        self.write("src/service.py", "VALUE = 1\n")
        self.write(
            ".mae-flow-work/survey-REQ-1.md",
            "关键邻近代码：`src/service.py`\n",
        )
        subprocess.run(
            ["git", "init", "-q"], check=True)
        subprocess.run(
            ["git", "config", "user.email", "spec2code@test.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Spec2Code Test"],
            check=True,
        )
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(
            ["git", "commit", "-qm", "base"], check=True)
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        self.state = {
            "current": "test_blueprint",
            "config": {
                "单号": "REQ-1",
                "单号类型": "feat",
                "基线分支": base,
                "需求文档": "docs/requirement.md",
                "编译方式": "python -m py_compile",
                "UT生成方式": "AutoUT",
                "UT运行命令": "python -m unittest",
            },
            "spec": {"design_doc": "docs/design.md"},
            "choices": {"workflow": "full"},
            "history": [],
            "initial_dirty": [],
            "initial_dirty_fingerprints": {},
        }

    def tearDown(self):
        os.chdir(self.previous)
        shutil.rmtree(self.repository, ignore_errors=True)

    def write(self, path, text):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(text)

    def role(self, role):
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_role_task(
                None,
                self.state,
                types.SimpleNamespace(role=role, checkpoint="CP1"),
            )
        record = self.state["role_tasks"][role]
        with open(record["path"], encoding="utf-8") as stream:
            return stream.read(), record

    def register(self, kind, path):
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_quality_artifact(
                None,
                self.state,
                types.SimpleNamespace(
                    quality_action="register",
                    kind=kind,
                    path=path,
                ),
            )

    def test_real_cli_orders_roadmap_task_analysis_plan_and_reviewer(self):
        test_card, _ = self.role("test-design")
        self.assertIn("docs/requirement.md", test_card)
        self.assertIn("survey-REQ-1.md", test_card)
        self.assertIn("src/service.py | SHA256", test_card)

        blueprint_path = ".mae-flow-work/test-blueprint-REQ-1.md"
        self.write(blueprint_path, BLUEPRINT)
        self.register("blueprint", blueprint_path)
        with contextlib.redirect_stdout(io.StringIO()):
            mf._confirm_spec2code_artifacts(
                self.state, ("blueprint",), "user")

        self.state["current"] = "build_plan"
        roadmap_path = ".mae-flow-work/roadmap-REQ-1.md"
        self.write(roadmap_path, ROADMAP)
        self.register("roadmap", roadmap_path)

        analyst_card, _ = self.role("task-analysis")
        self.assertIn("唯一允许写入的过程件", analyst_card)
        self.assertNotIn("- plan: （未登记）", analyst_card)
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stderr(io.StringIO()):
                self.role("craft-plan")
        self.assertEqual(2, caught.exception.code)

        plan_path = ".mae-flow-work/plan-REQ-1.md"
        self.write(plan_path, PLAN)
        self.register("plan", plan_path)
        review_card, review_task = self.role("craft-plan")
        plan_sha = self.state["spec2code"]["plan"]["sha256"]
        self.assertIn("REVIEW_TARGET_SHA256: " + plan_sha, review_card)
        self.assertIn(
            "TASK_CARD_SHA256: " + review_task["sha256"],
            review_card,
        )
        self.assertEqual(
            plan_sha,
            review_task["review_target_sha256"],
        )
        self.write(plan_path, PLAN + "\n")
        self.register("plan", plan_path)
        self.assertEqual(
            "",
            mf._role_task_sha(
                self.state, "craft-plan", "CP1"),
        )

        self.write("src/service.py", "VALUE = 2\n")
        subprocess.run(
            ["git", "add", "src/service.py"], check=True)
        subprocess.run(
            ["git", "commit", "-qm", "[REQ-1][feat]implement"],
            check=True,
        )
        self.state["current"] = "verify_ut"
        with contextlib.redirect_stdout(io.StringIO()):
            mf.cmd_agent_task(
                FLOW,
                self.state,
                types.SimpleNamespace(
                    kind="ut",
                    scope=None,
                    checkpoint=None,
                ),
            )
        ut_task = self.state["agent_tasks"]["UT"]
        with open(ut_task["path"], encoding="utf-8") as stream:
            ut_card = stream.read()
        self.assertIn("已确认 UT 行为蓝图", ut_card)
        self.assertIn("SC-1", ut_card)


if __name__ == "__main__":
    unittest.main()
