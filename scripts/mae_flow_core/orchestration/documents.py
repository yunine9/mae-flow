"""Pure document locations and conservative commit defaults.

Ticket text is business content and is therefore kept verbatim on
``DocumentPaths.ticket``.  Only the filesystem segment is normalized.  This
keeps Windows path restrictions out of the domain identifier while preventing
different identifiers from silently becoming the same directory on a
case-insensitive filesystem.
"""

from dataclasses import dataclass
import hashlib
import ntpath
import os
import re
import unicodedata


_INVALID_WINDOWS_CHARACTER = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_RESERVED_WINDOWS_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {"COM%d" % number for number in range(1, 10)}
    | {"LPT%d" % number for number in range(1, 10)}
)
_DURABLE_KINDS = frozenset({"spec", "behavior", "behavior-baseline"})
_CONDITIONAL_KINDS = frozenset({
    "story",
    "decisions",
    "engineering",
    "engineering-notes",
    "chain",
    "review",
    "review-ledger",
    "codecheck",
    "codecheck-ledger",
    "delivery",
    "delivery-notes",
})


def _ticket_text(ticket):
    if not isinstance(ticket, str):
        raise TypeError("ticket must be text")
    if not ticket.strip():
        raise ValueError("ticket must not be empty")
    return ticket


def _ticket_digest(ticket):
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()[:12]


def _safe_ticket_segment(ticket):
    original = _ticket_text(ticket)
    candidate = original.strip()
    if "/" in candidate or "\\" in candidate:
        raise ValueError("ticket must be one path segment")
    if ".." in candidate or candidate == ".":
        raise ValueError("ticket must not contain path traversal")
    if _DRIVE_PREFIX.match(candidate) or ntpath.splitdrive(candidate)[0]:
        raise ValueError("ticket must not contain a drive prefix")

    normalized = unicodedata.normalize("NFC", candidate)
    safe = _INVALID_WINDOWS_CHARACTER.sub("-", normalized).rstrip(" .")
    if not safe:
        safe = "ticket"

    reserved = safe.split(".", 1)[0].upper() in _RESERVED_WINDOWS_NAMES
    if reserved:
        safe = "ticket-" + safe

    # Keep familiar all-uppercase safe identifiers readable.  Every transform
    # and every cased alias receives an exact-input digest, so NTFS cannot fold
    # distinct business tickets into one directory.
    changed = safe != original or normalized != candidate or reserved
    case_alias_risk = safe != safe.upper()
    if changed or case_alias_risk:
        safe = "%s-%s" % (safe, _ticket_digest(original))

    # A Windows component is limited to 255 UTF-16 code units.  Leave room for
    # the digest and avoid cutting a surrogate pair by trimming Python code
    # points until the encoded segment fits.
    if len(safe.encode("utf-16-le")) // 2 > 255:
        digest = _ticket_digest(original)
        suffix = "-" + digest
        prefix = safe
        available = 255 - len(suffix.encode("utf-16-le")) // 2
        while prefix and len(prefix.encode("utf-16-le")) // 2 > available:
            prefix = prefix[:-1]
        prefix = prefix.rstrip(" .-") or "ticket"
        safe = prefix + suffix

    return safe


def _root_text(root):
    try:
        value = os.fspath(root)
    except TypeError as exc:
        raise TypeError("root must be a filesystem path") from exc
    if not isinstance(value, str):
        raise TypeError("root must be a text filesystem path")
    if not value:
        raise ValueError("root must not be empty")
    return value


def _path_join(root, *parts):
    windows_root = bool(ntpath.splitdrive(root)[0]) or "\\" in root
    join = ntpath.join if windows_root else os.path.join
    return join(root, *parts)


@dataclass(frozen=True)
class DocumentPaths:
    """All candidate locations for one requirement, without filesystem I/O."""

    ticket: str
    safe_ticket: str
    local_root: str
    local_story: str
    ut_handoff: str
    review_notes: str
    codecheck_ledger: str
    delivery_notes: str
    spec: str
    story: str
    decisions: str
    engineering_notes: str
    chain: str
    behavior_root: str

    @classmethod
    def for_ticket(cls, root, ticket):
        root = _root_text(root)
        original = _ticket_text(ticket)
        safe = _safe_ticket_segment(original)
        local_root = _path_join(root, ".mae-flow-work", safe)
        requirement_root = _path_join(
            root, "docs", "mae-flow", "requirements", safe)
        return cls(
            ticket=original,
            safe_ticket=safe,
            local_root=local_root,
            local_story=_path_join(local_root, "story.md"),
            ut_handoff=_path_join(local_root, "ut-handoff.md"),
            review_notes=_path_join(local_root, "review-notes.md"),
            codecheck_ledger=_path_join(local_root, "codecheck-ledger.md"),
            delivery_notes=_path_join(local_root, "delivery-notes.md"),
            spec=_path_join(requirement_root, "spec.md"),
            story=_path_join(requirement_root, "story.md"),
            decisions=_path_join(requirement_root, "decisions.md"),
            engineering_notes=_path_join(requirement_root, "engineering.md"),
            chain=_path_join(requirement_root, "chain.md"),
            behavior_root=_path_join(root, "docs", "mae-flow", "behavior"),
        )


def commit_policy(kind, explicitly_requested):
    """Return whether a document kind belongs in the exact commit manifest.

    Unknown kinds stay local even when passed an unrelated affirmative flag;
    callers must first classify them deliberately instead of gaining a new
    commit surface by typo.
    """
    if not isinstance(kind, str):
        raise TypeError("document kind must be text")
    normalized = kind.strip().lower().replace("_", "-")
    if not normalized:
        raise ValueError("document kind must not be empty")
    if type(explicitly_requested) is not bool:
        raise TypeError("explicitly_requested must be a bool")
    if normalized in _DURABLE_KINDS:
        return True
    if normalized in _CONDITIONAL_KINDS:
        return explicitly_requested
    return False
