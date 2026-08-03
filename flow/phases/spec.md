## 目标

通过交互式质询（Interactive Grill）确认“系统必须表现成什么样”，包括可观察行为、
边界、失败语义、兼容性和非目标；本阶段不决定具体实现方式。

## 当前要做：完整质询

读取 `current` 输出的精确本地资源：

- `.mae-flow-work/plugin-resources/guidance/grill.md`
- `.mae-flow-work/plugin-resources/assets/GRILL-PREP-TEMPLATE.md`

禁止在业务仓搜索插件的 `runtime/`、`skills/` 或 `flow/`。调查需求、相关行为基线、
当前代码与约束，在 `current` 给出的安全目录写 `survey.md` 和 `grill-prep.md`。
八个维度都必须有带证据的候选问题或明确的不适用依据；有占位内容时不能开始或
结束质询。问题数量由真实缺口决定，超过 15 题时告知用户并由用户决定是否继续。

旧 Grill 或 Spec 只能作为历史线索。只有当前状态中有对应问题与回答收据的决定，
才属于本轮确认结果。

每次只问一个 `GQ-*` 问题。提问前先执行：

`python ".mae-flow-work/bin/mae-flow.py" advance grill-question --key <GQ-ID> --parent <ROOT|已回答GQ-ID> --evidence "<证据>" --impact "<影响>" --recommendation "<推荐及理由>"`

用户回答后执行完整 `decision grill-answer` 命令。若答案先于问题登记到达，在该
decision 命令上附同一组元数据，原子补登记并消费答案。每个回答都要检查模糊词、
矛盾、新状态和衍生分支。

全部问题关闭后，将证据、问题树、回答、边界、兼容性、失败行为和非目标写入精确
`grill.md`，再执行：

`python ".mae-flow-work/bin/mae-flow.py" advance grill-converged`

## 生成候选 Spec

收敛后才生成 `spec.md`。需求、相关行为基线和 `grill.md` 都是关键输入；Spec 必须
包含“Grill 决策追溯”，把每个 `GQ-*` 映射到章节或可观察验收标准。实现方式留给
详细设计阶段。

随后为当前 Grill/Spec 内容调用一次 `grill-critic-agent`。它只读检查输入覆盖、
决定是否被弱化、术语一致性、可验收性和 WHAT/HOW 混杂；不编辑文件、不替用户
决定。调用前只看本次 `current` 的动态能力区：仍列出 Grill Critic 命令时调用一次，
真实返回后只执行匹配结果的一条命令；已显示“当前语义位置已记录一次”时直接继续，
禁止再次调用。该命令会原子记录调用事实和当前 Grill/Spec 检视收据，不存在第二条
收尾命令。

启动失败、超时或未观察到返回时，同样只执行动态能力区匹配结果的一条命令，不重跑
Critic。Critic 后的普通内容修正不会使其重新运行；最终由用户确认当前 Grill/Spec，
文件摘要只记录版本，不作为回退门禁。

## 何时询问用户

逐题询问真实产品决定；最终请用户确认完整的可观察范围。普通 Critic CLEAR 不增加
用户停点。

## 本阶段产出

本地 `grill.md` 和已确认 `spec.md`。只有用户明确要求时，才复制 Spec 到
`docs/specs/requirements/<ticket>/spec.md`。

## 下一步

用户确认当前最终 Spec 后进入详细设计。
