STORY 模板绝对路径 = {STORY_TEMPLATE_PATH}(直接传给 agent,勿再查找、勿用其他位置)。
中断恢复:读 docs/story/STORY-{单号}.md——残留"(待确认)"标注 = 未完成项,从那里继续逐项确认
(文档即状态,agent 无需重跑;文档不存在才重新派 agent)。
启动 story-generator-agent(契约见 agents/story-generator-agent.md)。
**模板禁止编造**:任何情况下不得"按标准结构自行创建"——传入的路径读不到就如实 FAIL 上报。
传入:单号、CHANGE_NAME、proposal/design/delta spec 路径、**上述模板绝对路径**、模式=常规生成。
**给 agent 的任务提示禁止包含终态指标**("零待确认残留""写成不涉及(已确认)"等 done 校验要求)——
那些是**你**在用户确认后要达成的,塞给 agent 只会诱导它伪造终态;agent 的交付标准只有它契约里那几条。
agent 异常中断/无 STORY_RESULT 标记 → 删除半成品,**重启 agent**(附上次异常信息,最多 2 次),
仍失败停下报告用户;**禁止你亲自代写 STORY**(绕过契约=待确认纪律全部失效)。
返回 DONE→展示 STORY 文件路径与章节概览;FAIL→展示缺失项由用户定;
NEEDS_CONFIRM→待确认项是**用户的决策,禁止以"判定合理/我认为妥当"自答**:
用 AskUserQuestion 逐项(或 multiSelect)拿用户确认,按答复把文档中的"(待确认)"标注更新为
"(已确认)"或修正内容——这个更新动作**只能由你在拿到用户答复后亲自做**,
**禁止把"消除待确认"转包给 agent**(agent 问不了用户,只会洗掉标记=伪造确认)。
**文档里残留"待确认"字样 = 本步没做完**;反之,零残留但你没走过 AskUserQuestion = 造假,更糟。
完成后同样展示路径与概览。
定稿后用 AskUserQuestion 询问用户 STORY 是否入库(一般不入库,仅本地交付给测试):
要 → git add docs/story/STORY-{单号}.md && git commit -m "[单号][类型]STORY文档"(精确路径,禁止宽 add);
不要 → 不要手动移动，也不要 `git add`；直接执行 done --set STORY入库=<用户选择原文>。
证据通过后 harness 会自动把文件移入 `.mae-flow-work/story/`，该区已 gitignore，随后把新路径告知用户交给测试。
如果文件已经被误加入 Git，done 会明确拒绝并给出精确移出方法；推送前还会再检查一次。
done 的硬校验(骗不过去):文档零"待确认"残留、每个"不涉及"必须写作"不涉及(已确认)"
(裸"不涉及"=未经用户确认的非法状态)、STORY入库 必填——三者共同保证确认闭环真实发生过。
