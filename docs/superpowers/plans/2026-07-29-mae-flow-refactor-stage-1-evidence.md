# Mae-Flow Refactor Stage 1: Evidence Implementation Plan

> **执行要求：** 每个任务严格按 RED → GREEN → 回归 → 提交执行。行为保持型提交不得修改
> Phase-10 任何旧快照；真实缺陷必须独立测试、独立 `fix:` 提交。

**Goal:** 将全部 Evidence 值语义、注册和业务裁决迁出 `scripts/mae-flow.py`，保持证据名称、
失败文案、执行顺序、状态、文件和 Git 行为完全不变。

**Architecture:** 先在 Foundation/Workflow 建立不可变结果与唯一注册执行源，再通过最小
I/O 端口将通用、Agent、Delivery、Quality 四组规则逐步迁入内核。CLI 在迁移期保留同名
兼容绑定，但不保留判断逻辑。

**Tech Stack:** Python 标准库、`unittest`、临时 Git 仓、现有 Phase-10 差分 harness、
AST 架构守卫、fault injection。

---

## Task 1: 建立 Stage 1 迁移前 Evidence Oracle

**Files:**

- Modify: `scripts/tests/differential/scenarios.py`
- Add: `scripts/tests/differential/stage1_evidence_scenarios.py`
- Modify: `scripts/tests/differential/coverage.json`
- Add: `scripts/tests/differential/goldens/phase11.json`
- Modify: `scripts/tests/differential/runner.py`
- Modify: `scripts/tests/test_differential_harness.py`
- Add/Modify: Evidence 相关现有单测

1. 先添加固定场景名测试，覆盖多证据失败顺序、Agent 令牌缺失/过期、Checkpoint、
   commit/push、CodeCheck、spec/glob/clean-path、异常拒绝和 Moonlight/Standalone 边界。
2. 运行差分 harness，确认新场景未注册而失败。
3. 实现确定性场景，避免真实网络、动态远端和宿主 transcript。
4. 从 Stage 0 最终复核通过、Evidence 生产代码尚未迁移的实现生成 Phase-11。
5. 添加 `phase11 preserves every phase10 snapshot` 测试；必须逐项比较原始
   `Snapshot`，不能只比 key。
6. 将 runner 默认 golden 切到 Phase-11，运行完整 runner 零输出。
7. 提交：`test: characterize evidence behavior`

## Task 2: 引入不可变 EvidenceResult 与唯一执行源

**Files:**

- Add: `scripts/mae_flow_core/foundation/models.py`
- Add: `scripts/mae_flow_core/workflow/evidence.py`
- Modify: `scripts/mae_flow_core/workflow/completion.py`
- Add: `scripts/tests/test_evidence.py`
- Modify: `scripts/tests/test_workflow_completion.py`
- Modify: `scripts/selftest.py`
- Modify: `scripts/tests/selftest_suites.py`

1. 写失败测试固定 `EvidenceResult` 不可变、二元组解包、严格 bool/reason 值语义。
2. 写失败测试固定注册表顺序、历史 tuple 规范化、未知证据沿用 KeyError 语义、
   evaluator 异常不被新层吞掉。
3. 实现最小值对象、只读注册表和 `evaluate_step_evidence`。
4. 让 `workflow/completion.evidence_failures` 成为薄兼容委托。
5. 将新测试加入结构化 selftest 清单与语法清单。
6. 运行 Evidence/Completion 单测、Phase-11 runner。
7. 提交：`refactor: establish evidence result and registry`

## Task 3: 迁移通用文件、分支与规格 Evidence

**Files:**

- Add: `scripts/mae_flow_core/workflow/evidence_rules.py`
- Add: `scripts/tests/test_evidence_rules.py`
- Modify: `scripts/mae-flow.py`
- Modify: `scripts/tests/probe_gate_smoke.py`
- Modify: `scripts/tests/test_workflow_completion.py`
- Modify: `scripts/selftest.py`
- Modify: `scripts/tests/selftest_suites.py`

迁移规则：

- `glob`
- `glob_absent`
- `content_free`
- `clean_paths`
- `branch_ok`
- `tasks_checked`
- `spec_field` / `yaml_field`
- `spec_validate`
- `tier_scope`

步骤：

1. 用 fake ports 写每条规则的成功、失败、占位符、异常和文案测试。
2. 确认测试因模块/规则不存在而失败。
3. 定义只提供文件、Git、spec engine、路径替换和业务文件事实的冻结端口。
4. 原样迁移判断与文案；不得在 CLI 和内核各保留一份。
5. CLI 构造规则对象，并用无逻辑别名兼容旧调用。
6. 将 `probe_gate_smoke.py` 改为优先测试公开规则 API，只保留一组 CLI 装配断言。
7. 运行新单测、probe、Phase-11、完整 Evidence 相关回归。
8. 提交：`refactor: extract workflow evidence rules`

## Task 4: 迁移 Agent 令牌与源码新鲜度 Evidence

**Files:**

- Add: `scripts/mae_flow_core/workflow/agent_evidence.py`
- Add: `scripts/tests/test_agent_evidence.py`
- Modify: `scripts/mae-flow.py`
- Modify: `scripts/tests/test_task_scope.py`
- Modify: `scripts/tests/test_checkpoints.py`
- Modify: `scripts/tests/test_workflow_completion.py`

迁移规则：

- `agent_ran`
- `agent_or_no_source`
- `review_agent_or_no_code`
- `review_snapshot`

步骤：

1. 用 fake ports 固定 token step/head/status、时间、源码 snapshot、风险许可和拒签文案。
2. 增加 token 签发后提交、未提交源码、存量脏文件和不可解析 HEAD 的失败测试。
3. 确认 RED。
4. 迁移规则到内核；端口只返回 token/state/source facts，不决定放行。
5. Checkpoint/Moonlight/质量入口改用公开 evaluator；CLI 仅保留绑定别名。
6. 运行 task scope、checkpoint、completion、Phase-11。
7. 提交：`refactor: extract agent evidence rules`

## Task 5: 迁移 Delivery Evidence

**Files:**

- Add: `scripts/mae_flow_core/delivery/evidence.py`
- Add: `scripts/tests/test_delivery_evidence.py`
- Modify: `scripts/mae-flow.py`
- Modify: `scripts/tests/test_checkpoints.py`
- Modify: `scripts/tests/test_commit_ownership.py`
- Modify: `scripts/tests/test_delivery_policies.py`

迁移规则：

- `checkpoint_plan`
- `checkpoint_plan_complete`
- `final_review_clear`
- `archive_paths_clean`
- `pushed`
- `commit_tagged`
- `commit_tagged_after_entry`
- `review_fix_committed`

步骤：

1. 写失败测试固定 staged/continuous/revise、final review delta、archive dirty、
   upstream/head、STORY local、提交消息和 entry head。
2. 定义 Git/Delivery 最小端口并原样迁移规则。
3. 将 Checkpoint、spec、goto、Moonlight 的直接调用改用 Delivery Evidence API。
4. 保留所有状态字段和值；不改变提交和 push 的实际执行。
5. 运行 delivery/checkpoint/ownership/Phase-11。
6. 提交：`refactor: extract delivery evidence rules`

## Task 6: 迁移 Quality Evidence

**Files:**

- Add: `scripts/mae_flow_core/quality/evidence.py`
- Add: `scripts/tests/test_quality_evidence.py`
- Modify: `scripts/mae-flow.py`
- Modify: `scripts/tests/test_lightcheck.py`
- Modify: `scripts/tests/test_codecheck_logging.py`
- Modify: `scripts/tests/test_task_scope.py`

迁移规则：

- `codecheck_clean`
- `review_codecheck`

步骤：

1. 写失败测试固定 scan/verify/manual receipt、诊断哈希、告警计数、豁免配对、
   CLEAN/REMAINING/FAIL、源码变化和 standalone snapshot。
2. 用 fault ports 固定 Git/文件/CodeCheck 异常路径。
3. 迁移规则，不改变 CodeCheck 执行次数、日志事件顺序或恢复入口。
4. 质量命令与 `done` 统一调用同一 evaluator。
5. 运行 quality/task-scope/lightcheck/codecheck logging/Phase-11。
6. 提交：`refactor: extract quality evidence rules`

## Task 7: 删除 CLI Evidence 业务实现与重复注册

**Files:**

- Modify: `scripts/mae-flow.py`
- Modify: `scripts/mae_flow_core/workflow/evidence.py`
- Modify: `scripts/tests/test_architecture.py`
- Modify: `scripts/tests/architecture_rules.py`
- Modify: `docs/refactor-architecture.md`
- Modify: Evidence 相关测试

1. 添加 AST 失败测试：CLI 不得包含 `def ev_*`、`EVIDENCE = {...}` 或第二个证据循环。
2. 添加注册完整性测试：23 个历史名称和 `yaml_field` 必须精确映射；禁止缺失和额外名称。
3. 添加内核依赖测试：Evidence 模块不得导入 CLI、测试模块或直接执行 subprocess。
4. 删除 CLI 规则实现体和重复注册，只保留必要的无逻辑导入别名。
5. 将仍直接加载 monolith 的 Evidence 测试改用公开模块；更新
   `private_monolith_test_imports` 进度，但不得放宽最终目标 0。
6. 更新架构文档。
7. 提交：`refactor: remove evidence policy from cli`

## Task 8: Stage 1 全量证明与独立审查

**Files:**

- Modify: `docs/superpowers/mae-flow-refactor-findings.md`（仅有真实发现时）
- Modify: `scripts/tests/refactor_completion_contract.json`（只更新阶段状态；不得改阈值）
- Modify: `docs/refactor-architecture.md`

依次运行并保存新鲜结果：

1. `python -m unittest discover -s scripts/tests -p 'test_*.py'`
2. `python scripts/selftest.py`
3. `python scripts/tests/differential/runner.py --implementation-root .`
4. `python -W error::ResourceWarning scripts/tests/test_state_core.py`
5. `python -W error::ResourceWarning scripts/tests/test_checkpoints.py`
6. Evidence 新增测试在 `-W error::ResourceWarning` 下运行
7. `git diff --check main...HEAD`
8. 架构指标：新增业务模块 ≤500 行、策略复杂度 ≤15
9. AST/全文搜索：CLI 无 Evidence 判断，内核无反向依赖，Phase-10 未改
10. 独立代码审查；修复全部 Critical/Important 后重跑上述命令

若发现真实功能 bug：

1. 记录可复现输入和现有错误输出；
2. 写失败回归测试；
3. 独立 `fix:` 提交；
4. Phase-11 只增加已批准 bugfix 场景，不重写 Phase-10；
5. 重跑完整证明。

最终提交：`docs: record evidence refactor completion`
