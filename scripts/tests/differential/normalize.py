"""Explicit-only normalization for differential snapshots."""


def normalize_text(text, replacements):
    result = str(text or "")
    for source, target in sorted(
            replacements.items(), key=lambda item: len(item[0]), reverse=True):
        if source:
            result = result.replace(source, target)
    return result


def normalize_value(value, replacements):
    if isinstance(value, dict):
        return {
            key: normalize_value(item, replacements)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize_value(item, replacements) for item in value]
    if isinstance(value, tuple):
        return tuple(normalize_value(item, replacements) for item in value)
    if isinstance(value, str):
        return normalize_text(value, replacements)
    return value
