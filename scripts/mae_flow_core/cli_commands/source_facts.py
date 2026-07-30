"""CLI responsibilities extracted from the historical entrypoint."""

from .shared import (
    hashlib, json, re, time,
)
from .wiring import api

def _branch_adoption_requested(text):
    """Whether the user explicitly chose to keep working on the current branch."""
    value = re.sub(r"[（(]推荐[）)]", "", str(text or "")).strip()
    if re.search(
            r"(不要|不在|不想|拒绝|取消|改用其他|另开|新建|切到|切换到|"
            r"是否|能否|可以吗|怎么|如何|为什么|[?？])",
            value, re.I):
        return False
    branch = r"(?:当前|现有|现在|这个)分支"
    keep = r"(?:继续|沿用|保留|使用|开发|往下做)"
    return bool(
        re.search(branch + r"[^，。！？,;；]{0,12}" + keep, value, re.I)
        or re.search(keep + r"[^，。！？,;；]{0,12}" + branch, value, re.I)
    )

def _adopt_current_branch(st, ack):
    """Bind the explicitly chosen existing branch to this delivery round."""
    current = api.sh("git branch --show-current")
    head = api.argv_out(["git", "rev-parse", "--verify", "HEAD"])
    base = str((st.get("config", {}) or {}).get("基线分支", "") or "")
    base_head = api.argv_out(["git", "rev-parse", "--verify", base + "^{commit}"]) if base else ""
    if not current or not head:
        return False, "当前处于 detached HEAD 或 Git 状态不可读，不能登记为本单工作分支。"
    if not base or not base_head:
        return False, "配置中的基线分支不可解析，不能判断现有分支是否来自正确基线。"
    if current == base:
        return False, (
            "当前仍是基线分支 %s，不能把主干直接登记成本单工作分支。"
            "请创建约定分支，或先让用户选择一个非基线的现有工作分支。" % base
        )
    if api.argv_out(["git", "merge-base", base_head, head]) != base_head:
        return False, (
            "现有分支 %s 不包含基线 %s 的当前 HEAD，直接沿用会把无关历史带入本单。"
            "请先迁移/同步分支后重新让用户裁决。" % (current, base)
        )
    previous = str((st.get("config", {}) or {}).get("分支名", "") or "")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    st.setdefault("config", {})["分支名"] = current
    st["branch_resolution"] = {
        "mode": "adopt-current",
        "branch": current,
        "head": head,
        "base": base,
        "base_head": base_head,
        "previous_branch": previous,
        "ack_sha256": hashlib.sha256(
            str(ack or "").encode("utf-8")).hexdigest(),
        "at": now,
    }
    return True, (
        "用户明确选择沿用现有分支；本单分支由 %s 调整为 %s，"
        "裁决时 HEAD=%s" % (previous or "(未配置)", current, head[:10])
    )

def _unchanged_initial_dirty(path, st):
    """流程启动前已脏且指纹未变的文件不是本单变化，仍保留在状态中可审计。"""
    rel = api.norm(path).strip().strip('"')
    initial = set((st or {}).get("initial_dirty", []) or [])
    fingerprints = (st or {}).get("initial_dirty_fingerprints", {}) or {}
    return bool(rel in initial and fingerprints.get(rel) == api._path_fingerprint(rel))

def _blocking_dirty_source_paths(st, flow=None):
    return [p for p in api._dirty_paths()
            if api._is_source_path(p, st, flow or api.FLOW)
            and not _unchanged_initial_dirty(p, st)]

def _unchanged_initial_dirty_source_paths(st, flow=None):
    return [p for p in api._dirty_paths()
            if api._is_source_path(p, st, flow or api.FLOW)
            and _unchanged_initial_dirty(p, st)]

def _source_changed_since(head, st=None):
    """令牌签发时 HEAD 之后,源码是否变化:已提交 diff + 工作区未提交改动。
    返回 (变更清单, 错误);基点不可解析(amend/rebase/GC)属错误,由调用方判拒——重签令牌即可恢复。"""
    if not re.fullmatch(r"[0-9a-f]{7,64}", head):
        return None, "令牌基点格式异常"
    cur = api.sh("git rev-parse --verify HEAD")
    if not cur:
        return None, "无法读取当前 HEAD（仓库可能已切走、损坏或不再是 Git 工作区）"
    changed = []
    if cur and cur != head:
        # cat-file 探基点存在性(不用 rev-parse ^{commit}:^ 在 Windows cmd 是转义符)
        if api.argv_out(["git", "cat-file", "-t", head]) != "commit":
            return None, "令牌基点 commit 不可解析(经历过 amend/rebase?)"
        # core.quotepath=false:否则非 ASCII 文件名被引号+八进制转义,pattern 匹配不到 = 漏检
        out = api.argv_out([
            "git", "-c", "core.quotepath=false",
            "diff", "--name-only", head, cur,
        ])
        changed += [f for f in out.splitlines() if f and api._is_source_path(f, st)]
    # 校准实锤:令牌签发前就存在、内容此后未变的存量脏文件曾被算作"签发后
    # 变化",连锁封死任务卡/accept-risk/令牌复用(连裁决出口一起封)。init 已
    # 记 initial_dirty + 指纹,据此豁免:仅当该文件本单真动过(指纹变了)才算变化。
    for line in api.sh("git -c core.quotepath=false status --porcelain --untracked-files=all").splitlines():
        # 按空白切"状态 路径",不用列偏移:sh() 会 strip 首行前导空格(' M' → 'M'),偏移取路径会错位
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        f = parts[1].split(" -> ")[-1].strip().strip('"')
        if not f or not api._is_source_path(f, st):
            continue
        if _unchanged_initial_dirty(f, st):
            continue  # 存量脏文件,本单未动,不算签发后变化
        changed.append(f + "(未提交)")
    return changed, ""

def _changed_paths_since_head(head):
    paths = []
    if head and api.argv_out(["git", "cat-file", "-t", head]) == "commit":
        paths.extend(api.argv_out([
            "git", "-c", "core.quotepath=false", "diff",
            "--name-only", "--no-renames", head, "HEAD",
        ]).splitlines())
    paths.extend(api.argv_out([
        "git", "-c", "core.quotepath=false", "diff",
        "--name-only", "--no-renames", "HEAD",
    ]).splitlines())
    paths.extend(api._dirty_paths())
    return list(dict.fromkeys(api.norm(path) for path in paths if path))

def _source_fingerprints(paths, st=None, flow=None):
    result = {}
    for path in paths:
        if api._is_source_path(path, st, flow or api.FLOW):
            result[path] = api._review_path_fingerprint(path)
    return result

def _source_snapshot_since(head, st=None, flow=None):
    """Fingerprint committed, staged, unstaged and untracked source changes."""
    return _source_fingerprints(
        _changed_paths_since_head(head), st, flow)


def _worktree_snapshot_since(head):
    """Fingerprint every Git-visible change for a COMPILE provenance baseline."""
    return {
        path: api._review_path_fingerprint(path)
        for path in _changed_paths_since_head(head)
    }


def _checkpoint_candidate_path(path, st, flow=None):
    if api._is_source_path(path, st, flow or api.FLOW):
        return True
    if api._repo_path_identity(path) in api._agent_written_paths():
        return True
    return api._trusted_harness_commit_path(path, st)

def _checkpoint_delivery_snapshot(st, head, flow=None):
    """Fingerprint all reviewable delivery candidates, not just code suffixes."""
    result = {}
    for path in _changed_paths_since_head(head):
        if _unchanged_initial_dirty(path, st):
            continue
        if _checkpoint_candidate_path(path, st, flow):
            result[path] = api._review_path_fingerprint(path)
    return result

def _checkpoint_worktree_snapshot(st, flow=None):
    """Return the exact uncommitted delivery snapshot shown in the IDE."""
    head = api.sh("git rev-parse --verify HEAD")
    return _checkpoint_delivery_snapshot(st, head, flow)

def _numstat_line_net(line, st=None, flow=None):
    fields = line.split("\t")
    if len(fields) != 3:
        return 0
    if not api._is_source_path(fields[2], st, flow or api.FLOW):
        return 0
    try:
        added, deleted = int(fields[0]), int(fields[1])
    except ValueError:
        return 0
    return added - deleted

def _numstat_source_net(output, st=None, flow=None):
    return sum(
        _numstat_line_net(line, st, flow)
        for line in output.splitlines())

def _file_line_count(path):
    try:
        with open(path, "rb") as stream:
            return sum(1 for _line in stream)
    except OSError:
        return 0

def _untracked_source_net(st=None, flow=None):
    tracked = set(api.argv_out([
        "git", "ls-files", "--others", "--exclude-standard",
    ]).splitlines())
    return sum(
        _file_line_count(path) for path in tracked
        if api._is_source_path(path, st, flow or api.FLOW))

def _working_source_net(head, st=None, flow=None):
    committed = api.argv_out([
        "git", "-c", "core.quotepath=false", "diff",
        "--numstat", head, "HEAD",
    ])
    working = api.argv_out([
        "git", "-c", "core.quotepath=false", "diff",
        "--numstat", "HEAD",
    ])
    return (
        _numstat_source_net(committed, st, flow)
        + _numstat_source_net(working, st, flow)
        + _untracked_source_net(st, flow))

def _snapshot_sha256(snapshot):
    body = json.dumps(
        snapshot or {}, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
