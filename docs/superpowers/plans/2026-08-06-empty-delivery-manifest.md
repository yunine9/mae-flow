# Empty Delivery Manifest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让领域归档 `unchanged` 的合法交付无需伪造文件或空提交即可从最终检视进入 push，并清除新流程中的旧分段编译误导。

**Architecture:** 在现有 `delivery_manifest` 状态中增加显式 `no_changes` 变体，不增加流程节点。CLI 只在领域归档已应用且无新增脏文件时创建该变体；交付证据对它执行零文件复核后放行。普通非空 manifest 的确认、暂存和提交路径保持不变。

**Tech Stack:** Python 3 标准库、`unittest`、现有 Mae-Flow JSON 状态机与 Git 事实端口。

## Global Constraints

- 不迁移旧 CP 在途状态，不读取或恢复旧 checkpoint 任务。
- 不允许把已提交源码重新加入最终 manifest。
- 不制造空 Git 提交，不放宽非空 manifest 的精确文件门禁。
- Windows 用户可见命令继续使用 `python`，输出尊重宿主 CP936/GBK 编码。

---

### Task 1: 受约束的空交付清单

**Files:**
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Modify: `scripts/mae_flow_core/cli_commands/delivery_manifest.py`
- Modify: `scripts/mae_flow_core/delivery/evidence.py`
- Modify: `flow/steps/delivery_review.md`
- Test: `scripts/tests/test_delivery_confirmation.py`
- Test: `scripts/tests/test_delivery_commit_cycle.py`
- Test: `scripts/tests/test_quality_flow_redlines.py`

**Interfaces:**
- Consumes: `state["domain_archive"]`, `api._dirty_paths()`, `api._unchanged_initial_dirty(path, state)`。
- Produces: `manifest set --unchanged --target <branch>` 和 `delivery_manifest.no_changes: true`。

- [ ] **Step 1: Write failing parser and pure-policy tests**

```python
args = parse_args(["manifest", "set", "--unchanged", "--target", "main"])
self.assertTrue(args.unchanged)

manifest = build_unchanged_delivery_manifest(
    applied_unchanged_state, "main", current_dirty=())
self.assertEqual([], manifest["files"])
self.assertTrue(manifest["confirmed"])
self.assertTrue(manifest["no_changes"])
```

同时断言领域归档未应用、`applied_paths` 非空和存在新增脏文件时分别拒绝。

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest scripts.tests.test_delivery_confirmation scripts.tests.test_delivery_commit_cycle scripts.tests.test_quality_flow_redlines`

Expected: FAIL，因为 parser 不认识 `--unchanged`，且空 manifest 没有构造与证据语义。

- [ ] **Step 3: Implement minimal no-op manifest behavior**

实现 `build_unchanged_delivery_manifest(state, target, current_dirty, preserved_initial_dirty=())`：验证 `domain_archive.status == "applied"`、`result == "unchanged"`、`applied_paths == []`，并拒绝 `current_dirty - preserved_initial_dirty`。返回：

```python
{
    "files": [],
    "commit_message": "",
    "target_branch": target,
    "adopted_dirty": {},
    "confirmed": True,
    "no_changes": True,
    "unchanged_initial_dirty": ["docs/user-notes.md"],
    "confirmation": {"mode": "unchanged"},
}
```

CLI 的 `--file` 与 `--unchanged` 互斥；普通文件模式继续要求 `--message`。空模式不展示二次确认命令。

`delivery_manifest_committed` 在 `no_changes` 分支复核领域归档状态和当前脏文件集合，不要求本步骤产生提交；其他分支保持原实现。

- [ ] **Step 4: Update delivery guidance**

明确两条命令：有领域文件时使用完整 `manifest set --file ... --message ... --target ...`；归档 `unchanged` 时使用 `manifest set --unchanged --target ...`。明确禁止使用已经提交的源码填充清单。

- [ ] **Step 5: Run targeted tests and verify GREEN**

Run: `python -m unittest scripts.tests.test_delivery_confirmation scripts.tests.test_delivery_commit_cycle scripts.tests.test_quality_flow_redlines scripts.tests.test_command_prompt_agreement`

Expected: PASS。

### Task 2: 清除活跃分段编译误导

**Files:**
- Modify: `scripts/mae_flow_core/cli_commands/done_status.py`
- Modify: `scripts/tests/test_spec2code_prompt_resources.py`

**Interfaces:**
- Consumes: 当前整体 `COMPILE` 任务卡与源码快照。
- Produces: 只提示重新签发整体 Compile 任务或重新执行 `done`，不提示提交、CP 或 checkpoint。

- [ ] **Step 1: Write failing active-resource scan**

扫描 `flow/steps`、`commands`、`skills/mae-flow` 和除 `lean_migration.py` 外的活跃 `scripts/mae_flow_core`，断言不存在 `分段编译`、`checkpoint ready`、`CP1`、`CP2`。

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m unittest scripts.tests.test_spec2code_prompt_resources`

Expected: FAIL，命中 `done_status.py` 的“分段编译风险确认”。

- [ ] **Step 3: Replace the stale recovery wording**

任务卡源码快照变化时提示重新运行 `agent-task compile`；风险确认成功后始终重新执行 `done`，不得提示先提交当前修复。

- [ ] **Step 4: Run the test and verify GREEN**

Run: `python -m unittest scripts.tests.test_spec2code_prompt_resources`

Expected: PASS。

### Task 3: Windows current 输出回归与发布验证

**Files:**
- Modify: `scripts/tests/test_state_core.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `PYTHONIOENCODING=cp936`、真实 `scripts/mae-flow.py current` 子进程。
- Produces: 对完整步骤标题和中文正文的编码回归。

- [ ] **Step 1: Extend the CP936 subprocess test**

在临时 Git 仓写入最小 `build` 状态，以 `PYTHONIOENCODING=cp936` 执行 `current`，按 CP936 解码并断言包含 `当前步骤`、`编码实现`，且不包含 `鈺`、`褰`、`姝` 等 UTF-8→GBK 乱码特征。

- [ ] **Step 2: Run the encoding test**

Run: `python -m unittest scripts.tests.test_state_core.RuntimeAndStateTests.test_cli_respects_cp936_stdout_selected_by_windows_host`

Expected: PASS；若失败，只修改 CLI 输出编码适配，不改资源文件编码。

- [ ] **Step 3: Record the user-visible fixes**

在 `CHANGELOG.md` 顶部记录空 manifest、新流程活跃话术清理和 CP936 发布回归。

- [ ] **Step 4: Run full verification**

Run:

```text
git diff --check
python -m unittest discover -s scripts/tests -p 'test_*.py'
python scripts/selftest.py
```

Expected: 全部 PASS。提交后用规范化物理路径解包 `git archive HEAD`，再次运行 `scripts/selftest.py`。
