"""Loading and static validation for Mae-Flow workflow definitions."""

import json
import os

from .transitions import transition_targets


def load_definition(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def definition_errors(definition, steps_dir=None):
    if not isinstance(definition, dict):
        return ["flow root must be an object"]
    steps = definition.get("steps")
    if not isinstance(steps, dict):
        return ["steps must be an object"]

    errors = []
    start = definition.get("start")
    if start not in steps:
        errors.append(
            "start references unknown step: %s" % (start or "(empty)")
        )

    for step_id in sorted(steps, key=str):
        step = steps[step_id]
        if not isinstance(step_id, str) or not step_id:
            errors.append("step id must be a non-empty string: %r" % step_id)
            continue
        if not isinstance(step, dict):
            errors.append("step %s must be an object" % step_id)
            continue

        nxt = step.get("next")
        if nxt is not None and not isinstance(nxt, (str, dict)):
            errors.append(
                "step %s has unsupported next type: %s"
                % (step_id, type(nxt).__name__)
            )
        else:
            for target in transition_targets(step):
                if not isinstance(target, str) or not target:
                    errors.append(
                        "step %s has invalid next target: %r"
                        % (step_id, target)
                    )
                elif target not in steps:
                    errors.append(
                        "step %s references unknown step: %s"
                        % (step_id, target)
                    )

        if (
            steps_dir is not None
            and not step.get("terminal")
            and not os.path.isfile(
                os.path.join(steps_dir, step_id + ".md")
            )
        ):
            errors.append(
                "step %s is missing document: %s.md"
                % (step_id, step_id)
            )

    return sorted(errors)
