# 可读需求目录与提示词—CLI 契约设计

## 背景与根因

Mae-Flow 当前把单号原文的完整 SHA-256 无条件附加到需求工作目录。该策略能区分
Windows 大小写、Unicode 规范化和非法字符替换后的别名，但让普通单号也变成难以
辨认的长路径。

能力调用链存在更严重的契约问题：阶段提示要求 Agent“记录能力事实”，却没有在
动作发生处给出完整命令；宿主能力名 `grill-critic-agent` 与状态机 kind `grill`
不同；CLI 对猜错的事件、参数只给通用帮助。`grill-clear` 又要求已记录匹配的
`grill/returned` 事实，因此 Agent 会在无法推导正确命令时进入确定性死循环。

## 目标

1. 普通单号产生直观、简短的 `.mae-flow-work/<单号>/` 目录。
2. Windows 非法或保留单号仍具有确定、可移植、不会与普通命名空间混淆的路径。
3. 已有在途流程继续使用状态中持久化的旧路径，不自动移动或损坏现场。
4. 每个要求 CLI 状态变更的提示都在动作处提供唯一、完整、可复制的命令。
5. CLI 对常见错误写法给出当前场景的精确修复命令，使 Agent 一次恢复。
6. 自动化契约测试阻止提示词和 CLI 再次漂移。

## 非目标

- 不自动重命名或删除现有 `.mae-flow-work` 目录。
- 不改变 schema-v3 的稳定阶段值、事件名或能力记录格式。
- 不把能力返回内容解释成质量结论。
- 不为错误别名静默伪造一次成功的能力调用。

## 目录命名设计

可移植的普通单号直接使用经过 NFC 规范化和首尾空白校验的可读文本。路径仍拒绝
分隔符、盘符、遍历片段、Windows 保留名称、控制字符和结尾空格/句点。

需要编码的异常单号进入保留命名空间，并保留完整摘要，例如：

```text
.mae-flow-work/REQ-123/
.mae-flow-work/_mae-ticket-REQ-42-<sha256>/
```

所有以 `_mae-ticket-` 开头的原始单号也按异常单号编码，避免普通单号冒充编码结果。
大小写或 Unicode 规范化后相同的普通单号视为同一业务单号目录；这与常见工单系统
的标识语义一致，也与同一单号重复启动时复用同一路径的现状一致。

新流程使用新规则。已有状态的 `artifacts` 是本地 Spec、Grill、Story 和 UT 交接
路径的权威来源；Grill 收据处理不得再按当前算法重新拼接路径。只有缺少持久化产物
的旧状态才使用路径生成器兜底。Chain 状态继续以已持久化指针和文档路径恢复。

## 能力命令契约

保留现有稳定命令：

```bash
python ".mae-flow-work/bin/mae-flow.py" advance capability-returned --key grill --decision "<简短不透明摘要>"
python ".mae-flow-work/bin/mae-flow.py" advance capability-failed-to-start --key grill --decision "<简短不透明摘要>"
python ".mae-flow-work/bin/mae-flow.py" advance capability-timed-out --key grill --decision "<简短不透明摘要>"
python ".mae-flow-work/bin/mae-flow.py" advance capability-not-observed --key grill --decision "<简短不透明摘要>"
```

稳定 kind 只有 `build`、`ut`、`codecheck`、`reviewer`、`grill`、`story`。宿主名称到
kind 的映射由现有能力注册表维护，用户提示不要求 Agent 自行推导。

Spec、Story、Construction、Quality 的阶段说明必须在每次能力调用旁边给出对应
kind 的四种完整记录命令，或引用由 `current` 同屏输出的精确命令卡；不得再出现
`capability-<outcome>`、`<kind>` 或孤立的“记录能力事实”。Spec 的正常路径明确为：

```bash
python ".mae-flow-work/bin/mae-flow.py" advance capability-returned --key grill --decision "<简短不透明摘要>"
python ".mae-flow-work/bin/mae-flow.py" advance grill-clear
```

`current` 按当前阶段和能力 slot 展示可复制的记录命令。CLI 参数错误或状态机收到
`grill-critic-attempt`、`capability.grill-critic`、`capability-attempt`、`--note`
等能力相关错误写法时，不静默接受，也不只输出通用帮助；它应打印允许的 outcome、
kind，以及上面同形的精确命令。这样既保持事实真实性，又让恢复只需一次复制。

## 红线与全局审计

以下规则作为生产契约：

- 提示要求执行状态变更时，必须同屏提供完整入口、子命令、事件和所有必需参数。
- 提示词使用的事件和参数必须由当前解析器接受，并能在对应状态产生预期变化。
- 显示名称与内部 kind 不一致时，提示必须直接给出映射后的值。
- 错误信息必须给出当前动作的纠正命令，不得仅列无关高频命令。
- 记录失败不得触发昂贵能力重跑。

新增契约测试将：

1. 验证所有公开能力 kind 和 outcome 的命令能被解析器接受；
2. 在 Spec、Story、Construction、Quality 的真实状态中执行对应记录命令；
3. 验证 Grill Critic 返回记录后 `grill-clear` 能推进；
4. 禁止阶段说明出现模糊的能力命令占位符；
5. 验证常见错误写法的错误输出包含精确纠正命令；
6. 验证普通、异常、保留、超长、Unicode 和旧哈希目录的兼容行为。

## 交付与验证

实现采用测试先行：先用失败测试固定可读目录、旧状态恢复、精确命令卡和错误恢复，
再修改生产代码。完成后运行相关测试、全部 `scripts/tests`、`scripts/selftest.py`、
`git diff --check`，最后提交并推送 `main`。
