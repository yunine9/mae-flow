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
        """当前动作优先，流程细节在侧栏，不抢用户注意力。"""
        html = build(dict(STATE, current="config_confirm"))
        self.assertLess(html.index("现在需要你看什么"),
                        html.index(">流程细节<"))
        self.assertIn("REQ2026080901", html)

    def test_quiet_when_nothing_needs_the_user(self):
        html = build()
        self.assertIn("当前不需要你处理", html)

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

    def test_change_generator_feeds_both_summary_and_diff(self):
        """渲染层不应因先消费迭代器而让首屏统计变成 0。"""
        data = snapshot.build(TESTS, STATE, FLOW)
        html = page.render(data, (item for item in CHANGES), TESTS)
        summary = html[html.index('<div class="summary-grid">'):
                       html.index("现在需要你看什么")]
        self.assertIn("1 个文件 · +3 / −1", summary)
        self.assertIn("src/", html)
        self.assertIn("a.py", html)

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
            card = html[html.index("现在需要你看什么"):
                        html.index("需求与设计资产")]
            self.assertIn("story.md", card)
            self.assertIn("要检视的文件", card)
            self.assertIn("show('doc-story')", card)   # 点开就地阅读
            self.assertNotIn("工号", card)             # 不倒配置
        finally:
            shutil.rmtree(os.path.join(TESTS, ".mae-flow-work"), True)

    def test_artifacts_are_a_first_class_section_before_execution_details(self):
        """Grill/Spec/Story/实现说明是实现依据，不是缩在侧栏的普通附件。"""
        folder = os.path.join(TESTS, ".mae-flow-work", "REQ2026080901")
        os.makedirs(folder, exist_ok=True)
        try:
            for name in ("grill.md", "spec.md", "story.md",
                         "implementation.md"):
                with open(os.path.join(folder, name), "w",
                          encoding="utf-8") as stream:
                    stream.write("# %s\n" % name)
            html = build()
            action = html.index("现在需要你看什么")
            assets = html.index("需求与设计资产")
            history = html.index("执行记录")
            changes = html.index("代码变更")
            self.assertLess(action, assets)
            self.assertLess(assets, history)
            self.assertLess(assets, changes)
            for name in ("grill.md", "spec.md", "story.md",
                         "implementation.md"):
                self.assertIn(name, html)
            self.assertIn('<span class="asset-kind">规格条目</span>', html)
            self.assertIn('<span class="asset-kind">实现记录</span>', html)
            # 显示名单一来源(snapshot DOC_KINDS);Grill 等上游术语不进用户视野
            self.assertIn("需求澄清 / 决策", html)
            self.assertNotIn("Grill / 决策", html)
            self.assertIn("Story", html)
            self.assertIn("实现记录 / 代码", html)
        finally:
            shutil.rmtree(os.path.join(TESTS, ".mae-flow-work"), True)

    def test_phase_rail_is_a_connected_horizontal_node_track(self):
        """当前阶段不准再被挤成逐字竖排的胶囊。"""
        html = build()
        self.assertIn('class="phase-node past"', html)
        self.assertIn('class="phase-node current"', html)
        self.assertIn("grid-template-columns:repeat(7,1fr)", html)
        self.assertIn(".phase-node:not(:last-child):after", html)
        self.assertIn("@media (max-width:860px)", html)
        self.assertNotIn("writing-mode", html)

    def test_execution_history_is_visible_without_replacing_quality_facts(self):
        html = build()
        self.assertIn("执行记录", html)
        self.assertIn("配置确认", html)
        self.assertIn("交付方式选择", html)
        self.assertIn('class="history-result">已完成</span>', html)
        self.assertNotIn('class="history-result">done</span>', html)
        self.assertIn("质量事实", html)

    def test_summary_deduplicates_files_across_change_groups(self):
        """同一文件常同时在"已提交"与"未提交"两组:首屏文件数必须去重。
        实测踩过:两组直加显示 11 个文件,真实去重是 8——首屏第一个数字撒谎。"""
        overlapping = [
            {"title": "已提交", "note": "", "files": [
                {"path": "a.py", "added": 10, "removed": 1, "patch": ""}]},
            {"title": "未提交", "note": "", "files": [
                {"path": "a.py", "added": 5, "removed": 0, "patch": ""}]},
        ]
        html = build(changes=overlapping)
        self.assertIn("1 个文件 · +15 / −1", html)

    def test_history_count_excludes_the_now_row(self):
        """"现在"行不是执行记录,不计入"最近 N 条"。"""
        html = build()
        self.assertIn("最近 2 条", html)     # STATE 里恰有两条 history
        self.assertIn(">现在<", html.replace("<time>现在</time>", ">现在<"))


if __name__ == "__main__":
    unittest.main()
