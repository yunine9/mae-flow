"""云端宿主适配层样机演练——阶段 0 的入口(详设 §8)。

这是演练不是门禁:用参考 Pi 样机把整条链当场跑一遍——同步拦截、
打回、子 Agent 桥、人工节点挂起与决定回注、证据落盘——并用现有
契约函数验收产物。现场留档在输出目录,每个文件都能直接打开看。

真 Pi 客户端就位后,本命令是对拍入口:同一剧本换真实现,
行为必须与样机一致;不一致的差异就是阶段 0 要逐条裁决的清单。
"""

import os

from mae_flow_core.adapters.cloud.agent_bridge import AgentBridge
from mae_flow_core.adapters.cloud.gate_service import GateDecision, GateService
from mae_flow_core.adapters.cloud.human_gate import HumanGate
from mae_flow_core.adapters.cloud.pi_session import SessionDriver
from mae_flow_core.adapters.cloud.reference_runtime import ReferencePi
from mae_flow_core.adapters.cloud.semantic_events import EventLog
from mae_flow_core.adapters.cloud.transcript_store import TranscriptStore
from mae_flow_core.quality.tool_transcript import (
    bash_call,
    parse_transcript,
    select_contract_marker,
)


_QUESTION = {"questions": [{"question": "未提交 Diff 通过吗?",
                            "options": ["通过", "打回"]}]}

_MAIN_PLAN = {
    "on_message": [
        {"type": "assistant_text", "text": "先跑专项编译"},
        {"type": "tool_request", "call_id": "p1", "name": "Bash",
         "input": {"command": "mvn -B compile"}},
    ],
    "requests": {
        "p1": {"name": "Bash", "input": {"command": "mvn -B compile"}},
        "p2": {"name": "Bash", "input": {"command": "rm -rf build"}},
        "p3": {"name": "Task", "input": {}},
        "p4": {"name": "AskUserQuestion", "input": _QUESTION},
    },
    "auto_result": {"p1": {"is_error": False, "result": "BUILD SUCCESS"}},
    "after_answer": {
        "p1": [{"type": "tool_request", "call_id": "p2", "name": "Bash",
                "input": {"command": "rm -rf build"}}],
        "p2": [{"type": "tool_request", "call_id": "p3", "name": "Task",
                "input": {"subagent_type": "compile-agent",
                          "description": "专项编译验证",
                          "prompt": "按契约执行编译并报告"}}],
        "p3": [{"type": "tool_request", "call_id": "p4",
                "name": "AskUserQuestion", "input": _QUESTION}],
        "p4": [{"type": "assistant_text",
                "text": "COMPILE_RESULT: PASS 按决定继续交付"},
               {"type": "turn_end"}],
    },
}

_CHILD_PLAN = {
    "on_message": [
        {"type": "tool_request", "call_id": "pc1", "name": "Bash",
         "input": {"command": "mvn -B compile"}},
    ],
    "requests": {
        "pc1": {"name": "Bash", "input": {"command": "mvn -B compile"}}},
    "auto_result": {"pc1": {"is_error": False, "result": "BUILD SUCCESS"}},
    "after_answer": {"pc1": [
        {"type": "assistant_text", "text": "COMPILE_RESULT: PASS 编译通过"},
        {"type": "turn_end"},
    ]},
}


def _demo_contract(tool, value, event):
    """演练用契约:只拦这条演示危险命令,展示打回通道;不是生产门禁。"""
    if "rm -rf" in str(value or ""):
        return GateDecision("deny", "演练拦截:危险命令被打回,原样返回给 Agent")
    return None


def _fact(passed, text):
    print(("  ✅ " if passed else "  ❌ ") + text)
    return bool(passed)


def cmd_cloud_probe(args):
    out = os.path.abspath(
        getattr(args, "out", None)
        or os.path.join(".mae-flow-work", "cloud-probe"))
    os.makedirs(out, exist_ok=True)
    main_path = os.path.join(out, "transcript.jsonl")
    events_path = os.path.join(out, "events.jsonl")
    waiting_path = os.path.join(out, "waiting.json")
    for stale in (main_path, events_path, waiting_path):
        if os.path.exists(stale):
            os.remove(stale)

    runtime = ReferencePi([_MAIN_PLAN, _CHILD_PLAN])
    human_gate = HumanGate(waiting_path, project_root=out)
    driver = SessionDriver(
        runtime=runtime,
        task_id="PROBE-1",
        workspace=out,
        event_log=EventLog(events_path),
        transcript=TranscriptStore(main_path, ""),
        gate=GateService(contract=_demo_contract),
        human_gate=human_gate,
        agent_bridge=AgentBridge(),
        current_step=lambda: "build_review",
    )

    print("[cloud-probe] 参考 Pi 样机演练开始,现场目录: %s" % out)
    outcome = driver.start("交付 PROBE-1:完成需求并编译验证")
    ok = _fact(outcome.get("status") == "waiting_for_human",
               "人工节点挂起:任务暂停等待决定(而不是 Agent 替人选)")
    waiting = outcome.get("waiting") or {}
    resolved = human_gate.resolve(
        waiting.get("waiting_id", ""),
        state_version=waiting.get("state_version", 0),
        decision="通过", notes="演练自动决定;云端由 Web 审批页提交")
    outcome = driver.resume_with_decision(resolved)
    ok = _fact(outcome.get("status") == "turn_finished",
               "决定回注后本轮收口: %s" % outcome.get("status")) and ok

    denied = [answer for answer in runtime.answers
              if answer["call_id"] == "p2"]
    ok = _fact(denied and not denied[0]["allow"],
               "同步拦截:危险命令在执行前被打回(exit 2 的云端等价物)"
               ) and ok

    import json as _json
    with open(main_path, "r", encoding="utf-8") as handle:
        rows = [_json.loads(line) for line in handle if line.strip()]
    transcript = parse_transcript(rows)
    compile_call = bash_call(transcript.tool_calls, "mvn -B compile")
    ok = _fact(compile_call is not None and compile_call.result_seen,
               "编译证据经现有契约函数命中(格式一个字节没漂)") and ok
    marker = select_contract_marker(transcript.assistant_texts[-1])
    ok = _fact((marker.kind, marker.status) == ("COMPILE", "PASS"),
               "结果标记判定照旧: %s_RESULT %s"
               % (marker.kind or "?", marker.status or "?")) and ok
    task_calls = [call for call in transcript.tool_calls
                  if call.name == "Task"]
    ok = _fact(len(task_calls) == 1
               and "COMPILE_RESULT" in task_calls[0].result,
               "子 Agent 桥:Task 一次调用,子会话证据单独落盘") and ok

    print("[cloud-probe] 现场文件:")
    for name in ("transcript.jsonl", "events.jsonl", "waiting.json"):
        print("  - %s" % os.path.join(out, name))
    child = driver.transcript.child_path("S2")
    if child:
        print("  - %s" % child)
    if ok:
        print("[cloud-probe] 全部事实成立。真 Pi 客户端就位后,"
              "同一剧本换实现对拍即阶段 0 验收。")
        return 0
    print("[cloud-probe] ❌ 有事实不成立,先修样机链路再谈接真 Pi。")
    return 1
