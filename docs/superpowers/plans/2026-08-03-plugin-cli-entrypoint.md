# Stable Plugin CLI Entrypoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Mae-Flow production prompt invoke the CLI through the active host plugin-root environment instead of guessing or searching installation paths.

**Architecture:** Keep path resolution in the prompt contract because the CLI cannot locate itself before Python has opened it. Reuse the existing Hook precedence, `CODEAGENT3_PLUGIN_ROOT` then `CLAUDE_PLUGIN_ROOT`, while leaving Hook code and the state machine unchanged.

**Tech Stack:** Markdown production prompts, Python `unittest`, Git Bash-compatible parameter expansion.

## Global Constraints

- The canonical launcher is `python "${CODEAGENT3_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/mae-flow.py"`.
- Preserve double quoting around the complete script path.
- Never guess `.cac/skills/mae-flow`, hard-code a marketplace/cache version, or run `find` to locate the CLI.
- If neither plugin-root variable is available, report a host environment error and stop.
- Do not modify Hook registration, Hook behavior, CLI behavior, workflow state, or delivery policy.

---

### Task 1: Enforce the production prompt entrypoint contract

**Files:**
- Modify: `scripts/tests/test_architecture.py`
- Modify: `commands/mae-flow.md`
- Modify: `skills/mae-flow/SKILL.md`

**Interfaces:**
- Consumes: CodeAgent3 environment variable `CODEAGENT3_PLUGIN_ROOT` and compatibility variable `CLAUDE_PLUGIN_ROOT`.
- Produces: A stable prompt-level launcher string used for `current`, `start`, `decision`, `advance`, `manifest`, `exit`, and toolbox invocations.

- [ ] **Step 1: Write the failing production prompt contract test**

Add this test to `ArchitectureTests` in `scripts/tests/test_architecture.py`:

```python
def test_production_prompts_use_host_plugin_root_for_cli(self):
    launcher = (
        'python "${CODEAGENT3_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}'
        '/scripts/mae-flow.py"'
    )
    for relative in ("commands/mae-flow.md", "skills/mae-flow/SKILL.md"):
        with open(os.path.join(ROOT, relative), encoding="utf-8") as stream:
            source = stream.read()
        with self.subTest(relative=relative):
            self.assertIn(launcher, source)
            self.assertNotIn('python "<插件', source)
            self.assertNotIn(".cac/skills/mae-flow", source)
            self.assertIn("禁止猜测或搜索插件安装目录", source)
            self.assertIn("插件根目录环境变量缺失", source)
```

- [ ] **Step 2: Run the targeted test and verify RED**

Run:

```bash
python -m unittest scripts.tests.test_architecture.ArchitectureTests.test_production_prompts_use_host_plugin_root_for_cli
```

Expected: FAIL because neither production prompt contains the canonical launcher or required failure guidance.

- [ ] **Step 3: Update the Command and Skill prompt contracts**

In both production prompts, add the exact canonical launcher and the following semantic rules:

```text
所有 Mae-Flow CLI 调用都必须使用：
python "${CODEAGENT3_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/mae-flow.py" <command>
禁止猜测或搜索插件安装目录；禁止使用旧式 skill 目录、版本化缓存路径或 `find` 定位入口。
两个插件根变量都不可用时，报告“插件根目录环境变量缺失”并停止，不执行目录扫描。
```

Replace the existing `current`, `start`, and `decision` examples that contain `<插件>` or `<插件目录>` with the canonical launcher. State that abbreviated command names elsewhere in the prompt are protocol suffixes and must not be executed without the canonical launcher.

- [ ] **Step 4: Run the targeted test and verify GREEN**

Run:

```bash
python -m unittest scripts.tests.test_architecture.ArchitectureTests.test_production_prompts_use_host_plugin_root_for_cli
```

Expected: PASS.

- [ ] **Step 5: Run the architecture suite**

Run:

```bash
python scripts/tests/test_architecture.py
```

Expected: PASS with no failures or errors.

- [ ] **Step 6: Run the complete release gate**

Run:

```bash
python scripts/selftest.py
git diff --check
```

Expected: all selftest checks pass and `git diff --check` produces no output.

- [ ] **Step 7: Commit the implementation**

```bash
git add -- scripts/tests/test_architecture.py commands/mae-flow.md skills/mae-flow/SKILL.md docs/superpowers/plans/2026-08-03-plugin-cli-entrypoint.md
git commit -m "fix: use host plugin root for CLI entrypoint"
```
