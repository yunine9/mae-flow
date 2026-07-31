#!/usr/bin/env python3
"""Unit tests for generic workflow Evidence rules."""

import hashlib
import os
import sys
import unittest


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.workflow.evidence_rules import (  # noqa: E402
    WorkflowEvidencePorts,
    WorkflowEvidenceRules,
    substitute,
)


class SpecError(Exception):
    pass


def make_ports(**overrides):
    values = {
        "cwd": lambda: "/repo",
        "glob_paths": lambda _pattern: [],
        "is_file": lambda _path: False,
        "read_text": lambda _path: "",
        "read_text_replace": lambda _path: "",
        "shell_output": lambda _command: "",
        "argv_output": lambda _arguments: "",
        "tasks_source": lambda _root, _change: ("change.md", ""),
        "spec_has_delta": lambda _root, _change: False,
        "spec_validate": lambda _root, _change: (True, []),
        "spec_required_sections": lambda _root, _change, _workflow: [],
        "spec_error": SpecError,
        "spec_data": lambda state: state.setdefault("spec", {}),
        "risk_acceptance": lambda _kind, _state: (False, ""),
        "business_changed_files": lambda _state: ([], ""),
        "spec2code_plan_review": lambda _spec, _state: (
            False, "missing review"),
    }
    values.update(overrides)
    return WorkflowEvidencePorts(**values)


class WorkflowEvidenceRuleTests(unittest.TestCase):
    def test_spec2code_artifact_requires_registered_fresh_file(self):
        text = "# artifact\n"
        state = {
            "spec2code": {
                "blueprint": {
                    "path": ".mae-flow-work/test-blueprint-REQ-1.md",
                    "sha256": hashlib.sha256(
                        text.encode("utf-8")).hexdigest(),
                },
            },
        }
        rules = WorkflowEvidenceRules(make_ports(
            is_file=lambda _path: True,
            read_text=lambda _path: text,
        ))
        self.assertTrue(rules.spec2code_artifact(
            {"kind": "blueprint"}, state).passed)
        stale = WorkflowEvidenceRules(make_ports(
            is_file=lambda _path: True,
            read_text=lambda _path: text + "changed",
        ))
        self.assertIn(
            "摘要已变化",
            stale.spec2code_artifact(
                {"kind": "blueprint"}, state).reason,
        )

    def test_substitute_and_glob_keep_legacy_placeholder_semantics(self):
        self.assertEqual(
            "docs/REQ-7/change.md",
            substitute(
                "docs/{单号}/change.md",
                {"config": {"单号": "REQ-7"}},
            ),
        )
        rules = WorkflowEvidenceRules(make_ports())
        passed, reason = rules.glob(
            {"any": ["docs/{MISSING}.md"]},
            {"config": {}},
        )
        self.assertFalse(passed)
        self.assertEqual(
            "证据 pattern 含未解析占位符(对应配置未 --set): "
            "docs/{MISSING}.md",
            reason,
        )

    def test_glob_content_absent_and_clean_path_rules(self):
        files = {
            "docs/one.md": "safe text",
            "docs/two.md": "contains TODO",
        }
        dirty = {"docs/two.md"}
        rules = WorkflowEvidenceRules(make_ports(
            glob_paths=lambda pattern: (
                sorted(files) if pattern == "docs/*.md"
                else [pattern] if pattern in files else []),
            read_text=lambda path: files[path],
            read_text_replace=lambda path: files[path],
            argv_output=lambda arguments: (
                " M " + arguments[-1]
                if arguments[-1] in dirty else ""),
        ))
        self.assertTrue(rules.glob(
            {"any": ["docs/*.md"]}, {"config": {}}).passed)
        self.assertEqual(
            (False, "内容含禁止残留(命中 pattern: TODO)"),
            tuple(rules.content_free(
                {"file": "docs/two.md", "patterns": ["TODO"]},
                {"config": {}},
            )),
        )
        self.assertEqual(
            (
                False,
                "以下路径必须已不存在(残留=动作未完成,如复制式假归档): "
                "docs/*.md",
            ),
            tuple(rules.glob_absent(
                {"any": ["docs/*.md"]}, {"config": {}})),
        )
        self.assertEqual(
            (
                False,
                "以下产物未提交(或有未提交改动),先 git add/commit 再 done: "
                "docs/two.md(M)",
            ),
            tuple(rules.clean_paths(
                {"paths": ["docs/one.md", "docs/two.md"]},
                {"config": {}},
            )),
        )

    def test_branch_rule_preserves_adoption_receipt_and_mismatch(self):
        outputs = {
            "git branch --show-current": "feature/existing",
            "git rev-parse --verify main^{commit}": "a" * 40,
            "git rev-parse --verify HEAD": "b" * 40,
        }
        rules = WorkflowEvidenceRules(make_ports(
            shell_output=lambda command: outputs.get(command, ""),
            argv_output=lambda arguments: outputs.get(
                " ".join(arguments), ""),
        ))
        state = {
            "config": {
                "分支名": "feature/existing",
                "基线分支": "main",
            },
            "branch_resolution": {
                "mode": "adopt-current",
                "branch": "feature/existing",
                "head": "b" * 40,
                "base": "main",
                "base_head": "a" * 40,
            },
        }
        self.assertTrue(rules.branch_ok({}, state).passed)
        state["config"]["分支名"] = "feature/other"
        self.assertIn(
            "当前分支 feature/existing != 约定分支 feature/other",
            rules.branch_ok({}, state).reason,
        )

    def test_tasks_and_spec_field_rules_keep_failure_messages(self):
        rules = WorkflowEvidenceRules(make_ports(
            tasks_source=lambda _root, _change: (
                "change.md", "- [x] done\n- [ ] pending\n"),
            is_file=lambda _path: False,
        ))
        state = {
            "config": {"CHANGE_NAME": "change-x"},
            "spec": {"design_doc": "docs/design.md"},
        }
        self.assertEqual(
            (False, "change.md 还有 1 个未勾选任务"),
            tuple(rules.tasks_checked({}, state)),
        )
        self.assertEqual(
            (
                False,
                "交付登记 design_doc 指向 docs/design.md,"
                "但该文件现在不存在(被删或改名);重新生成产物并重新登记",
            ),
            tuple(rules.spec_field({"field": "design_doc"}, state)),
        )

    def test_legacy_ut_only_tasks_do_not_block_implementation_progress(self):
        state = {"config": {"CHANGE_NAME": "change-x"}}
        rules = WorkflowEvidenceRules(make_ports(
            tasks_source=lambda _root, _change: (
                "change.md",
                "- [x] 1. 实现 PRACH SUL 分支\n"
                "- [ ] 2. UT频段类型判断 PRACHCellObjImplTest.cpp\n",
            ),
        ))
        self.assertTrue(rules.tasks_checked({}, state).passed)

        production_pending = WorkflowEvidenceRules(make_ports(
            tasks_source=lambda _root, _change: (
                "change.md",
                "- [x] 1. 完成接口\n"
                "- [ ] 2. 修正 PRACH 控制流\n",
            ),
        ))
        result = production_pending.tasks_checked({}, state)
        self.assertFalse(result.passed)
        self.assertIn("1 个未勾选", result.reason)

    def test_tier_scope_requires_risk_or_small_change(self):
        rules = WorkflowEvidenceRules(make_ports(
            business_changed_files=lambda _state: (
                ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py"], ""),
        ))
        state = {"choices": {"workflow": "tweak"}}
        result = rules.tier_scope({}, state)
        self.assertFalse(result.passed)
        self.assertIn("超过 tweak 档升级阈值(5)", result.reason)
        accepted = WorkflowEvidenceRules(make_ports(
            risk_acceptance=lambda _kind, _state: (True, "approved"),
        ))
        self.assertTrue(accepted.tier_scope({}, state).passed)

    def test_spec_validate_preserves_allow_empty_and_error_boundaries(self):
        calls = []
        rules = WorkflowEvidenceRules(make_ports(
            spec_has_delta=lambda root, change: (
                calls.append(("delta", root, change)) or False),
        ))
        state = {
            "config": {"CHANGE_NAME": "change-x"},
            "choices": {"workflow": "tweak"},
        }
        self.assertTrue(
            rules.spec_validate({"allow_empty": True}, state).passed)
        self.assertEqual([("delta", "/repo", "change-x")], calls)

        broken = WorkflowEvidenceRules(make_ports(
            spec_has_delta=lambda _root, _change: True,
            spec_validate=lambda _root, _change: (
                False, ["[错误] missing requirement"]),
        ))
        result = broken.spec_validate({}, state)
        self.assertFalse(result.passed)
        self.assertIn(
            "规格结构校验未通过: [错误] missing requirement",
            result.reason,
        )

        unavailable = WorkflowEvidenceRules(make_ports(
            spec_has_delta=lambda _root, _change: (
                (_ for _ in ()).throw(SpecError("not found"))),
        ))
        self.assertEqual(
            (False, "规格校验无法执行: not found"),
            tuple(unavailable.spec_validate(
                {"allow_empty": True}, state)),
        )


if __name__ == "__main__":
    unittest.main()
