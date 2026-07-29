"""Coverage-catalog validation for differential behavior scenarios."""

import json


DOMAINS = {
    "runtime", "workflow", "evidence", "gate", "ownership",
    "delivery", "quality", "hook", "state", "platform",
}
FIELDS = {
    "domain", "runtime", "workflow", "transition", "delivery", "fault",
}


def load_coverage(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def validate_coverage(catalog, scenario_names):
    errors = []
    entries = catalog.get("scenarios", {})
    for name in sorted(scenario_names - set(entries)):
        errors.append("coverage missing registered scenario " + name)
    for name in sorted(set(entries) - scenario_names):
        errors.append("coverage references unknown scenario " + name)
    for name, metadata in sorted(entries.items()):
        missing = sorted(FIELDS - set(metadata))
        if missing:
            errors.append(
                "%s: missing fields %s" % (name, ",".join(missing)))
        if metadata.get("domain") not in DOMAINS:
            errors.append(
                "%s: unknown domain %s" % (
                    name, metadata.get("domain")))
    return errors
