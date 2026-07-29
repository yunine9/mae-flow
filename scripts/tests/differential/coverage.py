"""Coverage-catalog validation for differential behavior scenarios."""

import json


DOMAINS = {
    "runtime", "workflow", "evidence", "gate", "ownership",
    "delivery", "quality", "hook", "state", "platform",
}
VALUES = {
    "domain": DOMAINS,
    "runtime": {
        "inactive", "flow", "corrupt", "direct", "standalone",
        "flow-terminal",
    },
    "workflow": {"none", "full", "tweak", "review", "all"},
    "transition": {
        "none", "repair", "rejection", "finalize", "report",
        "normal", "graph", "plan", "cancel", "defer", "ready",
        "revise", "final-review", "push-to-review", "scope-confirm",
    },
    "delivery": {
        "none", "standalone", "checkpoint-staged", "moonlight", "review",
        "checkpoint-continuous", "archive", "push", "all",
    },
    "fault": {
        "none", "corrupt-json", "recorded-issue", "missing-task-card",
        "missing-agent-token", "missing-artifact",
        "missing-checkpoint-plan", "missing-codecheck-scan",
        "missing-review-receipt", "missing-upstream",
        "foreign-artifact", "protected-requirement", "protected-state",
        "stale-head",
        "authentication", "tool-unavailable", "user-cancelled",
    },
}
FIELDS = {
    "domain", "runtime", "workflow", "transition", "delivery", "fault",
}


def load_coverage(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def validate_coverage(catalog, scenario_names):
    errors = []
    if catalog.get("schema") != 1:
        errors.append("coverage schema must be 1")
    unknown_catalog_fields = sorted(
        set(catalog) - {"schema", "scenarios"})
    if unknown_catalog_fields:
        errors.append(
            "coverage has unknown top-level fields "
            + ",".join(unknown_catalog_fields))
    entries = catalog.get("scenarios", {})
    if not isinstance(entries, dict):
        return errors + ["coverage scenarios must be an object"]
    for name in sorted(scenario_names - set(entries)):
        errors.append("coverage missing registered scenario " + name)
    for name in sorted(set(entries) - scenario_names):
        errors.append("coverage references unknown scenario " + name)
    for name, metadata in sorted(entries.items()):
        if not isinstance(metadata, dict):
            errors.append("%s: metadata must be an object" % name)
            continue
        missing = sorted(FIELDS - set(metadata))
        if missing:
            errors.append(
                "%s: missing fields %s" % (name, ",".join(missing)))
        unknown = sorted(set(metadata) - FIELDS)
        if unknown:
            errors.append(
                "%s: unknown fields %s" % (name, ",".join(unknown)))
        for field in sorted(FIELDS):
            value = metadata.get(field)
            if not isinstance(value, str) or value not in VALUES[field]:
                if field == "domain":
                    errors.append(
                        "%s: unknown domain %s" % (name, value))
                else:
                    errors.append(
                        "%s: invalid %s %s" % (name, field, value))
    return errors
