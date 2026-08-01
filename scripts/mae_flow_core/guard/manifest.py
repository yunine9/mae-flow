"""Immutable exact delivery manifests and pure authorization policy."""

from dataclasses import dataclass, replace
import os
import re

from ..orchestration import FlowState


_GLOB_CHARACTERS = re.compile(r"[*?\[\]]")
_ADOPTION_DECISION = "delivery.adopted_dirty"


def _is_absolute(path):
    return path.startswith("/") or bool(re.match(r"^[A-Za-z]:/", path))


def _relative_absolute(path, repository_root):
    root = repository_root.replace("\\", "/").rstrip("/")
    windows_identity = (
        os.name == "nt"
        or bool(re.match(r"^[A-Za-z]:/", path))
        or bool(re.match(r"^[A-Za-z]:/", root))
    )
    comparable_path = path.casefold() if windows_identity else path
    comparable_root = root.casefold() if windows_identity else root
    if comparable_path == comparable_root:
        return ""
    if comparable_path.startswith(comparable_root + "/"):
        return path[len(root) + 1:]
    return None


def _normalize_path(path, repository_root):
    if not isinstance(path, str):
        raise ValueError("delivery paths must be strings")
    if path != path.strip() or not path:
        raise ValueError("delivery paths must be non-empty exact paths")

    normalized = path.replace("\\", "/")
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
    if os.path.isdir(native):
        raise ValueError("delivery path identifies a directory")
    return normalized


def _identity(path):
    """Use a portable Windows-safe repository path identity."""
    return path.replace("\\", "/").casefold()


def _normalize_paths(paths, repository_root=None):
    if isinstance(paths, str) or paths is None:
        raise ValueError("delivery paths must be a collection of exact paths")
    root = (repository_root or os.getcwd()).replace("\\", "/")
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
    decisions = state.decisions + tuple(
        fact for fact in adoption_facts if fact not in state.decisions)
    return replace(
        state,
        delivery_files=manifest.files,
        decisions=decisions,
    )
