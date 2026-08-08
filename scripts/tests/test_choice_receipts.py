import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DISPATCH = os.path.join(ROOT, "hooks", "dispatch.py")
MAE = os.path.join(ROOT, "scripts", "mae-flow.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from mae_flow_core.cli_commands import ack


class ChoiceReceiptTests(unittest.TestCase):
    def test_codeagent_posttool_answer_advances_without_second_confirmation(self):
        with tempfile.TemporaryDirectory() as project:
            subprocess.run(
                ["git", "init", "-q", project], check=True,
                capture_output=True)
            state_path = os.path.join(project, ".mae-flow.json")
            with open(state_path, "w", encoding="utf-8") as stream:
                json.dump({
                    "current": "workflow_select",
                    "config": {}, "choices": {}, "history": [],
                    "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                }, stream)
            payload = json.dumps({
                "cwd": project,
                "tool_name": "AskUserQuestion",
                "tool_input": {"questions": [{
                    "question": "选择开发方式？",
                    "options": [
                        {"label": "完整开发"},
                        {"label": "已定位问题修复"},
                        {"label": "局部修改"},
                        {"label": "处理评审意见"},
                    ],
                }]},
                "tool_response": {
                    "answers": {"选择开发方式？": "完整开发"},
                },
            }, ensure_ascii=False) + "\n"
            captured = subprocess.run(
                [sys.executable, DISPATCH, "posttooluse"],
                cwd=project, input=payload, text=True,
                capture_output=True, timeout=15)
            advanced = subprocess.run(
                [sys.executable, MAE, "done", "--choice", "full"],
                cwd=project, text=True, capture_output=True, timeout=30)
            with open(state_path, encoding="utf-8") as stream:
                state = json.load(stream)

        self.assertEqual(0, captured.returncode, captured.stderr)
        self.assertEqual(0, advanced.returncode, advanced.stderr)
        self.assertEqual("code_reviewer_ask", state["current"])

    def test_askuser_token_without_selected_answer_cannot_authorize_choice(self):
        step = {
            "choice_answers": {
                "full": ["完整开发"],
                "hotfix": ["快速修复"],
            },
        }
        state = {"current": "workflow_select"}

        with mock.patch.object(ack, "_current_ack_messages", return_value=[]), \
                mock.patch.object(ack, "_fresh_askuser", return_value=True), \
                mock.patch.object(ack, "_out_of_scope_ack_reason", return_value=""), \
                mock.patch.object(ack, "_ack_failure", return_value=1):
            accepted, reason = ack._choice_verified(
                step, state, "full")

        self.assertFalse(accepted)
        self.assertIn("真实选项回答", reason)

    def test_structured_claude_code_answer_authorizes_matching_choice(self):
        step = {
            "choice_answers": {
                "full": ["完整开发"],
                "hotfix": ["快速修复"],
            },
        }
        state = {"current": "workflow_select"}
        rows = [{
            "text": '{"answers":{"交付方式":"完整开发"}}',
            "step": "workflow_select",
            "at": "9999-12-31 23:59:59",
        }]

        with mock.patch.object(ack, "_current_ack_messages", return_value=rows), \
                mock.patch.object(ack, "_ack_failure", return_value=0):
            accepted, reason = ack._choice_verified(
                step, state, "full")

        self.assertTrue(accepted, reason)


class ReorderedParaphrasedOptionsTests(unittest.TestCase):
    """2026-08-09 实战事故:模型把推荐项排到第一位并改写标签,
    按位置映射把「需要预检」判成 disabled,机器反过来指控模型
    "替用户改选",用户被迫回答两遍。位置从来不是证据,文字才是。
    载荷取自事故现场原文(fieldtest REQ2026080901 第二轮)。
    """

    STEP = {
        "choices": ["disabled", "enabled"],
        "choice_answers": {
            "disabled": ["不需要 Agent 预检，我直接检视"],
            "enabled": ["需要，人工检视前先由 Agent 预检"],
        },
    }
    ITEM = {
        "askuser": {"questions": [{
            "question": "人工检视前，是否需要一次只读 CODE Agent 预检？",
            # 推荐项排第一 = enabled 在前,与 flow.json 的 choices 顺序相反
            "options": ["需要，先预检 (推荐)", "不需要，我直接检视"],
        }]},
    }

    def test_paraphrased_reordered_answer_maps_to_the_right_choice(self):
        from mae_flow_core.workflow import completion
        self.assertEqual("enabled", completion.receipt_choice(
            self.STEP, self.ITEM, "需要，先预检(推荐)"))
        self.assertEqual("disabled", completion.receipt_choice(
            self.STEP, self.ITEM, "不需要，我直接检视"))

    def test_canonical_labels_keep_working_in_any_order(self):
        from mae_flow_core.workflow import completion
        item = {"askuser": {"questions": [{
            "options": ["需要，人工检视前先由 Agent 预检",
                        "不需要 Agent 预检，我直接检视"],
        }]}}
        self.assertEqual("enabled", completion.receipt_choice(
            self.STEP, item, "需要，人工检视前先由 Agent 预检"))

    def test_unmappable_labels_refuse_to_guess(self):
        """标签完全对不上时返回空——宁可打回重问,不做无声的翻转。"""
        from mae_flow_core.workflow import completion
        item = {"askuser": {"questions": [{
            "options": ["方案 A", "方案 B"],
        }]}}
        self.assertEqual("", completion.receipt_choice(
            self.STEP, item, "方案 A"))

    def test_multi_choice_with_recommendation_suffix(self):
        """四选一的 workflow 卡:标准文本+(推荐)后缀必须照常工作。"""
        from mae_flow_core.workflow import completion
        step = {
            "choices": ["full", "hotfix", "tweak", "review"],
            "choice_answers": {
                "full": ["完整开发"], "hotfix": ["已定位问题修复"],
                "tweak": ["局部修改"], "review": ["处理评审意见"],
            },
        }
        item = {"askuser": {"questions": [{
            "options": ["完整开发 (推荐)", "已定位问题修复",
                        "局部修改", "处理评审意见"],
        }]}}
        self.assertEqual("full", completion.receipt_choice(
            step, item, "完整开发 (推荐)"))


if __name__ == "__main__":
    unittest.main()
