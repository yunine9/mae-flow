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
        for word in ("done --ack", "mae-flow.py done", "goto ", "skip "):
            self.assertNotIn(word, html,
                             "页面不应提供可执行的推进入口: " + word)
        # 命令占位符与"面板不提供执行按钮"这类设计自辩不进用户视野
        self.assertNotIn("给人复制到终端用", html)
        self.assertNotIn("面板不提供执行按钮", html)

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

    def test_page_admits_when_it_may_be_stale(self):
        """红线:面板是快照不是实时视图,显示与当前阶段不符的信息会造成误解。
        file:// 读不到新状态,那就诚实地按时间弱声明,绝不假装最新。"""
        html = build()
        self.assertIn('data-born=', html)
        self.assertIn('id="stale"', html)
        self.assertIn("分钟前的快照", html)
        self.assertIn("以会话里的最新输出为准", html)
        self.assertIn("visibilitychange", html)   # 切回标签自动重取
        # 自动发现更新:手动按钮只在"文件刚重生成且你没切走"时有用,
        # 其余时候点了没反应,反而制造"我刷新过了"的错觉——退役,
        # 改为页面每 5 秒探 stamp,发现更新即自动重载。
        self.assertIn("panel-stamp.js", html)
        self.assertIn("setInterval(probe", html)
        # 自动重载必须独立于陈旧横幅:横幅元素缺失曾让整段逻辑被守卫跳过
        reload_block = html[html.index("// 自动发现更新"):html.index("// 陈旧兜底")]
        self.assertIn("location.reload()", reload_block)
        self.assertNotIn("getElementById('stale')", reload_block)
        self.assertIn("panelReloadedAt", reload_block)   # 同版本只重载一次
        self.assertNotIn('id="reget"', html)
        self.assertNotIn("流程重算", html)
        self.assertIn('id="age"', html)           # 页眉常显新鲜度

    def test_pulse_keeps_light_facts_live_without_full_regeneration(self):
        """轻重分离:全量重生成要渲染文档与全量 diff(几百毫秒),编码期间
        hook 高频触发,每次都算会拖慢流程;而用户要"随时最新"的只是
        轻量事实(到哪一步、要不要我出场)。脉冲报事实,不假装自己有内容。"""
        html = build()
        self.assertIn("panel-pulse.js", html)
        self.assertIn('data-pulse=', html)
        self.assertIn('id="live"', html)
        self.assertIn("setInterval(pulse, 2000)", html)
        self.assertIn("正在等你确认", html)
        # 诚实:脉冲变了也要说清"文档与 diff 还是上一次的"
        self.assertIn("重内容会在下个节点自动更新", html)

    def test_pulse_payload_is_state_only_and_throttled(self):
        import shutil, tempfile, time as _time
        from mae_flow_core.panel import pulse
        room = tempfile.mkdtemp(prefix="pulse-")
        self.addCleanup(shutil.rmtree, room, True)
        state_path = os.path.join(room, ".mae-flow.json")
        with open(state_path, "w", encoding="utf-8") as handle:
            json.dump(dict(STATE, current="config_confirm"), handle,
                      ensure_ascii=False)
        self.assertTrue(pulse.write_pulse(state_path, FLOW, room))
        with open(pulse.pulse_path(room), encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("window.__panelPulse=", body)
        self.assertIn('"waiting": true', body)      # 该步要用户确认
        self.assertIn('"step": "config_confirm"', body)
        # 两秒内不重复写(hook 高频事件不能变成高频磁盘写)
        self.assertFalse(pulse.write_pulse(state_path, FLOW, room))
        # 状态坏了也只是不写,绝不抛错
        with open(state_path, "w", encoding="utf-8") as handle:
            handle.write("{broken")
        os.utime(pulse.pulse_path(room), (0, 0))
        self.assertFalse(pulse.write_pulse(state_path, FLOW, room))

    def test_write_page_emits_the_stamp_beside_the_panel(self):
        """stamp 与页面同一个 born:早一秒都会让新页面自认过期而反复重载。"""
        import re as _re, shutil, tempfile
        room = tempfile.mkdtemp(prefix="panel-stamp-")
        self.addCleanup(shutil.rmtree, room, True)
        target = os.path.join(room, "out", "panel.html")
        page.write_page(target, snapshot.build(TESTS, STATE, FLOW), [], TESTS)
        with open(target, encoding="utf-8") as handle:
            html = handle.read()
        with open(os.path.join(room, "out", "panel-stamp.js"),
                  encoding="utf-8") as handle:
            stamp = handle.read()
        born = _re.search(r'data-born="(\d+)"', html).group(1)
        self.assertIn("window.__panelStamp=%s;" % born, stamp)
        self.assertIn('id="age"', html)           # 页眉常显新鲜度
        # 它仍然不是推进入口
        self.assertNotIn("mae-flow.py done", html)

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

    def test_viewer_scrolls_inside_the_pane_not_under_a_sticky_bar(self):
        """弹层标题栏固定、滚动只发生在内容区内部。

        sticky 方案实测有 bug:滚动容器带内边距时,正文会从标题栏上方的
        缝里穿出去,标题栏悬在内容中间(截图确认过)。回归锁:面板 CSS
        不再使用 sticky,内容区自己滚。"""
        from mae_flow_core.panel import assets
        self.assertNotIn("position:sticky", assets.CSS)
        self.assertIn("overflow-y:auto", assets.CSS)
        self.assertIn("pane.scrollTop = 0", assets.JS)

    def test_auto_reload_defers_while_reading_and_resumes_on_close(self):
        """自动重载不能把读到一半的文档弹层关掉;关闭弹层时补查一次,
        读文档期间攒下的更新此刻安全落地。"""
        from mae_flow_core.panel import assets
        self.assertIn("visibilitychange", assets.JS)      # 切回即查
        self.assertIn("reading = V && V.classList.contains('on')", assets.JS)
        self.assertIn("&& !reading", assets.JS)
        self.assertIn("window.__panelProbe", assets.JS)   # 关闭弹层后补查


if __name__ == "__main__":
    unittest.main()
