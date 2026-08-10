#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Git 放行的授权契约。"""

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


class UserDecisionIsFinalTests(unittest.TestCase):
    """用户高于一切:验真该证明"确实是你决定的",不该质疑"你决定得够不够细"。

    内网实战:仓刚 init 没有任何提交,要先做基线提交才能切分支。Agent 用
    AskUserQuestion 把动作与风险摆给用户,用户点了「允许创建基线提交」。
    可 allow 拒绝了——它只比对"回答"字段,而回答是个短选项标签(流程本身明令
    选项要短),装不下 12 个路径;于是契约自相矛盾:走点选必死,只能让用户手打
    12 行路径。Agent 转而去传 allow --paths,而这个参数不存在,撞上参数错误。

    改法:点选授权的是"用户看见的那一屏"。问题文本由宿主记录、Agent 事后改不了,
    所以它能界定范围;而同意与否仍然只看回答本身。
    """

    def test_paths_shown_in_the_question_are_authorized(self):
        from mae_flow_core.cli_commands.git_authorization import (
            authorization_gap)
        action = {"operation": "commit",
                  "paths": ["pom.xml", "notify-web/src/", "docs/se/REQ.md"]}
        shown = ("是否允许把 pom.xml、notify-web/src/、docs/se/REQ.md "
                 "作为基线提交?")
        self.assertEqual(
            [], authorization_gap(action, "允许创建基线提交", shown),
            "用户看着清单点了允许,就是授权了这些路径")

    def test_paths_never_shown_are_still_refused(self):
        from mae_flow_core.cli_commands.git_authorization import (
            authorization_gap)
        action = {"operation": "commit", "paths": ["pom.xml", "web/src/"]}
        missing = authorization_gap(
            action, "允许创建基线提交", "是否允许创建基线提交?")
        self.assertEqual(["pom.xml", "web/src/"], missing,
                         "没让用户看见的路径不能算授权过")

    def test_agreement_still_comes_only_from_the_answer(self):
        from mae_flow_core.cli_commands.git_authorization import (
            answer_is_affirmative)
        for said in ("允许创建基线提交", "同意", "可以", "ok", "批准"):
            self.assertTrue(answer_is_affirmative(said), said)
        for said in ("不允许", "拒绝", "取消", "先不要", "", "看看再说"):
            self.assertFalse(answer_is_affirmative(said), said)

    def test_receipt_keeps_what_the_user_saw(self):
        import io as _io
        with _io.open(os.path.join(ROOT, "scripts", "mae_flow_core",
                                   "cli_commands", "ack.py"),
                      encoding="utf-8") as stream:
            source = stream.read()
        self.assertIn('"shown"', source, "收据要留档用户看见的那一屏")
