"""Shared pure validation for business commit-message prefixes."""

import re


def valid_business_commit_message(ticket, message):
    """Return whether ``message`` starts with the exact required prefix."""
    if not isinstance(ticket, str) or not ticket:
        return False
    if not isinstance(message, str):
        return False
    return bool(re.match(
        r"^\[" + re.escape(ticket) + r"\]\[(?:feat|fix)\](?=\S)",
        message,
    ))
