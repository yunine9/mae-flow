# Mae-Flow 重构问题收口设计

**基线：** `refactor/mae-flow-phase-8` / `7dc4fde`

## 目标

修复重构问题账本中仍未关闭的 MF-RF-001、MF-RF-002 和 MF-RF-003。
每个问题必须先有可稳定失败的测试，再实施最小修复；除明确修正的行为外，CLI、
Hook、状态文件、输出、退出码和 Git 副作用继续与固定旧实现一致。

## MF-RF-001：文件句柄生命周期

根因是 CLI、Hook 和兼容入口仍存在 `open(...).read/write`、`json.load(open(...))`
等未托管文件对象。CPython 通常会很快回收，但测试已稳定产生 `ResourceWarning`，
Windows 上还可能延迟释放文件。

新增 `mae_flow_core/file_io.py`，提供保持原编码、errors、读取长度和 JSON 异常语义的
受控读写函数。生产运行路径中的未托管文件操作迁移到该入口或显式 `with open(...)`。
架构测试扫描生产 Python 文件，拒绝新增不在 context manager 中的 `open()`。

测试夹具自身产生的已知警告同时改为 context manager。验收时以开启
`ResourceWarning` 的 Checkpoint 回归和全量 unittest 输出为准。

## MF-RF-002：动态流程边

根因是 `transition_targets()` 只读取普通 `next`，但运行时还会通过以下方式进入步骤：

- `source_change_next`；
- `source_change_recheck`；
- push 后进入 `moonlight_review`；
- 旧状态直接恢复到 `rf_verify`。

`transition_targets()` 扩展为读取流程定义中声明的动态目标字段。`flow.json` 为 push
声明 `dynamic_next: ["moonlight_review"]`，并在顶层声明
`compatibility_entries: ["rf_verify"]`。新增纯 `workflow_graph_errors()`，从 start
遍历普通和动态边，将兼容入口作为合法外部入口，同时验证所有目标和兼容入口存在。

这些字段只用于定义、自检和架构可视性；运行时推进仍使用现有业务策略，不改变状态迁移。

## MF-RF-003：Git 组合短参数

根因是 `git_add_intent()` 使用 token 精确集合判断 `-f/-u/-A`，而
`git_commit_intent()` 已使用 `short_option_flags()` 展开组合短参数。

`git_add_intent()` 改为复用同一展开规则：

- `f` → force；
- `u` → tracked_only，并在无显式 pathspec 时使用 `.`；
- `A` → all，并在无显式 pathspec 时使用 `.`。

覆盖 `-fu`、`-uf`、`-Af`、独立长短参数和显式 `-- path`。新增真实 Git/Gate 黑盒
场景，证明组合参数会进入与拆分参数相同的候选检查。

## 差分策略

phase 9 golden 包含 phase 8 的所有旧场景，并新增组合短参数 Gate 场景：

- 固定旧实现必须只在新场景上表现为旧漏判；
- 修复实现必须匹配 phase 9 期望；
- 现有场景不得产生其他差异。

文件句柄和流程图修复不允许改变公开输出。

## 提交边界

1. `fix: close unmanaged runtime file handles`
2. `fix: declare dynamic workflow entries`
3. `fix: parse combined git add flags`
4. 最终测试/账本收口提交（仅测试、golden 和文档）

## 非目标

- 不继续拆解 10,408 行兼容适配层；
- 不重写 selftest 中所有测试夹具的文件辅助代码；
- 不修复账本之外的新产品行为；
- 不合并、不推送。
