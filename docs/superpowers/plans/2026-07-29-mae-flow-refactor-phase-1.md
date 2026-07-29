# Mae-Flow Refactor Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变任何外部行为的前提下，建立 Mae-Flow 新旧差分 Oracle 和架构门禁，并把 CLI/Hook 重复的指纹、源码路径及 Git 意图逻辑迁入共享底座。

**Architecture:** 保留 `scripts/mae-flow.py` 和 `hooks/dispatch.py` 作为稳定入口；新代码进入 `scripts/mae_flow_core/foundation/`，旧私有函数暂时保留为薄委托。差分测试捕获输出、状态、文件和 Git 副作用，任何未解释差异都阻断迁移。

**Tech Stack:** Python 3.8+ 标准库、`unittest`、Git CLI、现有 Mae-Flow selftest。

## Global Constraints

- 生产运行时零新增依赖；不得引入 Pydantic、Click、Hypothesis、pytest 或其他第三方包。
- Windows/Git Bash 是一等环境；路径大小写、分隔符、GBK/UTF-8 和 PATHEXT 行为不得退化。
- CLI、Hook、状态 JSON、sidecar、输出、退出码、Git 副作用和旧状态恢复必须与基线 `d5e7d7b2cb5d3def06d21df79fb3069efea94f16` 兼容。
- 重构提交不得修复疑似 Bug；疑似 Bug只进入 findings ledger。
- 新生产模块软上限 500 行；新普通函数圈复杂度软上限 15。
- 每个生产改动必须先有会因共享实现缺失而失败的测试，并实际观察 RED。
- 每个任务独立提交；旧包装只能委托共享实现，不能保留第二份规则。

---

## File Map

**Create**

- `scripts/tests/differential/__init__.py`：差分测试包。
- `scripts/tests/differential/normalize.py`：动态值白名单归一化。
- `scripts/tests/differential/snapshot.py`：命令、文件、状态和 Git 快照。
- `scripts/tests/differential/runner.py`：隔离仓库执行器与 golden 比较。
- `scripts/tests/differential/scenarios.py`：第一期公开行为场景。
- `scripts/tests/differential/goldens/phase1.json`：固定基线结果。
- `scripts/tests/test_differential_harness.py`：差分框架单元和黑盒测试。
- `scripts/tests/architecture_rules.py`：标准库 AST 依赖检查。
- `scripts/tests/architecture_baseline.json`：现有大入口禁止净增长基线。
- `scripts/tests/test_architecture.py`：架构门禁测试。
- `scripts/mae_flow_core/foundation/__init__.py`：共享底座导出。
- `scripts/mae_flow_core/foundation/fingerprints.py`：文件和检视指纹。
- `scripts/mae_flow_core/foundation/source_paths.py`：源码、构建和仓库相对路径分类。
- `scripts/mae_flow_core/foundation/git_intent.py`：纯 Git/Bash 意图解析。
- `docs/superpowers/mae-flow-refactor-findings.md`：疑似 Bug 与设计偏差账本。

**Modify**

- `scripts/mae-flow.py`：把对应私有函数改为共享底座薄委托。
- `hooks/dispatch.py`：把对应私有函数改为共享底座薄委托。
- `scripts/tests/test_checkpoints.py`：增加共享指纹与旧包装等价测试。
- `scripts/tests/test_task_scope.py`：增加共享源码分类与 Git 意图等价测试。
- `scripts/selftest.py`：执行新增差分和架构测试。

---

### Task 1: Differential Normalization and Snapshot Model

**Files:**

- Create: `scripts/tests/differential/__init__.py`
- Create: `scripts/tests/differential/normalize.py`
- Create: `scripts/tests/differential/snapshot.py`
- Create: `scripts/tests/test_differential_harness.py`

**Interfaces:**

- Produces: `normalize_text(text, replacements) -> str`
- Produces: `normalize_value(value, replacements) -> object`
- Produces: `Snapshot(stdout, stderr, returncode, files, state, git)`
- Produces: `Snapshot.to_dict() -> dict` and `Snapshot.from_dict(data) -> Snapshot`

- [ ] **Step 1: Write normalization tests**

Add these tests to `scripts/tests/test_differential_harness.py`:

```python
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts", "tests"))

from differential.normalize import normalize_text, normalize_value
from differential.snapshot import Snapshot


class DifferentialNormalizationTests(unittest.TestCase):
    def test_normalize_text_replaces_only_explicit_dynamic_values(self):
        replacements = {
            "/tmp/mf-123": "<TMP>",
            "2026-07-29 12:34:56": "<TIME>",
            "receipt-abcd": "<RECEIPT>",
        }
        actual = normalize_text(
            "path=/tmp/mf-123 at=2026-07-29 12:34:56 "
            "id=receipt-abcd semantic=2026-07-29",
            replacements,
        )
        self.assertEqual(
            "path=<TMP> at=<TIME> id=<RECEIPT> semantic=2026-07-29",
            actual,
        )

    def test_normalize_value_preserves_types_and_unknown_fields(self):
        source = {
            "path": "/tmp/mf-123/state.json",
            "nested": [{"at": "2026-07-29 12:34:56", "count": 2}],
            "unknown": {"keep": True},
        }
        actual = normalize_value(
            source,
            {
                "/tmp/mf-123": "<TMP>",
                "2026-07-29 12:34:56": "<TIME>",
            },
        )
        self.assertEqual(
            {
                "path": "<TMP>/state.json",
                "nested": [{"at": "<TIME>", "count": 2}],
                "unknown": {"keep": True},
            },
            actual,
        )

    def test_snapshot_round_trip_is_lossless(self):
        snapshot = Snapshot(
            stdout="out",
            stderr="err",
            returncode=2,
            files={"a.txt": {"sha256": "abc", "size": 3}},
            state={"flow": {"current": "build", "unknown": 7}},
            git={"branch": "main", "head": "deadbeef", "status": ""},
        )
        self.assertEqual(snapshot, Snapshot.from_dict(snapshot.to_dict()))
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
python3 -m unittest scripts.tests.test_differential_harness -v
```

Expected: import failure for missing `differential.normalize` or `differential.snapshot`.

- [ ] **Step 3: Implement the normalizer and snapshot**

Create `scripts/tests/differential/normalize.py`:

```python
def normalize_text(text, replacements):
    result = str(text or "")
    for source, target in sorted(
            replacements.items(), key=lambda item: len(item[0]), reverse=True):
        if source:
            result = result.replace(source, target)
    return result


def normalize_value(value, replacements):
    if isinstance(value, dict):
        return {
            key: normalize_value(item, replacements)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize_value(item, replacements) for item in value]
    if isinstance(value, tuple):
        return tuple(normalize_value(item, replacements) for item in value)
    if isinstance(value, str):
        return normalize_text(value, replacements)
    return value
```

Create `scripts/tests/differential/snapshot.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Snapshot:
    stdout: str
    stderr: str
    returncode: int
    files: dict
    state: dict
    git: dict

    def to_dict(self):
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "files": self.files,
            "state": self.state,
            "git": self.git,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            stdout=data["stdout"],
            stderr=data["stderr"],
            returncode=int(data["returncode"]),
            files=dict(data["files"]),
            state=dict(data["state"]),
            git=dict(data["git"]),
        )
```

Create an empty `scripts/tests/differential/__init__.py`.

- [ ] **Step 4: Run the test and verify GREEN**

Run:

```bash
python3 -m unittest scripts.tests.test_differential_harness -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/tests/differential scripts/tests/test_differential_harness.py
git commit -m "test: add differential snapshot primitives"
```

---

### Task 2: Isolated Scenario Runner and Baseline Goldens

**Files:**

- Create: `scripts/tests/differential/runner.py`
- Create: `scripts/tests/differential/scenarios.py`
- Create: `scripts/tests/differential/goldens/phase1.json`
- Modify: `scripts/tests/test_differential_harness.py`

**Interfaces:**

- Consumes: `Snapshot`, `normalize_value`
- Produces: `run_scenario(implementation_root, scenario_name) -> Snapshot`
- Produces: `load_goldens(path) -> Dict[str, Snapshot]`
- Produces: `assert_matches_golden(testcase, name, actual, goldens) -> None`

- [ ] **Step 1: Write runner contract tests**

Add:

```python
from differential.runner import (
    assert_matches_golden,
    load_goldens,
    run_scenario,
)


class DifferentialRunnerTests(unittest.TestCase):
    def test_phase1_scenarios_match_fixed_baseline(self):
        golden_path = os.path.join(
            ROOT, "scripts", "tests", "differential", "goldens",
            "phase1.json",
        )
        goldens = load_goldens(golden_path)
        for name in (
                "inactive_pretooluse_bypass",
                "terminal_status",
                "corrupt_state_doctor"):
            with self.subTest(name=name):
                actual = run_scenario(ROOT, name)
                assert_matches_golden(self, name, actual, goldens)

    def test_unknown_scenario_is_rejected_without_running_process(self):
        with self.assertRaisesRegex(ValueError, "unknown scenario"):
            run_scenario(ROOT, "not-registered")
```

- [ ] **Step 2: Run the runner tests and verify RED**

Run:

```bash
python3 -m unittest \
  scripts.tests.test_differential_harness.DifferentialRunnerTests -v
```

Expected: import failure for missing `differential.runner`.

- [ ] **Step 3: Implement repository capture**

Implement `runner.py` with these exact responsibilities:

```python
import hashlib
import json
import os
import subprocess
import tempfile

from differential.normalize import normalize_value
from differential.snapshot import Snapshot
from differential.scenarios import SCENARIOS


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _capture_files(root):
    result = {}
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(
            name for name in dirs
            if name not in {".git", "__pycache__"})
        for name in sorted(files):
            absolute = os.path.join(current, name)
            relative = os.path.relpath(absolute, root).replace("\\", "/")
            result[relative] = {
                "sha256": _sha256(absolute),
                "size": os.path.getsize(absolute),
            }
    return result


def _read_states(root):
    result = {}
    for name in sorted(os.listdir(root)):
        if not name.startswith(".mae-flow"):
            continue
        path = os.path.join(root, name)
        if not os.path.isfile(path) or name.endswith(".jsonl"):
            continue
        try:
            with open(path, encoding="utf-8-sig") as stream:
                result[name] = json.load(stream)
        except Exception as exc:
            result[name] = {
                "__unreadable__": "%s: %s" %
                (type(exc).__name__, exc),
            }
    return result


def _git(root, *args):
    return subprocess.run(
        ["git", *args], cwd=root, text=True,
        encoding="utf-8", errors="replace",
        capture_output=True, check=False,
    ).stdout.strip()


def run_scenario(implementation_root, scenario_name):
    if scenario_name not in SCENARIOS:
        raise ValueError("unknown scenario: " + scenario_name)
    with tempfile.TemporaryDirectory(prefix="mae-flow-diff-") as project:
        invocation, replacements = SCENARIOS[scenario_name](
            project, implementation_root)
        completed = subprocess.run(
            invocation["argv"],
            cwd=project,
            input=invocation.get("stdin", ""),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            env=invocation["env"],
            timeout=30,
        )
        replacements = dict(replacements)
        replacements[project.replace("\\", "/")] = "<PROJECT>"
        replacements[os.path.abspath(implementation_root).replace(
            "\\", "/")] = "<IMPLEMENTATION>"
        snapshot = Snapshot(
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
            files=_capture_files(project),
            state=_read_states(project),
            git={
                "branch": _git(project, "branch", "--show-current"),
                "head": _git(project, "rev-parse", "--verify", "HEAD"),
                "status": _git(
                    project, "-c", "core.quotepath=false",
                    "status", "--porcelain", "--untracked-files=all"),
            },
        )
        return Snapshot.from_dict(
            normalize_value(snapshot.to_dict(), replacements))


def load_goldens(path):
    with open(path, encoding="utf-8") as stream:
        raw = json.load(stream)
    return {name: Snapshot.from_dict(value) for name, value in raw.items()}


def assert_matches_golden(testcase, name, actual, goldens):
    testcase.assertIn(name, goldens)
    testcase.assertEqual(goldens[name], actual)
```

- [ ] **Step 4: Implement three deterministic scenarios**

Create `scenarios.py`. Each setup initializes a local Git repository with
`user.name=Mae Flow Diff`, `user.email=diff@example.invalid`, one committed
`README.md`, fixed author/committer dates `2026-07-29T00:00:00+00:00`, and
`PYTHONDONTWRITEBYTECODE=1`. Fixed dates make the initial Git HEAD identical
on every platform. Initialize with `git init -q`, immediately run
`git checkout -qb main`, then configure identity and commit; this prevents
the user's global `init.defaultBranch` from changing captured output.
Register:

```python
SCENARIOS = {
    "inactive_pretooluse_bypass": inactive_pretooluse_bypass,
    "terminal_status": terminal_status,
    "corrupt_state_doctor": corrupt_state_doctor,
}
```

The exact invocations are:

```python
# inactive_pretooluse_bypass
[
    sys.executable,
    os.path.join(implementation_root, "hooks", "dispatch.py"),
    "pretooluse",
]
# stdin:
json.dumps({
    "cwd": project,
    "tool_name": "Edit",
    "tool_input": {"file_path": os.path.join(project, "README.md")},
}) + "\n"

# terminal_status
[
    sys.executable,
    os.path.join(implementation_root, "scripts", "mae-flow.py"),
    "status",
]
# setup state, written directly as deterministic valid JSON:
{
    "schema_version": 2,
    "revision": 1,
    "updated_at": "2026-07-29 10:00:00",
    "current": "end",
    "config": {"单号": "REQ-DIFF", "分支名": "main"},
    "choices": {"workflow": "tweak"},
    "history": [],
    "started": "2026-07-29 10:00:00",
}

# corrupt_state_doctor
[
    sys.executable,
    os.path.join(implementation_root, "scripts", "mae-flow.py"),
    "doctor",
]
# setup bytes:
b"{broken"
```

Write the terminal fixture directly with sorted, indented UTF-8 JSON so its
revision and timestamp remain deterministic. Write corrupt bytes directly for
the corrupt fixture because corruption is the behavior under test.

- [ ] **Step 5: Generate and inspect fixed goldens**

Add a `__main__` block to `runner.py` accepting:

```text
python3 scripts/tests/differential/runner.py \
  --implementation-root <repo> \
  --write-goldens scripts/tests/differential/goldens/phase1.json
```

The writer must sort scenario names and JSON keys, use `ensure_ascii=False`,
indent 2, and append one newline. Without `--write-goldens`, the command loads
`scripts/tests/differential/goldens/phase1.json` by default, compares all
registered scenarios, prints one unified JSON diff per mismatch, and exits 1
on any difference. An optional `--goldens <path>` overrides that default.
Run write mode against the current checkout, then inspect every captured
stdout, stderr, state and Git field:

```bash
python3 scripts/tests/differential/runner.py \
  --implementation-root . \
  --write-goldens scripts/tests/differential/goldens/phase1.json
git diff -- scripts/tests/differential/goldens/phase1.json
```

Expected: three named scenarios; no absolute temporary or implementation paths.

- [ ] **Step 6: Run the differential tests and verify GREEN**

```bash
python3 -m unittest scripts.tests.test_differential_harness -v
```

Expected: all Task 1 and Task 2 tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/tests/differential scripts/tests/test_differential_harness.py
git commit -m "test: capture phase one behavior oracle"
```

---

### Task 3: Architecture Dependency and Growth Guards

**Files:**

- Create: `scripts/tests/architecture_rules.py`
- Create: `scripts/tests/architecture_baseline.json`
- Create: `scripts/tests/test_architecture.py`

**Interfaces:**

- Produces: `module_imports(path) -> set[str]`
- Produces: `forbidden_calls(path) -> list[str]`
- Produces: `line_count(path) -> int`
- Produces: `assert_foundation_dependencies(root) -> list[str]`

- [ ] **Step 1: Write failing architecture tests**

```python
import json
import os
import sys
import unittest

TESTS = os.path.abspath(os.path.dirname(__file__))
if TESTS not in sys.path:
    sys.path.insert(0, TESTS)

from architecture_rules import (  # noqa: E402
    assert_foundation_dependencies,
    line_count,
)


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class ArchitectureTests(unittest.TestCase):
    def test_existing_monoliths_do_not_grow(self):
        baseline_path = os.path.join(
            ROOT, "scripts", "tests", "architecture_baseline.json")
        with open(baseline_path, encoding="utf-8") as stream:
            baseline = json.load(stream)
        for relative, maximum in baseline["max_lines"].items():
            with self.subTest(relative=relative):
                self.assertLessEqual(
                    line_count(os.path.join(ROOT, relative)), maximum)

    def test_foundation_has_no_reverse_dependencies(self):
        self.assertEqual([], assert_foundation_dependencies(ROOT))
```

Create `architecture_baseline.json` with:

```json
{
  "max_lines": {
    "scripts/mae-flow.py": 10653,
    "hooks/dispatch.py": 2860
  }
}
```

This first guard covers production entrypoints. `selftest.py` receives two new
safety-suite registrations in Task 7, so its reduction remains a later
dedicated migration rather than a misleading phase-one line budget.

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest scripts.tests.test_architecture -v
```

Expected: import failure for missing `scripts.tests.architecture_rules`.

- [ ] **Step 3: Implement AST checks**

`assert_foundation_dependencies` must scan
`scripts/mae_flow_core/foundation/**/*.py` and report:

- imports beginning with `mae_flow_core.workflow`;
- imports beginning with `mae_flow_core.delivery`;
- imports beginning with `mae_flow_core.quality`;
- imports beginning with `mae_flow_core.guard`;
- calls to `print`, `sys.exit`, `os.chdir`, `subprocess.run`,
  `subprocess.Popen`, or `subprocess.call`.

Return messages formatted as:

```text
<repo-relative-path>:<line>: forbidden import <name>
<repo-relative-path>:<line>: forbidden call <name>
```

Keep all traversal in `architecture_rules.py` using `ast`, `os`, and `pathlib`.

- [ ] **Step 4: Run and verify GREEN**

```bash
python3 -m unittest scripts.tests.test_architecture -v
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add \
  scripts/tests/architecture_rules.py \
  scripts/tests/architecture_baseline.json \
  scripts/tests/test_architecture.py
git commit -m "test: enforce refactor architecture boundaries"
```

---

### Task 4: Shared File Fingerprints

**Files:**

- Create: `scripts/mae_flow_core/foundation/__init__.py`
- Create: `scripts/mae_flow_core/foundation/fingerprints.py`
- Modify: `scripts/mae-flow.py:724-780`
- Modify: `hooks/dispatch.py:1997-2054`
- Modify: `scripts/tests/test_checkpoints.py`

**Interfaces:**

- Produces: `path_fingerprint(path) -> str`
- Produces: `review_path_fingerprint(path) -> str`
- Preserves: `mf._path_fingerprint`, `mf._review_path_fingerprint`
- Preserves: `dispatch._path_fingerprint`, `dispatch._review_path_fingerprint`

- [ ] **Step 1: Write failing shared-implementation tests**

Add:

```python
from mae_flow_core.foundation import fingerprints


def test_main_and_hook_delegate_to_shared_fingerprints(self):
    path = os.path.join(self.repo, "src", "main.cpp")
    shared = fingerprints.review_path_fingerprint(path)
    self.assertEqual(shared, mf._review_path_fingerprint(path))
    self.assertEqual(shared, dispatch._review_path_fingerprint(path))
    self.assertIs(
        mf._review_path_fingerprint.__wrapped__,
        fingerprints.review_path_fingerprint,
    )
    self.assertIs(
        dispatch._review_path_fingerprint.__wrapped__,
        fingerprints.review_path_fingerprint,
    )
```

The production wrappers must expose `__wrapped__` manually without importing
`functools.wraps`, so tests can prove there is one implementation.

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest \
  scripts.tests.test_checkpoints.CheckpointTests.test_main_and_hook_delegate_to_shared_fingerprints -v
```

Expected: import failure for missing `mae_flow_core.foundation`.

- [ ] **Step 3: Move the exact algorithms to foundation**

Copy the current algorithms without semantic edits into
`foundation/fingerprints.py`:

```python
import hashlib
import os


def path_fingerprint(path):
    h = hashlib.sha256()
    absolute = os.path.abspath(path)
    try:
        if os.path.isfile(absolute):
            h.update(b"file\0")
            with open(absolute, "rb") as stream:
                for chunk in iter(
                        lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
        elif os.path.isdir(absolute):
            h.update(b"dir\0")
            for name in sorted(os.listdir(absolute)):
                child = os.path.join(absolute, name)
                stat = os.stat(child)
                h.update((
                    name + "\0" + str(stat.st_size) + "\0"
                    + str(stat.st_mtime_ns)
                ).encode("utf-8", errors="replace"))
        else:
            h.update(b"missing\0")
    except OSError as exc:
        h.update(("error:" + str(exc)).encode(
            "utf-8", errors="replace"))
    return h.hexdigest()


def _update_review_hash(digest, absolute, path_stat):
    git_mode = path_stat.st_mode & 0o170000
    executable = bool(path_stat.st_mode & 0o100)
    digest.update(("type:%o\0exec:%d\0" % (
        git_mode, executable)).encode("ascii"))
    if os.path.islink(absolute):
        digest.update(b"symlink\0")
        digest.update(os.readlink(absolute).encode(
            "utf-8", errors="surrogateescape"))
        return
    if os.path.isfile(absolute):
        digest.update(b"file\0")
        with open(absolute, "rb") as stream:
            for chunk in iter(
                    lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return
    digest.update(
        b"dir\0" if os.path.isdir(absolute) else b"other\0")


def review_path_fingerprint(path):
    digest = hashlib.sha256()
    absolute = os.path.abspath(path)
    try:
        _update_review_hash(digest, absolute, os.lstat(absolute))
    except FileNotFoundError:
        digest.update(b"missing\0")
    except OSError as exc:
        digest.update(("error:" + str(exc)).encode(
            "utf-8", errors="replace"))
    return digest.hexdigest()
```

- [ ] **Step 4: Replace old bodies with thin wrappers**

In both entry files:

```python
from mae_flow_core.foundation.fingerprints import (
    path_fingerprint as _shared_path_fingerprint,
    review_path_fingerprint as _shared_review_path_fingerprint,
)


def _path_fingerprint(path):
    return _shared_path_fingerprint(path)


_path_fingerprint.__wrapped__ = _shared_path_fingerprint


def _review_path_fingerprint(path):
    return _shared_review_path_fingerprint(path)


_review_path_fingerprint.__wrapped__ = _shared_review_path_fingerprint
```

Delete both duplicate `_update_review_hash` definitions.

- [ ] **Step 5: Run focused and differential tests**

```bash
python3 -m unittest \
  scripts.tests.test_checkpoints \
  scripts.tests.test_commit_ownership \
  scripts.tests.test_differential_harness -v
```

Expected: all tests pass and phase-one goldens remain unchanged.

- [ ] **Step 6: Run architecture tests**

```bash
python3 -m unittest scripts.tests.test_architecture -v
```

Expected: foundation has no reverse dependency or forbidden call.

- [ ] **Step 7: Commit**

```bash
git add \
  scripts/mae_flow_core/foundation \
  scripts/mae-flow.py \
  hooks/dispatch.py \
  scripts/tests/test_checkpoints.py
git commit -m "refactor: share file fingerprint implementation"
```

---

### Task 5: Shared Source Path Classification

**Files:**

- Create: `scripts/mae_flow_core/foundation/source_paths.py`
- Modify: `scripts/mae-flow.py:903-1006`
- Modify: `hooks/dispatch.py:2060-2120`
- Modify: `scripts/tests/test_task_scope.py`
- Modify: `scripts/selftest.py:2400-2440`

**Interfaces:**

- Produces: `normalize_path(path) -> str`
- Produces: `repo_relative_for_match(path, project_root) -> Optional[str]`
- Produces: `is_build_path(path) -> bool`
- Produces: `is_source_path(path, patterns, project_root=None, require_membership=False) -> bool`
- Preserves: `mf.norm`, `mf._repo_rel_for_match`, `mf._is_build_path`, `mf._is_source_path`
- Preserves: `dispatch._source_like`

- [ ] **Step 1: Write direct shared-classifier tests**

Add a table-driven test covering:

```python
cases = [
    ("src/main.cpp", True),
    ("include/api.hpp", True),
    ("CMakeLists.txt", True),
    ("package-lock.json", True),
    ("src/README.md", False),
    ("docs/design.md", False),
    ("module/custom.file", True),
]
patterns = [r"(^|/)src/", r"(^|/)include/", r"^module/"]
for path, expected in cases:
    with self.subTest(path=path):
        self.assertEqual(
            expected,
            source_paths.is_source_path(path, patterns),
        )
```

Add Windows and membership cases:

```python
self.assertEqual(
    "src/main.cpp",
    source_paths.repo_relative_for_match(
        os.path.join(self.repo, "src", "main.cpp"), self.repo),
)
self.assertIsNone(source_paths.repo_relative_for_match(
    os.path.abspath(os.path.join(self.repo, "..", "outside.py")),
    self.repo,
))
self.assertFalse(source_paths.is_source_path(
    os.path.abspath(os.path.join(self.repo, "..", "outside.py")),
    [r"(^|/)src/"],
    project_root=self.repo,
    require_membership=True,
))
```

Finally assert old wrappers equal the shared classifier for the existing
cross-language matrix.

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest \
  scripts.tests.test_task_scope.TaskScopeTests.test_shared_source_classifier_contract -v
```

Expected: import failure for missing `foundation.source_paths`.

- [ ] **Step 3: Implement pure classification**

Move the current extension, build filename and build extension constants into
`source_paths.py`. Implement in this order:

```python
def is_source_path(path, patterns, project_root=None,
                   require_membership=False):
    normalized = normalize_path(path).strip().strip("\"'")
    if normalized.endswith("(未提交)"):
        normalized = normalized[:-len("(未提交)")]
    relative = (
        repo_relative_for_match(normalized, project_root)
        if project_root else
        re.sub(r"^(?:\./)+", "", normalized)
    )
    if require_membership and is_absolute_path(
            normalized) and relative is None:
        return False
    if is_build_path(normalized) or normalized.lower().endswith(
            SOURCE_EXTENSIONS):
        return True
    if normalized.lower().endswith(
            (".md", ".rst", ".adoc", ".txt")):
        return False
    if relative is None:
        return False
    return any(matches_pattern(relative, pattern)
               for pattern in patterns)
```

`repo_relative_for_match` must preserve the current raw-path plus realpath
fallback and case-insensitive root comparison; do not use `os.path.relpath`
for absolute paths because Windows cross-drive paths are part of the contract.
`is_absolute_path` must recognize both POSIX `/...` paths and
`^[A-Za-z]:/` Windows drive paths even when the test itself runs on macOS or
Linux.

- [ ] **Step 4: Convert main and Hook to adapters**

Keep config/defaults loading and its current stderr/log behavior in each
entrypoint. Pass only the resulting pattern list to the shared classifier:

```python
def _is_source_path(path, st=None, flow=None):
    patterns = list(
        (flow or FLOW or {}).get("source_patterns", []))
    patterns.extend(_configured_source_patterns(st))
    return source_paths.is_source_path(
        path,
        patterns,
        project_root=os.getcwd(),
        require_membership=True,
    )
```

For Hook, pass its existing common directory patterns plus state/defaults
patterns with `require_membership=False`, preserving its contract-state
loading and logging outside the shared module.

- [ ] **Step 5: Run focused, selftest classifier, and differential tests**

```bash
python3 -m unittest \
  scripts.tests.test_task_scope \
  scripts.tests.test_checkpoints \
  scripts.tests.test_differential_harness -v
python3 scripts/selftest.py
```

Expected: all tests and selftest pass; no golden changes.

- [ ] **Step 6: Commit**

```bash
git add \
  scripts/mae_flow_core/foundation/source_paths.py \
  scripts/mae-flow.py \
  hooks/dispatch.py \
  scripts/tests/test_task_scope.py \
  scripts/selftest.py
git commit -m "refactor: share source path classification"
```

---

### Task 6: Shared Git Command Intent Parser

**Files:**

- Create: `scripts/mae_flow_core/foundation/git_intent.py`
- Modify: `scripts/mae-flow.py:255-364`
- Modify: `scripts/tests/test_task_scope.py`

**Interfaces:**

- Produces: `git_subcommand_tokens(command, subcommand) -> list[list[str]]`
- Produces: `command_pathspecs(tokens, value_options=None) -> list[str]`
- Produces: `git_add_intent(tokens) -> dict`
- Produces: `git_add_intents(command) -> list[dict]`
- Produces: `git_commit_intent(command) -> dict`
- Preserves all existing `mf._git_*` private call signatures and dictionary keys.

- [ ] **Step 1: Write parser matrix against desired shared API**

```python
matrix = [
    (
        "git add -- src/a.cpp 'src/a b.cpp' && git commit -m x",
        [{
            "pathspecs": ["src/a.cpp", "src/a b.cpp"],
            "force": False,
            "tracked_only": False,
            "all": False,
        }],
        {"pathspecs": [], "all": False, "include": False},
    ),
    (
        "git add -A && git commit -am x",
        [{
            "pathspecs": ["."],
            "force": False,
            "tracked_only": False,
            "all": True,
        }],
        {"pathspecs": [], "all": True, "include": False},
    ),
    (
        "git commit --include -- src/a.cpp",
        [],
        {
            "pathspecs": ["src/a.cpp"],
            "all": False,
            "include": True,
        },
    ),
]
```

Assert the shared parser and old private wrappers return the expected values.
Add malformed quoting:

```python
self.assertEqual(
    [],
    git_intent.git_subcommand_tokens(
        "git add 'unterminated", "add"),
)
```

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest \
  scripts.tests.test_task_scope.TaskScopeTests.test_shared_git_intent_matrix -v
```

Expected: import failure for missing `foundation.git_intent`.

- [ ] **Step 3: Move parser implementation unchanged**

Move `_COMMIT_VALUE_OPTIONS`, `_option_consumes_following`,
`_PathspecCollector`, `_command_pathspecs`, `_git_subcommand_tokens`,
`_git_add_intent`, `_git_add_intents`, `_short_option_flags`, and
`_git_commit_intent` into `foundation/git_intent.py`.

Rename only the shared definitions by removing the leading underscore.
Keep return dictionaries and `shlex.split(..., posix=True)` unchanged.

- [ ] **Step 4: Add thin private wrappers**

Each old private function calls the shared equivalent. Alias
`_PathspecCollector` to `git_intent.PathspecCollector` so code using the
private class continues to work during migration.

- [ ] **Step 5: Run Gate/task-scope and differential coverage**

```bash
python3 -m unittest \
  scripts.tests.test_task_scope \
  scripts.tests.test_commit_ownership \
  scripts.tests.test_differential_harness -v
python3 scripts/tests/probe_gate_smoke.py
```

Expected: all tests and gate probe pass; phase-one goldens remain unchanged.

- [ ] **Step 6: Commit**

```bash
git add \
  scripts/mae_flow_core/foundation/git_intent.py \
  scripts/mae-flow.py \
  scripts/tests/test_task_scope.py
git commit -m "refactor: extract git command intent parser"
```

---

### Task 7: Findings Ledger and Selftest Integration

**Files:**

- Create: `docs/superpowers/mae-flow-refactor-findings.md`
- Modify: `scripts/selftest.py`
- Test: `scripts/tests/test_differential_harness.py`
- Test: `scripts/tests/test_architecture.py`

**Interfaces:**

- Selftest runs `test_differential_harness.py` and `test_architecture.py`.
- Findings use stable IDs `MF-RF-NNN` and never change production behavior.

- [ ] **Step 1: Add selftest expectations before wiring execution**

Add a syntax/list assertion to `test_architecture.py` that reads
`scripts/selftest.py` and requires both filenames:

```python
def test_selftest_runs_refactor_safety_suites(self):
    text = open(
        os.path.join(ROOT, "scripts", "selftest.py"),
        encoding="utf-8",
    ).read()
    self.assertIn("test_differential_harness.py", text)
    self.assertIn("test_architecture.py", text)
```

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest \
  scripts.tests.test_architecture.ArchitectureTests.test_selftest_runs_refactor_safety_suites -v
```

Expected: failure because selftest does not yet name the suites.

- [ ] **Step 3: Wire both suites into selftest**

Add both files to the syntax check list. Add two subprocess checks beside the
existing focused test suites, each using `sys.executable`, captured UTF-8 text,
and a 180-second timeout:

```python
for label, filename in (
        ("行为差分安全网", "test_differential_harness.py"),
        ("重构架构边界", "test_architecture.py")):
    result = subprocess.run(
        [sys.executable, os.path.join(
            ROOT, "scripts", "tests", filename)],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=180,
    )
    check(
        label,
        result.returncode == 0,
        (result.stdout + result.stderr)[-5000:],
    )
```

- [ ] **Step 4: Create the initial findings ledger**

Create the document with two evidence-only entries:

```markdown
# Mae-Flow Refactor Findings

## MF-RF-001: File handles remain open during tests

- Classification: evidence insufficient
- Baseline: d5e7d7b2cb5d3def06d21df79fb3069efea94f16
- Trigger: checkpoint tests reading `.tokens`, `.usermsg`, and step Markdown
- Evidence: Python emits `ResourceWarning: unclosed file`
- Refactor action: none
- Required next step: isolate a deterministic resource-warning test before
  deciding whether this is a user-visible defect

## MF-RF-002: Static next graph does not enumerate every entered step

- Classification: documentation and implementation mismatch
- Baseline: d5e7d7b2cb5d3def06d21df79fb3069efea94f16
- Trigger: enumerate `flow.json` ordinary `next` edges
- Evidence: `moonlight_review`, `rf_verify`, and `verify_recompile` require
  dynamic or compatibility code paths
- Refactor action: none in phase one
- Required next step: register dynamic transition policies in phase two
  without changing their behavior
```

- [ ] **Step 5: Re-run the explicit state-invariant contract**

These existing regression tests pin the transaction and lifecycle semantics
that Phase 1 must not alter:

```bash
python3 -m unittest \
  scripts.tests.test_state_core.RuntimeAndStateTests.test_runtime_matrix_schema_and_corrupt_preservation \
  scripts.tests.test_state_core.RuntimeAndStateTests.test_compare_and_swap_rejects_stale_snapshot \
  scripts.tests.test_state_core.RuntimeAndStateTests.test_concurrent_read_modify_write_does_not_lose_updates \
  scripts.tests.test_state_core.RuntimeAndStateTests.test_corrupt_sidecar_is_quarantined_not_deadlocked \
  scripts.tests.test_state_core.RuntimeAndStateTests.test_terminal_flow_keeps_cli_state_but_all_hooks_bypass \
  scripts.tests.test_state_core.RuntimeAndStateTests.test_namespaced_slash_exit_and_terminal_exit_are_safe \
  -v
```

Expected: all six tests pass; corruption preservation, compare-and-swap,
concurrent updates, terminal bypass, and namespaced/terminal exit behavior
remain unchanged.

- [ ] **Step 6: Run focused integration**

```bash
python3 -m unittest \
  scripts.tests.test_differential_harness \
  scripts.tests.test_architecture -v
```

Expected: all safety-net tests pass.

- [ ] **Step 7: Run the complete phase verification**

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
python3 scripts/selftest.py
git diff --check
git status --short
```

Expected:

- all unit tests pass with zero failures;
- selftest ends with `全部通过`;
- no whitespace errors;
- only the intended Task 7 files are uncommitted.

- [ ] **Step 8: Commit**

```bash
git add \
  docs/superpowers/mae-flow-refactor-findings.md \
  scripts/selftest.py \
  scripts/tests/test_architecture.py
git commit -m "test: integrate refactor safety gates"
```

---

## Phase 1 Completion Review

- [ ] Verify every phase-one requirement in
  `docs/superpowers/specs/2026-07-29-mae-flow-refactor-design.md` sections
  10-15 has a corresponding task or explicit later-phase exclusion.
- [ ] Run `git log --oneline d5e7d7b..HEAD` and confirm no `fix:` commit is
  mixed into phase one.
- [ ] Run the complete unit suite and selftest again from a clean process.
- [ ] Run `python3 scripts/tests/differential/runner.py
  --implementation-root .` in compare-only mode and confirm zero golden
  differences.
- [ ] Run the bundled Lizard report on the new foundation modules and confirm
  no new ordinary function exceeds CCN 15.
- [ ] Inspect `git diff d5e7d7b..HEAD -- scripts/mae-flow.py
  hooks/dispatch.py` and confirm every changed legacy function is a thin
  delegation or import change.
- [ ] Confirm `git status --short` is clean.
