#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主动通知契约。

通知的唯一敌人是噪声:只在两种时刻响(需要用户裁决、进入新阶段),
其余一律安静。桌面弹窗默认关闭——不问自取地弹系统通知是打扰,不是服务。
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

TESTS = os.path.abspath(os.path.dirname(__file__))
SCRIPTS = os.path.abspath(os.path.join(TESTS, ".."))
ROOT = os.path.abspath(os.path.join(SCRIPTS, ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.panel import notify  # noqa: E402

FLOW = {
    "steps": {
        "config_confirm": {"title": "配置确认", "user_ack": True},
        "workflow_select": {"title": "交付方式选择", "user_ack": True,
                            "choice_key": "workflow"},
        "branch_create": {"title": "创建工作分支"},
        "grill": {"title": "需求拷问"},
        "build": {"title": "编码"},
        "build_commit": {"title": "提交"},
        "verify_ut": {"title": "UT 验证"},
    },
}


def announce(previous, nxt, root="."):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        lines = notify.announce(FLOW, previous, nxt, root, "REQ-1")
    return lines, buffer.getvalue()


class NotifyTests(unittest.TestCase):
    def setUp(self):
        os.environ[notify.ENV_OFF] = "1"       # 测试期禁止真弹窗
        self.addCleanup(os.environ.pop, notify.ENV_OFF, None)

    def test_every_flow_step_has_a_phase(self):
        """阶段表是唯一来源;漏一个步骤就会静默错标,所以用覆盖断言钉死。"""
        with open(os.path.join(ROOT, "flow", "flow.json"),
                  encoding="utf-8") as stream:
            steps = set(json.load(stream)["steps"])
        missing = sorted(step for step in steps if not notify.phase_of(step))
        self.assertEqual([], missing, "这些步骤没有归入任何阶段")
        stale = sorted(step for step in notify._STEP_PHASE if step not in steps)
        self.assertEqual([], stale, "阶段表里有 flow.json 已删除的步骤")

    def test_confirmation_step_rings(self):
        lines, printed = announce("branch_create", "config_confirm")
        self.assertTrue(any("需要你确认" in line for line in lines))
        self.assertIn("配置确认", printed)

    def test_choice_step_says_choose_not_confirm(self):
        lines, _printed = announce("config_confirm", "workflow_select")
        self.assertTrue(any("需要你选择" in line for line in lines))
        self.assertFalse(any("需要你确认" in line for line in lines))

    def test_phase_change_rings_once(self):
        lines, printed = announce("grill", "build")
        self.assertEqual(["🔔 进入「写代码」阶段"], lines)
        self.assertIn("写代码", printed)

    def test_same_phase_movement_stays_silent(self):
        """同阶段内推进不响——噪声化的通知等于没有通知。"""
        self.assertEqual(([], ""), announce("build", "build_commit"))

    def test_both_reasons_can_ring_together(self):
        lines, _printed = announce("build", "config_confirm")
        self.assertEqual(2, len(lines))

    def test_desktop_popup_is_opt_in(self):
        folder = tempfile.mkdtemp(prefix="notify-")
        self.addCleanup(shutil.rmtree, folder, True)
        os.environ.pop(notify.ENV_OFF, None)
        self.assertFalse(notify.desktop_enabled(folder))   # 无预设 → 关闭
        with open(os.path.join(folder, notify.DEFAULTS_PATH), "w",
                  encoding="utf-8") as stream:
            json.dump({notify.FIELD: True}, stream)
        self.assertTrue(notify.desktop_enabled(folder))
        os.environ[notify.ENV_OFF] = "1"
        self.assertFalse(notify.desktop_enabled(folder))   # 环境变量总能关掉

    def test_popup_failure_is_swallowed(self):
        """通知失败就是没通知,绝不许影响流程。"""
        original = notify._command
        notify._command = lambda title, body: ["definitely-not-a-command"]
        try:
            self.assertFalse(notify._popup("t", "b"))
        finally:
            notify._command = original

    def test_unknown_step_does_not_raise(self):
        self.assertEqual([], notify.announce(FLOW, "build", "no_such_step"))

    def test_advance_stays_wired_to_the_announcement(self):
        """通知的价值全在"推进那一刻响";接线掉了就是静默失效,必须钉死。"""
        path = os.path.join(SCRIPTS, "mae_flow_core", "cli_commands",
                            "advancement.py")
        with open(path, encoding="utf-8") as stream:
            source = stream.read()
        self.assertIn("notify.announce(", source)
        # 感知时机契约:通知响 = 面板刷新 = 告知路径,同一个瞬间;
        # 面板只在响的时刻刷新(rang 守卫),其余时刻没人看,不刷。
        self.assertIn("_announce_and_sync_panel(flow, st, sid, nxt)", source)
        self.assertIn("_panel_refresh", source)
        self.assertIn("if not rang:", source)

    def test_init_is_the_first_perception_moment(self):
        """开启流程就生成面板并要求转述路径——没人知道存在的面板等于不存在。"""
        path = os.path.join(SCRIPTS, "mae_flow_core", "cli_commands",
                            "init_capability.py")
        with open(path, encoding="utf-8") as stream:
            source = stream.read()
        self.assertIn("_panel_refresh", source)
        self.assertIn("原样告诉用户", source)

    def test_panel_path_rides_the_config_card_relay_contract(self):
        """实战验证:单独一行"告诉用户"的指令会被模型跳过——面板路径必须
        并进配置确认单,搭"逐项复制进回复正文"转述义务的便车。"""
        path = os.path.join(SCRIPTS, "mae_flow_core", "cli_commands",
                            "advancement.py")
        with open(path, encoding="utf-8") as stream:
            source = stream.read()
        self.assertIn("现场面板(浏览器打开一次", source)
        self.assertIn("与现场面板路径", source)

    def test_review_doc_write_regenerates_the_panel(self):
        """用户原话即契约:凡请用户检视的东西,面板必须能直接看。

        open/story 在进了步之后才生成文档,进步瞬间的面板拍不到它们——
        实战反馈:请用户确认 spec 时,面板上没有 spec.md。"""
        import subprocess
        from mae_flow_core.panel import sync
        root = tempfile.mkdtemp(prefix="panel-sync-")
        self.addCleanup(shutil.rmtree, root, True)
        subprocess.run(["git", "-C", root, "init", "-q"], check=True)
        state_path = os.path.join(root, ".mae-flow.json")
        with open(state_path, "w", encoding="utf-8") as stream:
            json.dump({"current": "open", "revision": 1,
                       "config": {"单号": "REQ-1"}, "choices": {},
                       "history": [], "started": "2026-08-09 08:00:00"},
                      stream, ensure_ascii=False)
        doc = os.path.join(root, ".mae-flow-work", "REQ-1", "spec.md")
        os.makedirs(os.path.dirname(doc), exist_ok=True)
        with open(doc, "w", encoding="utf-8") as stream:
            stream.write("# 规格\n- 条目一\n")
        before = os.getcwd()
        os.chdir(root)
        try:
            # 检视文档落盘 → 面板重生成,且内容里真有这份文档
            self.assertTrue(sync.refresh_on_doc_write(state_path, doc))
            panel_page = os.path.join(root, ".mae-flow-work", "panel.html")
            with open(panel_page, encoding="utf-8") as stream:
                html = stream.read()
            self.assertIn("spec.md", html)
            self.assertIn("条目一", html)      # 待裁决卡可点开就地读的就是它
            # 非检视文档一行判断直接跳过
            self.assertFalse(sync.refresh_on_doc_write(
                state_path, os.path.join(root, "src", "a.py")))
            # 状态文件损坏也只能静默,hook 绝不因面板受伤
            with open(state_path, "w", encoding="utf-8") as stream:
                stream.write("{broken")
            self.assertFalse(sync.refresh_on_doc_write(state_path, doc))
        finally:
            os.chdir(before)

    def test_doc_write_hook_stays_wired(self):
        """接线锁:posttool 的 Write 台账点必须同时触发面板重生成。"""
        path = os.path.join(SCRIPTS, "mae_flow_core", "adapters",
                            "hook_active_events.py")
        with open(path, encoding="utf-8") as stream:
            source = stream.read()
        self.assertIn("refresh_on_doc_write", source)

    def test_panel_refresh_is_soft_fail(self):
        """面板刷新失败只能返回 None——它永远不能反过来影响推进。"""
        from mae_flow_core.cli_commands import panel as panel_command
        original = panel_command._write_page

        def explode(*_args, **_kwargs):
            raise OSError("disk full")

        panel_command._write_page = explode
        try:
            self.assertIsNone(panel_command.refresh({}, {"current": "build"}))
        finally:
            panel_command._write_page = original

    def test_real_flow_transitions_produce_sensible_announcements(self):
        """拿真 flow.json 走几步真实转移,确认不是只有构造的假数据能过。"""
        with open(os.path.join(ROOT, "flow", "flow.json"),
                  encoding="utf-8") as stream:
            flow = json.load(stream)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            first = notify.announce(flow, "code_reviewer_ask",
                                    "workflow_select")
            crossing = notify.announce(flow, "story", "build")
            inside = notify.announce(flow, "verify_ponytail",
                                     "verify_codecheck")
        self.assertTrue(any("需要你选择" in line for line in first))
        self.assertEqual(["🔔 进入「写代码」阶段"], crossing)
        self.assertEqual([], inside)       # 质量阶段内部推进保持安静


if __name__ == "__main__":
    unittest.main()
