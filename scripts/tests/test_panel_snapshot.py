#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读快照契约——本文件是"面板不会伤到流程"的那道锁。

三条底线各有一条断言:
只读(调用前后状态字节不变)、软失败(缺 git/缺状态都要给得出快照)、
不知道就写 null(进度百分比在有分支和回退的图上必然是编的)。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.abspath(os.path.dirname(__file__))
SCRIPTS = os.path.abspath(os.path.join(TESTS, ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from mae_flow_core.panel import snapshot  # noqa: E402

FLOW = {
    "start": "config_confirm",
    "steps": {
        "config_confirm": {"title": "配置确认", "user_ack": True,
                           "require_sets": ["单号", "分支名"],
                           "next": "workflow_select"},
        "workflow_select": {"title": "交付方式选择", "user_ack": True,
                            "choice_key": "workflow",
                            "choice_answers": {"full": ["完整开发"],
                                               "hotfix": ["已定位问题修复"]},
                            "next": "story"},
        "story": {"title": "Story 与实施附录生成及一次设计检视",
                  "user_ack": True, "next": "build"},
        "build": {"title": "编码", "next": "verify"},
        "verify": {"title": "验证", "terminal": True},
    },
}

STATE = {
    "current": "build",
    "revision": 27,
    "started": "2026-08-07 23:24:20",
    "config": {"单号": "REQ2026080901", "分支名": "dev_REQ", "基线分支": "master"},
    "choices": {"workflow": "full"},
    "history": [{"step": "config_confirm", "result": "done"},
                {"step": "workflow_select", "result": "done"}],
    "agent_tasks": {"COMPILE": {"at": "2026-08-08 16:35:28",
                                "head": "f63972b6", "task_files": ["a.py"],
                                "path": "/tmp/build-compile.md"}},
    "quality": {"codecheck_scan": {"status": "TOOL_ERROR", "count": None,
                                   "at": "2026-08-08 16:45:05",
                                   "files": ["a.py", "b.py"],
                                   "error": "CodeCheck CLI 当前不可用"}},
    "quality_attempts": {"ponytail": {"count": 1}},
    "ut_session": {"phase": "generate", "complete": False,
                   "batches": [[], [], []], "completed_batches": []},
}


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="panel-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        subprocess.run(["git", "-C", self.root, "init", "-q"], check=True)
        self.state_path = os.path.join(self.root, ".mae-flow.json")
        with open(self.state_path, "w", encoding="utf-8") as stream:
            json.dump(STATE, stream, ensure_ascii=False)

    def _docs(self):
        folder = os.path.join(self.root, ".mae-flow-work", "REQ2026080901")
        os.makedirs(folder, exist_ok=True)
        for name in ("story.md", "spec.md"):
            with open(os.path.join(folder, name), "w",
                      encoding="utf-8") as stream:
                stream.write("# %s\n" % name)

    def test_snapshot_never_touches_the_state_file(self):
        """只读锁:面板读现场,不能改现场。这条红了就是真事故。"""
        before = os.stat(self.state_path)
        with open(self.state_path, "rb") as stream:
            body = stream.read()
        snapshot.build(self.root, STATE, FLOW)
        snapshot.changes(self.root, "")
        after = os.stat(self.state_path)
        with open(self.state_path, "rb") as stream:
            self.assertEqual(body, stream.read())
        self.assertEqual(before.st_mtime, after.st_mtime)
        self.assertEqual(27, snapshot.build(
            self.root, STATE, FLOW)["state_revision"])

    def test_missing_state_still_produces_a_usable_snapshot(self):
        data = snapshot.build(self.root, None, FLOW)
        self.assertEqual(snapshot.SCHEMA, data["schema"])
        self.assertEqual([], data["pending"])
        self.assertTrue(any("没有 .mae-flow.json" in text
                            for text in data["warnings"]))

    def test_outside_a_git_repository_it_warns_instead_of_failing(self):
        plain = os.path.realpath(tempfile.mkdtemp(prefix="panel-nogit-"))
        self.addCleanup(shutil.rmtree, plain, True)
        data = snapshot.build(plain, STATE, FLOW)
        self.assertEqual("", data["repo"]["branch"])
        self.assertTrue(any("git" in text for text in data["warnings"]))
        self.assertEqual([], snapshot.changes(plain, ""))

    def test_percent_stays_null_and_estimate_is_derived_from_the_graph(self):
        progress = snapshot.build(self.root, STATE, FLOW)["progress"]
        self.assertIsNone(progress["percent"])
        self.assertEqual(["config_confirm", "workflow_select"],
                         progress["steps_done"])
        self.assertEqual(4, progress["steps_total_estimate"])
        self.assertEqual("编码", progress["step_title"])

    def test_progress_projects_history_for_the_read_only_timeline(self):
        """页面执行记录只消费快照，不回头读取或猜测状态历史。"""
        state = json.loads(json.dumps(STATE))
        state["history"] = [
            {"step": "config_confirm", "result": "done",
             "at": "2026-08-08 14:10:00"},
            {"step": "workflow_select", "result": "choice:full",
             "at": "2026-08-08 14:15:00"},
            "broken-row",
        ]
        history = snapshot.build(self.root, state, FLOW)["progress"]["history"]
        self.assertEqual([
            {"step": "config_confirm", "title": "配置确认",
             "result": "done", "at": "2026-08-08 14:10:00"},
            {"step": "workflow_select", "title": "交付方式选择",
             "result": "choice:full", "at": "2026-08-08 14:15:00"},
        ], history)

    def test_progress_history_projection_is_bounded(self):
        """长需求不能让 panel --json 随历史无限膨胀。"""
        state = json.loads(json.dumps(STATE))
        state["history"] = [
            {"step": "config_confirm", "result": "done-%d" % index,
             "at": "2026-08-08 14:%02d:00" % (index % 60)}
            for index in range(75)
        ]
        history = snapshot.build(self.root, state, FLOW)["progress"]["history"]
        self.assertEqual(50, len(history))
        self.assertEqual("done-25", history[0]["result"])
        self.assertEqual("done-74", history[-1]["result"])

    def test_pending_lists_confirmations_and_choices_only(self):
        ack = dict(STATE, current="config_confirm")
        item = snapshot.build(self.root, ack, FLOW)["pending"][0]
        self.assertEqual("config_review", item["kind"])
        self.assertEqual(
            [("单号", "REQ2026080901"), ("分支名", "dev_REQ")],
            [(entry["label"], entry["value"]) for entry in item["items"]])

        choose = dict(STATE, current="workflow_select")
        picked = snapshot.build(self.root, choose, FLOW)["pending"][0]
        self.assertEqual("choice", picked["kind"])
        self.assertEqual("choice", picked["needs"])

        # 纯机器证据步骤不该出现在"待你裁决"里
        self.assertEqual([], snapshot.build(self.root, STATE, FLOW)["pending"])

    def test_story_confirmation_lists_the_story_not_the_config(self):
        """卡片说"确认 Story",内容就必须真是 Story——倒整张项目配置进去,
        是视觉在提醒、信息在撒谎(实战反馈)。"""
        self._docs()
        data = snapshot.build(self.root, dict(STATE, current="story"), FLOW)
        item = data["pending"][0]
        self.assertEqual("doc_review", item["kind"])
        self.assertEqual([], item["items"])          # 不再倒配置
        names = sorted(os.path.basename(path) for path in item["paths"])
        self.assertEqual(["story.md"], names)        # implementation.md 不存在则不列
        self.assertTrue(all(os.path.isabs(path) for path in item["paths"]))

    def test_degraded_tool_is_distinguishable_from_passing(self):
        """"工具没跑起来"和"跑了且干净"混成一个绿灯,是这套系统最不能容忍的谎。"""
        check = snapshot.build(self.root, STATE, FLOW)["evidence"]["codecheck"]
        self.assertTrue(check["degraded"])
        self.assertEqual("TOOL_ERROR", check["status"])
        self.assertIsNone(check["count"])

    def test_documents_report_absolute_paths_and_sizes(self):
        self._docs()
        docs = snapshot.build(self.root, STATE, FLOW)["artifacts"]["documents"]
        self.assertEqual(["spec", "story"], sorted(doc["kind"] for doc in docs))
        for doc in docs:
            self.assertTrue(os.path.isabs(doc["path"]), doc)
            self.assertGreater(doc["bytes"], 0)

    def test_snapshot_carries_no_file_contents(self):
        """只给路径与统计:载荷恒小,出口也不会变成源码外泄通道。"""
        self._docs()
        body = json.dumps(snapshot.build(self.root, STATE, FLOW),
                          ensure_ascii=False)
        self.assertNotIn("# story.md", body)
        self.assertLess(len(body.encode("utf-8")), 64 * 1024)

    def test_advisories_are_scoped_to_the_current_step(self):
        with open(os.path.join(self.root, ".mae-flow.json.advisories"), "w",
                  encoding="utf-8") as stream:
            json.dump({"advisories": [
                {"step": "build", "kind": "lightcheck", "message": "本轮"},
                {"step": "verify", "kind": "lightcheck", "message": "别轮"}]},
                stream, ensure_ascii=False)
        notices = snapshot.build(self.root, STATE, FLOW)["advisories"]
        self.assertEqual(["本轮"], [item["message"] for item in notices])


if __name__ == "__main__":
    unittest.main()
