# Hook 契约加固设计

## 目标

消除生产 Hook 组合入口、提示词命令、用户选择回执和 Agent transcript 之间的契约漂移，确保子 Agent 已执行时不会因 Hook 漏记而循环，也不会因不可执行命令或猜测用户选择卡住流程。

## 设计

1. 生产 `hooks/dispatch.py` 不再复制 `TaskCardPorts` 装配，统一复用 `HookRuntimeAdapter` 的权威工厂；真实入口测试必须直接构造并调用该工厂。
2. 所有生产步骤中的可执行命令统一使用 `python "{MAEFLOW_PATH}" ...`；测试扫描步骤、Agent、运行指导、Skill 和 Slash 命令资源，并拒绝裸 `mae-flow` 入口。
3. `done --choice` 只有在捕获到具体答案或可确定映射的结构化回执时才通过。仅有 ASKUSER 生命周期不能证明用户选择了哪个选项。
4. Agent transcript 只接受宿主显式路径，或通过 invocation/agent ID 唯一匹配的子会话文件；禁止按修改时间选择“最新文件”。
5. `doctor` 展示本单开始后的最近 Hook 内部异常和看门狗事件，让 fail-open 不再等于静默失效。
6. 删除权威文档、Slash 指令和实机验收清单中的 CP、Staged/Continuous、实现 tasks 提交等退役协议；Story 过程件不再提供入库分支。
7. 新增精简端到端红线场景，至少覆盖生产 Hook 端口装配、活跃 Agent 缺任务卡拦截、命令可执行性、选择不可猜和 transcript 不错绑。

## 错误处理

Hook 顶层仍保持 fail-open，避免插件自身故障锁死用户工作区；但内部异常必须写日志并由 `doctor` 可见。质量执行证据无法绑定 transcript 时不伪造成功，也不自动重派：由 `done/doctor` 给出明确诊断和既有风险出口。

## 验收

- 生产 `_task_card_ports()` 可真实构造，活跃 Agent 缺任务卡时在 PreToolUse 当场拦截。
- 仓库生产提示不存在会被 Agent直接执行的裸 `mae-flow` 命令。
- 仅有 ASKUSER token、没有答案正文时，`--choice` 被拒绝。
- 多个 transcript 并存时不会按 mtime 错绑。
- `doctor` 能展示最近 Hook `EXC`。
- 权威文档和实机清单不再描述 CP 协议。
- 全量单测、自检和干净归档包自检通过。
