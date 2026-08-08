#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""面板页面契约:自包含、无写入入口、版面优先级不许倒过来。"""

import os
import re
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


if __name__ == "__main__":
    unittest.main()
