#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接受风险之后不能再被同一份缺失证据的衍生记账挡住。

内网实战(限流后新开 session 续跑):UT 真跑过了(28/28 BUILD SUCCESS),但宿主
取不到子会话记录,harness 连 6 次判"证据不足"。用户 accept-risk ut 放行了
第一道闸,done 却仍被第二道闸 ut_session_complete 拦下——而它要的
phase=="final" 恰恰靠"上一批 Agent 真实返回"来推进,也就是同一份取不到的证据。

于是形成死循环:派 agent → 无证据 → 批次不前进 → done 拒 → 再派 agent…
accept-risk 等于无效,用户只剩"整步跳过"——那会把本步其余所有检查一起扔掉,
是最坏的结局。这个洞的性质:**放行了一扇门,却没放行由它派生的记账**。
"""

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


class _Ports(object):
    """只提供这条证据要用到的事实;其余一律不实现,免得测到别的东西。"""

    def __init__(self, accepted):
        self.accepted = accepted

    def business_changed_files(self, _state):
        return ["service/src/A.java"], ""

    def risk_acceptance(self, kind, _state):
        return (True, "") if (self.accepted and kind == "UT") else (False, "")

    def agent_ran(self, _spec, _state):
        return False, "本步内没有可信的 UT Agent 执行证据"


def _evidence(accepted):
    from mae_flow_core.quality.evidence import QualityEvidenceRules
    return QualityEvidenceRules(_Ports(accepted))


class UtRiskDeadlockTests(unittest.TestCase):
    def test_accepted_risk_also_clears_the_batch_bookkeeping(self):
        """批次记账依赖的正是用户已接受风险的那份证据,不能再拦一次。"""
        state = {"current": "verify_ut",
                 "ut_session": {"step": "verify_ut", "phase": "generate"}}
        result = _evidence(True).ut_session_complete({}, state)
        self.assertTrue(result.passed, result.reason)

    def test_without_accepted_risk_the_batches_still_gate(self):
        """没接受风险时该拦照拦——放宽只针对"已明确接受风险"这一种处境。"""
        state = {"current": "verify_ut",
                 "ut_session": {"step": "verify_ut", "phase": "generate"}}
        result = _evidence(False).ut_session_complete({}, state)
        self.assertFalse(result.passed)
        self.assertIn("尚未全部完成", result.reason)

    def test_repeated_issuance_names_the_real_cause(self):
        """同一批签发多次仍不前进,要说出真相并指向 accept-risk,不是整步跳过。"""
        state = {"current": "verify_ut",
                 "ut_session": {"step": "verify_ut", "phase": "generate",
                                "issued": 4}}
        reason = _evidence(False).ut_session_complete({}, state).reason
        self.assertIn("已签发 4 次", reason)
        self.assertIn("accept-risk ut", reason)
        self.assertIn("不要再派下一轮", reason)
        self.assertIn("整步跳过会把本步其余检查一起扔掉", reason)

    def test_early_issuance_stays_quiet(self):
        """头两次不啰嗦:正常流程本来就要签发多批。"""
        state = {"current": "verify_ut",
                 "ut_session": {"step": "verify_ut", "phase": "generate",
                                "issued": 2}}
        reason = _evidence(False).ut_session_complete({}, state).reason
        self.assertNotIn("已签发", reason)

    def test_no_business_change_needs_no_ut_at_all(self):
        """没改业务代码就不该要 UT 证据——这条既有语义不能被上面的放宽影响。"""
        ports = _Ports(False)
        ports.business_changed_files = lambda _s: ([], "")
        evidence = _evidence(False)
        evidence.ports = ports
        self.assertTrue(evidence.ut_session_complete({}, {}).passed)


if __name__ == "__main__":
    unittest.main()
