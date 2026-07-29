"""Evidence registration and ordered step evaluation."""

from types import MappingProxyType

from ..foundation.models import EvidenceResult


def legacy_result(value):
    """Normalize one historical ``(bool, str)`` evaluator result."""
    if isinstance(value, EvidenceResult):
        return value
    if not isinstance(value, tuple) or len(value) != 2:
        raise TypeError("evidence evaluator must return EvidenceResult or pair")
    return EvidenceResult(value[0], value[1])


class EvidenceRegistry:
    """An immutable snapshot of Evidence names and evaluators."""

    def __init__(self, evaluators):
        self._evaluators = MappingProxyType(dict(evaluators))
        self._names = tuple(self._evaluators)

    @property
    def names(self):
        return self._names

    def evaluate(self, name, spec, state):
        evaluator = self._evaluators[name]
        return legacy_result(evaluator(spec, state))


def evaluate_step_evidence(step, state, registry):
    """Evaluate declared Evidence in order and return failure reasons."""
    failures = []
    for spec in step.get("evidence", []):
        result = registry.evaluate(spec["type"], spec, state)
        if not result.passed:
            failures.append(result.reason)
    return failures
