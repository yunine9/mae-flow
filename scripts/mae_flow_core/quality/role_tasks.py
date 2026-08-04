"""Pure stage policy for Spec2Code role task cards."""


ROLE_STEPS = {
    "test-design": {"test_blueprint"},
    "task-analysis": {"build_plan", "build"},
    "craft-plan": {"build_plan", "build"},
    "cp-implement": {"build"},
    "craft-code": {"build"},
    "story-generate": {"story"},
    "story-review": {"story"},
    "grill-critic": {"grill"},
}


def role_allowed(role, step):
    return str(step or "") in ROLE_STEPS.get(str(role or ""), set())
