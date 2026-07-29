# Mae-Flow Refactor Phase 5 Plan

## Task 1：纯 Gate Intent

1. 新建 `test_guard_intent.py`，先覆盖解析与不修改输入的失败测试。
2. 实现 `guard/intent.py`，运行测试到 GREEN。
3. 提交纯解析边界。

## Task 2：拆分 Gate 适配器

1. 写 `cmd_gate` 分发特征测试。
2. 按原顺序把 Edit 和 Bash 三段移动到命名函数。
3. 使用 `GateIntent` 替代入口内联 token/分支/递归删除解析。
4. 运行 gate smoke、ownership、task scope 与全量单测。
5. 提交适配器拆分。

## Task 3：架构与差分门禁

1. 为 `cmd_gate` 和分段函数登记复杂度上限，自测显式运行新测试。
2. 从固定提交 `d5e7d7b...` 生成允许 Edit 与危险 Bash 拒绝 golden。
3. 对重构实现运行同一差分。
4. 提交门禁与 golden。

## Task 4：阶段冻结

1. 运行全量 unittest、selftest、phase 5 golden 与语法检查。
2. 审查规则顺序、permit 继续执行语义和绝对拒绝分类。
3. 确认工作树干净，冻结 phase 5 分支。
