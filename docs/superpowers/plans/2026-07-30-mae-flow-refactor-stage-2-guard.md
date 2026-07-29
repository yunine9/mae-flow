# Mae-Flow Stage 2：Gate、Permit 与 Ownership 实施计划

> 严格执行 RED → GREEN → 回归 → 小提交。Phase-11 旧快照不可修改。

## Task 1：建立 Phase-12 Guard Oracle

- 为 Edit、Bash、Permit、Ownership 和 Git 路径矩阵添加确定性差分场景；
- 更新 coverage manifest，生成只追加场景的 Phase-12；
- 固定 `phase12 preserves every phase11 snapshot`；
- 提交 `test: characterize guard and ownership behavior`。

## Task 2：提取 GateDecision 与编辑规则

- 先用 fake facts 固定绝对禁令、可放行规则、checkpoint/source/tests-only；
- 在 `guard/gate.py` 实现不可变决策；
- CLI `_gate_edit` 只收集事实、执行决策；
- 提交 `refactor: extract edit gate policies`。

## Task 3：提取 Bash 写入与危险命令规则

- 固定重定向、强/弱写入、内部状态、spec/source、递归删除和分支命令；
- 纯策略不得执行正则之外的 I/O；
- 保持软提醒与硬拦截顺序；
- 提交 `refactor: extract bash gate policies`。

## Task 4：提取 Permit 状态机

- 固定 block id、step/head 绑定、一次消费、损坏 sidecar、三振和 Moonlight；
- `guard/permits.py` 返回事件，CLI 适配器按原顺序保存；
- fault injection 覆盖读取、隔离、CAS/更新和历史保存失败；
- 提交 `refactor: extract gate permit policies`。

## Task 5：提取 Ownership 裁决

- 固定 reviewed snapshot、initial carryover、foreign OpenSpec、强产物、
  unproven/artifact hints；
- `guard/ownership.py` 只接收已采集候选事实；
- CLI 保留 Git 采集和 advisory lightcheck；
- 提交 `refactor: extract commit ownership policies`。

## Task 6：统一 CLI/Hook 公共入口并清理旧实现

- 增加 AST 门禁：CLI/Hook 不得复制 Gate/Permit/Ownership 策略；
- 将相关测试迁到公开内核 API，仅保留入口装配冒烟；
- 删除无调用兼容桥和重复正则；
- 更新架构文档；
- 提交 `refactor: remove guard policy from entrypoints`。

## Task 7：Stage 2 全量证明与独立审查

依次运行：

1. 完整 unittest discover；
2. 完整 selftest；
3. Phase-12 differential runner；
4. fault injection；
5. State、Checkpoint、Guard/Ownership 测试的严格 ResourceWarning；
6. 架构大小、复杂度、依赖与私有单体耦合扫描；
7. `git diff --check` 和 Phase-11 不变检查；
8. 独立审查并修复全部 Critical/Important。

最终提交：`docs: record guard refactor completion`。
