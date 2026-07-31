"""Evidence registration and ordered step evaluation."""

from collections.abc import Mapping
from types import MappingProxyType

from ..foundation.models import EvidenceResult


def legacy_result(value):
    """Normalize one historical ``(bool, str)`` evaluator result."""
    if isinstance(value, EvidenceResult):
        return value
    if not isinstance(value, tuple) or len(value) != 2:
        raise TypeError("evidence evaluator must return EvidenceResult or pair")
    return EvidenceResult(value[0], value[1])


class EvidenceRegistry(Mapping):
    """An immutable snapshot of Evidence names and evaluators."""

    def __init__(self, evaluators):
        self._evaluators = MappingProxyType(dict(evaluators))
        self._names = tuple(self._evaluators)

    @property
    def names(self):
        return self._names

    def __iter__(self):
        return iter(self._names)

    def __len__(self):
        return len(self._names)

    def __contains__(self, name):
        return name in self._evaluators

    def __getitem__(self, name):
        return self._evaluators[name]

    def evaluate(self, name, spec, state):
        evaluator = self._evaluators[name]
        return legacy_result(evaluator(spec, state))


def build_evidence_registry(*, workflow, agent, delivery, quality):
    """Compose the one authoritative legacy Evidence name registry."""
    return EvidenceRegistry((
        ("glob", workflow.glob),
        ("branch_ok", workflow.branch_ok),
        ("tasks_checked", workflow.tasks_checked),
        ("commit_tagged", delivery.commit_tagged),
        ("commit_tagged_after_entry", delivery.commit_tagged_after_entry),
        ("review_fix_committed", delivery.review_fix_committed),
        ("review_snapshot", agent.review_snapshot),
        ("checkpoint_plan", delivery.checkpoint_plan),
        ("checkpoint_plan_complete", delivery.checkpoint_plan_complete),
        ("final_review_clear", delivery.final_review_clear),
        ("spec_field", workflow.spec_field),
        ("spec2code_artifact", workflow.spec2code_artifact),
        ("spec2code_plan_review", workflow.spec2code_plan_review),
        ("yaml_field", workflow.spec_field),
        ("spec_validate", workflow.spec_validate),
        ("tier_scope", workflow.tier_scope),
        ("pushed", delivery.pushed),
        ("agent_ran", agent.agent_ran),
        ("content_free", workflow.content_free),
        ("clean_paths", workflow.clean_paths),
        ("archive_paths_clean", delivery.archive_paths_clean),
        ("codecheck_clean", quality.codecheck_clean),
        ("glob_absent", workflow.glob_absent),
        ("review_agent_or_no_code", agent.review_agent_or_no_code),
        ("agent_or_no_source", agent.agent_or_no_source),
        ("review_codecheck", quality.review_codecheck),
    ))


def _checkpoint_compile_covered(state):
    review = state.get("development_review")
    if (
        not isinstance(review, dict)
        or review.get("status") != "active"
    ):
        return False
    expected = {
        "full": "build",
        "hotfix": "build",
        "tweak": "tw_change",
        "review": "rf_fix",
    }.get((state.get("choices") or {}).get("workflow", ""), "")
    if state.get("current") != expected:
        return False
    items = review.get("checkpoints") or []
    return bool(items) and int(
        review.get("current_index", 0) or 0
    ) >= len(items)


def evaluate_step_evidence(step, state, registry):
    """Evaluate declared Evidence in order and return failure reasons."""
    failures = []
    for spec in step.get("evidence", []):
        if (
            spec.get("type") == "agent_or_no_source"
            and str(spec.get("agent", "")).upper() == "COMPILE"
            and _checkpoint_compile_covered(state)
        ):
            # Every CP ready receipt already required a compile token for its
            # exact source snapshot. The enclosing build step must not demand
            # another token after the reviewed snapshot is committed.
            continue
        result = registry.evaluate(spec["type"], spec, state)
        if not result.passed:
            failures.append(result.reason)
    return failures
