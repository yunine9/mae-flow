# Single-Action Compile Wait Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove repeated sleep/poll actions from every configured compile path while preserving the existing compile, UT, and CodeCheck quality contracts.

**Architecture:** Treat the configured build provider's synchronous return as the only completion signal. Keep the change in agent/Skill instructions and add a package-aware regression test so the checked-in `build-fix.skill` cannot silently retain the old background-loop behavior.

**Tech Stack:** Python `unittest`, Markdown agent/Skill instructions, ZIP-packaged Claude Skill, Git Bash/Windows-compatible command guidance.

## Global Constraints

- One compile round issues one synchronous build invocation.
- Use the Bash tool's longest supported timeout, targeting ten minutes.
- Do not use shell background jobs, PID probing, `/tmp`, log-tail completion guessing, or separate sleep actions.
- Do not rerun a completed build when source and build inputs are unchanged.
- A tool timeout is not compile success and must not produce an OK receipt.
- Do not change UT, CodeCheck, task-card, source-freshness, or receipt acceptance criteria.

---

### Task 1: Lock the compile-wait instruction contract

**Files:**
- Create: `scripts/tests/test_compile_wait_instructions.py`
- Modify: `scripts/tests/selftest_suites.py`
- Modify: `scripts/selftest.py`

**Interfaces:**
- Consumes: operational Markdown from `agents/*.md` and ZIP members from `build-fix.skill`.
- Produces: a focused `unittest` suite that rejects the historical wait loop and requires the chosen synchronous contract.

- [ ] **Step 1: Write the failing regression test**

Create a test that reads the three agent instructions and the two relevant ZIP members:

```python
#!/usr/bin/env python3
import os
import re
import unittest
import zipfile


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def repository_text(relative):
    with open(os.path.join(ROOT, relative), encoding="utf-8") as stream:
        return stream.read()


class CompileWaitInstructionTests(unittest.TestCase):
    def test_compile_agents_use_one_synchronous_build_action(self):
        for relative in (
            "agents/compile-agent.md",
            "agents/codecheck-fix-agent.md",
            "agents/ut-generator-agent.md",
        ):
            with self.subTest(relative=relative):
                content = repository_text(relative)
                self.assertNotRegex(content, r"sleep\s+(?:120|180|后)")
                self.assertNotIn("长间隔轮询", content)
                self.assertIn("单次同步", content)

    def test_packaged_build_fix_uses_command_return_as_completion(self):
        with zipfile.ZipFile(os.path.join(ROOT, "build-fix.skill")) as archive:
            skill = archive.read("build-fix/SKILL.md").decode("utf-8")
            loop = archive.read(
                "build-fix/references/step2_build_loop.md").decode("utf-8")
        self.assertIn("单次同步", skill)
        self.assertIn('cd "$BUILD_DIR" && mcde build -i', loop)
        self.assertIn("源码和构建输入未变化", loop)
        self.assertNotIn("后台执行+轮询", skill)
        self.assertNotIn("/tmp/build_output.txt", loop)
        self.assertNotRegex(loop, r"mcde build -i[^\n]*&")
        self.assertNotRegex(loop, r"\bsleep\s+\d")


if __name__ == "__main__":
    unittest.main()
```

Register `scripts/tests/test_compile_wait_instructions.py` in
`REFACTOR_SAFETY_SUITES` and in `scripts/selftest.py`'s syntax-check file list.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python3 scripts/tests/test_compile_wait_instructions.py -v`

Expected: FAIL because current agents contain `长间隔轮询`/`sleep`, and the
packaged Skill still contains `/tmp/build_output.txt` plus a background build.

- [ ] **Step 3: Commit the red test**

```bash
git add scripts/tests/test_compile_wait_instructions.py scripts/tests/selftest_suites.py scripts/selftest.py
git commit -m "test: lock single-action compile waiting"
```

### Task 2: Replace sleep polling with provider completion

**Files:**
- Modify: `agents/compile-agent.md`
- Modify: `agents/codecheck-fix-agent.md`
- Modify: `agents/ut-generator-agent.md`
- Modify: `MAINTAINERS.md`
- Modify: `FIELD-TEST.md`
- Modify: `CHANGELOG.md`
- Modify: `build-fix.skill` members `build-fix/SKILL.md` and `build-fix/references/step2_build_loop.md`

**Interfaces:**
- Consumes: the configured provider (`build-fix` Skill or explicit command) and the host Bash completion result.
- Produces: one synchronous invocation per compile round; the existing provider result continues into the unchanged Hook contract.

- [ ] **Step 1: Update agent instructions with the positive execution recipe**

Use this contract consistently in the three agent files:

```markdown
编译采用单次同步调用：一轮只启动一次配置的编译方式，并把 Bash 工具超时设为宿主允许的最大值
（目标 10 分钟）。命令/Skill 返回就是完成信号；源码和构建输入未变化时复用已完成结果。
宿主报告 timeout/transport failure 时如实 FAIL/BLOCKED，不转后台、不轮询、不重复执行同一编译。
```

For `compile-agent`, also state that the `build-fix` Skill is invoked once and its
result is consumed directly. For UT and CodeCheck, change only their repair-time
compile execution wording; leave their result contracts untouched.

- [ ] **Step 2: Update the packaged build-fix Skill**

Extract `build-fix.skill` into a temporary directory, replace Step 2.1 with:

````markdown
### 2.1 执行编译（单次同步调用）

```bash
cd "$BUILD_DIR" && mcde build -i
```

一轮只执行一次命令，并把 Bash 工具超时设为宿主允许的最大值（目标 10 分钟）。
命令返回就是完成信号。源码和构建输入未变化时不得重复编译；timeout/transport failure
按工具失败上报，不切换到后台任务、日志轮询或 sleep。
````

Change `build-fix/SKILL.md`'s Step 2 summary to “单次同步执行，命令返回即完成”.
Replace Step 1's `/home/claude`/timestamp scan with task-card paths or
NUL-delimited repository-local Git paths stored in a quoted Bash array; missing
paths fail explicitly instead of falling back to a project-root build.
Rebuild `build-fix.skill` without adding unrelated files, then run the Skill
Creator validator against the extracted folder:

```bash
python3 /Users/cyw/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  /private/tmp/mae-flow-build-fix-single-action/build-fix
```

Expected: validation succeeds and the archive still contains exactly six entries.

- [ ] **Step 3: Update maintainer and field-test guidance**

Replace the old “长间隔轮询” principle with “单次执行、以提供方返回为完成信号”.
Update field test 2.4d to verify one visible compile action, completion latency,
timeout reporting, and no unchanged-input rerun on the real Windows `mcde` host.
Add a top CHANGELOG bullet explaining that no quality contract changed.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `python3 scripts/tests/test_compile_wait_instructions.py -v`

Expected: both tests PASS.

- [ ] **Step 5: Run compile-boundary regression suites**

```bash
PYTHONPATH=scripts:scripts/tests python3 -m unittest -v \
  test_hook_receipts test_hook_compile_contract \
  test_hook_unit_test_contract test_hook_codecheck_contract
```

Expected: all tests PASS, demonstrating no acceptance-contract change.

- [ ] **Step 6: Commit the implementation**

```bash
git add agents/compile-agent.md agents/codecheck-fix-agent.md \
  agents/ut-generator-agent.md MAINTAINERS.md FIELD-TEST.md CHANGELOG.md \
  build-fix.skill
git commit -m "fix: replace compile sleep polling"
```

### Task 3: Validate the Skill and release the change

**Files:**
- Verify: `build-fix.skill`
- Verify: repository test suites and Git history

**Interfaces:**
- Consumes: completed Task 1 and Task 2 commits.
- Produces: forward-test evidence, clean regression results, and a pushed `main` branch.

- [ ] **Step 1: Forward-test the packaged Skill**

Give fresh agents the raw extracted Skill and realistic Windows scenarios: a
20-second successful build, a 7-minute successful build, and a provider timeout.
Verify each agent chooses one synchronous invocation, does not invent output
parsing, and does not introduce sleep/background polling.

- [ ] **Step 2: Run full automated verification**

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
python3 scripts/selftest.py
git diff --check HEAD~2..HEAD
```

Expected: all unit tests and selftest checks PASS, and diff check is empty.

- [ ] **Step 3: Inspect and push**

Confirm only the two user-owned untracked state files remain outside the commits:

```bash
git status --short
git log -3 --oneline
git push origin main
```

Expected: `.mae-flow.json` and `.mae-flow.json.failures` remain untouched, and
`origin/main` advances to the implementation commit.
