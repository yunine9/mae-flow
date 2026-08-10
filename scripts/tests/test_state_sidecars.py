#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""退出与开新单必须把旁路状态收干净——漏一个就是给新流程留旧证据。

用户实战反馈:手动退出流程后再单独让补个 UT,结果又被拽回上一单的流程里。
查下去发现 `exit` 和"开新单前清理"用的是同一份白名单,而这份名单漏了三个
本该在内的文件:

- `.mae-flow.json.quality-executions` —— 编译/UT 的执行台账
- `.mae-flow.json.agent-observations` —— Agent 派发与返回的生命周期证据
- `.mae-flow.json.advisories` —— 上一单的非阻断提示

前两个是**证据来源**。退出不删、开新单不清,新一单就可能拿上一单的执行
记录充数;第三个会让早已处理完的旧提示重新冒出来。

所以名单的完整性不能靠人记:凡是代码里会写出的 `.mae-flow.json.*`,
都必须出现在白名单里。
"""

import io
import os
import re
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

# 这几个不属于"流程旁路状态",不该被退出清理波及:
# .exited 是退出记录本身(删了就不知道退过);.last 是上一单的留档,
# 独立任务专门靠它继承运行方式(编译命令/UT 命令),清掉反而要重问用户。
NOT_SIDECARS = {".exited", ".last"}

WRITTEN = re.compile(
    r'(?:STATE_PATH|state_path\)?)\s*\+\s*"(\.[a-z][a-z0-9-]*)"'
    r'|"\.mae-flow\.json(\.[a-z][a-z0-9-]*)"')


def _suffixes_written_by_code():
    found = set()
    for here, _dirs, names in os.walk(os.path.join(SCRIPTS, "mae_flow_core")):
        for name in sorted(names):
            if not name.endswith(".py"):
                continue
            with io.open(os.path.join(here, name), encoding="utf-8") as stream:
                for direct, quoted in WRITTEN.findall(stream.read()):
                    found.add(direct or quoted)
    return {item for item in found if item not in NOT_SIDECARS}


class SidecarCoverageTests(unittest.TestCase):
    def test_whitelist_covers_every_sidecar_the_code_writes(self):
        from mae_flow_core.cli_commands.shared import STATE_PATH
        from mae_flow_core.cli_commands.standalone_core import _state_sidecars
        listed = {
            path[len(STATE_PATH):]
            for path in _state_sidecars()
            if path.startswith(STATE_PATH) and path != STATE_PATH
        }
        missing = sorted(_suffixes_written_by_code() - listed)
        self.assertEqual(
            [], missing,
            "这些旁路状态代码会写,但退出/开新单不会收走——旧证据会留给新流程: %s"
            % missing)

    def test_the_three_that_bit_us_are_on_the_list(self):
        from mae_flow_core.cli_commands.standalone_core import _state_sidecars
        listed = set(_state_sidecars())
        for suffix in (".quality-executions", ".agent-observations",
                       ".advisories"):
            self.assertIn(".mae-flow.json" + suffix, listed)

    def test_exit_record_and_last_round_are_deliberately_kept(self):
        """.exited 是退出记录本身,.last 是独立任务继承运行方式的来源。"""
        from mae_flow_core.cli_commands.standalone_core import _state_sidecars
        listed = set(_state_sidecars())
        self.assertNotIn(".mae-flow.json.exited", listed)
        self.assertNotIn(".mae-flow.json.last", listed)


if __name__ == "__main__":
    unittest.main()
