# Mae-Flow Stage 4：Quality Use Cases 设计

## 目标

将 CLI 中 CodeCheck、编译/UT/Grill 任务卡、范围裁决、机器结果缓存与复验编排迁入
`mae_flow_core.application.quality`，保持命令、输出、状态 schema、工具调用、缓存命中与
失效顺序完全不变。

Stage 4 不迁移 `hooks/dispatch.py` 的 Agent transcript 与最终报告验签；那部分属于
Stage 5。Stage 4 只负责在派发前生成冻结任务、执行 CLI 侧机器检查、登记可供 Hook
验签的事实。

## 当前边界

CLI 仍负责：

- CodeCheck 可执行文件发现、分批、命令执行和多格式结果解析；
- 首检范围分类、用户范围裁决、scan/verify 缓存与日志事件；
- COMPILE/CODECHECK/UT/GRILL 任务卡的文件范围、执行目录、基点与指纹；
- 独立任务和完整流程两套相似但不完全相同的质量编排；
- 源码变化后的缓存失效与质量链回流。

`quality/task_cards.py` 与 `quality/evidence.py` 已有纯规则，但入口仍组合大量业务判断。

## 目标结构

- `application/quality/codecheck.py`：首检/复验请求到有序 effect；
- `application/quality/task_cards.py`：完整流程与独立任务的任务卡用例；
- `quality/codecheck.py`：输出解析、分批聚合、范围和缓存纯策略；
- `quality/unit_tests.py`：UT 范围与缓存有效性纯策略；
- `adapters/processes.py`：后续 Stage 7 统一的进程执行端口；本阶段先使用显式 ports。

Application 层不得直接 `open`、`subprocess`、`chdir` 或 `print`。CLI 只收集平台事实、
执行 effect 并映射历史文案。

## 行为冻结

Phase-14 在 Phase-13 上只追加：

- CodeCheck 多批告警、工具错误、未知成功输出、check-only；
- 范围内/疑似范围外裁决与月光保守全纳入；
- task card 基点、文件组、execution roots 与 SHA256；
- 源码变化后的 scan/verify/Agent task 缓存失效；
- UT 范围缩小、旧执行凭证复用与必须重跑边界；
- 独立 CodeCheck/UT 的 clean、repair-required 和 tool-error。

既有 Phase-13 快照不得修改。

## 完成条件

- CLI 不再包含 CodeCheck 解析、任务卡状态转换或质量缓存业务判断；
- Quality 用例使用 fake ports 独立测试；
- 新模块不超过 500 行，复杂度不超过 15；
- Phase-14、完整测试、fault injection、ResourceWarning 与独立审查通过。
