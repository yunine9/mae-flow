执行 /comet-open(comet 技能,内部会经 comet-state 登记 .comet.yaml 状态),输入 = SE 设计文档(含内联需求)+ clarifications(如有)。
**禁止绕过技能手工创建产物**;若已手工补齐产物,状态登记必须走 comet 脚本
(comet-state init <change-name> <workflow>),.comet.yaml/.openspec.yaml 手写会被 gate 拦截——这不是故障,是纠偏。
有 clarifications 时明确告知 comet-open:需求澄清已在 Grill 完成(附文档路径),其 Step 1 勿重复质询,直接进入产物生成。
确认产物:proposal.md、design.md、tasks.md、specs/<domain>/spec.md(delta spec)。
delta spec 的 Scenario 用 EARS 句式表述(WHEN <条件> THE SYSTEM SHALL <可观测行为>,每条独立可测;
clarifications 里已是 EARS 的答案直接沿用)——UT 阶段将按这些条目逐条对照覆盖,含糊句式=测不了=白写。
逐条比对 delta spec 与 SE 文档,不一致则修正;记录 CHANGE_NAME;确认 .comet.yaml phase=open。
展示比对结果,结束回复等用户确认。确认后 git add openspec/ docs/ && git commit -m "[单号][类型]提案与规格"
(spec 产物必须进 MR,同时保持工作区洁净),再 done --ack --set CHANGE_NAME=<change目录名>(校验本 change 的 proposal/delta spec/.comet.yaml 存在)。
