#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""规格条目得能溯源到需求——弱模型最擅长的是"顺着想象把活干得很漂亮"。

无人值守实战:一次"新增短信渠道与失败重试"的交付,最终交了 25 个文件 +2076 行,
里面有 alert_service.py、metrics.py、feature_flag.py、validate-config.sh。
追下去,"告警"在需求原文出现 0 次,在 grill 出现 10 次、decisions 11 次、
spec 10 次、story 13 次——范围是在需求澄清那一步凭空长出来的,之后每一层都
忠实地把它带下去,连测试和领域归档都补齐了。

流程一直在检查"验收项都实现了吗",从没检查反方向:**这条验收项是从哪来的**。
"""

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


class ScopeDriftTests(unittest.TestCase):
    def test_catches_a_subsystem_invented_out_of_thin_air(self):
        from mae_flow_core.workflow.scope_drift import invented_topics
        requirement = (
            "# REQ 通知服务新增短信渠道与失败重试\n"
            "通知服务目前支持 email/push/webhook。新增短信渠道,"
            "并对发送失败做重试。按租户控制短信是否开通。\n")
        spec = (
            "1. 新增短信渠道,复用既有四段结构\n"
            "2. 失败重试:最多 3 次\n"
            "3. 监控与告警:失败率告警(>5% 触发告警,邮件+钉钉)\n"
            "4. 灰度发布:灰度开关控制,支持灰度回滚\n"
            "5. 回滚策略:一键回滚到上一版本,回滚后告警\n")
        found = dict(invented_topics(requirement, spec, floor=2))
        self.assertIn("告警", found, "凭空发明的告警子系统必须被报出来")
        self.assertIn("灰度", found)
        self.assertIn("回滚", found)
        # 需求里说过的不报
        for said in ("短信", "重试", "租户"):
            self.assertNotIn(said, found, "需求里说过的不该报: %s" % said)

    def test_longest_run_does_not_swallow_the_real_term(self):
        """"失败率告警"取最长会把"告警"吞掉——实战里差点因此漏报。"""
        from mae_flow_core.workflow.scope_drift import invented_topics
        found = dict(invented_topics(
            "新增短信渠道", "失败率告警\n失败率告警\n监控与告警\n", floor=3))
        self.assertIn("告警", found)

    def test_stays_quiet_when_spec_tracks_the_requirement(self):
        from mae_flow_core.workflow.scope_drift import (
            drift_notice, invented_topics)
        requirement = "新增短信渠道,失败重试三次,按租户开通。\n"
        spec = ("1. 新增短信渠道\n2. 失败重试三次\n3. 按租户开通短信\n") * 3
        self.assertEqual([], invented_topics(requirement, spec))
        self.assertEqual("", drift_notice([]))

    def test_only_speaks_up_at_spec_confirmation(self):
        from mae_flow_core.panel.snapshot import ACK_REVIEW_DOCS
        spec_steps = [sid for sid, kinds in ACK_REVIEW_DOCS.items()
                      if "spec" in kinds]
        self.assertTrue(spec_steps, "总得有确认规格的步骤")
        self.assertNotIn("build", spec_steps)


if __name__ == "__main__":
    unittest.main()
