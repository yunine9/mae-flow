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
    | {"COM%s" % number for number in ("¹", "²", "³")}
    | {"LPT%s" % number for number in ("¹", "²", "³")}
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
_CONDITIONAL_FILENAMES = {
    "story.md": "story",
    "decisions.md": "decisions",
    "engineering.md": "engineering-notes",
    "chain.md": "chain",
    "review-ledger.md": "review-ledger",
    "codecheck-ledger.md": "codecheck-ledger",
    "delivery-notes.md": "delivery-notes",
}


def _ticket_text(ticket):
    if not isinstance(ticket, str):
        raise TypeError("ticket must be text")
    if not ticket.strip():
        raise ValueError("ticket must not be empty")
    return ticket


def _ticket_digest(ticket):
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


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

    # Every accepted ticket carries its complete exact-input digest.  Applying
    # this uniformly prevents an already-safe ticket from impersonating the
    # encoded spelling of a ticket that needed sanitization, and prevents NTFS
    # case folding or Unicode normalization from merging business identities.
    suffix = "-" + _ticket_digest(original)

    # A Windows component is limited to 255 UTF-16 code units.  Trim only the
    # readable prefix; the complete digest always survives.  Removing one
    # Python code point at a time avoids splitting a surrogate pair.
    available = 255 - len(suffix.encode("utf-16-le")) // 2
    while safe and len(safe.encode("utf-16-le")) // 2 > available:
        safe = safe[:-1]
    safe = safe.rstrip(" .-") or "ticket"
    return safe + suffix


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
    local_decisions: str
    local_engineering_notes: str
    local_chain: str
    ut_handoff: str
    local_review_notes: str
    local_codecheck_ledger: str
    local_delivery_notes: str
    spec: str
    story: str
    decisions: str
    engineering_notes: str
    chain: str
    review_ledger: str
    codecheck_ledger: str
    delivery_notes: str
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
            local_decisions=_path_join(local_root, "decisions.md"),
            local_engineering_notes=_path_join(
                local_root, "engineering-notes.md"),
            local_chain=_path_join(local_root, "chain.md"),
            ut_handoff=_path_join(local_root, "ut-handoff.md"),
            local_review_notes=_path_join(local_root, "review-notes.md"),
            local_codecheck_ledger=_path_join(
                local_root, "codecheck-ledger.md"),
            local_delivery_notes=_path_join(
                local_root, "delivery-notes.md"),
            spec=_path_join(requirement_root, "spec.md"),
            story=_path_join(requirement_root, "story.md"),
            decisions=_path_join(requirement_root, "decisions.md"),
            engineering_notes=_path_join(requirement_root, "engineering.md"),
            chain=_path_join(requirement_root, "chain.md"),
            review_ledger=_path_join(requirement_root, "review-ledger.md"),
            codecheck_ledger=_path_join(
                requirement_root, "codecheck-ledger.md"),
            delivery_notes=_path_join(requirement_root, "delivery-notes.md"),
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


def conditional_document_kind(path):
    """Classify one exact durable requirement document, or return ``""``."""
    if not isinstance(path, str):
        raise TypeError("document path must be text")
    normalized = path.replace("\\", "/")
    parts = normalized.casefold().split("/")
    if (
            len(parts) != 5
            or parts[:3] != ["docs", "mae-flow", "requirements"]
            or not parts[3]):
        return ""
    kind = _CONDITIONAL_FILENAMES.get(parts[4], "")
    if (
            kind
            and commit_policy(kind, True)
            and not commit_policy(kind, False)):
        return kind
    return ""
