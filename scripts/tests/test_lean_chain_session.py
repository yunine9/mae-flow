#!/usr/bin/env python3
"""Pure domain contracts for recoverable cross-repository Chain."""

import json
import os
import sys
import unittest


SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.orchestration.chain_session import (  # noqa: E402
    ChainRequest,
    ChainState,
    advance_chain,
    chain_completion_gaps,
    decode_chain_state,
    encode_chain_state,
)


def compact(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class LeanChainSessionTests(unittest.TestCase):
    def state(self):
        return ChainState(
            ticket="REQ-CHAIN",
            request="增加跨仓 SUL 支持",
            requirement_source="docs/REQ-CHAIN.md",
            anchor_root="/workspace/control",
            document_path=(
                "/workspace/control/.mae-flow-work/REQ-CHAIN/chain.md"),
        )

    def apply(self, state, kind, key="", value=""):
        return advance_chain(state, ChainRequest(kind, key, value))

    def repository(self, path, responsibility):
        return compact({
            "language_build": "C++ / configured build",
            "path": path,
            "responsibility": responsibility,
        })

    def touchpoint(self, repository, angle, file_name, symbol):
        return compact({
            "angle": angle,
            "confidence": "high",
            "file": file_name,
            "repository": repository,
            "symbol": symbol,
            "why": "该符号承载跨仓接口行为。",
        })

    def complete(self):
        state = self.state()
        for key, value in (
                ("control", self.repository(
                    "/workspace/control", "生成并下发 SUL 配置")),
                ("service", self.repository(
                    "/workspace/service", "消费 SUL 配置并选择资源"))):
            state = self.apply(state, "repository", key, value).state
        index = 0
        for repository in ("control", "service"):
            for angle in ("keyword", "interface", "config-routing"):
                index += 1
                state = self.apply(
                    state,
                    "touchpoint",
                    "TP-%03d" % index,
                    self.touchpoint(
                        repository, angle,
                        "src/%s.cpp" % repository,
                        "%sSulHandler" % repository.title()),
                ).state
        state = self.apply(
            state,
            "contract",
            "CT-001",
            compact({
                "error_semantics": "缺少 SUL 配置时明确回退主载波。",
                "fields": "mode, carrierId, sulEnabled",
                "repositories": ["control", "service"],
                "shape": "versioned configuration message",
            }),
        ).state
        state = self.apply(
            state,
            "dependency",
            "DEP-001",
            compact({
                "from": "control",
                "integration": "双方契约测试通过后联调。",
                "order": "control contract first, service second",
                "parallel": "本地解析可并行。",
                "to": "service",
            }),
        ).state
        for repository in ("control", "service"):
            state = self.apply(
                state,
                "reverse-check",
                repository,
                compact({
                    "independent": True,
                    "reason": "职责、契约、依赖和验证边界均完整。",
                }),
            ).state
        state = self.apply(
            state,
            "citations-verified",
            value=compact({"count": 6, "digest": "a" * 64}),
        ).state
        return state

    def test_schema_round_trip_is_exact_and_rejects_unknown_fields(self):
        state = self.state()
        self.assertEqual(state, decode_chain_state(encode_chain_state(state)))

        raw = encode_chain_state(state)
        raw["unknown"] = True
        with self.assertRaisesRegex(ValueError, "unknown"):
            decode_chain_state(raw)

    def test_repository_requires_unique_name_path_and_complete_ownership(self):
        state = self.state()
        added = self.apply(
            state, "repository", "control",
            self.repository("/workspace/control", "生成 SUL 配置"))
        duplicate = self.apply(
            added.state, "repository", "service",
            self.repository("/workspace/control", "消费 SUL 配置"))
        incomplete = self.apply(
            state, "repository", "service", compact({
                "language_build": "C++", "path": "/workspace/service",
                "responsibility": "",
            }))

        self.assertNotEqual(state, added.state)
        self.assertEqual(added.state, duplicate.state)
        self.assertIn("path", duplicate.reason.lower())
        self.assertEqual(state, incomplete.state)
        self.assertIn("responsibility", incomplete.reason)

    def test_question_protocol_allows_only_one_matching_answer(self):
        state = self.state()
        question = compact({
            "evidence": "两仓对缺省字段的解释不同。",
            "impact": "灰度期行为不一致。",
            "parent": "",
            "recommendation": "发送方显式下发 sulEnabled=false。",
        })
        opened = self.apply(state, "question", "CQ-001", question)
        blocked = self.apply(
            opened.state, "question", "CQ-002", question)
        wrong = self.apply(
            opened.state, "answer", "CQ-002", "确认推荐方案。")
        answered = self.apply(
            opened.state, "answer", "CQ-001", "确认推荐方案。")

        self.assertTrue(opened.needs_user)
        self.assertEqual(opened.state, blocked.state)
        self.assertEqual(opened.state, wrong.state)
        self.assertNotEqual(opened.state, answered.state)
        self.assertFalse(answered.needs_user)

    def test_completion_requires_three_angles_contract_dependency_and_reverse_checks(self):
        state = self.state()
        self.assertIn("two repositories", " ".join(chain_completion_gaps(state)))

        complete = self.complete()
        self.assertEqual([], chain_completion_gaps(
            complete, require_rendered=False))
        self.assertIn("rendered", " ".join(chain_completion_gaps(complete)))

    def test_contract_requires_shape_fields_and_error_semantics(self):
        state = self.state()
        invalid = self.apply(
            state, "contract", "CT-001", compact({
                "error_semantics": "",
                "fields": "mode",
                "repositories": ["control", "service"],
                "shape": "message",
            }))

        self.assertEqual(state, invalid.state)
        self.assertIn("error_semantics", invalid.reason)

    def test_render_confirmation_and_material_change_invalidation(self):
        state = self.complete()
        rendered = self.apply(
            state, "rendered", value=compact({"sha256": "b" * 64}))
        confirmed = self.apply(
            rendered.state, "confirmed", value="用户确认跨仓契约和启动卡。")

        self.assertFalse(rendered.needs_user)
        self.assertFalse(confirmed.needs_user)
        self.assertEqual([], chain_completion_gaps(confirmed.state))

        changed = self.apply(
            confirmed.state,
            "dependency",
            "DEP-002",
            compact({
                "from": "service",
                "integration": "回归完成后联调。",
                "order": "service validation after control",
                "parallel": "契约测试可并行。",
                "to": "control",
            }),
        )
        kinds = {record.kind for record in changed.state.records}
        self.assertNotIn("rendered", kinds)
        self.assertNotIn("confirmed", kinds)

    def test_exit_is_terminal_and_has_no_git_effects(self):
        exited = self.apply(
            self.state(), "exit", value="用户停止 Chain。")
        ignored = self.apply(
            exited.state,
            "repository",
            "service",
            self.repository("/workspace/service", "消费配置"),
        )

        self.assertEqual("exited", exited.state.status)
        self.assertEqual(exited.state, ignored.state)
        self.assertEqual((), exited.effects)


if __name__ == "__main__":
    unittest.main()
