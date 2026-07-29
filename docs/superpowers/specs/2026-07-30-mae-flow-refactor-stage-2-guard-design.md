# Mae-Flow Stage 2：Gate、Permit 与 Ownership 设计

## 目标

在不改变任何 Gate 输出、退出码、状态留痕或 Git 检查顺序的前提下，将 CLI 中的
编辑/命令裁决、一次性放行令和提交归属判断迁入内核，并让 CLI 与 Hook 共享同一组
值语义。Stage 2 不迁移命令路由，也不改变 break-glass 的安全等级。

## 当前问题

`guard/intent.py` 已负责请求解析，但最终裁决仍分散在 `scripts/mae-flow.py`：

- `_gate_edit` 与 `_gate_bash_writes` 混合绝对禁令、可放行裁决和 `sys.exit`；
- `_gate_die` 同时负责 block id、permit 消费、三振计数、历史保存和文案；
- `_gate_commit_candidates` 混合 Git 候选采集与跨单归属、OpenSpec、产物裁决；
- Hook 只负责转发，无法独立复用或测试最终决策；
- 大量测试必须动态加载 CLI 私有函数。

## 边界

新增纯策略：

- `guard/gate.py`：`GateDecision`、编辑/命令写入规则和绝对/可放行分类；
- `guard/permits.py`：block id、permit 有效性/消费事件、三振升级策略；
- `guard/ownership.py`：提交候选与初始遗留、OpenSpec 归属、构建产物的裁决。

CLI 仍负责：

- 读取 Flow/State/Git/文件事实；
- 调用纯策略；
- 按既有顺序消费 permit、保存 strike/history；
- 原样输出既有文案并映射 `exit 0/2`；
- 执行 advisory lightcheck。

## 值对象

`GateDecision` 为不可变值：

- `allowed: bool`
- `rule: str`
- `message: str`
- `absolute: bool`
- `advisories: tuple[str, ...]`

`PermitDecision` 只表达 `valid/expired/missing`、是否需要消费及升级附注，不直接写盘。
`OwnershipDecision` 返回有序阻断项和两组提示，不执行 Git。

## 行为冻结

Stage 2 新增 Phase-12，只追加以下可观察边界：

- Edit：状态文件、密钥、插件自身、spec truth、source、tests-only；
- Bash：危险递归删除、内部状态引用、重定向写源码、弱写入提醒；
- Permit：首次/三振、有效一次性消费、HEAD 变化、Moonlight；
- Ownership：初始遗留、foreign OpenSpec、强产物、未证明路径、检视快照；
- Git：dirty/staged/ignored、组合短参数、空格和特殊字符路径。

Phase-11 每个快照必须逐项保持一致。发现真实缺陷时必须独立 `fix:` 提交，不通过修改
旧 golden 掩盖。

## 完成条件

- CLI 不包含 Gate/Permit/Ownership 的业务分支，只保留 I/O 装配和效果执行；
- Hook 与 CLI 使用相同纯策略入口；
- 新模块各不超过 500 行，策略复杂度不超过 15；
- 旧规则名、block id、strike/permit 文件 schema、文案和退出码完全不变；
- Phase-12、完整 unittest/selftest、fault injection、ResourceWarning 和独立审查通过。
