# Hook 主动拦截诊断设计

## 背景

宿主会把 `PreToolUse` Hook 的非零退出统一显示为 `hook error`。Mae-Flow
使用退出码 2 表示正常的门禁拒绝，因此用户无法仅凭宿主标题区分“Mae-Flow
主动拦截”和“Hook 自身异常”。现有通用日志只记录事件、退出码和耗时，也无法
指出具体来源与规则。

## 目标

当 Mae-Flow 拒绝一次 `PreToolUse` 调用时，通用 Hook 日志额外写入一条结构化
诊断记录，使维护者可以确认：

- 被拦截的工具；
- 拒绝来自 Mae-Flow，而不是其他 Hook；
- 命中的规则；
- 多次报错是否对应同一条工具命令。

本改动不新增或放宽任何门禁，不改变状态机，不记录完整命令。

## 方案

### 规则传递

裁决类 Bash Gate 已持有稳定的内部规则名。拒绝输出增加机器可解析的规则标记，
由 Hook 分发器捕获并提取；原有面向 Agent 的恢复说明保持不变。未经过裁决类
规则的绝对禁止和 Hook 内部直接拒绝使用稳定的归类规则，不根据自然语言错误
文本猜测规则。

### 日志记录

`dispatch.py` 在 `pretooluse` 返回 2 时写入一条单行结构化记录，字段固定为：

```text
decision event=pretooluse tool=Bash result=blocked source=mae-flow rule=<rule> command_sha256=<sha256>
```

- `source` 固定为 `mae-flow`，明确插件归属；
- `rule` 使用稳定规则名；无法取得细分规则时使用明确的稳定兜底值；
- `command_sha256` 对 Bash `tool_input.command` 的 UTF-8 字节计算 SHA-256；
- 非 Bash 工具不伪造命令字段，使用其实际可用的稳定 subject；
- 日志不写完整命令、完整工具输入、用户提示词或完整 stderr。

每次拒绝只写一条 decision 记录，避免分发器与 CLI 重复记账。

### 异常区分

现有 `EXC`、`WATCHDOG` 和非门禁退出码继续代表 Hook/CLI 异常并保持 fail-open。
主动拒绝使用 `result=blocked`。两类记录不混用：

- `result=blocked`：策略按预期拒绝；
- `EXC` / `WATCHDOG` / 非语义退出码：实现或运行环境异常。

## 测试

测试覆盖：

1. Bash 裁决拒绝写出工具、来源、具体规则和确定的命令摘要；
2. 日志不包含原始 Bash 命令；
3. Hook 内部直接拒绝仍有稳定的兜底规则；
4. 放行调用不写 decision 记录；
5. 真实异常仍走现有 fail-open 日志，不伪装成策略拒绝。

## 非目标

- 不改变宿主的 `hook error` 展示文案；
- 不引入新的日志文件或流程产物；
- 不记录完整命令用于回放；
- 不修改门禁规则、重试策略或三振放行语义。
