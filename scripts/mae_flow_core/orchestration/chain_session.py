"""Pure recoverable domain for cross-repository Chain design."""

from dataclasses import dataclass, replace
import json
import ntpath
import posixpath
import re


_ENGINE = "lean-chain-v1"
_SCHEMA = 1
_ANGLES = frozenset({"keyword", "interface", "config-routing"})
_DIGEST = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z][A-Za-z0-9._-]*")
_MATERIAL = frozenset({
    "repository", "touchpoint", "question", "answer", "contract",
    "dependency", "reverse-check", "citations-verified",
})


@dataclass(frozen=True)
class ChainRecord:
    kind: str
    key: str
    value: str


@dataclass(frozen=True)
class ChainState:
    ticket: str
    request: str
    requirement_source: str
    anchor_root: str
    document_path: str
    status: str = "active"
    records: tuple = ()
    decisions: tuple = ()


@dataclass(frozen=True)
class ChainRequest:
    kind: str
    key: str = ""
    value: str = ""


@dataclass(frozen=True)
class ChainResult:
    state: ChainState
    needs_user: bool
    reason: str

    @property
    def effects(self):
        return ()


def _text(value, name, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError("%s must be text" % name)
    if not allow_empty and not value.strip():
        raise ValueError("%s must not be empty" % name)
    return value


def _object(raw):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _compact(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def encode_chain_state(state):
    if not isinstance(state, ChainState):
        raise TypeError("state must be a ChainState")
    return {
        "engine": _ENGINE,
        "schema_version": _SCHEMA,
        "ticket": state.ticket,
        "request": state.request,
        "requirement_source": state.requirement_source,
        "anchor_root": state.anchor_root,
        "document_path": state.document_path,
        "status": state.status,
        "records": [
            {"kind": item.kind, "key": item.key, "value": item.value}
            for item in state.records
        ],
        "decisions": [
            {"key": key, "value": value} for key, value in state.decisions
        ],
    }


def decode_chain_state(raw):
    if not isinstance(raw, dict):
        raise ValueError("Chain state must be an object")
    expected = {
        "engine", "schema_version", "ticket", "request",
        "requirement_source", "anchor_root", "document_path", "status",
        "records", "decisions",
    }
    unknown = sorted(set(raw) - expected)
    if unknown:
        raise ValueError("Chain state has unknown fields: %s" % ", ".join(unknown))
    missing = sorted(expected - set(raw))
    if missing:
        raise ValueError("Chain state is missing fields: %s" % ", ".join(missing))
    if raw["engine"] != _ENGINE or raw["schema_version"] != _SCHEMA:
        raise ValueError("unsupported Chain state schema")
    status = _text(raw["status"], "status")
    if status not in {"active", "exited"}:
        raise ValueError("invalid Chain status")
    if not isinstance(raw["records"], list):
        raise ValueError("records must be a list")
    records = []
    for item in raw["records"]:
        if not isinstance(item, dict) or set(item) != {"kind", "key", "value"}:
            raise ValueError("invalid Chain record")
        records.append(ChainRecord(
            _text(item["kind"], "record.kind"),
            _text(item["key"], "record.key", allow_empty=True),
            _text(item["value"], "record.value", allow_empty=True),
        ))
    if not isinstance(raw["decisions"], list):
        raise ValueError("decisions must be a list")
    decisions = []
    for item in raw["decisions"]:
        if not isinstance(item, dict) or set(item) != {"key", "value"}:
            raise ValueError("invalid Chain decision")
        decisions.append((
            _text(item["key"], "decision.key"),
            _text(item["value"], "decision.value", allow_empty=True),
        ))
    return ChainState(
        ticket=_text(raw["ticket"], "ticket"),
        request=_text(raw["request"], "request"),
        requirement_source=_text(
            raw["requirement_source"], "requirement_source"),
        anchor_root=_text(raw["anchor_root"], "anchor_root"),
        document_path=_text(raw["document_path"], "document_path"),
        status=status,
        records=tuple(records),
        decisions=tuple(decisions),
    )


def _records(state, kind):
    return tuple(item for item in state.records if item.kind == kind)


def _keys(state, kind):
    return tuple(item.key for item in _records(state, kind))


def _path_identity(path):
    windows = "\\" in path or bool(ntpath.splitdrive(path)[0])
    normalized = (
        ntpath.normpath(path).replace("\\", "/")
        if windows else posixpath.normpath(path))
    return normalized.casefold() if windows else normalized


def _without_results(state):
    return replace(
        state,
        records=tuple(
            item for item in state.records
            if item.kind not in {"rendered", "confirmed"}),
    )


def _append(state, kind, key, value, material=False):
    base = _without_results(state) if material else state
    return replace(
        base, records=base.records + (ChainRecord(kind, key, value),))


def _required_fields(value, fields):
    for field in fields:
        raw = value.get(field)
        if not isinstance(raw, str) or not raw.strip():
            return "%s must be non-empty text" % field
    return ""


def _open_question(state):
    answered = set(_keys(state, "answer"))
    return next((
        item.key for item in _records(state, "question")
        if item.key not in answered
    ), "")


def chain_completion_gaps(state, require_rendered=True):
    repositories = {
        item.key: _object(item.value) for item in _records(state, "repository")
    }
    gaps = []
    if len(repositories) < 2:
        gaps.append("Chain requires at least two repositories.")
    touchpoints = _records(state, "touchpoint")
    for repository in repositories:
        angles = {
            _object(item.value).get("angle") for item in touchpoints
            if _object(item.value).get("repository") == repository
        }
        missing = sorted(_ANGLES - angles)
        if missing:
            gaps.append(
                "Repository %s lacks evidence angles: %s."
                % (repository, ", ".join(missing)))
    if _open_question(state):
        gaps.append("Chain question %s remains open." % _open_question(state))
    if not _records(state, "contract"):
        gaps.append("Chain requires at least one interface contract.")
    if not _records(state, "dependency"):
        gaps.append("Chain requires dependency and integration order.")
    reverse = {
        item.key: _object(item.value) for item in _records(state, "reverse-check")
    }
    for repository in repositories:
        if reverse.get(repository, {}).get("independent") is not True:
            gaps.append("Repository %s has not passed reverse-check." % repository)
    verified = _records(state, "citations-verified")
    receipt = _object(verified[-1].value) if verified else {}
    if (receipt.get("count") != len(touchpoints)
            or not isinstance(receipt.get("digest"), str)
            or not _DIGEST.fullmatch(receipt.get("digest", ""))):
        gaps.append("Touchpoint citations are not verified for current evidence.")
    if require_rendered and not _records(state, "rendered"):
        gaps.append("Chain document has not been rendered.")
    return gaps


def _validate_key(request, label):
    key = request.key.strip()
    if not _ID.fullmatch(key):
        return "Chain %s key is invalid." % label
    return ""


def advance_chain(state, request):
    if not isinstance(state, ChainState):
        raise TypeError("state must be a ChainState")
    if not isinstance(request, ChainRequest):
        raise TypeError("request must be a ChainRequest")
    kind = request.kind.strip().lower()
    if kind == "exit":
        return ChainResult(
            replace(state, status="exited"), False,
            "Chain exited without repository effects.")
    if state.status != "active":
        return ChainResult(state, False, "Chain is inactive.")

    if kind == "repository":
        error = _validate_key(request, "repository")
        value = _object(request.value)
        error = error or _required_fields(
            value, ("path", "language_build", "responsibility"))
        if error:
            return ChainResult(state, False, error)
        if request.key in _keys(state, kind):
            return ChainResult(state, False, "Repository key already exists.")
        identity = _path_identity(value["path"])
        if any(
                _path_identity(_object(item.value).get("path", "")) == identity
                for item in _records(state, kind)):
            return ChainResult(state, False, "Repository path already exists.")
        return ChainResult(
            _append(state, kind, request.key, _compact(value), True),
            False, "Recorded one repository responsibility.")

    if kind == "touchpoint":
        error = _validate_key(request, "touchpoint")
        value = _object(request.value)
        error = error or _required_fields(
            value, ("repository", "file", "symbol", "why", "confidence",
                    "angle"))
        if error:
            return ChainResult(state, False, error)
        if request.key in _keys(state, kind):
            return ChainResult(state, False, "Touchpoint key already exists.")
        if value["repository"] not in _keys(state, "repository"):
            return ChainResult(state, False, "Touchpoint repository is unknown.")
        if value["angle"] not in _ANGLES:
            return ChainResult(state, False, "Touchpoint evidence angle is invalid.")
        if value["confidence"] not in {"high", "medium", "low"}:
            return ChainResult(state, False, "Touchpoint confidence is invalid.")
        return ChainResult(
            _append(state, kind, request.key, _compact(value), True),
            False, "Recorded one evidence-backed touchpoint.")

    if kind == "question":
        error = _validate_key(request, "question")
        value = _object(request.value)
        error = error or _required_fields(
            value, ("evidence", "impact", "recommendation"))
        if not isinstance(value.get("parent"), str):
            error = error or "parent must be text"
        if error:
            return ChainResult(state, False, error)
        if request.key in _keys(state, kind):
            return ChainResult(state, False, "Question key already exists.")
        opened = _open_question(state)
        if opened:
            return ChainResult(
                state, True, "Answer Chain question %s first." % opened)
        parent = value["parent"].strip()
        if parent and parent not in _keys(state, "answer"):
            return ChainResult(state, False, "Parent question is not answered.")
        return ChainResult(
            _append(state, kind, request.key, _compact(value), True),
            True, "Chain question %s needs one user answer." % request.key)

    if kind == "answer":
        opened = _open_question(state)
        if not opened:
            return ChainResult(state, False, "Chain has no open question.")
        if request.key.strip() != opened:
            return ChainResult(
                state, True, "Current Chain question is %s." % opened)
        if not request.value.strip():
            return ChainResult(state, True, "Chain answer must not be empty.")
        return ChainResult(
            _append(state, kind, opened, request.value.strip(), True),
            False, "Recorded the current Chain user answer.")

    if kind == "contract":
        error = _validate_key(request, "contract")
        value = _object(request.value)
        error = error or _required_fields(
            value, ("shape", "fields", "error_semantics"))
        repositories = value.get("repositories")
        if (not isinstance(repositories, list) or len(repositories) < 2
                or any(item not in _keys(state, "repository")
                       for item in repositories)):
            error = error or "repositories must name at least two known repositories"
        if error:
            return ChainResult(state, False, error)
        if request.key in _keys(state, kind):
            return ChainResult(state, False, "Contract key already exists.")
        return ChainResult(
            _append(state, kind, request.key, _compact(value), True),
            False, "Recorded one exact interface contract.")

    if kind == "dependency":
        error = _validate_key(request, "dependency")
        value = _object(request.value)
        error = error or _required_fields(
            value, ("from", "to", "order", "parallel", "integration"))
        known = set(_keys(state, "repository"))
        if value.get("from") not in known or value.get("to") not in known:
            error = error or "dependency repositories must be known"
        if error:
            return ChainResult(state, False, error)
        if request.key in _keys(state, kind):
            return ChainResult(state, False, "Dependency key already exists.")
        return ChainResult(
            _append(state, kind, request.key, _compact(value), True),
            False, "Recorded dependency and integration order.")

    if kind == "reverse-check":
        if request.key not in _keys(state, "repository"):
            return ChainResult(state, False, "Reverse-check repository is unknown.")
        value = _object(request.value)
        if value.get("independent") is not True:
            return ChainResult(state, True, "Repository is not independently startable.")
        if not isinstance(value.get("reason"), str) or not value["reason"].strip():
            return ChainResult(state, False, "Reverse-check reason is required.")
        base = replace(
            _without_results(state),
            records=tuple(
                item for item in _without_results(state).records
                if not (item.kind == kind and item.key == request.key)),
        )
        return ChainResult(
            _append(base, kind, request.key, _compact(value), True),
            False, "Repository passed the independent-start reverse-check.")

    if kind == "citations-verified":
        value = _object(request.value)
        if (value.get("count") != len(_records(state, "touchpoint"))
                or not isinstance(value.get("digest"), str)
                or not _DIGEST.fullmatch(value.get("digest", ""))):
            return ChainResult(state, False, "Citation receipt is invalid.")
        return ChainResult(
            _append(state, kind, "", _compact(value), True),
            False, "Verified every current Chain citation.")

    if kind == "rendered":
        gaps = chain_completion_gaps(state, require_rendered=False)
        if gaps:
            return ChainResult(state, False, gaps[0])
        value = _object(request.value)
        if (not isinstance(value.get("sha256"), str)
                or not _DIGEST.fullmatch(value["sha256"])):
            return ChainResult(state, False, "Rendered Chain digest is invalid.")
        return ChainResult(
            _append(_without_results(state), kind, "", _compact(value)),
            False, "Recorded the rendered Chain document digest.")

    if kind == "confirmed":
        gaps = chain_completion_gaps(state)
        if gaps:
            return ChainResult(state, False, gaps[0])
        if not request.value.strip():
            return ChainResult(state, True, "Chain confirmation must not be empty.")
        base = replace(
            state,
            records=tuple(item for item in state.records if item.kind != kind),
        )
        return ChainResult(
            _append(base, kind, "", request.value.strip()),
            False, "User confirmed the cross-repository Chain contract.")

    return ChainResult(state, False, "Unknown Chain event.")

