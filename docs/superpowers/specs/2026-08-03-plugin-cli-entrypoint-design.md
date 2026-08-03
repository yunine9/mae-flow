# Mae-Flow 插件 CLI 入口定位设计

## 背景

Mae-Flow 的 Slash Command 与 Skill 当前使用
`<插件>/scripts/mae-flow.py` 或 `<插件目录>/scripts/mae-flow.py` 作为示例入口。
这些占位符没有给 Agent 可执行的路径解析合同。插件通过市场安装后，真实目录位于带市场名和版本号的缓存路径，Agent 因而可能先猜测旧的 `.cac/skills/mae-flow`，失败后再扫描缓存目录。

CodeAgent3 已在插件 Hook 环境提供 `CODEAGENT3_PLUGIN_ROOT`；兼容宿主使用
`CLAUDE_PLUGIN_ROOT`。生产 Hook 已采用这两个变量的优先级作为插件根目录合同。

## 目标

- Mae-Flow 的内部 CLI 调用不再猜测或搜索插件安装目录。
- CodeAgent3 优先使用 `CODEAGENT3_PLUGIN_ROOT`，兼容宿主回退到
  `CLAUDE_PLUGIN_ROOT`。
- Windows Git Bash、带空格目录和版本化插件缓存路径保持可用。
- 插件根变量缺失时明确报告宿主环境异常，不扫描 `.cac` 寻找候选副本。

## 非目标

- 不修改 Hook 注册或 Hook 错误处理。
- 不修改 Mae-Flow CLI、状态机或交付策略。
- 不新增固定安装路径、版本目录或全局 launcher。
- 不改变用户可见的 Slash Command 入口。

## 设计

生产提示中的 Mae-Flow CLI 统一使用以下形式：

```bash
python "${CODEAGENT3_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/mae-flow.py" current
```

同一前缀用于 `start`、`decision`、`advance`、`manifest`、`exit` 和独立工具箱命令。
双引号必须保留，使含空格的 Windows 路径能够作为单个参数传给 Python。

`CODEAGENT3_PLUGIN_ROOT` 是主合同；只有它为空或未设置时才读取
`CLAUDE_PLUGIN_ROOT`。提示必须明确禁止以下恢复行为：

- 猜测 `.cac/skills/mae-flow`；
- 硬编码 `.cac/plugins/cache/.../<version>`；
- 使用 `find`、递归扫描或在 marketplace/cache 多副本之间自行选择。

两个变量都不可用时，Agent 应停止 CLI 调用并向用户报告插件根目录环境变量缺失。
该错误表示宿主没有满足插件运行合同，不能通过目录搜索掩盖。

## 修改范围

1. `commands/mae-flow.md`：把分流入口改成环境变量形式，并加入禁止猜测、搜索和硬编码的规则。
2. `skills/mae-flow/SKILL.md`：统一入口示例与后续命令前缀，说明缺失变量时的失败行为。
3. `scripts/tests/`：增加生产提示合同测试。

## 测试

回归测试必须证明：

- Command 和 Skill 不再包含 `<插件>`、`<插件目录>` 或 `.cac/skills/mae-flow`；
- 两个生产提示都包含 `CODEAGENT3_PLUGIN_ROOT` 主变量和
  `CLAUDE_PLUGIN_ROOT` 回退变量；
- CLI 路径整体被双引号包裹；
- 提示明确禁止猜路径和扫描缓存目录；
- 现有完整发布自测继续通过。

测试只验证生产提示合同，不修改或模拟 Hook，因为 Hook 不在本次范围内。

## 验收标准

在 CodeAgent3 中调用 `/mae-flow:mae-flow` 后，Agent 第一次执行 `current` 就使用宿主插件根变量构造入口；不会先访问 `.cac/skills/mae-flow`，也不会执行 `find` 定位 `mae-flow.py`。后续所有内部 CLI 调用沿用同一入口表达式。
