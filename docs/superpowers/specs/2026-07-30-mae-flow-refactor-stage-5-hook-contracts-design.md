# Mae-Flow Stage 5：Hook Agent Contracts 设计

## 目标

将 `hooks/dispatch.py` 中 Agent transcript 解释、任务卡验真、COMPILE/CODECHECK/UT/
GRILL 最终报告契约、收据复用和 Hook 事件编排迁入 `mae_flow_core`。迁移后 Hook
入口只负责跨平台协议解码、运行时装配、调用命名用例，以及把结果映射为既有
stdout、stderr 和退出码。

Stage 5 不改变任何 Agent 报告格式、任务卡字段、令牌/拒绝/收据 schema、fail-open
边界、月光 Stop 保护或宿主事件语义。CLI 命令迁移属于 Stage 6，Git/State/
Filesystem/Process 适配器统一属于 Stage 7。

## 已批准的实施方案

本阶段沿用总路线已批准的“纵向职责绞杀”方案：先冻结 Hook 公共行为，再逐条迁移
transcript、任务卡和四类 Agent 契约，最后切换事件编排并删除旧入口实现。

不采用一次性重写整个 Hook；它会同时改变编码、看门狗、状态读写、报告验签和退出码，
无法定位差分。也不采用仅按函数搬文件；那会保留隐式全局和反向依赖，不能降低维护
成本。

## 当前职责与风险

`hooks/dispatch.py` 约 2,812 行，同时承担：

- stdin 字节流解码、看门狗、日志、项目根定位和 `mae-flow.py` 子进程调用；
- PreToolUse、PostToolUse、UserPrompt、SessionStart、SubagentStop、Stop 路由；
- 子 Agent transcript 的工具调用、工具结果、失败状态和 Bash 片段解释；
- 任务卡正文 SHA256、步骤、HEAD、源码快照和文件范围验真；
- CodeCheck build/fullcheck、UT generator/run/baseline 等收据登记与复用；
- COMPILE、CODECHECK、UT、GRILL 的报告字段、状态和证据裁决；
- token、rejection、agent writes、codecheck trace 与 Stop guard 持久化。

这些职责共享模块全局变量和直接 I/O。现有测试还直接动态导入 Hook 私有函数，因此
移动任一规则都容易遗漏历史分支或改变副作用顺序。

## 目标结构

### Domain：纯 transcript 与 Agent 契约

- `quality/tool_transcript.py`
  - 将宿主 transcript 归一化为不可变 `ToolCall`；
  - 解释工具成功/失败、Skill 调用、Bash 命令与 shell 片段；
  - 不读取磁盘、Git、状态或环境变量。
- `quality/agent_reports.py`
  - 解析单值/多行/数字字段、章节、空值和 AC coverage 映射；
  - 保留既有大小写、空白、Markdown 表格和否定措辞兼容。
- `quality/agent_contracts.py`
  - 定义不可变 `ContractDecision`、`TaskCardFacts`、`SourceFacts`、
    `ReceiptFacts`；
  - 只编排四类契约的公共任务卡、状态和拒绝语义。
- `quality/compile_contract.py`
  - 编译方式、真实执行、BUILD_ERRORS 和净删代码豁免裁决。
- `quality/codecheck_contract.py`
  - build/fullcheck 执行、告警数字、范围、修复和最终状态裁决。
- `quality/unit_test_contract.py`
  - generator、基线、真实 UT、三数、失败吞噬、AC coverage 和风险裁决。
- `quality/grill_contract.py`
  - 真实只读检索、STAGE、GAPS_FOUND 与遗漏分支裁决。

以上模块只接收冻结事实并返回决策，不直接打印、不 `sys.exit`、不持久化收据。每个
业务模块不超过 500 行，函数复杂度不超过 15。

### Application：Hook 用例与有序副作用

- `application/hooks/task_cards.py`
  - 校验任务卡存在、步骤、正文 SHA256、HEAD 与签卡后源码快照；
  - 返回放行/拒绝决定和历史原文，不直接退出进程。
- `application/hooks/receipts.py`
  - 生成、复用和失效 CodeCheck/UT 收据；
  - 收据继续绑定 action/step/task SHA/head/source snapshot/config/真实数字。
- `application/hooks/agent_completion.py`
  - 接收 Agent 类型、status、report、transcript 和 ports；
  - 按“记录 trace → 验任务卡/范围 → 验真实工具证据 → 写收据 →
    写 token 或 rejection”的既有顺序执行。
- `application/hooks/events.py`
  - 编排六类宿主事件、RuntimeMode 路由、月光 AskUserQuestion 禁止、
    模板结构检查和 Stop 无进展计数；
  - 通过显式 ports 请求状态、文件、Git、时间、日志和子进程能力。
- `application/hooks/models.py`
  - 定义不可变 `HookRequest`、`HookResponse`、`HookPorts` 和 effect/result
    值对象。

Application 层可以定义副作用顺序，但不能直接 `open`、`subprocess`、`chdir`、
`print` 或 `sys.exit`。

### Entry：`hooks/dispatch.py`

入口最终仅保留：

- UTF-8 BOM、系统代码页与 GB18030 的严格 JSON 解码；
- stdin 守护线程、12 秒看门狗和基础 hook 日志；
- 项目根定位、Runtime 与 ports 装配；
- 调用 `handle_hook_event(request, ports)`；
- 原样输出 `HookResponse.stdout/stderr` 并映射 0/2；
- 顶层异常 fail-open 和未结束 stdin 线程的安全退出。

Stage 5 将 `dispatch.py` 降到不超过 800 行，并用 AST 门禁禁止已迁移私有契约重新
出现。跨平台启动方式、shell form、超时和编码行为保持原样。

## 数据流与副作用顺序

### SubagentStop

1. Entry 解码 payload，Application 从宿主 transcript 提取 Agent 类型、最终状态和
   报告。
2. CodeCheck Agent 先尽力写诊断 trace；trace 失败永不成为新拒绝理由。
3. Task-card use case 校验卡、步骤、正文摘要、HEAD 和源码范围。
4. Domain contract 仅根据 transcript、report 与 ports 提供的事实产生决定和待写收据。
5. Application 先登记成功收据，再写合法 token；拒绝时只写对应 rejection。
6. Entry 使用既有中文文案、stderr 和退出码 2 映射拒绝；合法或诚实 FAIL 沿用
   原语义。

### PreToolUse / PostToolUse / Stop

- PreToolUse 的 Task 派发在运行前验证任务卡；Edit/Bash 仍转交现有 gate；
- PostToolUse 继续先登记 Agent 写文件与 AskUserQuestion/UT 事实，再做模板结构检查；
- Stop 继续以 state revision 为进展标志，连续三次零进展后 fail-open；写 guard
  失败也 fail-open；
- CORRUPT、DIRECT、INACTIVE、STANDALONE、ACTIVE 与 terminal 路由保持原顺序。

## 兼容与错误处理

- Hook 顶层继续只有 0（放行）和 2（门禁拒绝）；插件缺失、子进程异常、超时和未知
  Runtime 继续 fail-open。
- transcript 缺字段、宿主未暴露子会话工具调用、旧状态缺新字段时，保持现有风险提示
  和 accept-risk 逃生路径，不把兼容缺口升级成死锁。
- 工具结果的 `is_error`、`result_seen`、return code、stdout/stderr 与 shell
  `&&`/`;`/管道含义按现状冻结。
- 完整流程与 Standalone 共用纯契约，但不合并其不同源码范围、初始脏文件、
  precommit review 和禁止提交边界。
- 所有新状态写入继续使用现有原子/versioned JSON API；未知字段必须保留。
- 发现真实缺陷时先增加失败回归与 findings 记录，再用独立 `fix:` 提交修复，不更新
  golden 掩盖差异。

## 行为 Oracle

Phase-15 在 Phase-14 上只追加 Hook 场景，Phase-14 的所有键和值必须逐项相同。至少
覆盖：

- SubagentStop 缺任务卡；
- COMPILE 合法 OK、BLOCKED 与伪造未执行；
- CODECHECK 合法 PASS、数字矛盾、旧收据失效；
- UT 合法 PASS、零用例、吞失败命令、报告重答凭证；
- GRILL CLEAR/GAPS 与零阅读伪造；
- Task 派发卡缺失、正文被改、HEAD/源码快照过期；
- Stop 月光进展、三次零进展放行和 guard 写失败；
- transcript 缺失、未知工具结果、UTF-8 BOM/GB18030 与缺宿主字段。

差分继续比较 stdout、stderr、退出码、状态 JSON、sidecar、产物哈希和 Git 状态。
时间、PID、临时路径只在既有归一化层最小替换。

## 完成条件

- `hooks/dispatch.py` 不超过 800 行，且只含协议/装配/响应映射；
- Agent contract 与 Hook application 可以用 fake ports 独立测试；
- 业务测试不再动态 import `dispatch.py` 私有策略，仅保留入口和跨平台冒烟；
- 新业务模块不超过 500 行，复杂度不超过 15；
- Phase-15 逐项保留 Phase-14；
- 完整 unittest、selftest、Phase-15、fault injection、严格 ResourceWarning、
  架构依赖和独立审查全部通过；
- 所有 Critical/Important 审查问题和本阶段发现的可复现缺陷全部修复并记录。
