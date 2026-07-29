"""CLI responsibilities extracted from the historical entrypoint."""

from .shared import (
    delivery_checkpoints, hashlib, os, re, read_text, shlex, specengine, subprocess,
)
from .wiring import api

def _risk_acceptance(kind, st):
    rec = (st.get("risk_acceptances", {}) or {}).get(kind, {})
    if not rec:
        return False, ""
    if rec.get("step") != st.get("current"):
        return False, f"旧风险确认属于步骤 {rec.get('step', '?')}"
    entered = api._step_entered_at(st)
    if rec.get("at", "") < entered:
        return False, "旧风险确认早于当前步骤"
    task = (st.get("agent_tasks", {}) or {}).get(kind, {})
    if rec.get("task_sha256") and rec.get("task_sha256") != task.get("sha256", ""):
        return False, "风险确认绑定的任务卡已经变化"
    head = rec.get("head", "")
    changed, err = api._source_changed_since(head, st) if head else ([], "风险确认缺少 HEAD")
    if err:
        return False, "风险确认新鲜度无法核实:" + err
    if changed:
        return False, "风险确认后代码发生变化:" + "、".join(changed[:5])
    return True, ""

def _source_files_for_diff(diff, st, include_tests=True):
    """指定 Git 范围内所有源码/构建入口变化，包含删除项。"""
    out = api.argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--name-only", diff])
    files = [f for f in out.splitlines() if f and api._is_source_path(f, st)]
    if not include_tests:
        files = [f for f in files if not api._is_test_file(f, st)]
    return files, ""

def _changed_source_files(st, include_tests=True):
    """当前交付范围内所有源码/构建入口变化，不把语言范围写死成 C++/Java。"""
    diff, err = api._scope_diff(st)
    if err:
        return None, err
    return _source_files_for_diff(diff, st, include_tests)

def _development_review(st):
    """Return the optional checkpoint state without migrating legacy deliveries.

    Absence is meaningful: an in-flight delivery created by an older release
    must keep its original build_review/tw_review/rf_review behavior.
    """
    data = st.get("development_review")
    return data if isinstance(data, dict) and data.get("version") == 1 else None

def _development_checkpoints_enabled(st):
    protocols = st.get("protocols") or {}
    return bool(
        isinstance(protocols, dict)
        and int(protocols.get("development_checkpoints", 0) or 0) >= 1)

def _task_structure_fingerprint(st):
    """Hash task identity/order while ignoring checkbox state and notes."""
    workflow = (st.get("choices", {}) or {}).get("workflow", "")
    lines = []
    if workflow == "review":
        path = os.path.join(
            "docs", "review",
            "REVIEW-" + str((st.get("config", {}) or {}).get("单号", "")) + ".md")
        try:
            text = read_text(path, errors="replace")
        except OSError:
            text = ""
        for raw in text.splitlines():
            if not raw.lstrip().startswith("|"):
                continue
            cells = [re.sub(r"\s+", " ", x.strip().strip("*`"))
                     for x in raw.strip().strip("|").split("|")]
            if (len(cells) >= 4 and cells[0] != "#"
                    and not set(cells[0]) <= {"-", ":"}
                    and cells[-1] == "修复(已确认)"):
                lines.append("|".join(cells[:-1]))
    else:
        change_name = str((st.get("config", {}) or {}).get("CHANGE_NAME", ""))
        try:
            from mae_flow_core import specengine
            _label, text = specengine.tasks_source(os.getcwd(), change_name)
        except Exception:
            text = ""
        for raw in (text or "").splitlines():
            match = re.match(r"^\s*[-*]\s*\[[ xX]\]\s*(.+?)\s*$", raw)
            if match:
                lines.append(re.sub(r"\s+", " ", match.group(1)).strip())
    body = "\n".join(lines)
    return hashlib.sha256(body.encode("utf-8")).hexdigest(), lines

def _checkpoint_current(st):
    return delivery_checkpoints.current_item(st)

def _checkpoint_expected_code_step(st):
    return delivery_checkpoints.expected_code_step(st)

def _checkpoint_review_pending(st):
    return delivery_checkpoints.review_pending(
        st, moonlight=api._moonlight(st))

def _final_review_item(st):
    return delivery_checkpoints.final_review_item(st)

def _checkpoint_locked_item(st):
    return delivery_checkpoints.locked_item(st)

def _checkpoint_review_locked(st):
    """Freeze reviewed code through exact commit and push verification."""
    return delivery_checkpoints.review_locked(
        st, moonlight=api._moonlight(st))

def _review_before_commit(data):
    """New plans review worktree code; old in-flight plans retain their route."""
    return bool((data or {}).get("review_before_commit"))

def _upstream_snapshot():
    ref = api.argv_out([
        "git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    remote_head = api.argv_out(["git", "rev-parse", "--verify", "@{u}"])
    local_head = api.argv_out(["git", "rev-parse", "--verify", "HEAD"])
    return ref, remote_head, local_head

def _reset_range_reaches_upstream(base, head, remote_head):
    shared = api.argv_out(["git", "merge-base", head, remote_head])
    if not shared or shared == base:
        return False
    if api.argv_out(["git", "merge-base", base, shared]) != base:
        return False
    return True

def _upstream_contains_reset_commit(base, head):
    """Return the upstream ref when resetting base..head would drop pushed work."""
    ref, remote_head, _local_head = _upstream_snapshot()
    if not ref or not remote_head:
        return ""
    if head == base:
        return ""
    return ref if _reset_range_reaches_upstream(
        base, head, remote_head) else ""

def _checkpoint_review_lines(base, head, title, remote_ref=""):
    commits = api.argv_out([
        "git", "-c", "core.quotepath=false", "log", "--format=%h %s",
        base + ".." + head,
    ]).splitlines()
    files = api.argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--name-status",
        base, head,
    ]).splitlines()
    stat = api.argv_out([
        "git", "-c", "core.quotepath=false", "diff", "--shortstat",
        base, head,
    ])
    lines = [
        "🔎 " + title,
        f"  范围: {base[:10]}..{head[:10]}",
    ]
    if remote_ref:
        lines.append(f"  远端收据: {remote_ref}@{head[:10]}")
    lines.append("  提交:")
    lines += ["    " + x for x in commits[:30]] or ["    （无提交）"]
    if len(commits) > 30:
        lines.append(f"    …另有 {len(commits) - 30} 个提交")
    lines.append("  文件:")
    lines += ["    " + x for x in files[:80]] or ["    （无文件差异）"]
    if len(files) > 80:
        lines.append(f"    …另有 {len(files) - 80} 个文件")
    if stat:
        lines.append("  统计: " + stat)
    lines.append(f"  完整差异命令: git diff {base} {head}")
    return lines

def _worktree_review_status(paths):
    if not paths:
        return [], ""
    status = api.argv_out([
        "git", "-c", "core.quotepath=false", "status", "--short",
        "--untracked-files=all", "--", *paths,
    ]).splitlines()
    stat = api.argv_out([
        "git", "-c", "core.quotepath=false", "diff",
        "--shortstat", "HEAD", "--", *paths,
    ])
    return status, stat

def _untracked_review_paths(paths):
    result = []
    for path in paths:
        tracked = api.argv_out([
            "git", "ls-files", "--error-unmatch", "--", path])
        if not tracked:
            result.append(path)
    return result

def _worktree_review_file_lines(status):
    lines = ["  文件:"]
    lines += ["    " + line for line in status[:80]]
    if not status:
        lines.append("    （无文件差异）")
    if len(status) > 80:
        lines.append("    …另有 %d 个文件" % (len(status) - 80))
    return lines

def _worktree_review_detail_lines(paths, stat, receipt):
    lines = []
    if stat:
        lines.append("  统计: " + stat)
    command = " ".join(shlex.quote(path) for path in paths)
    lines.append("  命令行复核: git diff HEAD -- " + command)
    untracked = _untracked_review_paths(paths)
    if untracked:
        lines.append("  未跟踪新文件也属于本收据，请在 IDE Source Control 中逐个打开: "
                     + "、".join(untracked))
    lines.append("  收据指纹: " + str(
        receipt.get("snapshot_sha256", ""))[:16])
    return lines

def _checkpoint_worktree_review_lines(item):
    receipt = item.get("receipt") or {}
    base = str(receipt.get("base", ""))
    paths = list((receipt.get("snapshot") or {}).keys())
    status, stat = _worktree_review_status(paths)
    lines = [
        "🔎 %s 用户代码检视（尚未提交）" % item.get("id"),
        "  对比基点: HEAD@%s" % base[:10],
        "  IDE 检视入口: Source Control / Local Changes；这里看到的未提交 diff "
        "就是确认后允许提交的代码。",
    ]
    lines += _worktree_review_file_lines(status)
    lines += _worktree_review_detail_lines(paths, stat, receipt)
    return lines

def _final_review_candidate_path(path, st):
    if api._is_source_path(path, st, api.FLOW):
        return True
    identity = api._repo_path_identity(path)
    if identity not in api._agent_written_paths():
        return False
    low = api.norm(path).lower()
    return not low.endswith((".md", ".rst", ".adoc"))

def _final_delivery_snapshot(st, head):
    result = {}
    for path in api._changed_paths_since_head(head):
        if api._unchanged_initial_dirty(path, st):
            continue
        if _final_review_candidate_path(path, st):
            result[path] = api._review_path_fingerprint(path)
    return result

def _final_review_delta(st):
    data = _development_review(st)
    if not data or api._moonlight(st):
        return [], ""
    base = str(data.get("last_reviewed_head") or data.get("delivery_base") or "")
    if not base:
        return None, "缺少上次已检视代码基点"
    current = api.sh("git rev-parse --verify HEAD")
    if (api.argv_out(["git", "cat-file", "-t", base]) != "commit"
            or api.argv_out(["git", "merge-base", base, current]) != base):
        return None, (
            "上次已检视代码基点 %s 已不在当前 HEAD 历史上，可能发生了 "
            "rebase/reset；旧收据不能为改写后的提交历史背书" % base[:10])
    snapshot = _final_delivery_snapshot(st, base)
    dirty = set(api._dirty_paths())
    changed = [
        path + ("(未提交)" if path in dirty else "")
        for path in snapshot
    ]
    return changed, ""

def _archive_delivery_paths(st):
    """Return only the paths produced by this delivery's archive operation."""
    data = (st or {}).get("spec", {}) or {}
    paths = [
        re.sub(r"^(?:\./)+", "", api.norm(path))
        for path in data.get("archive_paths", []) or []
        if isinstance(path, str) and path.strip()
    ]
    if paths:
        return list(dict.fromkeys(paths))

    # Compatibility for an archive completed by a pre-upgrade in-flight state:
    # archived_to identifies the moved change. The exact merged specs were not
    # persisted then, so derive only currently dirty spec files and exclude
    # unchanged dirt that was already present when this delivery started.
    archive_name = str(data.get("archived_to", "") or "")
    if archive_name:
        paths.append("openspec/changes/archive/" + archive_name)
    paths.extend(
        path for path in api._dirty_paths()
        if path.startswith("openspec/specs/")
        and not api._unchanged_initial_dirty(path, st or {})
    )
    return list(dict.fromkeys(paths))

def _committed_delivery_paths(st):
    """List paths committed in this delivery's quality scope."""
    scope, err = api._scope_diff(st)
    if err:
        return [], err
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotepath=false", "diff", "--name-only",
             "--no-renames", scope, "--"],
            shell=False, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
    except Exception as exc:
        return [], str(exc)
    if result.returncode != 0:
        return [], (result.stderr or result.stdout or "git diff 失败").strip()
    changed = {
        re.sub(r"^(?:\./)+", "", api.norm(path))
        for path in result.stdout.splitlines() if path.strip()
    }
    return sorted(changed), ""

def _committed_initial_carryover(st):
    """Find unchanged pre-flow dirt that was committed into this delivery."""
    if not st or not st.get("initial_dirty"):
        return [], ""
    changed, err = _committed_delivery_paths(st)
    if err:
        return [], err
    changed = set(changed)
    written = api._agent_written_paths()
    carried = [
        path for path in (st.get("initial_dirty", []) or [])
        if path in changed
        and api._unchanged_initial_dirty(path, st)
        and api._repo_path_identity(path) not in written
    ]
    return carried, ""
