#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依赖目录不能被当成交付内容灌进任务卡与面板。

内网实战:grill-critic 的任务卡里出现"### 未跟踪文件:
node_modules/@fission-ai/openspec/dist/cli/index.js"无穷重复,Agent 当场卡死。

根因是 `git ls-files --others --exclude-standard` 只认 .gitignore——仓里没忽略
node_modules 是很常见的事,于是几千个依赖文件被逐个整段(每个上限 10 万字符)
塞进卡片。总量 20 万字符的上限是**事后截断**,拼完才切,卡片早爆了。

同一个洞有两个出口:任务卡(role_task)与面板的未跟踪增量(snapshot)。两处都堵,
并且都要把"截断了多少"说出来——看起来完整、实则少了一半,比明说更难查。
"""

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

FLOOD = (
    "node_modules/@fission-ai/openspec/dist/cli/index.js",
    "web/node_modules/react/index.js",
    "target/classes/A.class",
    "build/libs/app.jar",
    ".venv/lib/python3.13/site-packages/x.py",
    "__pycache__/m.cpython-313.pyc",
    ".gradle/caches/x.bin",
)
DELIVERY = (
    "service/src/main/java/A.java",
    "docs/se/REQ2026081101.md",
    "src/vendors.py",          # 名字里带 vendor 但不是目录,不能误伤
    "tests/test_a.py",
)


class TaskCardFloodTests(unittest.TestCase):
    def test_dependency_paths_never_enter_a_card(self):
        from mae_flow_core.cli_commands.role_task import _skip_in_card
        for path in FLOOD:
            self.assertTrue(_skip_in_card(path), "该排除: %s" % path)

    def test_delivery_paths_still_enter(self):
        from mae_flow_core.cli_commands.role_task import _skip_in_card
        for path in DELIVERY:
            self.assertFalse(_skip_in_card(path), "不该排除: %s" % path)

    def test_card_caps_untracked_files(self):
        from mae_flow_core.cli_commands import role_task
        self.assertLessEqual(role_task._MAX_UNTRACKED_FILES, 100,
                             "上限要小到卡片还能读")


class PanelFloodTests(unittest.TestCase):
    def test_panel_skips_dependency_dirs(self):
        from mae_flow_core.panel.snapshot import _dependency_path
        for path in FLOOD:
            self.assertTrue(_dependency_path(path), "该排除: %s" % path)
        for path in DELIVERY:
            self.assertFalse(_dependency_path(path), "不该排除: %s" % path)

    def test_panel_caps_and_says_so(self):
        """截断必须说出来,否则面板看起来完整、实则少了一半。"""
        import io as _io
        from mae_flow_core.panel import snapshot
        self.assertLessEqual(snapshot._UNTRACKED_FILE_CAP, 200)
        with _io.open(os.path.join(SCRIPTS, "mae_flow_core", "panel",
                                   "snapshot.py"), encoding="utf-8") as s:
            source = s.read()
        self.assertIn("未展示", source)
        self.assertIn(".gitignore", source, "要告诉人怎么根治")


if __name__ == "__main__":
    unittest.main()
