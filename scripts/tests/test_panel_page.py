#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""面板页面契约:自包含、无写入入口、版面优先级不许倒过来。"""

import json
import os
import re
import shutil
import sys
import unittest

TESTS = os.path.abspath(os.path.dirname(__file__))
SCRIPTS = os.path.abspath(os.path.join(TESTS, ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.panel import page, snapshot  # noqa: E402
from test_panel_snapshot import FLOW, STATE  # noqa: E402

CHANGES = [{
    "title": "未提交", "note": "工作区待检视增量",
    "files": [{"path": "src/a.py", "added": 3, "removed": 1,
               "patch": "@@ -1,1 +1,3 @@\n-old\n+new\n+extra\n"}],
}]


def build(state=STATE, changes=CHANGES):
    data = snapshot.build(TESTS, state, FLOW)
    return page.render(data, changes, TESTS)


class PanelPageTests(unittest.TestCase):
    def test_page_is_self_contained(self):
        """内网零依赖:不许有任何外部请求,否则内网直接白屏。"""
        html = build()
        for pattern in (r'src="https?://', r'href="https?://[^"]*\.css',
                        r"@import", r"fetch\(", r"XMLHttpRequest"):
            self.assertIsNone(re.search(pattern, html), pattern)
        self.assertIn("<style>", html)
        self.assertIn("<script>", html)

    def test_page_offers_no_way_to_advance_the_flow(self):
        """面板上的"推进"按钮是绕过证据的官方通道,比模型偷懒危险得多。"""
        html = build()
        self.assertNotIn("<form", html)
        for word in ("done --ack", "mae-flow.py done ", "goto ", "skip "):
            self.assertNotIn(word, html.replace(
                "done ...", ""), "页面不应提供可执行的推进入口: " + word)

    def test_pending_section_precedes_progress_section(self):
        """版面优先级是契约:待裁决在前,进度在最后。"""
        html = build(dict(STATE, current="config_confirm"))
        self.assertLess(html.index("待你裁决"), html.index(">进度<"))
        self.assertIn("REQ2026080901", html)

    def test_quiet_when_nothing_needs_the_user(self):
        html = build()
        self.assertIn("当前没有需要你拍板的事项", html)

    def test_degraded_tool_gets_its_own_banner(self):
        html = build()
        self.assertIn("工具未就绪", html)
        self.assertIn("不是通过", html)

    def test_diff_is_rendered_as_split_view(self):
        html = build()
        self.assertIn("变更前", html)
        self.assertIn("变更后", html)
        self.assertIn('class="dr"', html)
        self.assertIn("+3", html)

    def test_progress_never_prints_a_percentage(self):
        html = build()
        self.assertNotIn("%</", html)
        self.assertIn("步", html)

    def test_missing_state_still_renders(self):
        html = page.render(snapshot.build(TESTS, None, FLOW), [], TESTS)
        self.assertIn("（无在途单）", html)
        self.assertIn("没有 .mae-flow.json", html)

    def test_dispatched_but_unfinished_checks_never_show_green(self):
        """有任务卡/尝试记录≠通过:Reviewer 在检视中、精简在跑、CodeCheck
        状态含糊时,一律不得进"已过关"——误绿比不显示更坏(实战反馈)。"""
        state = dict(STATE)
        state["agent_tasks"] = dict(STATE["agent_tasks"])
        state["agent_tasks"]["REVIEWER"] = {
            "at": "2026-08-08 16:36:29", "step": "build_agent_review",
            "task_files": [], "path": "/tmp/review.md"}
        # steps_done 只有 config_confirm/workflow_select:四项检查全没走完
        html = build(state)
        fineline = re.search(r'已过关：[^<]*', html)
        joined = fineline.group(0) if fineline else ""
        for name in ("Agent 预检", "代码精简", "编译", "CodeCheck"):
            self.assertNotIn(name, joined,
                             "%s 未走完却进了已过关——误绿" % name)
        self.assertGreaterEqual(html.count(">进行中<"), 3)

    def test_ambiguous_codecheck_status_is_not_clean(self):
        """REMAINING/空状态且无告警数:记录含糊就明说"没确认过",不当作通过。"""
        state = json.loads(json.dumps(STATE))
        state["quality"]["codecheck_scan"].update(
            {"status": "REMAINING", "count": None, "error": ""})
        html = build(state)
        self.assertIn("没确认过", html)
        self.assertIn("不当作通过", html)

    def test_explicit_clean_codecheck_is_green(self):
        state = json.loads(json.dumps(STATE))
        state["quality"]["codecheck_scan"].update(
            {"status": "CLEAN", "count": 0, "error": ""})
        html = build(state)
        self.assertNotIn("没确认过", html)
        self.assertIn("CodeCheck", re.search(r'已过关：[^<]*', html).group(0))

    def test_story_confirmation_card_shows_the_story_door(self):
        """确认 Story 的卡片里是可点开的 story.md,而不是项目配置。"""
        folder = os.path.join(TESTS, ".mae-flow-work", "REQ2026080901")
        os.makedirs(folder, exist_ok=True)
        try:
            with open(os.path.join(folder, "story.md"), "w",
                      encoding="utf-8") as stream:
                stream.write("# STORY\n")
            html = build(dict(STATE, current="story"))
            card = html[html.index("待你裁决"):html.index(">文档 <")]
            self.assertIn("story.md", card)
            self.assertIn("要检视的文件", card)
            self.assertIn("show('doc-story')", card)   # 点开就地阅读
            self.assertNotIn("工号", card)             # 不倒配置
        finally:
            shutil.rmtree(os.path.join(TESTS, ".mae-flow-work"), True)


if __name__ == "__main__":
    unittest.main()
