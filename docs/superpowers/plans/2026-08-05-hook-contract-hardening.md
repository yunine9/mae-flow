# Hook Contract Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复生产 Hook 契约漂移，并用真实组合入口和端到端红线测试防止 Agent 循环、命令卡死和用户选择被代填。

**Architecture:** 以 `HookRuntimeAdapter` 为唯一端口装配源；提示命令、选择回执和 transcript 都使用确定性绑定。顶层 Hook 继续 fail-open，但异常通过 doctor 可观察。

**Tech Stack:** Python 3、unittest、JSON Hook 协议、Markdown 流程资源。

## Global Constraints

- 不恢复 CP、开发批次、指纹重绑或固定 Agent 返回格式。
- 不改变正常流程的阶段顺序和质量尝试上限。
- 每项生产修复必须先有失败测试。
- 过程文档不上库；只有领域文档属于需求交付候选。

---

### Task 1: 修复生产 Hook 端口装配

**Files:**
- Modify: `hooks/dispatch.py`
- Create: `scripts/tests/test_production_hook_composition.py`

**Interfaces:**
- Consumes: `HookRuntimeAdapter._task_card_ports()`
- Produces: 可构造的生产任务卡端口和真实 PreToolUse 拦截行为

- [ ] 写失败测试：直接调用生产 `_task_card_ports()`，并通过 Hook 子进程验证活跃 Agent 缺任务卡返回 2。
- [ ] 运行测试，确认因缺少 `build_like` 或错误放行而失败。
- [ ] 让 dispatch 委托权威 runtime 工厂。
- [ ] 重跑测试确认通过。

### Task 2: 封死命令提示错配

**Files:**
- Modify: `scripts/tests/test_command_prompt_agreement.py`
- Modify: `flow/steps/config_confirm.md`
- Modify: `flow/steps/verify_ut.md`
- Modify: `scripts/mae_flow_core/adapters/hook_active_events.py`
- Modify: `scripts/mae_flow_core/adapters/hook_events.py`
- Modify: `scripts/mae_flow_core/guard/gate.py`

**Interfaces:**
- Consumes: `parse_args()` 与 `{MAEFLOW_PATH}` 占位符
- Produces: 所有生产命令可由真实 parser 解析且不依赖 PATH

- [ ] 扩大资源扫描并写“禁止裸入口”的失败测试。
- [ ] 确认测试命中当前裸命令。
- [ ] 将步骤命令改为绝对脚本占位符；运行时报错改为不可误执行的恢复描述或绝对命令。
- [ ] 重跑命令契约测试。

### Task 3: 用户选择必须绑定具体答案

**Files:**
- Create: `scripts/tests/test_choice_receipts.py`
- Modify: `scripts/mae_flow_core/cli_commands/ack.py`

**Interfaces:**
- Consumes: `_current_ack_messages()` 中的可信答案值
- Produces: `_choice_verified()` 不再用 ASKUSER token 代替选项正文

- [ ] 写失败测试：只有新鲜 ASKUSER token、没有答案时提交 `--choice full` 必须拒绝。
- [ ] 确认旧逻辑错误通过。
- [ ] 删除 token-only 降级并保留一次普通消息恢复指引。
- [ ] 重跑选择与确认相关测试。

### Task 4: Transcript 与 invocation 确定性绑定

**Files:**
- Modify: `scripts/tests/test_agent_observations.py`
- Modify: `scripts/mae_flow_core/adapters/hook_active_events.py`

**Interfaces:**
- Consumes: payload 中的 `agent_transcript_path`、`agent_id`、`invocation_id`
- Produces: 与当前 Agent 唯一匹配的 transcript 路径或空值

- [ ] 写失败测试：两个子 transcript 并存且没有 ID 匹配时不得选择最新文件；存在唯一 ID 文件时必须命中。
- [ ] 确认当前 mtime 回退导致失败。
- [ ] 实现显式路径优先、ID 唯一匹配、否则空值。
- [ ] 重跑 Agent 生命周期与质量 transcript 测试。

### Task 5: Hook 异常进入 doctor

**Files:**
- Modify: `scripts/mae_flow_core/adapters/hook_diagnostics.py`
- Modify: `scripts/mae_flow_core/cli_commands/story_diag.py`
- Modify: `scripts/tests/test_hook_block_diagnostics.py`

**Interfaces:**
- Produces: `recent_hook_anomalies(lines, since, limit)`

- [ ] 写失败测试：只返回本单开始后的最近 `EXC`/`WATCHDOG`，过滤普通日志和旧记录。
- [ ] 实现纯函数并接入 doctor。
- [ ] 验证 doctor 输出包含明确异常摘要。

### Task 6: 清理退役协议和过程件入库指令

**Files:**
- Modify: `scripts/tests/test_spec2code_prompt_resources.py`
- Modify: `MAINTAINERS.md`
- Modify: `FIELD-TEST.md`
- Modify: `commands/mae-flow.md`
- Modify: `skills/mae-flow/SKILL.md`

**Interfaces:**
- Produces: 与当前主 Agent 一次实现、编译、人工检视、提交相符的权威文档

- [ ] 写失败测试：权威资源不得包含 Staged/Continuous、`development_review`、`development_checkpoints` 或 Story 入库分支。
- [ ] 更新维护边界、实机清单、月光说明和 standalone Story 说明。
- [ ] 重跑资源契约测试。

### Task 7: 横向复审和发布验证

**Files:**
- Test: `scripts/tests/test_production_hook_composition.py`
- Test: `scripts/tests/test_command_prompt_agreement.py`
- Test: `scripts/tests/test_choice_receipts.py`
- Test: `scripts/tests/test_agent_observations.py`
- Test: `scripts/tests/test_hook_block_diagnostics.py`
- Test: `scripts/tests/test_spec2code_prompt_resources.py`

**Interfaces:**
- Produces: 完整验证证据和第二轮问题清单

- [ ] 扫描所有端口构造、裸命令、退役事件和 fail-open 异常点；新发现的问题另起一轮“失败测试→最小修复”，不夹带无测试改动。
- [ ] 运行目标测试与 `python -m unittest discover -s scripts/tests -p 'test_*.py'`。
- [ ] 运行 `python scripts/selftest.py`。
- [ ] 用 `git archive HEAD` 的等价临时目录执行自检，确认发布包不依赖工作区文件。
- [ ] 执行独立代码审查并处理真实问题。
