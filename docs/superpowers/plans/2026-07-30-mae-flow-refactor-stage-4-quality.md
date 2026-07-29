# Mae-Flow Stage 4：Quality Use Cases 实施计划

> 每项严格 RED → GREEN → 回归 → 小提交；Phase-13 不可修改。

## Task 1：建立 Phase-14 Quality Oracle

- 追加 CodeCheck 分批、工具错误、范围裁决和缓存场景；
- 追加任务卡、UT 凭证复用/失效和独立质量任务场景；
- 固定 Phase-14 逐项保留 Phase-13；
- 提交 `test: characterize quality use cases`。

## Task 2：提取 CodeCheck 纯策略

- 固定 console/report/JSON 解析、多批聚合和未知输出语义；
- 建立不可变扫描结果、告警与缓存键；
- 提交 `refactor: extract codecheck policies`。

## Task 3：迁移 CodeCheck 执行用例

- 通过 ports 请求 executable、process、日志和文件；
- CLI 只执行 effect，保留命令、超时、输出和事件顺序；
- 提交 `refactor: extract codecheck use cases`。

## Task 4：迁移质量任务卡用例

- 迁移文件分组、execution roots、源码快照、任务卡正文和 SHA256；
- 统一完整流程与独立任务的公共事实模型，不合并其不同安全边界；
- 提交 `refactor: extract quality task card use cases`。

## Task 5：迁移范围与缓存编排

- 迁移 scan/scope/record、月光范围策略和源码变化失效；
- 固定 UT/编译/Grill 任务派发前条件与历史状态；
- 提交 `refactor: extract quality cache and scope use cases`。

## Task 6：删除 CLI Quality 业务实现

- AST 门禁阻止解析、缓存和任务卡状态判断回流入口；
- 业务测试迁到公开 Quality API，保留 CLI 装配冒烟；
- 提交 `refactor: remove quality policy from cli`。

## Task 7：Stage 4 全量证明与独立审查

- 完整 unittest、自检、Phase-14、fault injection；
- Quality/CodeCheck/TaskCard 严格 ResourceWarning；
- 大小、复杂度、依赖和私有单体耦合检查；
- 修复全部 Critical/Important；
- 提交 `docs: record quality refactor completion`。
