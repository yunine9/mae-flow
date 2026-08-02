"""Small immutable facts used by lean workflow transitions."""

from dataclasses import dataclass, replace
import hashlib
import json
import re

from ..foundation.commit_message import valid_business_commit_message
from .models import CommitPace, DeliveryPath, FlowState, Phase


DELIVERY_CONFIRMATION = "delivery.confirmation"
DELIVERY_CONFIRMED_FILE = "delivery.confirmed_file"
DELIVERY_RESULT = "delivery.result"
STAGED_FINAL_FILE = "delivery.staged_final_file"
DELIVERY_RECEIPT_KEY = "delivery.receipt"
_RECEIPT_VERSION = 1
_COMMIT_MESSAGE_DECISION = "delivery.commit_message"
_TARGET_KEYS = {
    "remote": "delivery.plan.remote",
    "destination_ref": "delivery.plan.destination_ref",
    "expected_destination_sha": "delivery.plan.expected_destination_sha",
    "new_branch": "delivery.plan.new_branch",
}
GIT_COMMIT_OBSERVATION = "delivery.git.commit_observation"
GIT_PUSH_OBSERVATION = "delivery.git.push_observation"
_REVIEW_ATTEMPT = {
    Phase.SPEC: ("grill", "grill:spec:-"),
    Phase.STORY: ("reviewer", "reviewer:design"),
}

@dataclass(frozen=True)
class DeliveryReceipt:
    """Strict typed view of one persisted schema-v3 receipt JSON value."""

    scope: str
    checkpoint: str
    path: str
    pace: str
    files: tuple
    commits: tuple
    remote: str
    destination_ref: str
    expected_destination_sha: str
    new_branch: bool
    requested_actions: tuple
    user_decision: str
    digest: str
    version: int = _RECEIPT_VERSION

    def to_dict(self, include_digest=True):
        value = {
            "checkpoint": self.checkpoint,
            "commits": [
                {"checkpoint": checkpoint, "files": list(files),
                 "message": message}
                for checkpoint, files, message in self.commits
            ],
            "destination_ref": self.destination_ref,
            "expected_destination_sha": self.expected_destination_sha,
            "files": list(self.files),
            "new_branch": self.new_branch,
            "pace": self.pace,
            "path": self.path,
            "remote": self.remote,
            "requested_actions": list(self.requested_actions),
            "scope": self.scope,
            "user_decision": self.user_decision,
            "version": self.version,
        }
        if include_digest:
            value["digest"] = self.digest
        return value


def checkpoint_receipt_key(checkpoint):
    if not isinstance(checkpoint, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]+", checkpoint):
        raise ValueError("checkpoint receipt identity is invalid")
    return "delivery.cp.%s.receipt" % checkpoint


def _canonical_json(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _receipt_digest(value):
    return hashlib.sha256(
        _canonical_json(value).encode("utf-8", errors="strict")).hexdigest()


def _single_decision(state, key, required=False):
    values = _decision_values(state, key)
    if len(values) > 1:
        raise ValueError("conflicting delivery plan fact: %s" % key)
    if required and (not values or not isinstance(values[0], str)
                     or not values[0]):
        raise ValueError("missing delivery plan fact: %s" % key)
    return values[0] if values else ""


def _target_plan(state):
    values = {
        name: _single_decision(state, key)
        for name, key in _TARGET_KEYS.items()
    }
    if not any(values.values()):
        return "", "", "", False
    remote = values["remote"]
    destination = values["destination_ref"]
    expected = values["expected_destination_sha"]
    branch_value = values["new_branch"]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", remote or ""):
        raise ValueError("delivery remote must be one explicit safe name")
    if (not destination.startswith("refs/heads/")
            or not re.fullmatch(r"refs/heads/[A-Za-z0-9._/-]+", destination)
            or ".." in destination or destination.endswith("/")):
        raise ValueError(
            "delivery destination must be one explicit refs/heads ref")
    if branch_value not in {"true", "false"}:
        raise ValueError("delivery new-branch fact must be true or false")
    new_branch = branch_value == "true"
    if new_branch and expected:
        raise ValueError("new branch delivery must bind an empty prior SHA")
    if not new_branch and not re.fullmatch(r"[0-9a-fA-F]{40}", expected):
        raise ValueError("existing branch delivery must bind a 40-hex prior SHA")
    return remote, destination, expected.casefold(), new_branch


def _checkpoint_plan(state, checkpoint):
    prefix = "delivery.cp.%s." % checkpoint
    files = _decision_values(state, prefix + "file")
    message = _single_decision(state, prefix + "message", required=True)
    manifest = _validated_manifest(files)
    return checkpoint, manifest.files, _validate_message(state.ticket, message)


def _staged_receipt_commits(state):
    names = []
    for key, unused in state.decisions:
        match = re.fullmatch(r"delivery\.cp\.([A-Za-z0-9_-]+)\.file", key)
        if match and match.group(1) not in names:
            names.append(match.group(1))
    if not names:
        raise ValueError("Staged delivery requires at least one CP plan")
    commits = tuple(_checkpoint_plan(state, name) for name in names)
    cumulative = {
        _path_identity(path)
        for unused, files, unused_message in commits for path in files
    }
    if cumulative != {_path_identity(path) for path in state.delivery_files}:
        raise ValueError("Staged CP plans must equal the final manifest")
    if state.path.value == "full":
        for name in names:
            values = _decision_values(state, checkpoint_receipt_key(name))
            if len(values) != 1 or not valid_delivery_receipt(
                    state, values[0], name):
                raise ValueError(
                    "Full staged delivery requires every CP receipt")
    return commits


def _receipt_plan(state, checkpoint=""):
    if checkpoint:
        if state.commit_pace != CommitPace.STAGED:
            raise ValueError("Only Staged checkpoints have Git receipts")
        commit = _checkpoint_plan(state, checkpoint)
        return "checkpoint", commit[1], (commit,), "", "", "", False, (
            "add", "commit")

    files = _validated_manifest(state.delivery_files).files
    remote, destination, expected, new_branch = _target_plan(state)
    has_git = bool(remote)
    if state.commit_pace == CommitPace.CONTINUOUS:
        message = _single_decision(
            state, _COMMIT_MESSAGE_DECISION, required=has_git)
        commits = () if not message else ((
            "", files, _validate_message(state.ticket, message)),)
        actions = ("add", "commit", "push") if has_git else ()
    else:
        final_files = decision_values(state, STAGED_FINAL_FILE)
        if not same_exact_files(final_files, state.delivery_files):
            raise ValueError(
                "Staged receipt requires the explicit final checkpoint union")
        commits = _staged_receipt_commits(state)
        if not has_git:
            actions = ()
        elif state.path.value == "full":
            actions = ("push",)
        else:
            actions = tuple(
                action for unused in commits for action in ("add", "commit")
            ) + ("push",)
    return (
        "delivery", files, commits, remote, destination, expected,
        new_branch, actions,
    )


def issue_delivery_receipt(state, user_decision, checkpoint=""):
    """Build canonical strict JSON; callers never supply a receipt digest."""
    if not isinstance(state, FlowState):
        raise TypeError("state must be a FlowState")
    decision = user_decision.strip() if isinstance(user_decision, str) else ""
    if not decision:
        raise ValueError("receipt requires a natural-language user decision")
    (scope, files, commits, remote, destination, expected, new_branch,
     actions) = _receipt_plan(state, checkpoint)
    receipt = DeliveryReceipt(
        scope, checkpoint, state.path.value, state.commit_pace.value, files,
        commits, remote, destination, expected, new_branch, actions, decision,
        "",
    )
    digest = _receipt_digest(receipt.to_dict(include_digest=False))
    return _canonical_json(
        DeliveryReceipt(**{**receipt.__dict__, "digest": digest}).to_dict())


def load_delivery_receipt(raw):
    """Decode only the exact canonical receipt schema and verify its digest."""
    if not isinstance(raw, str):
        raise ValueError("delivery receipt must be JSON text")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("delivery receipt is not valid JSON") from exc
    expected_keys = {
        "checkpoint", "commits", "destination_ref", "digest",
        "expected_destination_sha", "files", "new_branch", "pace", "path",
        "remote", "requested_actions", "scope", "user_decision", "version",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ValueError("delivery receipt does not match the strict schema")
    if raw != _canonical_json(value):
        raise ValueError("delivery receipt is not canonical JSON")
    scalar_text = expected_keys - {
        "commits", "files", "new_branch", "requested_actions", "version",
    }
    if any(not isinstance(value[key], str) for key in scalar_text):
        raise ValueError("delivery receipt scalar types are invalid")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("delivery receipt version is invalid")
    if type(value["new_branch"]) is not bool:
        raise ValueError("delivery receipt new_branch is invalid")
    if not isinstance(value["files"], list) or not all(
            isinstance(path, str) for path in value["files"]):
        raise ValueError("delivery receipt files are invalid")
    if not isinstance(value["requested_actions"], list) or not all(
            action in {"add", "commit", "push"}
            for action in value["requested_actions"]):
        raise ValueError("delivery receipt actions are invalid")
    commits = []
    if not isinstance(value["commits"], list):
        raise ValueError("delivery receipt commits are invalid")
    for commit in value["commits"]:
        if (not isinstance(commit, dict)
                or set(commit) != {"checkpoint", "files", "message"}
                or not isinstance(commit["checkpoint"], str)
                or not isinstance(commit["message"], str)
                or not isinstance(commit["files"], list)
                or not all(isinstance(path, str) for path in commit["files"])):
            raise ValueError("delivery receipt commit is invalid")
        commits.append((
            commit["checkpoint"], tuple(commit["files"]), commit["message"]))
    body = dict(value)
    supplied_digest = body.pop("digest")
    if (not re.fullmatch(r"[0-9a-f]{64}", supplied_digest)
            or supplied_digest != _receipt_digest(body)):
        raise ValueError("delivery receipt digest is invalid")
    return DeliveryReceipt(
        value["scope"], value["checkpoint"], value["path"], value["pace"],
        tuple(value["files"]), tuple(commits), value["remote"],
        value["destination_ref"], value["expected_destination_sha"],
        value["new_branch"], tuple(value["requested_actions"]),
        value["user_decision"], supplied_digest, value["version"],
    )


def valid_delivery_receipt(state, raw, checkpoint=""):
    """Rebuild from current facts; never trust the persisted digest alone."""
    try:
        receipt = load_delivery_receipt(raw)
        if receipt.checkpoint != checkpoint:
            return False
        rebuilt = issue_delivery_receipt(
            state, receipt.user_decision, checkpoint)
        return rebuilt == raw
    except (TypeError, ValueError):
        return False



def path_identity(path):
    return path.replace("\\", "/").casefold()


def decision_values(state, key):
    return tuple(value for existing, value in state.decisions
                 if existing == key)


def _validated_manifest(paths):
    from ..guard.manifest import DeliveryManifest
    manifest = DeliveryManifest.from_paths(paths)
    if not manifest.files:
        raise ValueError("delivery manifest must not be empty")
    return manifest


def _validate_message(ticket, message):
    if not valid_business_commit_message(ticket, message):
        raise ValueError("commit message must be [ticket][feat|fix]description")
    return message


_decision_values = decision_values
_path_identity = path_identity


def same_exact_files(left, right):
    return (
        len(left) == len(right)
        and {path_identity(path) for path in left}
        == {path_identity(path) for path in right}
    )


def checkpoint_files(state):
    files = []
    identities = set()
    for key, value in state.decisions:
        if key.startswith("delivery.cp.") and key.endswith(".file"):
            identity = path_identity(value)
            if identity not in identities:
                files.append(value)
                identities.add(identity)
    return tuple(files)


def checkpoint_confirmation_key(checkpoint):
    return "construction.cp.%s.confirmation" % checkpoint


def checkpoint_name(value):
    name = (value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError(
            "checkpoint must contain only letters, digits, '_' or '-'")
    return name


def authorize_exact_delivery(state, request):
    receipt = issue_delivery_receipt(state, request.decision_value)
    decisions = tuple(
        item for item in state.decisions
        if item[0] not in {
            DELIVERY_CONFIRMATION,
            DELIVERY_CONFIRMED_FILE,
            DELIVERY_RESULT,
            DELIVERY_RECEIPT_KEY,
            GIT_COMMIT_OBSERVATION,
            GIT_PUSH_OBSERVATION,
        })
    decisions += ((DELIVERY_CONFIRMATION, request.decision_value.strip()),)
    decisions += tuple(
        (DELIVERY_CONFIRMED_FILE, path) for path in state.delivery_files)
    decisions += ((DELIVERY_RECEIPT_KEY, receipt),)
    return replace(state, decisions=decisions)


def authorize_checkpoint(state, request, checkpoint):
    """Bind one Staged CP plan to a user-owned receipt and confirmation."""
    receipt = issue_delivery_receipt(
        state, request.decision_value, checkpoint)
    confirmation = checkpoint_confirmation_key(checkpoint)
    receipt_key = checkpoint_receipt_key(checkpoint)
    decisions = tuple(
        item for item in state.decisions
        if item[0] not in {confirmation, receipt_key})
    decisions += (
        (confirmation, request.decision_value.strip()),
        (receipt_key, receipt),
    )
    return replace(state, decisions=decisions, current_cp=checkpoint)


def staged_checkpoint_receipts_valid(state):
    checkpoints = []
    for key, unused in state.decisions:
        match = re.fullmatch(
            r"delivery\.cp\.([A-Za-z0-9_-]+)\.file", key)
        if match and match.group(1) not in checkpoints:
            checkpoints.append(match.group(1))
    if not checkpoints:
        return False
    if not state.current_cp or state.current_cp not in checkpoints:
        return False
    return all(
        len(decision_values(state, checkpoint_receipt_key(checkpoint))) == 1
        and valid_delivery_receipt(
            state,
            decision_values(state, checkpoint_receipt_key(checkpoint))[0],
            checkpoint,
        )
        for checkpoint in checkpoints
    )


def current_delivery_receipt(state):
    values = decision_values(state, DELIVERY_RECEIPT_KEY)
    if len(values) != 1 or not valid_delivery_receipt(state, values[0]):
        return None
    try:
        return load_delivery_receipt(values[0])
    except ValueError:
        return None


def delivery_effects_observed(state, receipt):
    """Require Hook-owned observations for every requested Git effect."""
    commit_count = receipt.requested_actions.count("commit")
    commits = decision_values(state, GIT_COMMIT_OBSERVATION)
    pushes = decision_values(state, GIT_PUSH_OBSERVATION)

    def matching(values):
        matches = 0
        for raw in values:
            try:
                value = __import__("json").loads(raw)
            except (TypeError, ValueError):
                continue
            if (isinstance(value, dict)
                    and value.get("receipt_digest") == receipt.digest):
                matches += 1
        return matches

    return (
        matching(commits) >= commit_count
        and ("push" not in receipt.requested_actions or matching(pushes) == 1)
    )


def add_material_risk(state, kind, detail, default_detail):
    text = detail.strip() if isinstance(detail, str) else ""
    risk = "%s: %s" % (kind, text or default_detail)
    if risk in state.risks:
        return state
    return replace(state, risks=state.risks + (risk,))


def clear_downstream_authorization(state, include_construction=False):
    prefixes = ["quality.", "delivery."]
    exact = {"review.design"}
    if include_construction:
        prefixes += ["focused.", "construction.", "review."]
        exact = set()
    decisions = tuple(
        item for item in state.decisions
        if item[0] not in exact
        and not item[0].startswith(tuple(prefixes)))
    return replace(
        state,
        decisions=decisions,
        delivery_files=(),
        current_cp="" if include_construction else state.current_cp,
    )


def latest_review_attempt(state):
    requirement = _REVIEW_ATTEMPT.get(state.phase)
    if requirement is None:
        return None
    kind, slot = requirement
    matches = tuple(
        attempt for attempt in state.capabilities
        if attempt.kind == kind and attempt.source_revision == slot)
    return matches[-1] if matches else None


def review_attempt_risk(state, attempt):
    risk = "Review capability %s did not return in slot %s: %s." % (
        attempt.kind,
        attempt.source_revision,
        attempt.outcome,
    )
    if risk in state.risks:
        return state
    return replace(state, risks=state.risks + (risk,))
