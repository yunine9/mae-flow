# Mae-Flow 行为保持型重构第五阶段设计

**前置交付：** `refactor/mae-flow-phase-4` / `d7a22c0`

## 目标

把 `cmd_gate()` 从单个 356 行判断链拆成稳定的请求解析、Edit 规则、Bash 分段规则和统一裁决
适配器。所有规则顺序、绝对拒绝与可裁决拒绝的区别、permit 消费、三振计数、stderr、退出码和
Git/文件观察时机保持不变。

## 边界

新增 `mae_flow_core.guard.intent`：

- `GateIntent`：规范化的 `kind`、`subject`、token；
- `parse_intent(kind, subject)`：只做确定性解析；
- `hits_path(intent, pattern)`：保持 Bash token 路径匹配口径；
- `branch_command(intent)`：解析分支切换/创建事实；
- `recursive_delete_targets(intent)`：只检查 rm/rd 自己的命令段。

该模块无进程、文件、打印、退出和状态修改。

入口适配器拆为：

1. `cmd_gate`：只处理未启用/终态旁路并分发 edit/bash；
2. `_gate_edit`：按原顺序执行 Edit 规则；
3. `_gate_bash_repository`：内部文件、分支、Checkpoint、commit 与候选文件；
4. `_gate_bash_command`：force push、伪造通道、危险命令与 worktree；
5. `_gate_bash_writes`：写意图、规格/状态/源码权限和软提示。

分段边界严格遵循原判断顺序。任何分段一旦拒绝仍立即退出；permit 放行只跳过当前
`_gate_die()`，之后继续同一分段及后续分段规则。

## 验证

- 纯解析测试覆盖大小写、引号 token、分支恢复例外、递归删除命令段。
- 动态适配器测试验证 inactive、terminal、edit 和 bash 分发。
- 现有 gate smoke、commit ownership、task scope 测试全部保留。
- 固定旧实现 golden 增加一个允许 Edit、一个绝对拒绝 Bash 场景。
- `cmd_gate` 建立复杂度上限；新 guard 模块函数复杂度不超过 15。

## 非目标

- 不重排规则，不合并相似文案，不改变正则；
- 不把绝对拒绝改成 permit 拒绝，反之亦然；
- 不修复 MF-RF-002/MF-RF-003；
- 不合并、不推送。
