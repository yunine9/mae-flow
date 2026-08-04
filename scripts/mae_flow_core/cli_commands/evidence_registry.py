"""Evidence registries wired to public CLI command ports."""

from .shared import (
    AgentEvidencePorts, AgentEvidenceRules, DeliveryEvidencePorts,
    DeliveryEvidenceRules, QualityEvidencePorts, QualityEvidenceRules,
    RISK_AGENT_LABELS, WorkflowEvidencePorts, WorkflowEvidenceRules,
    append_codecheck_event, build_evidence_registry, globmod, hashlib, os,
    read_bytes,
    read_text, STATE_PATH, spec2code_artifact_path, spec2code_review_requires_rework,
    spec2code_review_requires_human_decision, specengine, sys, time,
    validate_spec2code_review, EvidenceResult,
)
from .wiring import api
from mae_flow_core.workflow.agent_observations import finished_observation
from mae_flow_core.workflow.quality_executions import (
    quality_input_snapshot, successful_quality_execution,
)
from mae_flow_core.orchestration.domain_archive import (
    candidate_from_dict,
    input_digest,
)
from mae_flow_core.orchestration.work_package import ensure_work_package


def _domain_archive_fresh(state):
    record = (state or {}).get("domain_archive") or {}
    ticket = str(((state or {}).get("config") or {}).get("单号", "")).strip()
    if not ticket:
        return False, "领域归档缺少需求单号；执行 domain-archive status"
    try:
        root = os.getcwd()
        package = ensure_work_package(root, ticket)
        entries = tuple(
            candidate_from_dict(root, value)
            for value in record.get("domains", ()))
        git_facts = "%s\n%s" % (
            api.sh("git -c core.quotepath=false diff --no-ext-diff --binary HEAD -- ."),
            api.sh("git -c core.quotepath=false status --porcelain --untracked-files=all"),
        )
        actual = input_digest(
            root,
            (package.spec, package.grill, package.story, package.decisions),
            git_facts,
            entries,
        )
    except (OSError, TypeError, ValueError) as exc:
        return False, "领域归档新鲜度无法校验: %s；执行 domain-archive status" % exc
    if actual != record.get("input_sha256"):
        return False, (
            "领域归档输入已变化；只需重新执行 domain-archive prepare，"
            "不会回退编码、检视或质量阶段")
    return True, ""


def _finished_agent_observation(kind, step, since):
    observed = finished_observation(STATE_PATH, kind, step, since)
    if observed:
        return observed
    # Read-only compatibility for in-flight stable-v2 work.  Old Hook tokens
    # are treated only as historical "returned" lifecycle facts; status,
    # digest, task issuance, HEAD and source fingerprints are intentionally
    # ignored.  New completions never create these tokens.
    legacy = api._agent_token_data().get(kind, "")
    at = legacy.get("at", "") if isinstance(legacy, dict) else legacy
    legacy_step = legacy.get("step", "") if isinstance(legacy, dict) else ""
    if at and at >= since and legacy_step in ("", step):
        return {
            "kind": kind, "step": step, "lifecycle": "returned",
            "at": at, "legacy": True,
        }
    return None


_AGENT_EVIDENCE = AgentEvidenceRules(AgentEvidencePorts(
    moonlight=lambda state: api._moonlight(state),
    step_entered=lambda state: api._step_entered_at(state),
    risk_acceptance=lambda kind, state: api._risk_acceptance(kind, state),
    script_path=lambda: sys.argv[0],
    risk_labels=RISK_AGENT_LABELS,
    finished_observation=_finished_agent_observation,
    quality_execution=lambda kind, step, state: successful_quality_execution(
        STATE_PATH, kind, step, quality_input_snapshot(state, kind, step)),
    askuser_tokens=lambda: api._agent_token_data(),
    changed_source_files=lambda state: api._changed_source_files(state),
    shell_output=lambda command: api.sh(command),
    argv_output=lambda arguments: api.argv_out(arguments),
    blocking_dirty_source_paths=lambda state: api._blocking_dirty_source_paths(
        state),
))

ev_agent_ran = _AGENT_EVIDENCE.agent_ran
ev_agent_or_no_source = _AGENT_EVIDENCE.agent_or_no_source
ev_review_agent_or_no_code = _AGENT_EVIDENCE.review_agent_or_no_code
ev_review_snapshot = _AGENT_EVIDENCE.review_snapshot


_DELIVERY_EVIDENCE = DeliveryEvidenceRules(DeliveryEvidencePorts(
    moonlight=lambda state: api._moonlight(state),
    development_review=lambda state: api._development_review(state),
    source_changed_since=lambda head, state: api._source_changed_since(
        head, state),
    review_before_commit=lambda data: api._review_before_commit(data),
    final_review_delta=lambda state: api._final_review_delta(state),
    archive_delivery_paths=lambda state: api._archive_delivery_paths(state),
    shell_output=lambda command: api.sh(command),
    argv_output=lambda arguments: api.argv_out(arguments),
    committed_initial_carryover=lambda state: api._committed_initial_carryover(
        state),
    committed_delivery_paths=lambda state: api._committed_delivery_paths(state),
    trusted_harness_commit_path=lambda path, state:
        api._trusted_harness_commit_path(
            path, state, include_user_authorized=True),
    dirty_paths=lambda: api._dirty_paths(),
    path_fingerprint=lambda path: api._path_fingerprint(path),
    repo_path_identity=lambda path: api._repo_path_identity(path),
    agent_written_paths=lambda: api._agent_written_paths(),
    read_text_replace=lambda path: read_text(path, errors="replace"),
    agent_ran=lambda spec, state: _AGENT_EVIDENCE.agent_ran(spec, state),
    review_document=lambda state: os.path.join(
        ensure_work_package(
            os.getcwd(), (state.get("config") or {}).get("单号", "")).root,
        "review.md"),
))

ev_checkpoint_plan = _DELIVERY_EVIDENCE.checkpoint_plan
ev_checkpoint_plan_complete = _DELIVERY_EVIDENCE.checkpoint_plan_complete
ev_final_review_clear = _DELIVERY_EVIDENCE.final_review_clear
ev_archive_paths_clean = _DELIVERY_EVIDENCE.archive_paths_clean
ev_pushed = _DELIVERY_EVIDENCE.pushed
ev_commit_tagged = _DELIVERY_EVIDENCE.commit_tagged
ev_commit_tagged_after_entry = _DELIVERY_EVIDENCE.commit_tagged_after_entry
ev_review_fix_committed = _DELIVERY_EVIDENCE.review_fix_committed


_QUALITY_EVIDENCE = QualityEvidenceRules(QualityEvidencePorts(
    business_changed_files=lambda state: api._biz_changed_files(state),
    risk_acceptance=lambda kind, state: api._risk_acceptance(kind, state),
    source_changed_since=lambda head, state: api._source_changed_since(
        head, state),
    agent_ran=lambda spec, state: _AGENT_EVIDENCE.agent_ran(spec, state),
    tokens=lambda: api._agent_token_data(),
    append_event=lambda state, event, payload: append_codecheck_event(
        os.getcwd(), state, event, payload),
    git_head=lambda: api.sh("git rev-parse --verify HEAD"),
    exists=os.path.exists,
    is_file=os.path.isfile,
    argv_output=lambda arguments: api.argv_out(arguments),
    run_codecheck=lambda files, state, source: api._run_codecheck(
        files, state, source),
    scope_filter=lambda result, state, files:
        api._filter_codecheck_with_repository_facts(
            result, state, files),
    read_bytes=lambda path: read_bytes(path),
    read_text_replace=lambda path: read_text(path, errors="replace"),
    now=lambda: time.strftime("%Y-%m-%d %H:%M:%S"),
    exemption_text_has_pair=lambda text, rule, path:
        api._exemption_text_has_pair(text, rule, path),
    approved_exemptions=lambda state: api._approved_exemptions(state),
    was_exempt_before_review=lambda state, exemption, rule, path:
        api._was_exempt_before_review(state, exemption, rule, path),
    approval_key=lambda rule, path: api._approval_key(rule, path),
    exemption_path=lambda state: os.path.join(
        ensure_work_package(
            os.getcwd(), (state.get("config") or {}).get("单号", "")).root,
        "codecheck-exemptions.md"),
))

ev_codecheck_clean = _QUALITY_EVIDENCE.codecheck_clean
ev_review_codecheck = _QUALITY_EVIDENCE.review_codecheck


def _spec2code_plan_review(spec, state):
    checkpoint = str(spec.get("checkpoint", "CP1") or "CP1")
    ticket = str((state.get("config") or {}).get("单号", "") or "")
    plan = (state.get("spec2code") or {}).get("plan") or {}
    task = (state.get("role_tasks") or {}).get("craft-plan") or {}
    expected_plan = str(plan.get("sha256", "") or "")
    if (
        not expected_plan
        or task.get("checkpoint") != checkpoint
        or task.get("review_target_sha256") != expected_plan
        or not task.get("sha256")
    ):
        return EvidenceResult(
            False,
            "PLAN Reviewer 任务卡未签发或已随 plan 修订失效；"
            "重新生成 role-task craft-plan。",
        )
    plan_path = str(plan.get("path", "") or "")
    if not plan_path or not os.path.isfile(plan_path):
        return EvidenceResult(False, "已登记 plan 文件不存在。")
    try:
        plan_text = read_text(plan_path, encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return EvidenceResult(False, "已登记 plan 无法读取: %s" % exc)
    if hashlib.sha256(
            plan_text.encode("utf-8")).hexdigest() != expected_plan:
        return EvidenceResult(
            False,
            "plan 登记后内容已变化；重新登记并重新签发 PLAN Reviewer。",
        )
    try:
        review_path = spec2code_artifact_path(
            "review", ticket, checkpoint, "plan")
    except ValueError as exc:
        return EvidenceResult(False, "PLAN Review 路径无效: %s" % exc)
    if not os.path.isfile(review_path):
        return EvidenceResult(
            False,
            "缺少 PLAN Review 记录: " + review_path,
        )
    try:
        review_text = read_text(review_path, encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return EvidenceResult(False, "PLAN Review 无法读取: %s" % exc)
    errors = validate_spec2code_review(
        review_text,
        "plan",
        checkpoint,
        str(task.get("sha256")),
        expected_plan,
    )
    if errors:
        return EvidenceResult(
            False,
            "PLAN Review 记录无效: " + "；".join(errors),
        )
    if (
        api._moonlight(state)
        and spec2code_review_requires_human_decision(review_text)
    ):
        return EvidenceResult(
            False,
            "PLAN Reviewer 存在“人工裁决”项，月光宝盒不得代替用户拍板；"
            "执行 moonlight blocked --reason "
            '"<CP、Finding、候选方案和当前风险>"，保留现场到早晨处理。',
        )
    if spec2code_review_requires_rework(review_text):
        return EvidenceResult(
            False,
            "PLAN Reviewer 仍有已接受待处理项。",
        )
    return EvidenceResult(True, "")


_WORKFLOW_EVIDENCE = WorkflowEvidenceRules(WorkflowEvidencePorts(
    cwd=os.getcwd,
    glob_paths=globmod.glob,
    is_file=os.path.isfile,
    read_text=lambda path: read_text(path),
    read_text_replace=lambda path: read_text(path, errors="replace"),
    shell_output=lambda command: api.sh(command),
    argv_output=lambda arguments: api.argv_out(arguments),
    tasks_source=lambda root, change: specengine.tasks_source(root, change),
    spec_has_delta=lambda root, change: specengine.has_delta(root, change),
    spec_validate=lambda root, change: specengine.validate(root, change),
    spec_required_sections=lambda root, change, workflow:
        specengine.check_required_sections(root, change, workflow),
    spec_error=specengine.SpecEngineError,
    spec_data=lambda state: api._spec_data(state),
    risk_acceptance=lambda kind, state: api._risk_acceptance(kind, state),
    business_changed_files=lambda state: api._biz_changed_files(state),
    spec2code_plan_review=lambda spec, state:
        _spec2code_plan_review(spec, state),
    domain_archive_fresh=_domain_archive_fresh,
))

# Compatibility names used by in-flight command handlers and legacy tests.
ev_glob = _WORKFLOW_EVIDENCE.glob
ev_branch_ok = _WORKFLOW_EVIDENCE.branch_ok
ev_tasks_checked = _WORKFLOW_EVIDENCE.tasks_checked
ev_spec_field = _WORKFLOW_EVIDENCE.spec_field
ev_spec2code_artifact = _WORKFLOW_EVIDENCE.spec2code_artifact
ev_spec2code_plan_review = _WORKFLOW_EVIDENCE.spec2code_plan_review
ev_tier_scope = _WORKFLOW_EVIDENCE.tier_scope
ev_spec_validate = _WORKFLOW_EVIDENCE.spec_validate
ev_content_free = _WORKFLOW_EVIDENCE.content_free
ev_glob_absent = _WORKFLOW_EVIDENCE.glob_absent
ev_clean_paths = _WORKFLOW_EVIDENCE.clean_paths
ev_domain_archive_complete = _WORKFLOW_EVIDENCE.domain_archive_complete


_EVIDENCE_REGISTRY = build_evidence_registry(
    workflow=_WORKFLOW_EVIDENCE,
    agent=_AGENT_EVIDENCE,
    delivery=_DELIVERY_EVIDENCE,
    quality=_QUALITY_EVIDENCE,
)
# Read-only compatibility view for older diagnostics that enumerate names.
EVIDENCE = _EVIDENCE_REGISTRY
