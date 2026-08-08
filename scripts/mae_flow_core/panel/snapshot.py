"""交付现场只读快照:面板与任何外部展示层的唯一结构化出口。

契约(改字段前先读):

- **只读**:本模块不写任何状态,调用前后 .mae-flow.json 的 revision 与 mtime 不变;
- **软失败**:取不到的东西写进 warnings,其余字段照给,永不抛栈、永不非零退出;
- **不内联文件内容**:只给绝对路径与统计,消费方在本地自己读——载荷恒小,
  也避免出口变成源码外泄通道(内网仓库必须守);
- **不知道就写 null**:进度百分比在有分支和回退的图上必然是编的,宁可空着。

加字段不算破坏;改语义或删字段要升 schema 版本号。
"""

import json
import os
import subprocess
import time

SCHEMA = "mae-flow-status/1"
WORK_DIR = ".mae-flow-work"
DOC_KINDS = (
    ("survey", "调研"), ("grill-prep", "拷问准备"), ("grill", "需求澄清"),
    ("decisions", "决策记录"), ("spec", "规格条目"), ("story", "Story"),
    ("implementation", "实现记录"),
)
COMMIT_CAP = 50


def _git(root, *args):
    try:
        done = subprocess.run(
            ["git", "-C", root] + list(args), shell=False,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30)
    except Exception:                      # noqa: BLE001 —— 看现场不能变卡点
        return ""
    return done.stdout if done.returncode == 0 else ""


def _abs(root, *parts):
    return os.path.abspath(os.path.join(root, *parts))


def _config(state):
    return (state or {}).get("config", {}) or {}


def _ticket(state):
    return str(_config(state).get("单号", "") or "")


def _repo(root, state, warnings):
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if not branch:
        warnings.append("git 不可用或此处不是仓库,分支与提交信息缺失")
    dirty = [line for line in
             _git(root, "status", "--porcelain").splitlines() if line.strip()]
    return {
        "root": os.path.abspath(root),
        "branch": branch,
        "baseline": _config(state).get("基线分支", ""),
        "head": _git(root, "rev-parse", "--short", "HEAD").strip(),
        "dirty_files": len(dirty),
    }


def _delivery(state):
    config = _config(state)
    return {
        "ticket": config.get("单号", ""),
        "ticket_type": config.get("单号类型", ""),
        "workflow": ((state or {}).get("choices", {}) or {}).get("workflow", ""),
        "requirement_doc": config.get("需求文档", ""),
        "owner": config.get("工号", ""),
        "started_at": (state or {}).get("started", ""),
        "moonlight": bool((state or {}).get("moonlight", {})),
    }


def _documents(root, state):
    ticket = _ticket(state)
    if not ticket:
        return []
    folder = os.path.join(root, WORK_DIR, ticket)
    out = []
    for stem, label in DOC_KINDS:
        path = os.path.join(folder, stem + ".md")
        if not os.path.isfile(path):
            continue
        try:
            info = os.stat(path)
        except OSError:
            continue
        out.append({
            "kind": stem, "label": label, "path": os.path.abspath(path),
            "relative": "%s/%s/%s.md" % (WORK_DIR, ticket, stem),
            "bytes": info.st_size,
            "updated_at": time.strftime("%Y-%m-%d %H:%M",
                                        time.localtime(info.st_mtime)),
        })
    return out


def _spec(root, state):
    legacy = os.path.join(root, "openspec")
    workspace = legacy if os.path.isdir(legacy) else os.path.join(
        root, WORK_DIR, "spec")
    data = (state or {}).get("spec", {}) or {}
    return {
        "workspace": os.path.abspath(workspace)
        if os.path.isdir(workspace) else "",
        "engine": data.get("engine", "builtin"),
        "phase": data.get("phase") or None,
        "change_dir": data.get("change_dir", ""),
    }


def _commits(root, base):
    if not base:
        return []
    span = "%s..HEAD" % base
    raw = _git(root, "log", "--no-merges", "--date=format:%Y-%m-%d %H:%M",
               "--pretty=%h\t%ad\t%s", span)
    out = []
    for body in raw.splitlines()[:COMMIT_CAP]:
        parts = body.split("\t", 2)
        if len(parts) == 3:
            out.append({"sha": parts[0], "at": parts[1], "subject": parts[2]})
    return out


def changes(root, base):
    """两组变更:本单已提交范围、当前未提交。patch 不进快照,只进 HTML。"""
    from . import diffview
    groups = []
    plans = [("未提交", "工作区待检视增量", ["diff", "--numstat"], ["diff"])]
    if base:
        span = "%s..HEAD" % base
        plans.insert(0, ("已提交", "本单范围 %s..HEAD" % base,
                         ["diff", "--numstat", span], ["diff", span]))
    for title, note, stat_args, patch_args in plans:
        stats = diffview.numstat(_git(root, *stat_args))
        patches = diffview.split_patch(_git(root, *patch_args))
        files = [{"path": path, "added": stats[path][0],
                  "removed": stats[path][1], "patch": patches.get(path, "")}
                 for path in sorted(stats)]
        if files:
            groups.append({"title": title, "note": note, "files": files})
    return groups


def _agent_evidence(state, name, label):
    task = ((state or {}).get("agent_tasks", {}) or {}).get(name)
    if not isinstance(task, dict):
        return None
    return {"name": label, "at": task.get("at", ""),
            "head": (task.get("head") or "")[:7],
            "files": len(task.get("task_files") or []),
            "task_card": task.get("path", "")}


def _codecheck(state):
    scan = ((state or {}).get("quality", {}) or {}).get("codecheck_scan")
    if not isinstance(scan, dict):
        return None
    status = str(scan.get("status", "") or "")
    return {
        "name": "CodeCheck", "at": scan.get("at", ""), "status": status,
        "count": scan.get("count"),
        "degraded": status in ("TOOL_ERROR", "UNAVAILABLE"),
        "files": len(scan.get("files") or []),
        "reason": (scan.get("error") or "").strip()[:300],
    }


def _reviews(state):
    out = []
    for name, task in sorted(((state or {}).get("role_tasks", {}) or {}).items()):
        if isinstance(task, dict):
            out.append({"role": name, "at": task.get("at", ""),
                        "path": task.get("path", "")})
    return out


def _evidence(state):
    attempts = (state or {}).get("quality_attempts", {}) or {}
    ut_session = (state or {}).get("ut_session", {}) or {}
    out = {
        "compile": _agent_evidence(state, "COMPILE", "编译"),
        "reviewer": _agent_evidence(state, "REVIEWER", "Agent 预检"),
        "codecheck": _codecheck(state),
        "reviews": _reviews(state),
    }
    ponytail = attempts.get("ponytail")
    if isinstance(ponytail, dict):
        out["ponytail"] = {"name": "代码精简", "rounds": ponytail.get("count", 0)}
    if ut_session:
        batches = ut_session.get("batches") or []
        out["ut"] = {
            "name": "UT", "at": ut_session.get("at", ""),
            "phase": ut_session.get("phase", ""),
            "complete": bool(ut_session.get("complete")),
            "batches": len(batches),
            "completed_batches": len(ut_session.get("completed_batches") or []),
        }
    return out


def _advisories(root, state):
    path = os.path.join(root, ".mae-flow.json.advisories")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
    except Exception:                      # noqa: BLE001
        return []
    current = (state or {}).get("current", "")
    notices = data.get("advisories", []) if isinstance(data, dict) else []
    return [item for item in notices
            if isinstance(item, dict) and item.get("step") == current]


def _pending(state, flow):
    """待你裁决:只列真正需要人拍板的事,不把机器证据混进来。"""
    current = (state or {}).get("current", "")
    step = ((flow or {}).get("steps", {}) or {}).get(current)
    if not isinstance(step, dict):
        return []
    config = _config(state)
    if step.get("choice_key"):
        answers = step.get("choice_answers", {}) or {}
        return [{
            "kind": "choice", "step": current, "title": step.get("title", ""),
            "needs": "choice",
            "items": [{"label": key, "value": "/".join(value)}
                      for key, value in sorted(answers.items())],
            "paths": [],
        }]
    if step.get("user_ack"):
        keys = step.get("require_sets") or sorted(config)
        return [{
            "kind": "config_review" if step.get("require_sets") else "ack",
            "step": current, "title": step.get("title", ""),
            "needs": "user_ack",
            "items": [{"label": key, "value": str(config.get(key, ""))}
                      for key in keys],
            "paths": [],
        }]
    return []


def _remaining(flow, current):
    """沿 flow 图数还剩几步;分支未定时给可达上界。"""
    steps = (flow or {}).get("steps", {}) or {}
    if current not in steps:
        return None
    seen, frontier, depth = {current}, [current], 0
    while frontier:
        following = []
        for name in frontier:
            nxt = (steps.get(name) or {}).get("next")
            options = list(nxt.values()) if isinstance(nxt, dict) else [nxt]
            for option in options:
                if option and option in steps and option not in seen:
                    seen.add(option)
                    following.append(option)
        if following:
            depth += 1
        frontier = following
    return depth


def _progress(state, flow):
    current = (state or {}).get("current", "")
    history = [item.get("step") for item in (state or {}).get("history", [])
               if isinstance(item, dict)]
    done = list(dict.fromkeys(name for name in history if name))
    remaining = _remaining(flow, current)
    step = ((flow or {}).get("steps", {}) or {}).get(current) or {}
    gotos = sum(1 for item in (state or {}).get("history", [])
                if isinstance(item, dict) and "goto" in str(item.get("result")))
    return {
        "step": current,
        "step_title": step.get("title", ""),
        "steps_done": done,
        "steps_total_estimate": (len(done) + remaining + 1)
        if remaining is not None else None,
        "percent": None,        # 有分支与回退,算出来必然是编的
        "started_at": (state or {}).get("started", ""),
        "revisits": {"goto": gotos},
    }


def build(root=".", state=None, flow=None):
    """组装快照。任何一段取不到都只记 warning,不影响其余字段。"""
    warnings = []
    if state is None:
        warnings.append("没有 .mae-flow.json:本仓当前没有在途交付,仅给出仓库信息")
    base = (state or {}).get("implementation_base_head", "")
    return {
        "schema": SCHEMA,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "state_revision": (state or {}).get("revision"),
        "repo": _repo(root, state, warnings),
        "delivery": _delivery(state),
        "pending": _pending(state, flow),
        "artifacts": {
            "documents": _documents(root, state),
            "spec": _spec(root, state),
            "commits": _commits(root, base),
            "logs": {
                key: _abs(root, WORK_DIR, sub)
                for key, sub in (("lightcheck", "lightcheck/latest.md"),
                                 ("codecheck", "codecheck-logs"),
                                 ("agent_tasks", "agent-tasks"),
                                 ("role_tasks", "role-tasks"))
                if os.path.exists(_abs(root, WORK_DIR, sub))
            },
        },
        "evidence": _evidence(state),
        "advisories": _advisories(root, state),
        "progress": _progress(state, flow),
        "warnings": warnings,
    }
