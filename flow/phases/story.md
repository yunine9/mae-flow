## 目标

把已确认需求整理成可独立交给开发和测试的软件详细设计，不重新打开需求范围。

## 当前要做

读取已确认 Spec、客户场景、性能规格、验收标准、相关架构、接口、测试策略和交付
约束。严格沿用 `.mae-flow-work/plugin-resources/assets/STORY-TEMPLATE.md`，禁止在
业务仓搜索插件模板。

`2.1.2 性能规格`只填写容量、最大并发、时延、吞吐、资源占用、兼容性和限制等
可度量约束，不复制 Spec 的业务行为规格。`2.2.2 接口设计`只描述 REST、CORBA、
RPC、消息或开放 SDK 等对外/跨组件公开契约；内部函数和方法统一写入
`2.2.7 关键函数/方法设计`。

调用一次 `story-generator-agent` 生成 Story，再调用一次 `craft-reviewer-agent`
并指定为设计检视角色。Story 说明实现边界、接口与依赖方向、数据流、错误语义、
资源生命周期、并发兼容性、可测性设计和连贯的开发批次；不要写成逐行编码计划。

两个能力正常返回后分别执行本次 `current` 同屏列出的完整命令，其固定 key 为：

- Story 生成：`python ".mae-flow-work/bin/mae-flow.py" advance capability-returned --key story --decision "<简短不透明摘要>"`
- 设计检视：`python ".mae-flow-work/bin/mae-flow.py" advance capability-returned --key reviewer --decision "<简短不透明摘要>"`

其他返回状态使用同屏对应的失败命令，不得猜事件名、改用 `--note` 或重跑能力。

## 何时询问用户

详细设计偏离已确认需求、存在真实设计取舍，或需要确认完整 Story 时询问用户。
普通设计检视通过不会新增停点；失败只记录，不自动重试。Design Reviewer 每份 Story
只调用一次；普通意见修正后把最终 Story 展示给用户，用户确认会绑定当前文件摘要，
不得因为修正发生在 Reviewer 返回后而再次调用 Reviewer。

## 本阶段产出

经检视的本地 Story，包含业务上下文、软件详细设计、开发批次、验证意图和已知风险。
只有用户明确要求时，才复制到 `docs/specs/requirements/<ticket>/story.md`。

## 下一步

用户确认详细设计后进入编码实现。
