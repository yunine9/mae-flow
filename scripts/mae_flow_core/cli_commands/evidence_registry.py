"""Evidence registries wired to public CLI command ports."""

from .shared import (
    AgentEvidencePorts, AgentEvidenceRules, DeliveryEvidencePorts,
    DeliveryEvidenceRules, QualityEvidencePorts, QualityEvidenceRules,
    RISK_AGENT_LABELS, WorkflowEvidencePorts, WorkflowEvidenceRules,
    append_codecheck_event, build_evidence_registry, globmod, os, read_bytes,
    read_text, specengine, sys, time,
)
from .wiring import api

_AGENT_EVIDENCE = AgentEvidenceRules(AgentEvidencePorts(
    moonlight=lambda state: api._moonlight(state),
    step_entered=lambda state: api._step_entered_at(state),
    risk_acceptance=lambda kind, state: api._risk_acceptance(kind, state),
    script_path=lambda: sys.argv[0],
    risk_labels=RISK_AGENT_LABELS,
    tokens=lambda: api._agent_token_data(),
    rejections=lambda: api._agent_rejection_data(),
    source_snapshot_since=lambda head, state: api._source_snapshot_since(
        head, state),
    source_changed_since=lambda head, state: api._source_changed_since(
        head, state),
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
))

ev_codecheck_clean = _QUALITY_EVIDENCE.codecheck_clean
ev_review_codecheck = _QUALITY_EVIDENCE.review_codecheck


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
))

# Compatibility names used by in-flight command handlers and legacy tests.
ev_glob = _WORKFLOW_EVIDENCE.glob
ev_branch_ok = _WORKFLOW_EVIDENCE.branch_ok
ev_tasks_checked = _WORKFLOW_EVIDENCE.tasks_checked
ev_spec_field = _WORKFLOW_EVIDENCE.spec_field
ev_spec2code_artifact = _WORKFLOW_EVIDENCE.spec2code_artifact
ev_tier_scope = _WORKFLOW_EVIDENCE.tier_scope
ev_spec_validate = _WORKFLOW_EVIDENCE.spec_validate
ev_content_free = _WORKFLOW_EVIDENCE.content_free
ev_glob_absent = _WORKFLOW_EVIDENCE.glob_absent
ev_clean_paths = _WORKFLOW_EVIDENCE.clean_paths


_EVIDENCE_REGISTRY = build_evidence_registry(
    workflow=_WORKFLOW_EVIDENCE,
    agent=_AGENT_EVIDENCE,
    delivery=_DELIVERY_EVIDENCE,
    quality=_QUALITY_EVIDENCE,
)
# Read-only compatibility view for older diagnostics that enumerate names.
EVIDENCE = _EVIDENCE_REGISTRY
