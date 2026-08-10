#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""退出授权的绑定纪律。"""

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


class ExitAuthorizationBindingTests(unittest.TestCase):
    """答选择题时顺口提到的字眼,不能给"退出流程"这种不可逆动作背书。

    实测(无人值守):流程在问交付方式(完整开发/已定位问题修复/局部修改/
    处理评审意见),用户答「选择 1（退出 Mae-Flow，直接开发）」——他要的是
    选项 1,括号里是自己的注解。可 exit 的 ack 只做精确匹配,这句话原样对
    得上,于是一次正常答题把整个流程退掉了,现场停在 workflow_select。

    与"choice 问了两遍"同源:授权必须绑定到当时在问的那个问题。
    """

    def test_answers_to_a_choice_are_not_exit_authorization(self):
        from mae_flow_core.cli_commands.lifecycle import (
            _looks_like_option_answer)
        for said in ("选择 1（退出 Mae-Flow，直接开发）", "1", "（2）",
                     "2.", "第 3 项", "确认：我选择完整开发 (full)"):
            self.assertTrue(_looks_like_option_answer(said),
                            "这是在答选择题: %r" % said)

    def test_a_real_exit_request_still_works(self):
        from mae_flow_core.cli_commands.lifecycle import (
            _looks_like_option_answer)
        for said in ("退出流程，我要直接改代码", "我确认退出 mae-flow",
                     "先退出吧，后面手工改"):
            self.assertFalse(_looks_like_option_answer(said),
                             "这是真要退出: %r" % said)
