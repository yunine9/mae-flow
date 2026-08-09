#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""被拦下的人必须知道下一步做什么。

实战教训:CodeCheck 步的门禁只说"旧首检不背新代码的书,重新执行
codecheck-scan"——而工具当时正好跑不起来,于是模型没有出路,在
"改—扫—又改"里空转几轮,最后自己回退了 5 个文件才脱身。

只说"不许"的拦截,对弱模型等同于死路。本文件把"每条拒绝都得给出路"
钉成红线:门禁层严格全覆盖,推进层用棘轮防新增。
"""

import ast
import io
import os
import re
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

# 出路长什么样:一条命令、一个动作、或一处明确指引。
WAY_OUT = re.compile(
    r"重新执行|重跑|重新|重试|先.{0,20}再|.{0,20}后再|回退|改成|改为|改用|换成|"
    r"删除|去掉|补齐|合并为|执行|运行|直接 |请|应|需|必须|参见|见 |走 |使用|"
    r"用 |维护人|--|`|<[^>]+>|\{MAEFLOW_PATH\}|mae-flow")

# 推进层现存的"只说不许"条数。只许降不许升——新写的拒绝必须带出路。
# 剩下这些多是诊断分支("无法…:⟨错误原文⟩"),模型很少撞上;热路径已清零。
# 每次顺手清掉几条就把数字调小,别让它涨回去。
_DEAD_END_BUDGET = 31


def _literal(node):
    """把 '甲' + 变量 + '乙' 还原成整句;变量段用 ⟨⟩ 占位,不参与判定。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left), _literal(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        return "".join(_literal(part) or "⟨⟩" for part in node.values)
    if isinstance(node, (ast.FormattedValue, ast.Call, ast.Name,
                         ast.Attribute)):
        return "⟨⟩"
    return None


def _refusals(path, kind):
    tree = ast.parse(io.open(path, encoding="utf-8").read())
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        label = getattr(node.func, "attr", None) or getattr(node.func, "id",
                                                            None)
        if kind == "gate" and label == "EvidenceResult" and len(node.args) > 1:
            first = node.args[0]
            if isinstance(first, ast.Constant) and first.value is False:
                text = _literal(node.args[1])
                if text:
                    out.append((node.lineno, text))
        if kind == "advance" and label == "die" and node.args:
            text = _literal(node.args[0])
            if text:
                out.append((node.lineno, text))
    return out


def _judgeable(rows):
    """文本几乎全是变量的,静态判不了——不冤枉它,也不给它记功。"""
    return [(line, text) for line, text in rows
            if len(text.replace("⟨⟩", "").strip()) >= 10]


class RefusalTests(unittest.TestCase):
    def test_every_gate_refusal_tells_you_what_to_do(self):
        path = os.path.join(SCRIPTS, "mae_flow_core", "quality",
                            "evidence.py")
        stuck = [(line, text) for line, text
                 in _judgeable(_refusals(path, "gate"))
                 if not WAY_OUT.search(text)]
        self.assertEqual(
            [], stuck,
            "门禁拒绝了却没说下一步做什么: %s"
            % [(line, text[:60]) for line, text in stuck])

    def test_advancement_refusals_do_not_regress(self):
        stuck = []
        base = os.path.join(SCRIPTS, "mae_flow_core", "cli_commands")
        for name in sorted(os.listdir(base)):
            if not name.endswith(".py"):
                continue
            path = os.path.join(base, name)
            stuck += [(name, line, text) for line, text
                      in _judgeable(_refusals(path, "advance"))
                      if not WAY_OUT.search(text)]
        self.assertLessEqual(
            len(stuck), _DEAD_END_BUDGET,
            "新增了只说「不许」不说出路的拒绝: %s"
            % [(name, line, text[:50]) for name, line, text in stuck])


if __name__ == "__main__":
    unittest.main()
