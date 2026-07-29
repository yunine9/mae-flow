# Mae-Flow 重构 Stage 1：Evidence 设计

## 目标

在不改变任何用户可观察行为的前提下，将证据的名称、结果语义、注册和裁决从
`scripts/mae-flow.py` 迁入内核。完成后：

- `done` 仍按 `flow/flow.json` 中的原顺序逐项检查证据；
- 所有证据名称、成功条件、失败文案、异常兜底和退出码保持不变；
- Checkpoint、Moonlight、规格和质量恢复入口仍可复用同一证据规则；
- CLI 不再定义 `ev_*` 业务判断，只装配 I/O 端口、保留必要兼容别名并映射结果；
- 后续 Stage 2–6 可以直接依赖稳定的 Evidence API，不再反向调用 CLI 私有函数。

本阶段不是重写规则，也不借机改变门禁强度。任何已确认缺陷必须先用独立失败测试证明，
再用单独的 `fix:` 提交修复；行为保持型提交的 Phase-10 旧场景必须逐项完全相同。

## 现状与风险

当前 `scripts/mae-flow.py` 有 23 个 `ev_*` 函数和一个 `EVIDENCE` 字典。规则横跨：

- 文件与规格产物；
- 分支、提交、推送和交付归属；
- Agent 令牌、源码新鲜度和用户风险许可；
- Checkpoint 与最终检视；
- CodeCheck 结果和缓存复用。

这些函数还被 `done` 之外的 Checkpoint、Moonlight、`goto`、`spec verify-pass` 和
CodeCheck 恢复入口直接调用。若只搬走 `EVIDENCE` 字典，CLI 仍然拥有全部业务规则；
若一次性把所有帮助函数也搬走，则会同时改动 Git、状态、交付和质量边界，无法可靠证明
行为保持。

## 采用方案：稳定内核 API + 分规则族绞杀

### 1. 值对象

在 `mae_flow_core/foundation/models.py` 定义不可变的 `EvidenceResult`：

- `passed: bool`
- `reason: str`

它保持二元组解包兼容，既有 `ok, why = ...` 调用无需改变。内核新增规则必须返回该值
对象；迁移期兼容适配器会把历史 `(bool, str)` 规范化为同一类型。

`EvidenceResult` 不携带状态、不读取环境，也不决定打印或退出。

### 2. 注册与执行

在 `mae_flow_core/workflow/evidence.py` 定义：

- `EvidenceEvaluator`：`(spec, state) -> EvidenceResult` 协议；
- `EvidenceRegistry`：只读名称到 evaluator 的映射；
- `evaluate_step_evidence(step, state, registry)`：按声明顺序执行并返回失败文案；
- `legacy_result(value)`：迁移期只负责将历史二元组规范化。

未知证据名继续产生与当前直接字典索引一致的错误，而不是静默跳过。`yaml_field` 继续和
`spec_field` 指向同一 evaluator，直到兼容桥清理阶段确认无历史调用。

`workflow/completion.py` 不再自己实现第二套证据循环，只委托给
`workflow/evidence.py`。保留原函数名的薄兼容入口，避免在途导入断裂。

### 3. 明确的 I/O 端口

具体证据规则按依赖分为四组：

- `workflow/evidence_rules.py`：glob、content、clean path、branch、spec、tier；
- `workflow/agent_evidence.py`：Agent 令牌、风险许可、源码新鲜度；
- `delivery/evidence.py`：Checkpoint、review、commit、archive、push；
- `quality/evidence.py`：CodeCheck 证据及质量缓存有效性。

规则不得导入 `scripts/mae-flow.py`，也不得读取其全局变量。每组通过最小的冻结端口对象
取得文件、Git、时间、状态或已有领域服务。端口只返回事实，不替规则作“放行/拒绝”
决定。这样既能保持现有 I/O 顺序，又不会把 CLI 整体伪装成一个 god-object 注入内核。

迁移顺序固定为：

1. 无副作用的通用规则；
2. Agent 令牌与源码新鲜度；
3. Delivery 规则；
4. Quality 规则；
5. 删除 CLI 中的实现体，只保留导入别名；
6. 在无直接调用后删除不再需要的别名。

每一步只迁移一个规则族，并在提交前运行同一套 Oracle。

### 4. CLI 装配

`scripts/mae-flow.py` 负责：

- 使用现有 Git、文件、StateStore 和时间函数构造端口；
- 构造一次 `EvidenceRegistry`；
- 将 step/state 交给 Evidence 内核；
- 按既有文案、退出码和 `done` 顺序映射结果。

CLI 中不允许出现：

- 新的证据成功/失败分支；
- 证据名称到实现的字典；
- Agent 令牌、新鲜度、CodeCheck 或提交合规判断；
- 为让测试通过而复制一份旧规则。

为了兼容尚未迁走的调用和旧测试，`ev_*` 名称可暂时绑定到内核函数或装配后的
evaluator，但不得包含判断逻辑。Stage 6 会在所有调用者改用公开 API 后删除这些别名。

## 行为保持 Oracle

Stage 1 新增 Phase-11，只允许在 Phase-10 上增加迁移前 characterization 场景。
Phase-10 的每个 key、stdout、stderr、退出码、状态、文件哈希和 Git 状态必须逐项相同。

Phase-11 至少固定：

- 多证据按声明顺序失败，失败文案顺序不变；
- `yaml_field` 历史别名；
- 未知证据名的失败语义；
- Agent 令牌不存在、过期、源码改变和 accept-risk；
- Checkpoint、最终检视、提交格式与推送证据；
- CodeCheck CLEAN、REMAINING、FAIL 和源码变化；
- 规格字段、占位符、空清单、glob/absent/clean path；
- evaluator 内部 I/O/解析异常仍按原文案拒绝而不是 traceback；
- DIRECT、STANDALONE 和 Moonlight 下证据旁路或复用边界。

单元测试分三层：

1. 值对象和注册表的纯测试；
2. 端口假对象驱动的每个规则族测试；
3. 真实临时 Git 仓和 CLI 差分测试。

现有直接加载 `mae-flow.py` 的测试在本阶段先改为断言公开 Evidence API；只有验证
CLI 装配/兼容时才允许继续加载入口。架构测试禁止生产内核导入测试故障注入模块，
并禁止 CLI 重新定义 `ev_*` 函数体。

## 故障与兼容处理

- 文件不存在、编码失败、Git 基点不可解析和状态损坏继续使用原有宽窄异常边界；
- 端口异常不统一吞掉：只有旧 evaluator 已明确转成失败文案的路径才继续转换；
- 时间、路径标准化和 Windows 非 UTF-8 行为由适配器保持，不放进纯策略；
- 状态字段和值不迁移、不重命名，未知字段仍由 `StateStore` 保留；
- Evidence 迁移不改变 `done` 中 choice、证据、源码回流和 advancement 的先后顺序；
- 兼容别名只有在 AST、字符串路由、完整 selftest 和 Phase-11 差分均无依赖后删除。

## 完成标准

Stage 1 只有同时满足以下条件才算完成：

- `scripts/mae-flow.py` 中没有 `def ev_*`，没有证据注册字典和证据业务判断；
- 所有 23 个历史证据名及 `yaml_field` 别名均由内核注册；
- Evidence 结果全部使用不可变值对象，规则族模块均不超过 500 行、复杂度不超过 15；
- `workflow/completion.py` 只有一个证据执行源；
- Phase-10 逐项完全保持，Phase-11 新场景全部通过；
- Evidence 单测、完整 unittest、`scripts/selftest.py`、严格 `ResourceWarning` 和
  `git diff --check` 全部通过；
- 独立代码审查无 Critical/Important 问题；
- 没有为了通过门禁降低 Stage 0 完成契约。
