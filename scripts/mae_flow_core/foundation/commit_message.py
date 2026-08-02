"""Shared pure validation for business commit-message prefixes."""

import re


def valid_business_commit_message(ticket, message, ticket_type=""):
    """Return whether ``message`` starts with the exact required prefix."""
    if (
            not isinstance(ticket, str)
            or not ticket
            or "[" in ticket
            or "]" in ticket):
        return False
    if not isinstance(message, str):
        return False
    if ticket_type not in {"", "feat", "fix"}:
        return False
    kind = re.escape(ticket_type) if ticket_type else r"(?:feat|fix)"
    return bool(re.match(
        r"^\[" + re.escape(ticket) + r"\]\[" + kind + r"\](?=\S)",
        message,
    ))
