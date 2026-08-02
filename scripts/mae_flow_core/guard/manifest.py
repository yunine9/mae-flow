"""Immutable exact delivery manifests and pure authorization policy."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
import ntpath
import os
import re

from ..foundation.git_shell import git_invocations
from ..orchestration.models import FlowState


_GLOB_CHARACTERS = re.compile(r"[*?\[\]]")
_ADOPTION_DECISION = "delivery.adopted_dirty"
_GIT_BUILTINS = frozenset("""
add am apply archive bisect blame branch bundle cat-file check-ref-format
checkout cherry cherry-pick clean clone commit config describe diff difftool
fetch for-each-ref format-patch fsck gc grep init log ls-files maintenance
merge merge-base mergetool mv name-rev notes pull push range-diff rebase reflog
remote repack replace reset restore rev-list rev-parse revert rm show show-branch
sparse-checkout stash status submodule switch symbolic-ref tag update-index
worktree
""".split())


def _is_absolute(path):
    return path.startswith("/") or bool(re.match(r"^[A-Za-z]:/", path))


def _is_drive_relative(path):
    drive, tail = ntpath.splitdrive(path)
    unc_drive = drive.startswith(("//", "\\\\"))
    return bool(
        drive
        and not unc_drive
        and not tail.startswith(("/", "\\"))
    )


def _relative_absolute(path, repository_root):
    root = repository_root.replace("\\", "/").rstrip("/")
    windows_identity = (
        os.name == "nt"
        or bool(ntpath.splitdrive(path)[0])
        or bool(ntpath.splitdrive(root)[0])
    )
    comparable_path = path.casefold() if windows_identity else path
    comparable_root = root.casefold() if windows_identity else root
    if comparable_path == comparable_root:
        return ""
    if comparable_path.startswith(comparable_root + "/"):
        return path[len(root) + 1:]
    return None


def _parent_stays_in_repository(path, repository_root):
    """Resolve existing parents, but never dereference the final path."""
    native_path = os.path.join(
        repository_root,
        *path.split("/"),
    )
    if not (os.path.isabs(native_path) and os.path.isabs(repository_root)):
        return True
    canonical_root = os.path.realpath(repository_root).replace("\\", "/")
    canonical_parent = os.path.realpath(
        os.path.dirname(native_path)).replace("\\", "/")
    return _relative_absolute(canonical_parent, canonical_root) is not None


def _reject_git_pathspec_magic(path):
    if path.startswith(":"):
        raise ValueError("delivery paths must not use Git pathspec magic")


def _normalize_path(path, repository_root):
    if not isinstance(path, str):
        raise ValueError("delivery paths must be strings")
    if path != path.strip() or not path:
        raise ValueError("delivery paths must be non-empty exact paths")

    if _is_drive_relative(path):
        raise ValueError("Windows drive-relative delivery paths are invalid")

    normalized = path.replace("\\", "/")
    _reject_git_pathspec_magic(normalized)
    if _GLOB_CHARACTERS.search(normalized):
        raise ValueError("delivery paths must not contain globs")

    if _is_absolute(normalized):
        normalized = _relative_absolute(normalized, repository_root)
        if normalized is None:
            raise ValueError("absolute delivery path is outside repository")

    parts = normalized.split("/")
    if (
            not normalized
            or normalized in (".", "..")
            or any(part in ("", ".", "..") for part in parts)):
        raise ValueError(
            "delivery paths must be exact files without aliases or '..'")

    native = os.path.join(repository_root, *parts)
    if not _parent_stays_in_repository(normalized, repository_root):
        raise ValueError("delivery path parent resolves outside repository")
    if os.path.isdir(native) and not os.path.islink(native):
        raise ValueError("delivery path identifies a directory")
    return normalized


def _identity(path):
    """Use a portable Windows-safe repository path identity."""
    return path.replace("\\", "/").casefold()


def _normalize_paths(paths, repository_root=None):
    if isinstance(paths, str) or paths is None:
        raise ValueError("delivery paths must be a collection of exact paths")
    if isinstance(paths, (set, frozenset, Mapping)):
        raise ValueError("delivery paths must be an ordered collection")
    root = (repository_root or os.getcwd()).replace("\\", "/")
    if _is_drive_relative(root):
        raise ValueError("repository root must not be drive-relative")
    if not _is_absolute(root):
        root = os.path.abspath(root)
    normalized = []
    identities = set()
    for path in paths:
        display = _normalize_path(path, root)
        identity = _identity(display)
        if identity in identities:
            raise ValueError("duplicate delivery path alias: %s" % display)
        identities.add(identity)
        normalized.append(display)
    return tuple(normalized)


@dataclass(frozen=True, init=False)
class DeliveryManifest:
    files: tuple
    adopted_dirty: tuple = ()

    def __init__(self, files, adopted_dirty=(), repository_root=None):
        object.__setattr__(
            self,
            "files",
            _normalize_paths(files, repository_root),
        )
        object.__setattr__(
            self,
            "adopted_dirty",
            _normalize_paths(adopted_dirty, repository_root),
        )

    @classmethod
    def from_paths(cls, paths, adopted_dirty=(), repository_root=None):
        """Build a manifest from exact paths without consulting Git."""
        return cls(paths, adopted_dirty, repository_root)


@dataclass(frozen=True)
class ManifestComparison:
    matches: bool
    missing: tuple
    extra: tuple

    def __post_init__(self):
        object.__setattr__(
            self,
            "missing",
            _ordered_tuple(self.missing, "missing"),
        )
        object.__setattr__(
            self,
            "extra",
            _ordered_tuple(self.extra, "extra"),
        )


def _ordered_tuple(paths, field):
    if isinstance(paths, str) or paths is None:
        raise ValueError("%s must be a collection of paths" % field)
    if isinstance(paths, (set, frozenset, Mapping)):
        raise ValueError("%s must be an ordered collection" % field)
    values = tuple(paths)
    if any(not isinstance(path, str) for path in values):
        raise ValueError("%s paths must be strings" % field)
    return values


def _by_identity(paths):
    return {_identity(path): path for path in paths}


def compare_staged(manifest, staged):
    """Compare a manifest with staged path facts using exact set equality."""
    if not isinstance(manifest, DeliveryManifest):
        raise TypeError("manifest must be a DeliveryManifest")
    staged_paths = _normalize_paths(staged)
    expected = _by_identity(manifest.files)
    actual = _by_identity(staged_paths)
    missing = tuple(
        expected[identity] for identity in sorted(set(expected) - set(actual)))
    extra = tuple(
        actual[identity] for identity in sorted(set(actual) - set(expected)))
    return ManifestComparison(
        matches=not missing and not extra,
        missing=missing,
        extra=extra,
    )


def authorize_delivery(state, manifest):
    """Return a state authorizing exactly one explicit delivery manifest."""
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    if not isinstance(manifest, DeliveryManifest):
        raise TypeError("manifest must be a DeliveryManifest")

    initial_dirty = _by_identity(_normalize_paths(state.initial_dirty))
    delivery = _by_identity(manifest.files)
    adopted = _by_identity(manifest.adopted_dirty)
    outside_initial = tuple(
        adopted[identity]
        for identity in sorted(set(adopted) - set(initial_dirty)))
    if outside_initial:
        raise ValueError(
            "adopted_dirty must be an exact subset of initial_dirty: %s" %
            ", ".join(outside_initial))

    outside_delivery = tuple(
        adopted[identity]
        for identity in sorted(set(adopted) - set(delivery)))
    if outside_delivery:
        raise ValueError(
            "adopted_dirty must also be authorized delivery files: %s" %
            ", ".join(outside_delivery))

    adoption_facts = tuple(
        (_ADOPTION_DECISION, path) for path in manifest.adopted_dirty)
    decisions = tuple(
        fact for fact in state.decisions
        if fact[0] != _ADOPTION_DECISION
    ) + adoption_facts
    return replace(
        state,
        delivery_files=manifest.files,
        decisions=decisions,
    )


def _git_receipt(state):
    from ..orchestration.transition_facts import (
        DELIVERY_RECEIPT_KEY,
        checkpoint_receipt_key,
        decision_values,
        load_delivery_receipt,
        valid_delivery_receipt,
    )

    if state.status != "active" or state.risks:
        return None
    checkpoint = ""
    key = DELIVERY_RECEIPT_KEY
    if state.phase.value == "construction":
        checkpoint = state.current_cp
        if not checkpoint:
            return None
        key = checkpoint_receipt_key(checkpoint)
    elif state.phase.value != "delivery":
        return None
    values = decision_values(state, key)
    if len(values) != 1 or not valid_delivery_receipt(
            state, values[0], checkpoint):
        return None
    try:
        return load_delivery_receipt(values[0])
    except ValueError:
        return None


def _observed_commit_count(state, digest):
    count = 0
    for key, raw in state.decisions:
        if key != "delivery.git.commit_observation":
            continue
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if (isinstance(value, dict)
                and value.get("receipt_digest") == digest):
            count += 1
    return count


def _commit_observations(state):
    values = []
    for key, raw in state.decisions:
        if key != "delivery.git.commit_observation":
            continue
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            values.append(value)
    return values


def _all_receipt_commits_observed(state, receipt):
    from ..orchestration.transition_facts import (
        checkpoint_receipt_key,
        decision_values,
        load_delivery_receipt,
        valid_delivery_receipt,
    )

    observations = _commit_observations(state)
    for checkpoint, files, unused_message in receipt.commits:
        digest = receipt.digest
        if checkpoint and state.path.value == "full":
            values = decision_values(state, checkpoint_receipt_key(checkpoint))
            if (len(values) != 1
                    or not valid_delivery_receipt(
                        state, values[0], checkpoint)):
                return False
            digest = load_delivery_receipt(values[0]).digest
        match = next((
            value for value in observations
            if value.get("receipt_digest") == digest
            and _same_git_files(files, value.get("files", ()))
        ), None)
        if match is None:
            return False
        observations.remove(match)
    return True


def _same_git_files(expected, actual):
    try:
        return _by_identity(_normalize_paths(expected)) == _by_identity(
            _normalize_paths(actual))
    except (TypeError, ValueError):
        return False


def _canonical_push_arguments(receipt):
    lease = "--force-with-lease=%s:%s" % (
        receipt.destination_ref, receipt.expected_destination_sha)
    return (
        lease,
        receipt.remote,
        "HEAD:%s" % receipt.destination_ref,
    )


def git_receipt_error(
        state, operation, actual_files=(), arguments=(), message=""):
    """Return why one Git effect is outside the current user receipt."""
    receipt = _git_receipt(state)
    if receipt is None:
        return "Git delivery requires one current exact user receipt."
    observed = _observed_commit_count(state, receipt.digest)
    if operation in {"add", "commit"}:
        if operation not in receipt.requested_actions:
            return "The current receipt does not request this Git effect."
        if observed >= len(receipt.commits):
            return "Every commit requested by the receipt is already observed."
        unused_checkpoint, files, expected_message = receipt.commits[observed]
        if not _same_git_files(files, actual_files):
            return "Git files must equal the next exact receipt commit."
        if operation == "commit" and message != expected_message:
            return "Commit message must equal the current receipt message."
    elif operation == "push":
        if "push" not in receipt.requested_actions:
            return "The current receipt does not request a push."
        required_commits = receipt.requested_actions.count("commit")
        if observed < required_commits:
            return "Push requires every receipt commit to be observed first."
        if not _all_receipt_commits_observed(state, receipt):
            return "Push requires repository observation of every receipt commit."
        if tuple(arguments) != _canonical_push_arguments(receipt):
            return (
                "Push must use the receipt's canonical explicit remote, "
                "destination ref, and force-with-lease SHA.")
        if (not receipt.new_branch
                and not _same_git_files(receipt.files, actual_files)):
            return "Published files must equal the exact receipt manifest."
    else:
        return "Unsupported Git delivery operation."
    return ""


def git_receipt_reservation(
        state, operation, actual_files=(), arguments=(), message=""):
    """Return immutable reservation facts after the same exact authorization."""
    error = git_receipt_error(
        state, operation, actual_files, arguments, message)
    if error:
        raise ValueError(error)
    receipt = _git_receipt(state)
    observed = _observed_commit_count(state, receipt.digest)
    files = receipt.files
    expected_message = ""
    if operation in {"add", "commit"}:
        unused_checkpoint, files, expected_message = receipt.commits[observed]
    return {
        "receipt_digest": receipt.digest,
        "files": list(files),
        "message": expected_message,
        "remote": receipt.remote,
        "destination_ref": receipt.destination_ref,
        "expected_destination_sha": receipt.expected_destination_sha,
        "new_branch": receipt.new_branch,
    }


def unknown_git_alias(command):
    inline_read_only = set(re.findall(
        r"alias\.([A-Za-z0-9_-]+)=(?:['\"])?"
        r"(?:log|status|diff|show|grep|blame)\b",
        command,
        re.I,
    ))
    known_inline = {name.casefold() for name in inline_read_only}
    return next((
        operation for operation, unused in git_invocations(command)
        if operation not in _GIT_BUILTINS
        and operation.casefold() not in known_inline
    ), "")
