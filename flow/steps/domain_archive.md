质量验证已经完成。现在只把本次最终代码中已经确认、实现并验证的长期知识归档到领域真相源；Spec、Grill、Story、实施附录、评审和验证过程件都留在 `.mae-flow-work/<单号>/`，不得提交。

先按 `docs/specs/index.md` 判断本次涉及的领域。每个领域分别执行：

`python "{MAEFLOW_PATH}" domain-archive prepare --domain "<领域>" --keyword "<关键词>"`

首次执行只会在本单 `domain-archive/` 下初始化候选。根据本地 Spec、Grill、Story、实施附录、最终代码和测试补充长期事实，删除模板草稿标记，然后原样重跑该命令。多个领域逐个准备；没有任何长期知识变化时执行：

`python "{MAEFLOW_PATH}" domain-archive prepare --unchanged`

用下列命令展示归档结论和 diff：

`python "{MAEFLOW_PATH}" domain-archive show`

若当前是月光宝盒无人值守模式，到这里不得替用户确认或伪造消息 ID。完成 prepare/show 后执行 `python "{MAEFLOW_PATH}" moonlight blocked --reason "领域归档候选等待用户确认"` 安全停止；早晨处理后从本步骤继续。

只向用户确认一次。收到回答后先执行 `python "{MAEFLOW_PATH}" messages` 取得当前回答 ID，再执行：

`python "{MAEFLOW_PATH}" domain-archive apply --message-id "<消息ID>"`

候选过期只重新 prepare，不回退编码、Reviewer、编译、CodeCheck 或 UT。命令失败时执行 `python "{MAEFLOW_PATH}" domain-archive status`，按输出的唯一恢复动作处理；禁止猜参数、循环重试或改写流程状态。应用完成后 done。
