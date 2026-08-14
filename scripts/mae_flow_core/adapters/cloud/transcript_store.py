"""语义事件 → transcript 同形 JSONL(详设 §3/D2)。

不让契约学新格式,让云端把事件流写成契约已认识的格式:
产物必须能直接过 quality/tool_transcript.parse_transcript 与四个契约。

子 Agent 各写各的 transcript,布局对齐 hook_transcript_paths 的确定性
绑定规则: <主transcript去扩展名>/subagents/agent-<call_id>.jsonl
——call_id 即派发时的 tool_use_id,契约到子 transcript 查证据的路径不变。
"""

import json
import os


def _user_row(blocks):
    return {"type": "user", "message": {"role": "user", "content": blocks}}


def _assistant_row(blocks):
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": blocks},
    }


class TranscriptStore:
    """按会话落 transcript;主会话之外的 session 必须先 bind_child。

    未绑定的子会话事件直接抛错而不是悄悄写进主 transcript:
    证据落错文件比缺证据更毒——契约会在主 transcript 里"查到"
    不属于本步的调用。
    """

    def __init__(self, main_path, main_session_id):
        self.main_path = main_path
        self.main_session_id = main_session_id
        self._children = {}

    def bind_child(self, child_session_id, call_id):
        """child_session_id ↔ 派发 call_id(tool_use_id)的确定性绑定。"""
        safe = os.path.basename(str(call_id or ""))
        if not safe or safe != str(call_id or ""):
            raise ValueError("子会话绑定需要一个可作文件名的 call_id")
        directory = os.path.join(
            os.path.splitext(self.main_path)[0], "subagents")
        self._children[child_session_id] = os.path.join(
            directory, "agent-%s.jsonl" % safe)

    def child_path(self, child_session_id):
        return self._children.get(child_session_id, "")

    def _path_for(self, session_id):
        if session_id == self.main_session_id:
            return self.main_path
        path = self._children.get(session_id)
        if not path:
            raise ValueError(
                "未绑定的会话 %s——子会话必须先 bind_child" % session_id)
        return path

    def _append(self, path, row):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()

    def record(self, event):
        """消费一条语义事件;与 transcript 无关的种类是 no-op。"""
        payload = event.payload
        if event.kind == "user_message":
            self._append(self._path_for(event.session_id), _user_row(
                [{"type": "text", "text": payload["text"]}]))
        elif event.kind == "assistant_message":
            self._append(self._path_for(event.session_id), _assistant_row(
                [{"type": "text", "text": payload["text"]}]))
        elif event.kind == "tool_requested":
            self._append(self._path_for(event.session_id), _assistant_row([{
                "type": "tool_use",
                "id": payload["call_id"],
                "name": payload["name"],
                "input": payload["input"],
            }]))
        elif event.kind == "tool_finished":
            # result 必须是宿主真实回传(含退出码文本),call_failed 靠它嗅探
            # 失败——上游禁止用 Agent 复述顶替。
            self._append(self._path_for(event.session_id), _user_row([{
                "type": "tool_result",
                "tool_use_id": payload["call_id"],
                "is_error": bool(payload["is_error"]),
                "content": payload["result"],
            }]))
        elif event.kind == "agent_spawned":
            # 主 transcript 视角:一次 Task 工具调用(agent_kind 靠
            # subagent_type/description/prompt 推断,字段名不能换)。
            self.bind_child(payload["child_session_id"], payload["call_id"])
            self._append(self.main_path, _assistant_row([{
                "type": "tool_use",
                "id": payload["call_id"],
                "name": "Task",
                "input": {
                    "subagent_type": payload["agent_type"],
                    "description": payload["description"],
                    "prompt": payload["prompt"],
                },
            }]))
        elif event.kind == "agent_finished":
            # XXX_RESULT 标记判定作用在 final_text 上,不得截断首行。
            self._append(self.main_path, _user_row([{
                "type": "tool_result",
                "tool_use_id": payload["call_id"],
                "is_error": payload["lifecycle"] != "returned",
                "content": payload["final_text"],
            }]))
