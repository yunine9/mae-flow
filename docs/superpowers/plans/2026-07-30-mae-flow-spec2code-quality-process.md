# Mae-Flow Spec2Code 编码质量流程 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不增加代码质量评分门禁的前提下，为完整开发补齐编码前 UT 行为蓝图与细粒度计划、按 CP 的独立代码走读、可反复修改的人工检视，以及最终 AutoUT 蓝图映射。

**Architecture:** 继续以 `flow/flow.json` 和 `flow/steps/*.md` 表达用户可见流程，以 `.mae-flow.json` 保存轻量状态指针，以 `.mae-flow-work/` 保存可恢复但不入库的 Markdown 过程件。新增的角色 Agent 使用由 Harness 生成并带摘要指纹的最小上下文任务卡；现有 COMPILE、CODECHECK、UT 证据合同保持不变，Craft Reviewer 只产出意见，由主 Agent 裁决、CP Implementer 修改。

**Tech Stack:** Python 3 标准库、`unittest`、JSON 状态机、Markdown Prompt/过程件、现有 Mae-Flow CLI 与 Hook。

## Global Constraints

- 只改完整开发（`full`）的 Spec2Code 主链；`hotfix`、`tweak`、`review` 保持现有入口和质量链。
- 不新增代码质量分数、注释覆盖率或普通 Reviewer 意见的签名令牌。
- `openspec/changes/{CHANGE_NAME}/change.md` 仍是新单唯一入库文档；不得恢复 proposal/design/tasks/specs 多件套。
- 每单新增的 UT 蓝图、路线图、细粒度计划和 Reviewer 记录全部位于 `.mae-flow-work/`，默认被 `.gitignore` 排除。
- 现有 `.mae-flow-work/plan-{单号}.md` 是细粒度任务唯一真相源，不再创建第二份 Task Markdown。
- Test Design、CP Task Analyst、Craft Reviewer、CP Implementer 均使用新鲜实例和角色化任务卡；不得传递完整会话历史。
- Craft Reviewer 每轮最多五条发现，必须包含位置、依据、证据、实际影响、最小改法；Reviewer 只读，不修改源码。
- 用户检视均为无轮次上限的 Loop；用户未明确继续时不得离开当前检视节点。
- Comment Standard v1 是唯一注释规范源；新增业务注释使用简体中文，代码符号和协议原文保持英文。
- 最终 AutoUT 必须读取已确认蓝图并输出“蓝图场景 → 测试用例 → 执行结果”，不得重新发明业务期望。
- 保留 Compile Agent、Ponytail、CodeCheck、AutoUT、规格核对和最终交付的既有职责。

---

## File Map

### 新增固定资源

- `runtime/standards/comment-standard-v1.md`：Comment Standard v1 唯一真相源。
- `agents/test-design-agent.md`：只设计和修订 UT 行为蓝图。
- `agents/cp-task-analyst-agent.md`：只展开当前 CP 的细粒度任务。
- `agents/craft-reviewer-agent.md`：PLAN/CODE 两种只读走读契约。
- `agents/cp-implementer-agent.md`：按已确认 CP Task 修改业务代码。

### 新增过程模型与 CLI

- `scripts/mae_flow_core/quality/spec2code_artifacts.py`：Markdown 过程件的路径、字段和纯校验规则。
- `scripts/mae_flow_core/application/quality/spec2code_artifacts.py`：登记过程件、构造状态更新的纯用例。
- `scripts/mae_flow_core/application/quality/role_task_documents.py`：五种角色化任务卡渲染。
- `scripts/mae_flow_core/cli_commands/quality_artifacts.py`：`quality-artifact` CLI 适配器。
- `scripts/mae_flow_core/cli_commands/role_task.py`：`role-task` CLI 适配器。
- `flow/steps/test_blueprint.md`：UT 蓝图生成与人工修订 Loop。
- `flow/steps/build_plan.md`：路线图、CP1 Task、PLAN 走读与人工修订 Loop。

### 主要修改点

- `flow/flow.json`：只在 full 链增加两个流程节点。
- `flow/steps/build.md`、`flow/steps/build_pace.md`：改成按已确认路线图即时展开 CP，并注入编码简报。
- `agents/ut-generator-agent.md`：按蓝图映射最终接口与测试。
- `scripts/mae_flow_core/cli_parser.py`、`command_dispatch.py`、`cli_runtime.py`、`cli_commands/shared.py`：接入两个新命令。
- `scripts/mae_flow_core/application/delivery/checkpoints.py`、`delivery/checkpoints.py`：扩展 CP 子状态，不改变现有提交/推送安全语义。
- `scripts/mae_flow_core/cli_commands/checkpoint_*.py`：接入 CP 计划检视和 Craft Review。
- `scripts/mae_flow_core/application/quality/task_card_documents.py`、`cli_commands/agent_task.py`：给最终 UT 卡注入蓝图和注释规范。
- `scripts/mae_flow_core/workflow/evidence_rules.py`：登记蓝图/路线图指针。
- `scripts/tests/selftest_suites.py`：注册新增测试。

### 每单新增但不入库的 Markdown

```text
.mae-flow-work/test-blueprint-{单号}.md
.mae-flow-work/roadmap-{单号}.md
.mae-flow-work/plan-{单号}.md                  # 复用现有产物
.mae-flow-work/reviews/{单号}/{CP}-plan.md
.mae-flow-work/reviews/{单号}/{CP}-code.md
.mae-flow-work/role-tasks/{步骤}-{角色}-{CP}.md
```

---

### Task 1: 固化 Comment Standard 与角色 Agent 契约

**Files:**

- Create: `runtime/standards/comment-standard-v1.md`
- Create: `agents/test-design-agent.md`
- Create: `agents/cp-task-analyst-agent.md`
- Create: `agents/craft-reviewer-agent.md`
- Create: `agents/cp-implementer-agent.md`
- Create: `scripts/tests/test_spec2code_prompt_resources.py`
- Modify: `scripts/tests/selftest_suites.py`

**Interfaces:**

- Consumes: 已确认设计第 6、8、10、12、13、16 节。
- Produces: 固定规范路径 `runtime/standards/comment-standard-v1.md`；角色名 `test-design`、`cp-task-analyst`、`craft-reviewer`、`cp-implementer`。

- [ ] **Step 1: 写固定资源存在性和关键契约的失败测试**

```python
class Spec2CodePromptResourceTests(unittest.TestCase):
    def test_comment_standard_is_single_versioned_source(self):
        text = read("runtime/standards/comment-standard-v1.md")
        self.assertIn("新增业务注释统一使用简体中文", text)
        self.assertIn("TODO(<问题单>)", text)
        self.assertIn("单行不超过 120 列", text)

    def test_craft_reviewer_is_read_only_and_bounded(self):
        text = read("agents/craft-reviewer-agent.md")
        self.assertIn("每轮最多五条", text)
        self.assertIn("禁止修改源码", text)
        self.assertIn("位置", text)
        self.assertIn("最小改法", text)
```

- [ ] **Step 2: 运行测试确认资源尚不存在**

Run: `python scripts/tests/test_spec2code_prompt_resources.py`

Expected: FAIL，报告 `runtime/standards/comment-standard-v1.md` 或 Agent 文件不存在。

- [ ] **Step 3: 写 Comment Standard v1**

正文必须逐字固化以下规则：

```text
允许：原因、不变量/约束、调用者契约、临时代码删除条件。
禁止：逐行翻译代码、注释掉的旧代码、修改历史、无依据警告、无问题单 TODO。
局部注释放目标代码正上方；不用行尾注释；超过三行的完整原因移入设计文档。
TODO(<问题单>): <待完成动作>；删除/完成条件：<明确条件>。
FIXME(<问题单>): <当前已知缺陷>；临时处理：<当前方案>。
```

- [ ] **Step 4: 写四个 Agent 契约**

每个文件必须带统一的失败纪律和最终结果标记：

```text
TEST_DESIGN_RESULT: READY|NEEDS_INPUT|FAIL
TASK_ANALYSIS_RESULT: READY|NEEDS_INPUT|FAIL
CRAFT_REVIEW_RESULT: CLEAN|FINDINGS|NEEDS_INPUT|FAIL
CP_IMPLEMENT_RESULT: DONE|NEEDS_INPUT|FAIL
```

Craft Reviewer 的 PLAN/CODE 模式共用一个文件，但每次派发必须使用新实例；CP Implementer
只允许改任务卡 `允许修改` 中的文件，发现跨 CP 矛盾时返回 `NEEDS_INPUT`。

- [ ] **Step 5: 注册并运行资源测试**

在 `REFACTOR_SAFETY_SUITES` 增加：

```python
("Spec2Code 固定 Prompt 与注释规范",
 ("scripts/tests/test_spec2code_prompt_resources.py",), 180, 5000),
```

Run: `python scripts/tests/test_spec2code_prompt_resources.py`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add runtime/standards agents scripts/tests/test_spec2code_prompt_resources.py scripts/tests/selftest_suites.py
git commit -m "feat: add spec2code role and comment contracts"
```

---

### Task 2: 建立过程 Markdown 的路径与结构校验

**Files:**

- Create: `scripts/mae_flow_core/quality/spec2code_artifacts.py`
- Create: `scripts/tests/test_spec2code_artifacts.py`
- Modify: `scripts/tests/selftest_suites.py`

**Interfaces:**

- Consumes: 单号、CP ID、Markdown 文本。
- Produces:

```python
def artifact_path(
    kind: str,
    ticket: str,
    checkpoint: str = "",
    mode: str = "",
) -> str
def validate_blueprint(text: str) -> tuple[str, ...]
def validate_roadmap(text: str) -> tuple[str, ...]
def validate_plan(text: str, checkpoint: str = "") -> tuple[str, ...]
def validate_review(text: str, mode: str, checkpoint: str) -> tuple[str, ...]
def review_requires_rework(text: str) -> bool
```

- [ ] **Step 1: 写路径和结构失败测试**

覆盖：

```python
self.assertEqual(
    ".mae-flow-work/test-blueprint-REQ-1.md",
    artifact_path("blueprint", "REQ-1"),
)
self.assertEqual(
    ".mae-flow-work/reviews/REQ-1/CP2-code.md",
    artifact_path("review", "REQ-1", "CP2", mode="code"),
)
self.assertIn("可观察结果", validate_blueprint("# UT 行为蓝图\n"))
self.assertIn("后续 CP", validate_roadmap(incomplete_roadmap))
self.assertIn("注释计划", validate_plan(incomplete_plan, "CP1"))
self.assertIn("最多五条", validate_review(six_findings, "CODE", "CP1"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python scripts/tests/test_spec2code_artifacts.py`

Expected: FAIL with `ModuleNotFoundError`。

- [ ] **Step 3: 实现安全路径构造**

只接受：

```python
_TICKET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_CP_RE = re.compile(r"^CP[1-6]$")
```

禁止 `/`、`\`、`..` 和空值进入路径；review 的 `mode` 只允许 `plan|code`。

- [ ] **Step 4: 实现四类 Markdown 结构校验**

蓝图必须包含场景 ID、规格来源、前置状态、动作、可观察结果、禁止副作用、分类、测试层级、
依赖策略和禁止内部耦合。路线图必须包含每个 CP 的目标、完成合同、非目标、Scenario、状态所有权、
前后接口、延后落点和风险。Plan 的每个顶层 Task 必须包含文件、符号/签名、行为语义、控制流、
状态所有权、复用、禁止事项、注释计划、蓝图场景和定向检查。

Review 的每条 `## Finding F<n>` 必须包含：

```text
- 位置：
- 依据：
- 证据：
- 实际影响：
- 最小改法：
- 处置：修改|验证后修改|人工裁决|拒绝/暂缓
- 状态：待处理|已解决|已拒绝
```

Review 文件顶部还必须包含：

```text
- CRAFT_REVIEW_RESULT: CLEAN|FINDINGS
- Reviewer 模式: PLAN|CODE
- 检查点: CPn
- TASK_CARD_SHA256: <角色任务卡摘要>
- REVIEW_TARGET_SHA256: <计划或源码快照摘要>
```

零条 Finding 只允许配合显式 `CLEAN`；`FINDINGS` 至少一条。摘要与当前冻结对象
不一致时拒绝推进。

初始顺序固定为：Coordinator 生成并登记 roadmap → Task Analyst 写 plan → 登记 plan
→ 签发 PLAN Reviewer 卡。plan 每次修订后都重新登记并重新签发 Reviewer；用户确认
当前 CP 前再读 plan/Review 文件并核对展示收据摘要，变化即退回 Loop。

- [ ] **Step 5: 运行测试**

Run: `python scripts/tests/test_spec2code_artifacts.py`

Expected: PASS。

- [ ] **Step 6: 注册测试并提交**

```bash
git add scripts/mae_flow_core/quality/spec2code_artifacts.py scripts/tests/test_spec2code_artifacts.py scripts/tests/selftest_suites.py
git commit -m "feat: validate spec2code process artifacts"
```

---

### Task 3: 增加过程件登记命令，不增加业务入库文档

**Files:**

- Create: `scripts/mae_flow_core/application/quality/spec2code_artifacts.py`
- Create: `scripts/mae_flow_core/cli_commands/quality_artifacts.py`
- Create: `scripts/tests/test_spec2code_artifact_use_cases.py`
- Create: `scripts/tests/test_quality_artifact_cli.py`
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Modify: `scripts/mae_flow_core/command_dispatch.py`
- Modify: `scripts/mae_flow_core/cli_runtime.py`
- Modify: `scripts/mae_flow_core/cli_commands/shared.py`
- Modify: `scripts/mae_flow_core/workflow/evidence_rules.py`
- Modify: `scripts/tests/selftest_suites.py`

**Interfaces:**

- Consumes: 已存在的本地 Markdown 文件。
- Produces:

```bash
python scripts/mae-flow.py quality-artifact register blueprint <path>
python scripts/mae-flow.py quality-artifact register roadmap <path>
python scripts/mae-flow.py quality-artifact register plan <path>
python scripts/mae-flow.py quality-artifact show
```

状态形状：

```python
state["spec2code"] = {
    "version": 1,
    "blueprint": {"path": "...", "sha256": "...", "confirmed_revision": 0},
    "roadmap": {"path": "...", "sha256": "...", "confirmed_revision": 0},
    "plan": {"path": "...", "sha256": "...", "confirmed_revision": 0},
}
```

- [ ] **Step 1: 写纯用例失败测试**

验证文件不存在、结构不合法、路径不在 `.mae-flow-work/`、摘要变化和合法登记。

- [ ] **Step 2: 运行纯用例测试确认失败**

Run: `python scripts/tests/test_spec2code_artifact_use_cases.py`

Expected: FAIL with import error。

- [ ] **Step 3: 实现纯用例**

```python
@dataclass(frozen=True)
class ArtifactPorts:
    is_file: Callable[[str], bool]
    read_text: Callable[[str], str]
    digest: Callable[[str], str]
    now: Callable[[], str]

def register_artifact(
    process: dict, kind: str, path: str, ticket: str, ports: ArtifactPorts
) -> DeliveryResult:
    ...
```

返回 `set_spec2code` 和 `append_history` effect；不直接读写全局状态。

- [ ] **Step 4: 写 CLI 路由失败测试**

验证 parser 只接受 `blueprint|roadmap|plan`，命令调用后状态保存了规范化路径与 SHA-256，
`show` 会显示“本地过程件，不入库”。

- [ ] **Step 5: 接入 CLI**

新增 parser：

```python
quality = sub.add_parser("quality-artifact")
actions = quality.add_subparsers(dest="quality_action", required=True)
register = actions.add_parser("register")
register.add_argument("kind", choices=["blueprint", "roadmap", "plan"])
register.add_argument("path")
actions.add_parser("show")
```

`SPEC_REGISTER_FIELDS` 保持原状；这三个过程件不得混入 `spec set` 的规格阶段登记。

- [ ] **Step 6: 运行测试并提交**

Run:

```bash
python scripts/tests/test_spec2code_artifact_use_cases.py
python scripts/tests/test_quality_artifact_cli.py
python scripts/tests/test_command_dispatch.py
python scripts/tests/test_cli_runtime_facade.py
```

Expected: 全部 PASS。

```bash
git add scripts/mae_flow_core scripts/tests
git commit -m "feat: register local spec2code artifacts"
```

---

### Task 4: 在 full 链增加 UT 蓝图和实现计划人工 Loop

**Files:**

- Create: `flow/steps/test_blueprint.md`
- Create: `flow/steps/build_plan.md`
- Modify: `flow/flow.json`
- Modify: `flow/steps/design.md`
- Modify: `flow/steps/story.md`
- Modify: `flow/steps/story_ask.md`
- Create: `scripts/tests/test_spec2code_workflow.py`
- Modify: `scripts/tests/selftest_suites.py`

**Interfaces:**

- Consumes: `spec2code.blueprint|roadmap|plan` 登记指针。
- Produces: full 链 `design → test_blueprint → story_ask/story → build_plan → build_pace`。

- [ ] **Step 1: 写流程失败测试**

```python
self.assertEqual("test_blueprint", steps["design"]["next"])
self.assertEqual("build_plan", steps["story"]["next"])
self.assertEqual("build_plan", steps["story_ask"]["next"]["no"])
self.assertEqual(
    {"continue": "story_ask", "revise": "test_blueprint"},
    steps["test_blueprint"]["next"],
)
self.assertEqual(
    {"continue": "build_pace", "revise": "build_plan"},
    steps["build_plan"]["next"],
)
```

同时断言 hotfix/tweak/review 的链路没有新增节点。

- [ ] **Step 2: 运行测试确认失败**

Run: `python scripts/tests/test_spec2code_workflow.py`

Expected: FAIL，缺少 `test_blueprint`。

- [ ] **Step 3: 定义两个 user_ack Loop**

`test_blueprint`：

```json
{
  "title": "UT 行为蓝图检视",
  "user_ack": true,
  "choice_key": "test_blueprint_decision",
  "choices": ["continue", "revise"],
  "evidence": [{"type": "spec2code_artifact", "kind": "blueprint"}],
  "next": {"continue": "story_ask", "revise": "test_blueprint"}
}
```

`build_plan` 同理，证据要求 roadmap 和 plan；`revise` 回自己。

- [ ] **Step 4: 写蓝图步骤指令**

指令要求主 Agent：

1. 生成 Test Design 角色任务卡；
2. 派新鲜 Test Design Agent；
3. 校验并登记蓝图；
4. 首轮展示完整蓝图，后续展示差异；
5. 用户反馈时原文留在消息账本，派修订实例后重新登记；
6. 只有用户明确继续才 `done --choice continue`。

- [ ] **Step 5: 写计划步骤指令**

一次生成全局路线图和 CP1 完整 Task；后续 CP 只保留合同、接口和 Task 摘要。派新鲜
CP Task Analyst 和 Craft Reviewer PLAN；主 Agent 按四类处置核实 Reviewer 意见，再向用户展示。
`.mae-flow-work/plan-{单号}.md` 仍通过现有 `spec set plan` 登记，同时通过
`quality-artifact register plan` 登记摘要。

- [ ] **Step 6: 运行流程测试**

Run:

```bash
python scripts/tests/test_spec2code_workflow.py
python scripts/tests/test_workflow_definition.py
python scripts/tests/test_workflow_advancement.py
```

Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add flow scripts/tests
git commit -m "feat: add pre-code blueprint and plan loops"
```

---

### Task 5: 生成角色化最小上下文任务卡

**Files:**

- Create: `scripts/mae_flow_core/application/quality/role_task_documents.py`
- Create: `scripts/mae_flow_core/cli_commands/role_task.py`
- Create: `scripts/tests/test_role_task_documents.py`
- Create: `scripts/tests/test_role_task_cli.py`
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Modify: `scripts/mae_flow_core/command_dispatch.py`
- Modify: `scripts/mae_flow_core/cli_runtime.py`
- Modify: `scripts/mae_flow_core/cli_commands/shared.py`
- Modify: `scripts/tests/selftest_suites.py`

**Interfaces:**

- Consumes: 已登记过程件、当前 CP、目标文件和 Git diff。
- Produces:

```bash
python scripts/mae-flow.py role-task test-design
python scripts/mae-flow.py role-task task-analysis --checkpoint CP2
python scripts/mae-flow.py role-task craft-plan --checkpoint CP2
python scripts/mae-flow.py role-task cp-implement --checkpoint CP2
python scripts/mae-flow.py role-task craft-code --checkpoint CP2
```

任务卡保存到 `.mae-flow-work/role-tasks/`，末尾使用现有 `TASK_CARD_SHA256`。

- [ ] **Step 1: 写五种任务卡字段失败测试**

断言每个角色只得到设计第 11 节允许的输入；特别断言：

```python
self.assertNotIn("完整会话历史", implementer.body())
self.assertIn("Comment Standard v1", implementer.body())
self.assertIn("注释计划", implementer.body())
self.assertIn("实际 diff", code_reviewer.body())
self.assertNotIn("允许修改", code_reviewer.body())
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python scripts/tests/test_role_task_documents.py`

Expected: FAIL with import error。

- [ ] **Step 3: 实现纯任务卡渲染**

```python
def build_role_task_document(
    role: str,
    project_root: str,
    ticket: str,
    checkpoint: str,
    artifacts: Mapping[str, ArtifactRef],
    files: tuple[str, ...],
    diff: str,
) -> TaskCardDocument:
    ...
```

所有角色卡都包含职责、允许读取、禁止事项、期望输出和固定资源路径；不嵌入完整 Markdown 正文，
只给经过校验的绝对路径和摘要。

- [ ] **Step 4: 接入 CLI 并限制调用阶段**

允许阶段：

```python
ROLE_STEPS = {
    "test-design": {"test_blueprint"},
    "task-analysis": {"build_plan", "build"},
    "craft-plan": {"build_plan", "build"},
    "cp-implement": {"build"},
    "craft-code": {"build"},
}
```

`craft-code` 必须有当前 CP 编译成功的新鲜证据；`cp-implement` 只在 CP 状态为 `coding` 时生成。
这些任务卡用于流程编排，不创建新的质量 PASS token。

- [ ] **Step 5: 运行测试并提交**

Run:

```bash
python scripts/tests/test_role_task_documents.py
python scripts/tests/test_role_task_cli.py
python scripts/tests/test_command_dispatch.py
python scripts/tests/test_cli_runtime_facade.py
```

Expected: 全部 PASS。

```bash
git add scripts/mae_flow_core scripts/tests
git commit -m "feat: generate scoped spec2code role tasks"
```

---

### Task 6: 扩展 CP 状态为“计划—编码—走读—用户检视”

**Files:**

- Modify: `scripts/mae_flow_core/delivery/checkpoints.py`
- Modify: `scripts/mae_flow_core/application/delivery/checkpoints.py`
- Modify: `scripts/mae_flow_core/application/delivery/checkpoint_decisions.py`
- Modify: `scripts/mae_flow_core/application/delivery/checkpoint_recovery.py`
- Modify: `scripts/mae_flow_core/cli_commands/checkpoint_plan.py`
- Modify: `scripts/mae_flow_core/cli_commands/checkpoint_commands.py`
- Modify: `scripts/mae_flow_core/cli_parser.py`
- Modify: `scripts/tests/test_delivery_checkpoint_use_cases.py`
- Modify: `scripts/tests/test_delivery_checkpoint_decisions.py`
- Modify: `scripts/tests/test_delivery_checkpoint_recovery.py`
- Modify: `scripts/tests/test_checkpoints.py`

**Interfaces:**

- Consumes: 路线图、当前 CP Task、PLAN/CODE review 文件。
- Produces:

```bash
python scripts/mae-flow.py checkpoint prepare CP2 --plan .mae-flow-work/plan-REQ-1.md --review .mae-flow-work/reviews/REQ-1/CP2-plan.md
python scripts/mae-flow.py checkpoint plan-decide continue|revise --ack "<用户原话>"
python scripts/mae-flow.py checkpoint craft-reviewed CP2 --review .mae-flow-work/reviews/REQ-1/CP2-code.md
```

CP 状态：

```text
planned → plan_review_pending → coding → craft_pending → review_pending → completed
             ↘ revise → planned       ↖ accepted fix → coding
```

- [ ] **Step 1: 写纯状态转换失败测试**

覆盖：

- CP1 在 `build_plan` 已确认，激活后直接 `coding`；
- CP2 激活时进入 `planned`，源码编辑仍保持锁定；
- `prepare` 绑定 plan/review 的 SHA-256 后进入 `plan_review_pending`；
- plan `revise` 回 `planned`，`continue` 进入 `coding`；
- `ready` 不再直接进入用户 review，而是进入 `craft_pending`；
- CODE review 有待处理的“修改/验证后修改/人工裁决”时回 `coding`；
- 所有意见已解决/拒绝时才进入 `review_pending`；
- 源码变化会使 compile 和 CODE review 摘要同时失效；
- v1 在途 checkpoint state 按原语义兼容，不强行升级。

- [ ] **Step 2: 运行测试确认旧状态机失败**

Run:

```bash
python scripts/tests/test_delivery_checkpoint_use_cases.py
python scripts/tests/test_delivery_checkpoint_decisions.py
```

Expected: 新断言 FAIL。

- [ ] **Step 3: 实现 v2 导航与迁移边界**

`development_review()` 同时读取 v1/v2；只有新生成的 full 计划写 `version: 2`。v1 的
`ready → review_pending` 保持不变，避免在途单被升级卡住。

- [ ] **Step 4: 实现 plan review 决策**

plan review receipt 绑定：

```python
{
    "plan_path": "...",
    "plan_sha256": "...",
    "review_path": "...",
    "review_sha256": "...",
    "ack_cursor": (...,),
}
```

用户反馈不设轮次上限；每次 revise 增加 `plan_attempt`，清除旧 receipt，不更改 CP 的固定代码基点。

- [ ] **Step 5: 实现 CODE review 登记**

`craft-reviewed` 读取并校验当前 CP CODE review，检查最多五条和处置状态。源码摘要必须等于
compile receipt 的源码摘要；不匹配时要求重新编译后派新 Reviewer。

- [ ] **Step 6: 保持提交、push 和最终检视安全语义**

不得改弱：

- staged 的“先检视、后提交”；
- receipt 指纹；
- 用户确认后的精确 add/commit；
- 上游 HEAD 对账；
- 禁止 force-push；
- revise 后质量证据失效。

- [ ] **Step 7: 运行 checkpoint 全组测试**

Run:

```bash
python scripts/tests/test_delivery_checkpoint_use_cases.py
python scripts/tests/test_delivery_checkpoint_decisions.py
python scripts/tests/test_delivery_checkpoint_recovery.py
python scripts/tests/test_delivery_checkpoint_status.py
python scripts/tests/test_checkpoints.py
```

Expected: 全部 PASS。

- [ ] **Step 8: 提交**

```bash
git add scripts/mae_flow_core scripts/tests
git commit -m "feat: add checkpoint planning and craft review loops"
```

---

### Task 7: 丰富 CP 路线图和检视卡，区分遗漏与计划内延后

**Files:**

- Modify: `scripts/mae_flow_core/application/delivery/checkpoints.py`
- Modify: `scripts/mae_flow_core/cli_commands/checkpoint_facts.py`
- Modify: `scripts/mae_flow_core/cli_commands/checkpoint_plan.py`
- Modify: `flow/steps/build_pace.md`
- Modify: `flow/steps/build.md`
- Modify: `scripts/tests/test_delivery_checkpoint_use_cases.py`
- Modify: `scripts/tests/test_checkpoints.py`

**Interfaces:**

- Consumes: `.mae-flow-work/roadmap-{单号}.md` 和 plan Task。
- Produces: 每次 CP review 的六段派生视图。

- [ ] **Step 1: 写路线图冻结和 review 文案失败测试**

断言 `checkpoint plan` 新增：

```bash
--roadmap .mae-flow-work/roadmap-REQ-1.md
--plan .mae-flow-work/plan-REQ-1.md
```

并断言 review 输出包含：

```text
整体交付地图
当前 CP 完成合同
当前 CP 非目标
延后事项 → 后续 CP/Task
Scenario → CP → Task → 状态
对后续暴露的接口
实际代码 diff
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
python scripts/tests/test_delivery_checkpoint_use_cases.py
python scripts/tests/test_checkpoints.py
```

Expected: FAIL，parser 或输出缺少新字段。

- [ ] **Step 3: 冻结路线图与计划摘要**

`plan_checkpoint()` 增加 `roadmap_path`、`roadmap_sha256`、`plan_path`、`plan_sha256`；
从路线图读取 CP ID 和标题，不再只依赖自由文本 `--item`。为一个发布周期保留 `--item` 兼容，
但新 full v2 必须传 `--roadmap` 和 `--plan`。

- [ ] **Step 4: 渲染 CP 卡**

从路线图和 plan 解析派生视图。任何“后续处理”但没有 `CPn/Task n.m` 的条目显示为：

```text
⚠ 计划缺口：该延后项没有具体 CP/Task 落点，请返回 build_plan 修改。
```

它触发计划 Loop，不作为新质量分数。

- [ ] **Step 5: 更新 build 指令**

编码开始前按顺序：

1. 为当前 CP 生成 Task Analyst 卡；
2. PLAN Reviewer 走读；
3. 用户计划 Loop；
4. 为同 CP 生成 CP Implementer 卡；
5. CP Implementer 完成全部细 Task；
6. Compile Agent；
7. Craft Reviewer CODE；
8. 主 Agent 裁决并由同一 CP Implementer 修改；
9. 源码变化则重编译、定向复查；
10. 用户 CP Loop。

连续模式仍执行每 CP 的独立 PLAN/CODE Reviewer，但按用户已选节奏不在中间等待人工；最终统一检视仍是 Loop。

- [ ] **Step 6: 运行测试并提交**

Run:

```bash
python scripts/tests/test_delivery_checkpoint_use_cases.py
python scripts/tests/test_checkpoints.py
python scripts/tests/test_workflow_completion.py
```

Expected: 全部 PASS。

```bash
git add flow scripts/mae_flow_core scripts/tests
git commit -m "feat: render global context in checkpoint reviews"
```

---

### Task 8: 把编码简报和注释计划注入 CP Implementer

**Files:**

- Modify: `scripts/mae_flow_core/application/quality/role_task_documents.py`
- Modify: `agents/cp-implementer-agent.md`
- Modify: `agents/craft-reviewer-agent.md`
- Modify: `flow/steps/build.md`
- Modify: `scripts/tests/test_role_task_documents.py`
- Modify: `scripts/tests/test_spec2code_prompt_resources.py`

**Interfaces:**

- Consumes: 当前 CP 合同、相关 Task、蓝图场景、Comment Standard v1。
- Produces: CP Implementer 的固定 Coding Charter 和动态编码简报。

- [ ] **Step 1: 写完整注入失败测试**

CP Implementer 卡必须出现八条固定 Charter，并包含：

```text
当前职责和非目标
模块与状态所有权
必须复用
错误和兼容语义
注释计划
相关 UT 蓝图场景
前序接口
后续接口
```

Task 的注释计划只允许 `ADD|UPDATE|REMOVE|NONE`，禁止“适当补充注释”。

- [ ] **Step 2: 运行测试确认失败**

Run: `python scripts/tests/test_role_task_documents.py`

Expected: FAIL，缺少动态简报字段。

- [ ] **Step 3: 实现卡片渲染与 Agent 约束**

卡片引用完整规范路径，同时内嵌八条精简规则。Craft Reviewer PLAN 检查注释计划是否具体；
CODE 检查是否应先重构、是否遗漏 why、注释是否与代码一致。

- [ ] **Step 4: 运行测试并提交**

Run:

```bash
python scripts/tests/test_role_task_documents.py
python scripts/tests/test_spec2code_prompt_resources.py
```

Expected: PASS。

```bash
git add agents flow/steps/build.md scripts/mae_flow_core/application/quality/role_task_documents.py scripts/tests
git commit -m "feat: inject coding and comment briefs per checkpoint"
```

---

### Task 9: 让最终 AutoUT 只映射已确认蓝图

**Files:**

- Modify: `scripts/mae_flow_core/cli_commands/agent_task.py`
- Modify: `scripts/mae_flow_core/application/quality/task_card_documents.py`
- Modify: `scripts/mae_flow_core/quality/task_cards.py`
- Modify: `scripts/mae_flow_core/quality/unit_test_contract.py`
- Modify: `agents/ut-generator-agent.md`
- Modify: `scripts/tests/test_quality_task_card_use_cases.py`
- Modify: `scripts/tests/test_quality_task_cards.py`
- Modify: `scripts/tests/test_hook_unit_test_contract.py`

**Interfaces:**

- Consumes: 已确认 blueprint 路径与摘要、最终代码范围、规格、测试配置、Comment Standard。
- Produces:

```text
BLUEPRINT_SHA256: <64 hex>
BLUEPRINT_MAPPING:
<场景 ID> | <测试文件::用例名> | PASS|FAIL|BLOCKED
```

- [ ] **Step 1: 写 UT 卡和结果合同失败测试**

覆盖：

- full `verify_ut` 没有已确认蓝图时拒绝生成 UT 卡；
- hotfix/tweak/review 继续沿用旧 UT 卡，不受影响；
- 卡片包含 blueprint 路径、摘要、最终规格、最终代码范围和 Comment Standard；
- PASS 报告缺场景映射、漏场景、摘要不一致时不签发 UT PASS；
- 生产接口缺 test seam 时使用 `NEEDS_INPUT`，不得改业务源码。

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
python scripts/tests/test_quality_task_card_use_cases.py
python scripts/tests/test_hook_unit_test_contract.py
```

Expected: 新断言 FAIL。

- [ ] **Step 3: 注入蓝图**

`cmd_agent_task()` 在 `kind == "UT"` 且 full 时重新读取已登记蓝图并核对摘要；摘要漂移就要求回
`test_blueprint` Loop。`task_record()` 保存：

```python
"blueprint": {"path": path, "sha256": digest, "scenario_ids": ids}
```

- [ ] **Step 4: 修改 UT Agent**

明确顺序：

1. 读取蓝图；
2. 把场景映射到最终公开接口；
3. 决定测试文件、Fixture、真实依赖或 Fake/Mock；
4. 生成并运行测试；
5. 输出逐场景映射。

不得测试 private 状态；发现合理 test seam 缺失时列出代码事实并返回 `NEEDS_INPUT`。

- [ ] **Step 5: 校验场景映射**

`unit_test_contract.py` 比较任务卡冻结的 `scenario_ids` 与报告中的映射 ID，要求集合相等且无重复。
原有测试数字、真实命令、生成器和写入范围合同全部保留。

- [ ] **Step 6: 运行 UT 合同测试并提交**

Run:

```bash
python scripts/tests/test_quality_task_cards.py
python scripts/tests/test_quality_task_card_use_cases.py
python scripts/tests/test_hook_unit_test_contract.py
python scripts/tests/test_hook_task_card_contracts.py
```

Expected: 全部 PASS。

```bash
git add agents/ut-generator-agent.md scripts/mae_flow_core scripts/tests
git commit -m "feat: bind final autout to approved blueprint"
```

---

### Task 10: 完成人工反馈回流、恢复和月光宝盒策略

**Files:**

- Modify: `scripts/mae_flow_core/cli_commands/current.py`
- Modify: `scripts/mae_flow_core/cli_commands/direct_reentry.py`
- Modify: `scripts/mae_flow_core/application/delivery/moonlight.py`
- Modify: `flow/steps/moonlight_review.md`
- Modify: `skills/mae-flow/SKILL.md`
- Create: `scripts/tests/test_spec2code_recovery.py`
- Modify: `scripts/tests/test_delivery_moonlight_use_cases.py`
- Modify: `scripts/tests/selftest_suites.py`

**Interfaces:**

- Consumes: `spec2code` 状态指针、CP 子状态、用户真实消息账本。
- Produces: `/clear` 后可恢复的下一动作；月光宝盒自动裁决但不伪造人工确认。

- [ ] **Step 1: 写恢复失败测试**

分别构造：

- 蓝图等待用户；
- CP2 计划等待用户；
- CP2 编译后等待 Craft Reviewer；
- Reviewer 有待人工裁决；
- 用户已要求修改、等待 Implementer；
- 最终 UT 因 test seam 回到 CP。

断言 `current` 输出只要求读取对应最小产物，不要求回放完整历史。

- [ ] **Step 2: 运行测试确认失败**

Run: `python scripts/tests/test_spec2code_recovery.py`

Expected: FAIL，旧 `current` 不认识新子状态。

- [ ] **Step 3: 实现恢复文案和摘要漂移处理**

蓝图、路线图、plan 或 review 文件摘要变化时，不删除现场；输出哪个结论失效、回到哪个 Loop。
用户反馈原话继续由现有 message ledger 保存，state 只记消息 ID/cursor。

- [ ] **Step 4: 明确月光宝盒行为**

月光宝盒仍生成蓝图、路线图、细粒度 Task，并运行 PLAN/CODE Reviewer；需要人工确认的节点采用
保守结论自动继续且写入 history。Reviewer 报告存在“人工裁决”时不得擅自拍板，按现有
`moonlight blocked/defer` 语义留到早晨处理。

- [ ] **Step 5: 更新 Mae-Flow 主 Skill**

把新增流程说明压缩为操作次序和命令，不复制 Comment Standard 全文。恢复顺序改为：

```text
规格/设计 → UT 蓝图 → 路线图 → 当前 plan → 当前 CP reviews → Git diff/历史
```

- [ ] **Step 6: 运行测试并提交**

Run:

```bash
python scripts/tests/test_spec2code_recovery.py
python scripts/tests/test_delivery_moonlight_use_cases.py
python scripts/tests/test_workflow_advancement.py
```

Expected: 全部 PASS。

```bash
git add flow skills scripts
git commit -m "feat: recover spec2code quality loops"
```

---

### Task 11: 增加端到端案例，证明流程而非门禁

**Files:**

- Create: `scripts/tests/test_spec2code_quality_flow.py`
- Modify: `scripts/tests/selftest_suites.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**

- Consumes: 前十个 Task 的完整 CLI 和状态机。
- Produces: 一个可重复的 full 流程回归，证明过程件、角色卡、Loop 和 UT 映射能串联。

- [ ] **Step 1: 写端到端失败测试**

临时仓库案例至少有 CP1/CP2 和三个场景，覆盖：

1. 蓝图首轮被用户修改后再确认；
2. CP1 计划 Reviewer 提一条有效问题和一条风格意见，主 Agent 分别“修改/拒绝”；
3. CP1 CODE review 发现重复实现，Implementer 修改后重新编译并定向复查；
4. 用户 CP review 再要求一次修改；
5. CP2 即时展开，不读取 CP1 完整对话；
6. 最终 UT 三个场景全部映射；
7. `.mae-flow-work` 过程件未出现在 `git status --short` 的可提交范围；
8. `change.md` 仍是唯一业务变更 Markdown。

- [ ] **Step 2: 运行测试确认失败**

Run: `python scripts/tests/test_spec2code_quality_flow.py`

Expected: 至少在新命令或新状态上 FAIL。

- [ ] **Step 3: 补齐端到端 fixture 和断言**

测试使用现有 subprocess/临时仓模式，不调用真实模型；以模拟 Agent 输出文件和现有 Hook 事件驱动状态。
明确断言没有新增 Reviewer PASS token。

- [ ] **Step 4: 更新文档**

README 只增加：

- 用户会看到的两个编码前 Loop；
- 每 CP 的计划/代码检视；
- 哪些 Markdown 入库、哪些仅在 `.mae-flow-work`；
- `/clear` 恢复顺序。

CHANGELOG 记录 Spec2Code 质量流程，不宣称编码质量已提高，只说明新增生产过程。

- [ ] **Step 5: 运行定向测试**

Run:

```bash
python scripts/tests/test_spec2code_quality_flow.py
python scripts/tests/test_spec2code_workflow.py
python scripts/tests/test_spec2code_recovery.py
```

Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add README.md CHANGELOG.md scripts/tests
git commit -m "test: cover spec2code quality workflow"
```

---

### Task 12: 全量验证与历史真实需求 A/B 试运行准备

**Files:**

- Create: `docs/field-tests/spec2code-quality-ab.md`
- Modify: `FIELD-TEST.md`

**Interfaces:**

- Consumes: 完整实现和一个历史真实需求。
- Produces: 可复用的 A/B 观察表；不产生自动质量分数或放行门禁。

- [ ] **Step 1: 写 A/B 试运行表**

只记录可核实事实：

```text
案例与基线提交
旧流程/新流程
CP 数与各角色 Agent 数
每个 Agent 实际读取路径
用户修改轮次
Reviewer 有效/拒绝意见及依据
最终独立盲审发现：模块边界、重复实现、可读性、注释准确性
UT 蓝图场景总数、映射数、遗漏数
总耗时和返工发生阶段
```

不计算“综合质量分”，避免把过程重新做成评分门禁。

- [ ] **Step 2: 运行全量自测**

Run: `python scripts/selftest.py`

Expected: 所有 suite PASS，退出码 0。

- [ ] **Step 3: 运行静态和仓库清洁检查**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` 无输出；`git status --short` 只包含本 Task 的文档修改。

- [ ] **Step 4: 提交**

```bash
git add docs/field-tests/spec2code-quality-ab.md FIELD-TEST.md
git commit -m "docs: add spec2code quality field test"
```

- [ ] **Step 5: 执行一次历史需求试运行**

选择同一历史需求、同一基线、同一模型档位；旧流程结果只读保存，新流程在独立分支执行。
试运行后由人工盲审者只看最终 diff，不看流程标签，再填写 A/B 表。若问题集中在 CP 过粗、
Reviewer 噪声或上下文包缺字段，回对应模板调整，不新增质量分门禁。

---

## Self-Review

### Spec coverage

- UT 行为蓝图与人工 Loop：Task 2–4、9。
- 全局 CP 路线图与“遗漏/延后”区分：Task 2、4、7。
- 细粒度“去哪写什么”Task：Task 2、4、5、8。
- 新鲜角色 Agent 和上下文治理：Task 1、5、10。
- PLAN/CODE 独立走读、四类处置、最多五条：Task 1、2、6。
- 每 CP 修改、重编译、定向复查和用户 Loop：Task 6、7。
- Comment Standard v1 与多阶段注入：Task 1、8、9。
- 最终 AutoUT 蓝图映射与 test seam 回流：Task 9、10。
- 不新增业务入库 Markdown：Global Constraints、File Map、Task 3、11。
- A/B 验收：Task 12。

### Placeholder scan

计划不包含 TBD、待实现或“适当处理”类占位。命令里的 `<path>`、`<用户原话>` 和模板字段是
CLI 参数说明，不是留给实现者自行发明的设计缺口。

### Type and name consistency

- 固定命令名：`quality-artifact`、`role-task`、`checkpoint prepare`、
  `checkpoint plan-decide`、`checkpoint craft-reviewed`。
- 固定角色名：`test-design`、`task-analysis`、`craft-plan`、`cp-implement`、`craft-code`。
- 固定状态根：`state["spec2code"]`；开发检查点继续使用 `state["development_review"]`。
- 固定过程件：blueprint、roadmap、现有 plan、每 CP plan/code review。
- 固定注释规范路径：`runtime/standards/comment-standard-v1.md`。
