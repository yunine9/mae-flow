"""Pure exact-file delivery plans for Continuous and Staged work."""

from collections.abc import Mapping
from dataclasses import dataclass

from ..foundation.commit_message import valid_business_commit_message
from .documents import conditional_document_kind
from .models import CommitPace, FlowState


_COMMIT_MESSAGE_DECISION = "delivery.commit_message"
_CONDITIONAL_DOCUMENT_DECISION = "delivery.conditional_document"
_ADOPTED_DIRTY_DECISION = "delivery.adopted_dirty"
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


def _validated_manifest(paths, adopted_dirty=()):
    manifest = _delivery_manifest_type().from_paths(
        paths, adopted_dirty=adopted_dirty)
    if not manifest.files:
        raise ValueError("delivery manifest must not be empty")
    for path in manifest.files:
        _validate_stage_path(path)
    return manifest


def _validate_existing_manifest(manifest):
    if not isinstance(manifest, _delivery_manifest_type()):
        raise TypeError("manifest must be a DeliveryManifest")
    # Reconstruct to keep the same portable exact-path checks at every entry.
    return _validated_manifest(manifest.files, manifest.adopted_dirty)


def _decision_values(state, wanted_key):
    values = []
    for decision in state.decisions:
        try:
            key, value = decision
        except (TypeError, ValueError) as exc:
            raise ValueError("state decisions must be key-value pairs") from exc
        if key == wanted_key:
            values.append(value)
    return tuple(values)


def _conditional_document_selections(state):
    selections = set()
    for value in _decision_values(state, _CONDITIONAL_DOCUMENT_DECISION):
        try:
            selected = _validated_manifest((value,)).files[0]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "conditional document selection must be an exact durable path"
            ) from exc
        if not conditional_document_kind(selected):
            raise ValueError(
                "conditional document selection must name a durable "
                "requirement document")
        selections.add(_path_identity(selected))
    return selections


def _global_delivery_manifest(state):
    adopted_dirty = _decision_values(state, _ADOPTED_DIRTY_DECISION)
    manifest = _validated_manifest(
        state.delivery_files, adopted_dirty=adopted_dirty)

    from ..guard.manifest import authorize_delivery
    authorize_delivery(state, manifest)

    initial_ids = {
        _path_identity(path)
        for path in _delivery_manifest_type().from_paths(
            state.initial_dirty).files
    }
    delivery_ids = {_path_identity(path) for path in manifest.files}
    adopted_ids = {_path_identity(path) for path in manifest.adopted_dirty}
    missing = (initial_ids & delivery_ids) - adopted_ids
    if missing:
        raise ValueError(
            "delivery adoption is required for every included initial-dirty "
            "file")
    return manifest


def _require_conditional_document_selections(state, manifest):
    required = tuple(
        path for path in manifest.files if conditional_document_kind(path))
    if not required:
        return
    selected = _conditional_document_selections(state)
    missing = tuple(
        path for path in required if _path_identity(path) not in selected)
    if missing:
        raise ValueError(
            "conditional document requires explicit delivery selection: %s"
            % ", ".join(missing))


def _validate_message(ticket, message):
    if not valid_business_commit_message(ticket, message):
        raise ValueError(
            "commit message must be [ticket][feat|fix]description")
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

        supplied = _validate_existing_manifest(item.manifest)
        supplied_ids = {
            _path_identity(path) for path in supplied.adopted_dirty}
        file_ids = {_path_identity(path) for path in supplied.files}
        expected_adoption = tuple(
            path for path in final_manifest.adopted_dirty
            if _path_identity(path) in file_ids)
        expected_ids = {
            _path_identity(path) for path in expected_adoption}
        if supplied_ids - expected_ids:
            raise ValueError(
                "CP adopted_dirty conflicts with global delivery adoption")
        manifest = _validated_manifest(
            supplied.files, adopted_dirty=expected_adoption)
        message = _validate_message(state.ticket, item.message)
        for path in manifest.files:
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

    This pure planner intentionally ignores phase and status.  A CLI adapter
    must reject inactive state before executing any returned effect.
    """
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    final_manifest = _global_delivery_manifest(state)
    _require_conditional_document_selections(state, final_manifest)

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
