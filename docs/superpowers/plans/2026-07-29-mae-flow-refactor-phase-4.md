# Mae-Flow Refactor Phase 4 Implementation Plan

> 按既有总设计执行；每个任务遵循 RED → GREEN → REFACTOR，并在阶段末做固定基线验证。

**Goal:** 将 `cmd_done()` 拆成完成命令编排器、纯完成裁决和保持原时序的副作用适配器。

**Architecture:** `workflow/completion.py` 只生成确定性结果和动作事件；`mae-flow.py` 依次执行
配置/确认、状态提交、源码回流、Evidence 和完成后动作。所有 Git、文件、时间、保存、输出与退出
仍由入口适配器负责。

**Tech Stack:** Python 3 标准库、`unittest`、AST 架构门禁、固定 golden 黑盒差分。

---

## Task 1: 冻结纯完成裁决契约

**Files**

- Create: `scripts/tests/test_workflow_completion.py`
- Create: `scripts/mae_flow_core/workflow/completion.py`

1. 先写失败测试，覆盖选择解析、选择配置、Evidence 顺序及完成事件。
2. 运行 `python3 scripts/tests/test_workflow_completion.py`，确认因模块缺失失败。
3. 实现最小纯策略。
4. 重跑并确认通过；检查输入未被修改。
5. 提交纯策略和测试。

## Task 2: 拆分 `cmd_done()` 适配器

**Files**

- Modify: `scripts/mae-flow.py`
- Modify: `scripts/tests/test_workflow_completion.py`

1. 写动态加载入口的失败特征测试，锁定阶段顺序和提前返回。
2. 将原逻辑逐段移动到 `_done_*` 命名适配器函数，不重写文案和副作用。
3. 让 `cmd_done()` 只负责编排阶段。
4. 使用 `completion.py` 解析选择、遍历 Evidence 并执行完成事件。
5. 跑完成策略、推进策略、Checkpoint 与现有单元测试。
6. 提交适配器拆分。

## Task 3: 建立架构门禁

**Files**

- Modify: `scripts/tests/architecture_baseline.json`
- Modify: `scripts/tests/test_architecture.py`
- Modify: `scripts/selftest.py`

1. 先写失败断言：`cmd_done()` 复杂度显著下降，自测显式运行完成策略测试。
2. 收紧单体行数基线并登记 `cmd_done()` 上限。
3. 重跑架构测试和 selftest 集成断言。
4. 提交门禁。

## Task 4: 扩展固定差分基线

**Files**

- Modify: `scripts/tests/differential/scenarios.py`
- Create: `scripts/tests/differential/goldens/phase4.json`
- Modify: `scripts/tests/differential/runner.py`
- Modify: `scripts/tests/test_differential_harness.py`

1. 从固定基线提交生成新增 `done` 场景快照。
2. 确认基线实现匹配 phase 4 golden。
3. 在重构实现上运行相同场景，要求逐字段一致。
4. 提交差分场景与 golden。

## Task 5: 阶段验证与审查

1. 运行所有 `scripts/tests/test_*.py`。
2. 运行 `scripts/selftest.py`。
3. 运行 phase 4 固定 golden 差分。
4. 运行语法、架构和工作树检查。
5. 审查行为、错误文案、保存时序和输入修改风险；只修重构引入的问题。
6. 提交验证集成，冻结 phase 4。
