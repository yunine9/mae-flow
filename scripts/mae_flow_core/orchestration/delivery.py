"""Pure exact-file delivery plans for Continuous and Staged work."""

from collections.abc import Mapping
from dataclasses import dataclass
import re

from .models import CommitPace, FlowState


_COMMIT_MESSAGE_DECISION = "delivery.commit_message"
_WIDE_STAGING_EXPRESSIONS = frozenset({"-a", "--all"})


def _delivery_manifest_type():
    # Kept lazy because the guard package imports FlowState from this package.
    from ..guard.manifest import DeliveryManifest
    return DeliveryManifest


@dataclass(frozen=True)
class CheckpointManifest:
    """One user-reviewed CP boundary, separate from Git authorization."""

    checkpoint: str
    message: str
    manifest: object
    user_approved: bool

    def __post_init__(self):
        if not isinstance(self.checkpoint, str):
            raise ValueError("checkpoint must be text")
        if not isinstance(self.message, str):
            raise ValueError("commit message must be text")
        if not isinstance(self.manifest, _delivery_manifest_type()):
            raise TypeError("manifest must be a DeliveryManifest")
        if type(self.user_approved) is not bool:
            raise ValueError("user_approved must be a bool")


@dataclass(frozen=True)
class CommitPlan:
    """One exact local commit effect for a later adapter to authorize."""

    message: str
    manifest: object
    requires_user: bool

    def __post_init__(self):
        if not isinstance(self.message, str):
            raise ValueError("commit message must be text")
        if not isinstance(self.manifest, _delivery_manifest_type()):
            raise TypeError("manifest must be a DeliveryManifest")
        if type(self.requires_user) is not bool:
            raise ValueError("requires_user must be a bool")


@dataclass(frozen=True)
class DeliveryPlan:
    """Immutable intended commits plus one final push effect."""

    commits: tuple
    push_once: bool

    def __post_init__(self):
        if isinstance(self.commits, (str, bytes, set, frozenset, Mapping)):
            raise ValueError("commits must be an ordered collection")
        try:
            commits = tuple(self.commits)
        except TypeError as exc:
            raise ValueError("commits must be an ordered collection") from exc
        if any(not isinstance(commit, CommitPlan) for commit in commits):
            raise TypeError("commits must contain CommitPlan values")
        if type(self.push_once) is not bool:
            raise ValueError("push_once must be a bool")
        object.__setattr__(self, "commits", commits)


def _path_identity(path):
    return path.replace("\\", "/").casefold()


def _validate_stage_path(path):
    identity = _path_identity(path)
    parts = identity.split("/")
    if identity in _WIDE_STAGING_EXPRESSIONS:
        raise ValueError("delivery staging must name exact files, not options")
    if any(part.startswith(".mae-flow.json") for part in parts):
        raise ValueError("delivery must not stage .mae-flow.json control files")
    if ".mae-flow-work" in parts:
        raise ValueError("delivery must not stage local .mae-flow-work files")


def _validated_manifest(paths):
    manifest = _delivery_manifest_type().from_paths(paths)
    if not manifest.files:
        raise ValueError("delivery manifest must not be empty")
    for path in manifest.files:
        _validate_stage_path(path)
    return manifest


def _validate_existing_manifest(manifest):
    if not isinstance(manifest, _delivery_manifest_type()):
        raise TypeError("manifest must be a DeliveryManifest")
    # Reconstruct to keep the same portable exact-path checks at every entry.
    return _validated_manifest(manifest.files)


def _validate_message(ticket, message):
    if not isinstance(ticket, str) or not ticket:
        raise ValueError("ticket must be non-empty text")
    if "[" in ticket or "]" in ticket:
        raise ValueError("ticket brackets make the commit message ambiguous")
    if not isinstance(message, str):
        raise ValueError("commit message must be text")
    pattern = re.compile(
        r"\[" + re.escape(ticket)
        + r"\]\[(?:feat|fix)\](?P<description>[^\r\n]+)"
    )
    match = pattern.fullmatch(message)
    if match is None:
        raise ValueError(
            "commit message must be [ticket][feat|fix]description")
    description = match.group("description")
    if not description or description != description.strip():
        raise ValueError("commit message description must be non-empty and trimmed")
    return message


def _continuous_message(state):
    messages = []
    for decision in state.decisions:
        try:
            key, value = decision
        except (TypeError, ValueError) as exc:
            raise ValueError("state decisions must be key-value pairs") from exc
        if key == _COMMIT_MESSAGE_DECISION:
            messages.append(value)
    if len(messages) != 1:
        raise ValueError(
            "Continuous delivery requires exactly one commit message decision")
    return _validate_message(state.ticket, messages[0])


def _ordered_checkpoints(cp_manifest):
    if (
            cp_manifest is None
            or isinstance(cp_manifest, (
                str, bytes, set, frozenset, Mapping, CheckpointManifest))):
        raise ValueError(
            "Staged delivery requires a non-empty ordered CP collection")
    try:
        checkpoints = tuple(cp_manifest)
    except TypeError as exc:
        raise ValueError(
            "Staged delivery requires a non-empty ordered CP collection"
        ) from exc
    if not checkpoints:
        raise ValueError(
            "Staged delivery requires a non-empty ordered CP collection")
    if any(not isinstance(item, CheckpointManifest) for item in checkpoints):
        raise TypeError(
            "Staged delivery requires CheckpointManifest values")
    return checkpoints


def _staged_commits(state, cp_manifest, final_manifest):
    checkpoints = _ordered_checkpoints(cp_manifest)
    checkpoint_names = set()
    file_owners = {}
    commits = []
    cumulative = []
    for item in checkpoints:
        name = item.checkpoint
        if not name.strip() or name != name.strip():
            raise ValueError("checkpoint identity must be non-empty and trimmed")
        if name in checkpoint_names:
            raise ValueError("checkpoint identity must be unique")
        checkpoint_names.add(name)
        if not item.user_approved:
            raise ValueError("each CP manifest must be explicitly user-approved")

        manifest = _validate_existing_manifest(item.manifest)
        message = _validate_message(state.ticket, item.message)
        for path in manifest.files:
            identity = _path_identity(path)
            if identity in file_owners:
                raise ValueError(
                    "delivery file is owned by more than one CP: %s" % path)
            file_owners[identity] = name
            cumulative.append(path)
        commits.append(CommitPlan(message, manifest, True))

    final_ids = {_path_identity(path) for path in final_manifest.files}
    cumulative_ids = {_path_identity(path) for path in cumulative}
    if final_ids != cumulative_ids:
        raise ValueError(
            "Staged CP manifests must equal the final delivery manifest")
    return tuple(commits)


def plan_delivery(state, cp_manifest=None):
    """Return immutable delivery intent without running Git or writing files.

    A staged ``cp_manifest`` is an ordered collection of
    :class:`CheckpointManifest` values.  Its ``user_approved`` flag records
    approval of that checkpoint boundary only.  Every resulting commit still
    requires separate current-user authorization; a Moonlight adapter may
    satisfy that later without changing this planner's meaning.
    """
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    final_manifest = _validated_manifest(state.delivery_files)

    if state.commit_pace == CommitPace.CONTINUOUS:
        if cp_manifest is not None:
            raise ValueError("Continuous delivery does not accept CP manifests")
        message = _continuous_message(state)
        commits = (CommitPlan(message, final_manifest, True),)
    elif state.commit_pace == CommitPace.STAGED:
        commits = _staged_commits(state, cp_manifest, final_manifest)
    else:
        raise ValueError("state commit_pace must be Continuous or Staged")

    return DeliveryPlan(commits=commits, push_once=True)
