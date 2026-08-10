#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全新仓的第一条命令从哪来——先有鸡还是先有蛋。

内网实战第一个问题:会话启动没把转发壳铺到工作目录,而 SKILL 让模型
用转发壳去跑 init。全新仓里那三条路当时全断:

- 转发壳:只给"已经有流程状态"的仓铺(对的,否则每个项目一发消息就多出个
  脏文件,用户删了还回来);
- Hook 注入:没状态就直接旁路,一个字不说;
- SKILL:明令禁止读环境变量、搜插件缓存或猜版本目录。

于是要用蛋去孵鸡。破环只能靠外部给一个起点:用户真的发起交付时,
Hook 把插件入口的绝对路径递过去;init 在同一条命令里把转发壳铺好,
之后一律用短路径(插件目录带版本号、升级即变;短路径不变,权限白名单才稳)。
"""

import io
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


class BootstrapTests(unittest.TestCase):
    def test_skill_never_asks_the_model_to_handle_plugin_paths(self):
        """铺桥是机器的活:模型从头到尾只知道短路径。第一版修法让 Hook 打印
        插件绝对路径给 Agent 抄——内网实测它把 Windows 长路径抄错了两处。"""
        with io.open(os.path.join(ROOT, "skills", "mae-flow", "SKILL.md"),
                     encoding="utf-8") as stream:
            skill = stream.read()
        head = skill.split("首次触发")[1][:400]
        self.assertIn("转发壳由 Hook 在你发起交付时自动铺好", head)
        self.assertIn("不需要找", head)
        self.assertIn('先执行 `python ".mae-flow-work/bin/mae-flow.py" init`',
                      skill)

    def test_hook_lays_the_bridge_itself_on_a_delivery_request(self):
        """hook 直接铺桥,不递路径;铺不动才降级——那是宿主故障,不该常见。"""
        with io.open(os.path.join(SCRIPTS, "mae_flow_core", "adapters",
                                  "hook_events.py"), encoding="utf-8") as s:
            source = s.read()
        block = source.split("_offer_first_entry")[2]
        self.assertIn("install_project_launcher()", block)
        self.assertIn("转发壳已就位", block)
        # 只在明确的交付请求上动手,无关项目一个文件都不写
        self.assertIn("_explicit_flow_start_prompt", block)
        self.assertIn('event != "userprompt"', block)
        # 降级路径必须自我声明"这不该经常出现"
        self.assertIn("这不该经常出现", block)

    def test_the_bridge_explains_itself_when_the_entry_is_gone(self):
        """内网反馈"明显报错了,不知道从哪来的"——原来只甩一句
        python: can't open file,既不说这是谁铺的,也不说怎么修。"""
        import shutil
        import subprocess
        import tempfile
        from mae_flow_core.adapters.project_launcher import (
            install_project_launcher)
        room = tempfile.mkdtemp(prefix="bridge-")
        self.addCleanup(shutil.rmtree, room, True)
        with io.open(os.path.join(room, ".mae-flow.json"), "w",
                     encoding="utf-8") as stream:
            stream.write("{}")
        bridge = install_project_launcher(room, plugin_root="/不存在的插件目录")
        self.assertTrue(bridge)
        done = subprocess.run([sys.executable, bridge, "current"],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(3, done.returncode)
        for said in ("插件入口不在这个路径了", "转发壳", "流程状态没坏",
                     "CODEAGENT3_PLUGIN_ROOT"):
            self.assertIn(said, done.stderr, said)

    def test_the_bridge_records_where_it_came_from(self):
        from mae_flow_core.adapters.project_launcher import bridge_source
        body = bridge_source("/plug/scripts/mae-flow.py", "/plug",
                             at="2026-08-10 18:00:00")
        self.assertIn("由 Mae-Flow 自动生成", body)
        self.assertIn("生成于 2026-08-10 18:00:00", body)
        self.assertIn("插件根 /plug", body)


if __name__ == "__main__":
    unittest.main()
