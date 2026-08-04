读取本单 `spec.md`、`grill.md`、`story.md` 和当前 CP。禁止另建 Test Blueprint、Roadmap、详细 Build Plan 或 Task 分析文档。

每个 CP 执行固定顺序：

1. `role-task cp-implement --checkpoint CPn`：任务卡给出精确输入路径、当前 CP 范围和允许修改的源码路径。
2. `agent-task compile --checkpoint CPn --scope "<当前 CP 范围>"`：一轮只执行一次同步编译；构建输入未变化时不得重跑。
3. 开场启用 CODE Reviewer 时，用 `role-task craft-code --checkpoint CPn` 生成精确任务卡并按节奏派发 craft-reviewer-agent：
   - Staged：当前 CP 最多一次；
   - Continuous：中间 CP 不派发，所有 CP 完成后统一一次。
4. 处理真实问题后重新编译；修正动作不自动触发第二轮 Reviewer。
5. 由现有 checkpoint 命令登记当前快照并推进。

Staged：每个 CP 完成后必须停下展示精确 diff、编译结果和检视结论，等待用户确认后才进入下一 CP。不得因为一起实现更高效而越过停点。

Continuous：所有 CP 连续完成，中间不询问、不推送；全部完成后展示一次最终代码增量供用户检视。

Adjust：不得进入编码，返回 Story 的 CP 小节调整后重新选择节奏。

实现中发现 Spec、Grill 决策或 Story 有实质错误时，停下说明问题、影响和最小修法，由用户决定是否回到对应上游；普通格式、注释或摘要变化不得触发流程回退。

{{CAPABILITY_PACK:build}}
