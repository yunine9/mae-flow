"""Pure task-card document and state-record contracts."""

from dataclasses import dataclass, field
import hashlib


EXPECTED_STEPS = {
    "COMPILE": {
        "build",
        "rf_fix",
        "rf_compile",
        "tw_change",
        "tw_compile",
        "verify_recompile",
        "verify_post_ponytail_compile",
    },
    "CODECHECK": {
        "verify_codecheck",
        "tw_codecheck",
        "rf_codecheck",
        "rf_verify",
    },
    "UT": {
        "verify_ut",
        "rf_ut",
        "tw_ut",
        "rf_verify",
    },
}


def task_allowed(kind, step):
    return step in EXPECTED_STEPS.get(
        str(kind).upper(),
        set(),
    )


@dataclass
class TaskCardDocument:
    lines: list = field(default_factory=list)

    def __iter__(self):
        return iter(self.lines)

    def __iadd__(self, lines):
        self.extend(lines)
        return self

    def append(self, line):
        self.lines.append(line)

    def extend(self, lines):
        self.lines.extend(lines)

    def body(self):
        return "\n".join(self.lines).rstrip() + "\n"

    def digest(self):
        return hashlib.sha256(
            self.body().encode("utf-8")
        ).hexdigest()

    def sealed_body(self):
        return (
            self.body()
            + "TASK_CARD_SHA256: "
            + self.digest()
            + "\n"
        )


def task_record(
    *,
    step,
    path,
    digest,
    head,
    scope,
    checkpoint,
    precommit_review,
    initial_compile_net,
    source_snapshot,
    allowed_files,
    task_files,
    execution_roots,
    lightcheck,
    ut_targets,
    unchanged_initial_dirty,
    at,
):
    return {
        "step": step,
        "path": path,
        "sha256": digest,
        "head": head,
        "scope": scope,
        "checkpoint": checkpoint,
        "precommit_review": precommit_review,
        "initial_compile_net": initial_compile_net,
        "source_snapshot": dict(source_snapshot),
        "allowed_files": list(allowed_files),
        "task_files": list(task_files),
        "execution_roots": list(execution_roots),
        "lightcheck": dict(lightcheck),
        "ut_targets": {
            key: [dict(item) for item in value]
            for key, value in ut_targets.items()
        },
        "unchanged_initial_dirty": list(
            unchanged_initial_dirty),
        "at": at,
    }
