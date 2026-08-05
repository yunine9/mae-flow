"""CLI responsibilities extracted from the historical entrypoint."""

from .shared import (
    CONFIG_CONFIRM_ACK, FAILURE_PATH, STATE_PATH, hashlib, json, re, read_text, time,
    update_json, workflow_completion,
)
from .wiring import api

def _evidence_failure_count(sid, success=False):
    """按步骤统计 done 证据连拒次数;成功推进即清零。与 _ack_failure 同一存储。"""
    key = "evidence:" + (sid or "")
    result = [0]

    def mutate(data):
        if not isinstance(data, dict):
            data = {}
        if success:
            data.pop(key, None)
            return data
        result[0] = int((data.get(key, {}) or {}).get("count", 0)) + 1
        data[key] = {"count": result[0],
                     "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        return data

    try:
        update_json(FAILURE_PATH, mutate, default={}, recover_corrupt=True)
    except Exception:
        return 1 if not success else 0
    return result[0]

def _ack_failure(st, reason="", success=False):
    """记录确认通道失败；只停止盲目重试，不制造不可恢复的锁。"""
    sid = (st or {}).get("current", "")
    key = "ack:" + sid
    result = [0]

    def mutate(data):
        if not isinstance(data, dict):
            data = {}
        if success:
            data.pop(key, None)
            return data
        previous = data.get(key, {})
        result[0] = int(previous.get("count", 0)) + 1
        data[key] = {
            "count": result[0],
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason[:1000],
        }
        return data

    update_json(
        FAILURE_PATH, mutate, default={}, recover_corrupt=True)
    return result[0]

def _ack_candidates(text):
    """Extract exact user answers without treating prompt/options metadata as consent."""
    out = [text or ""]
    try:
        value = json.loads(text)
        answer_keys = {
            "answer", "answers", "response", "responses", "selected",
            "selection", "selectedoption", "selectedoptions", "result",
        }

        def walk(v, trusted=False):
            if isinstance(v, str) and trusted:
                out.append(v)
            elif isinstance(v, dict):
                for key, item in v.items():
                    normalized_key = re.sub(r"[^a-z]", "", str(key).lower())
                    walk(item, trusted or normalized_key in answer_keys)
            elif isinstance(v, list):
                for item in v:
                    walk(item, trusted)

        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            walk(value, trusted=True)
        else:
            walk(value)
    except Exception:
        pass
    return [re.sub(r"\s+", "", v) for v in out if re.sub(r"\s+", "", v)]

def _trusted_answer_candidates(text):
    """Return actual answer values, excluding question/option metadata."""
    return [
        re.sub(r"\s+", "", value)
        for value in _trusted_answer_values(text)
        if re.sub(r"\s+", "", value)
    ]


def _trusted_answer_values(text):
    """Return answer values with their original wording and whitespace."""
    try:
        parsed = json.loads(text)
    except Exception:
        return [(text or "").strip()] if (text or "").strip() else []
    if isinstance(parsed, str):
        return [parsed.strip()] if parsed.strip() else []
    out = []
    answer_keys = {
        "answer", "answers", "response", "responses", "selected",
        "selection", "selectedoption", "selectedoptions", "result",
    }

    def walk(value, trusted=False):
        if isinstance(value, str) and trusted and value.strip():
            out.append(value.strip())
        elif isinstance(value, dict):
            for key, item in value.items():
                normalized = re.sub(
                    r"[^a-z]", "", str(key).lower())
                walk(item, trusted or normalized in answer_keys)
        elif isinstance(value, list):
            for item in value:
                walk(item, trusted)

    if isinstance(parsed, list):
        walk(parsed, trusted=True)
    else:
        walk(parsed)
    return out

def _all_ack_messages():
    try:
        msgs = json.loads(read_text(STATE_PATH + ".usermsg") or "[]")
    except Exception:
        return []
    return msgs if isinstance(msgs, list) else []

def _ack_message_signature(item):
    payload = json.dumps({
        "id": item.get("id", ""),
        "step": item.get("step", ""),
        "at": item.get("at", ""),
        "text": item.get("text", ""),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def _ack_message_cursor():
    return [_ack_message_signature(item) for item in _all_ack_messages()]

def _current_ack_messages(st, extra_steps=()):
    msgs = _all_ack_messages()
    sid = st.get("current", "")
    entered = api._step_entered_at(st)
    started = st.get("started", "")
    out = []
    for item in msgs:
        if (item.get("at", "") >= entered
                and (not item.get("step") or item.get("step") == sid)):
            out.append(item)
        elif (extra_steps and item.get("step") in extra_steps
              and item.get("at", "") >= started):
            # 一卡合一预答通道:配置确认卡合并收集的选择(交付方式/质询/STORY),
            # 供随后的选择步直接消费,免逐步重复提问;仍是本单内真实捕获的用户答案。
            out.append(item)
    return out


def _authorization_message(st, message_id):
    """Resolve one current-step user message without shell text transport."""
    wanted = str(message_id or "").strip()
    if not wanted:
        return False, "", {}, (
            "缺少 --message-id。先执行 messages，使用当前步骤用户授权消息左侧的 ID；"
            "不要把用户原话复制进 shell。")
    current = [
        item for item in _current_ack_messages(st)
        if str(item.get("id", "") or "") == wanted
    ]
    if not current:
        old = [
            item for item in _all_ack_messages()
            if str(item.get("id", "") or "") == wanted
        ]
        if old:
            return False, "", {}, (
                "消息 ID %s 属于步骤 %s，当前是 %s；"
                "高风险授权不能跨步骤复用。"
                % (wanted, old[-1].get("step", "(未标步骤)"),
                   st.get("current", "")))
        return False, "", {}, (
            "当前步骤不存在消息 ID %s。先执行 messages 查看可用 ID；"
            "不要自行构造或复用旧 ID。" % wanted)
    row = current[-1]
    values = _trusted_answer_values(str(row.get("text", "") or ""))
    if not values:
        return False, "", {}, (
            "消息 ID %s 的结构中没有可信回答字段。执行 messages --id %s --full "
            "核对宿主回传；不得用问题或候选项文本冒充用户回答。"
            % (wanted, wanted))
    answer = "\n".join(dict.fromkeys(values))
    receipt = {
        "message_id": wanted,
        "answer_sha256": hashlib.sha256(
            answer.encode("utf-8")).hexdigest(),
        "captured_at": str(row.get("at", "") or ""),
        "step": str(row.get("step", "") or st.get("current", "")),
    }
    _ack_failure(st, success=True)
    return True, answer, receipt, ""

def _out_of_scope_ack_reason(st):
    """Explain captured-but-stale answers without blaming the Hook."""
    rows = _all_ack_messages()
    if not rows:
        return ""
    sid = st.get("current", "")
    entered = api._step_entered_at(st)
    latest = rows[-1]
    old_step = str(latest.get("step", "") or "(未标步骤)")
    old_at = str(latest.get("at", "") or "?")
    if old_step != sid:
        return (
            "Hook 已捕获用户回复，但最新一条绑定在步骤 %s；当前已是 %s。"
            "步骤切换后旧回答按设计失效，不能再次授权新的 done/goto；"
            "请展示当前步骤需要的决定并取得一次新回复（旧回复时间 %s）。"
            % (old_step, sid, old_at)
        )
    if old_at < entered:
        return (
            "Hook 已捕获用户回复，但它早于当前步骤这一轮的进入时间 %s；"
            "旧轮回答按设计失效，不能为重进后的新一轮背书。"
            "请展示当前步骤需要的决定并取得一次新回复。"
            % entered
        )
    return (
        "Hook 已捕获用户回复，但其结构中没有当前命令可验真的答案字段。"
        "先执行 messages --full 查看原始回传；若按钮正文确实缺失，"
        "让用户发送当前页面要求的普通确认消息。"
    )

def _fresh_askuser(st):
    ok, _ = api.ev_agent_ran({"agent": "ASKUSER"}, st)
    return ok

def _is_positive_confirmation(value):
    compact = re.sub(r"[\s，。；;：:、!！]+", "", value or "")
    compact = re.sub(r"[（(]推荐[）)]", "", compact)
    if not compact or re.search(
            r"不确认|不同意|不是|不要|不能|没有|没法|拒绝|暂不|取消|"
            r"需要修改|需要调整|先别|等等|不对|有误|有问题|但是|不过|"
            r"什么意思|怎么|是否|能否|为什么|[?？]",
            compact, re.I):
        return False
    return (
        compact.lower() in {
            "确认", "确认并继续", "确认范围并继续", "确认定稿",
            "同意", "可以", "没问题", "继续", "按此执行", "以上正确",
            "无异议", "yes", "y", "ok",
        }
        or bool(re.match(
            r"^(?:确认|同意|可以|没问题|继续|按此|无异议)", compact, re.I))
    )

def _button_confirmation_alias(item, candidate, expected):
    """Accept a topical positive alias only when it was a displayed button."""
    normalized = re.sub(
        r"[\s，。；;：:、!！]+", "", str(candidate or "")).lower()
    labels = {
        re.sub(r"[\s，。；;：:、!！]+", "", str(label or "")).lower()
        for question in ((item.get("askuser") or {}).get("questions") or [])
        for label in (question.get("options") or [])
    }
    if normalized not in labels or not _is_positive_confirmation(candidate):
        return False
    subject = re.sub(r"(?:并)?继续$", "", re.sub(r"^(?:确认|同意)", "", normalized))
    return len(subject) >= 2 and any(subject in value for value in expected)

def _implicit_ack_verified(step, st):
    """Use a fresh button/plain-text answer directly; no second typed ACK."""
    expected = {
        re.sub(r"[\s，。；;：:、!！]+", "", str(value)).lower()
        for value in step.get("confirmation_answers", [])
        if str(value).strip()
    }
    rows = _current_ack_messages(st)
    for item in reversed(rows):
        for candidate in reversed(_trusted_answer_candidates(item.get("text", ""))):
            normalized = re.sub(r"[\s，。；;：:、!！]+", "", candidate)
            normalized = re.sub(
                r"[（(]推荐[）)]", "", normalized).lower()
            if expected and normalized in expected:
                _ack_failure(st, success=True)
                return True, ""
            if expected and _button_confirmation_alias(
                    item, candidate, expected):
                _ack_failure(st, success=True)
                return True, ""
            if _is_positive_confirmation(candidate):
                if expected:
                    continue
                _ack_failure(st, success=True)
                return True, ""
    wanted = " / ".join(step.get("confirmation_answers", []))
    actual = " / ".join(dict.fromkeys(value for item in rows for value in
        _trusted_answer_values(item.get("text", ""))))
    why = (_out_of_scope_ack_reason(st) if not rows else "") or (
        ("已捕获当前步骤答案「%s」，但未匹配标准确认按钮「%s」。"
         "不要猜 --choice 或重复询问；按 current 输出原样展示标准按钮。"
         % (actual or "无", wanted or "肯定")) if rows else
        ("尚未捕获到本步骤的%s选择。正常情况下直接使用 AskUserQuestion 让用户点选即可，"
         "done 会自动读取结果；只有宿主确实没有回传按钮结果时，才让用户发送一次标准选项。"
         % (("「" + wanted + "」") if wanted else "肯定")))
    count = _ack_failure(st, why)
    return False, why + _ack_retry_guidance(count)

def _choice_verified(step, st, choice, ack_cursor=None):
    """Bind --choice to the concrete answer returned by Claude Code/CodeAgent."""
    # 一卡合一:开场三个选择步同时接受配置确认卡期间捕获的真实答案。
    extra = (("config_confirm",)
             if st.get("current") in (
                 "workflow_select", "grill_ask", "story_ask")
             else ())
    alias_rows = []
    for key, values in (step.get("choice_answers") or {}).items():
        for value in [key] + list(values or []):
            normalized = re.sub(r"[\s，。；;：:、!！]+", "", str(value))
            normalized = re.sub(r"[（(]推荐[）)]", "", normalized)
            if normalized:
                alias_rows.append((key, normalized.lower()))

    rows = _current_ack_messages(st, extra_steps=extra)
    if ack_cursor is not None:
        cursor = set(ack_cursor or [])
        rows = [item for item in rows
                if _ack_message_signature(item) not in cursor]
    readable = []
    for item in rows:
        readable.extend(
            (item, candidate)
            for candidate in _trusted_answer_candidates(
                item.get("text", "")))
    for item, candidate in reversed(readable):
        normalized = re.sub(r"[\s，。；;：:、!！]+", "", candidate)
        normalized = re.sub(r"[（(]推荐[）)]", "", normalized).lower()
        # 全等,或"标签开头+补充说明"(按钮文案常带括号注释)。禁止全文子串搜索:
        # 「这次不是 hotfix,走完整开发」会命中 hotfix、消息里出现 docs/review/ 路径
        # 会命中 review——把用户的合法回答误判成 Agent 替用户改选。
        # 纯 ASCII 代号(full/hotfix/tweak/review)只认全等,防叙述句里的英文词误触。
        matches = [
            (key, alias) for key, alias in alias_rows
            if normalized == alias
            or (not re.fullmatch(r"[a-z0-9_-]+", alias)
                and normalized.startswith(alias))
        ]
        if not matches:
            selected = (
                workflow_completion.receipt_choice(
                    step, item, candidate)
                or workflow_completion.natural_binary_choice(
                    step, candidate, _is_positive_confirmation)
            )
        else:
            longest = max(len(alias) for _, alias in matches)
            keys = {key for key, alias in matches if len(alias) == longest}
            selected = next(iter(keys)) if len(keys) == 1 else ""
        if selected:
            if selected == choice:
                _ack_failure(st, success=True)
                return True, ""
            return False, (
                "用户点选的是「%s」，但 Agent 准备提交 --choice %s。"
                "请按按钮真实结果执行，禁止替用户改选。" % (candidate, choice)
            )

    scope_why = _out_of_scope_ack_reason(st) if not rows else ""
    if scope_why:
        return False, scope_why
    return False, (
        "没有检测到本步骤的真实选项回答。请用 AskUserQuestion 展示固定选项；"
        "用户点选后直接执行 done --choice %s，不需要再输入确认句。" % choice
    )

def _ack_retry_guidance(count):
    if count < 2:
        return ""
    return (
        " 同一确认自动校验已连续失败 %d 次，现停止重复执行同一条命令。"
        "流程没有锁死，也不需要 exit/init：先运行 messages 查看实际捕获答案；"
        "若结构化选择未回传，让用户发送一条当前页面要求的普通确认消息，再原样提交。"
    ) % count

def _ack_verified(st, ack, exact=True):
    """ack 必须来自当前步骤之后的真实用户输入；旧步骤的“可以”不能循环使用。

    如果宿主拿不到 AskUserQuestion 的应答正文，用户再发一条普通消息即可恢复；不允许静默降级为
    “模型自己写一句 --ack 也算用户确认”。
    """
    msgs = _current_ack_messages(st)
    if not msgs:
        why = _out_of_scope_ack_reason(st) or (
            "harness 尚未记录到任何用户回复。先执行 doctor 检查 UserPromptSubmit 输入，"
            "不要重复执行相同 done，也无需退出重开。")
        count = _ack_failure(st, why)
        return False, why + _ack_retry_guidance(count)

    def nt(s):
        return re.sub(r"\s+", "", s or "")

    na = nt(ack)
    actual = [v for m in msgs for v in _ack_candidates(m.get("text", ""))]
    matched = any((na == v if exact else na in v) for v in actual) if na else False
    if matched:
        _ack_failure(st, success=True)
        return True, ""
    why = ("--ack 与当前步骤开始后的用户真实输入不匹配。"
           "ack 必须是用户回复/选项的原文复制；先执行 messages 核对实际捕获答案，"
           "不要再次执行相同命令。")
    count = _ack_failure(st, why)
    return False, why + _ack_retry_guidance(count)

def _requirement_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _config_sha256(config, requirement_sha=""):
    payload = json.dumps(
        {"config": config or {}, "requirement_sha256": requirement_sha},
        ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def _is_full_config_confirmation(value):
    compact = re.sub(r"[\s，。；;：:、!！]+", "", value or "")
    if not compact or re.search(
            r"不确认|不是|不要|不能|没有|没法|否认|拒绝|暂不|修改|调整|"
            r"不对|有误|有问题|什么意思|怎么|是否|能否|为什么|[?？]",
            compact):
        return False
    return (
        compact in (
            re.sub(r"\s+", "", CONFIG_CONFIRM_ACK),
            "全部正确",
            "以上配置全部正确",
            "所有配置都正确",
        )
        or bool(re.search(r"确认(?:以上|全部|所有).{0,4}配置", compact))
    )

def _config_ack_verified(st, ack, config_sha, review_id):
    """Verify one final confirmation bound to the exact reviewed config."""
    current_rows = _current_ack_messages(st)
    messages = [
        item for item in current_rows
        if item.get("config_review_sha256") == config_sha
        and item.get("config_review_id") == review_id
    ]
    normalized_ack = re.sub(r"\s+", "", ack or "")
    matched = False
    for item in messages:
        for candidate in _trusted_answer_candidates(item.get("text", "")):
            same_answer = (
                normalized_ack == candidate if normalized_ack else True)
            if same_answer and _is_full_config_confirmation(candidate):
                matched = True
                break
        if matched:
            break
    if matched:
        _ack_failure(st, success=True)
        return True, ""

    if normalized_ack and not _is_full_config_confirmation(normalized_ack):
        why = (
            "配置确认必须针对完整配置，不能用“确认 master”等单项回答给整份配置背书。"
            "请展示 config-review 输出后，只询问一次“是否确认以上全部配置”。"
        )
    elif not messages and not current_rows and _out_of_scope_ack_reason(st):
        why = _out_of_scope_ack_reason(st)
    elif not messages:
        why = (
            "没有捕获到与当前配置确认单绑定的用户回复。AskUserQuestion 的应答可能未被宿主回传；"
            "无需退出或重新初始化，让用户发送一条普通消息“%s”即可恢复。"
            % CONFIG_CONFIRM_ACK
        )
    else:
        why = (
            "当前配置确认单之后没有肯定的完整配置选择。用户在 AskUserQuestion 点选后可直接 done，"
            "不需要再手动输入或由 Agent 拼接 --ack。"
        )
    count = _ack_failure(st, why)
    return False, why + _ack_retry_guidance(count)

def check_evidence(step, st):
    return workflow_completion.evidence_failures(
        step, st, api._EVIDENCE_REGISTRY)
