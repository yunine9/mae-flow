本步派发采用**分批协议**(2026-07-20 实战定型:弱模型单实例马拉松 60-80 轮后被上下文裁剪拖垮,
加轮次预算救不了,分批才行):
1. **划批**:按变更文件/模块切批,每批 3-5 个方法或一个文件(依据变更文件清单与 delta spec);
2. **逐批派全新 ut-generator-agent 实例**,任务注明「第 N 批:仅处理 <文件/方法清单>」,并**喂到嘴边**:
   附该批相关的 delta spec EARS/Scenario 条目**原文**、该批文件清单(标注新增/修改)、
   docs/delivery-notes.md 的 mock 相关条目(如有)——不给路径让它自己读;
3. 批实例收尾(批内通过+已 commit)→ 派下一批;某批 NEEDS_INPUT/SUSPECTED_BUGS → 按下方协议处理完再续;
4. **收口实例**:所有批完成后派最后一个实例并注明「收口批」——跑**全量** UT 运行命令确认整体通过,
   出最终 PASS(其令牌绑最终代码状态,新鲜度证据由此成立)。
本步在 Ponytail/CodeCheck 之后,代码形态已定稿,UT 针对最终代码补测,不会因后续重构失效。
本仓配置了「测试路径」时(config 或 .mae-flow-defaults.json),gate 默认只放行测试路径写入;
这拦的是"未经用户裁决自行改被测源码",不是死禁——裁决通道见下方 SUSPECTED_BUGS 处理。未配置的仓行为不变。
PASS→done(codecheck 不检查测试文件,无需对测试代码补查);
NEEDS_INPUT→展示 PENDING_QUESTIONS 等用户答复后二轮启动;
FAIL→按 Fallback(隔离失败 UT,展示 KNOWN_FAILURES 等用户裁决)。
**SUSPECTED_BUGS 非空(可伴随任一状态)→ 这是"UT 测出代码可能有问题"的正规通道,逐项处理**:
UT 发现真缺陷是它的价值所在,不是异常。逐项用 AskUserQuestion 呈用户裁决,每项必须呈现 agent 的
自查报告(失败用例、期望 vs 实际、spec 依据、自查过程、倾向判断)——没有自查报告的项先打回 agent 补查。
三个选项与去向:
- **确认代码缺陷,本单修** → 执行 mae-flow unlock source --reason "<第N项:结论>" --ack "用户原话"
  (解锁仅本步有效,推进自动失效)→ 修复源码 → 编译 → git commit -m "[单号][类型]修复UT暴露的缺陷"
  → **重启 ut-generator-agent**(新鲜度绑定:源码已变,旧 UT 证据过期,重跑不是可选项);
- **判定 UT 理解有误,修测试** → 重启 agent 修订该用例(把用户结论原文带给它,作为修订授权);
- **本单不修(另立单)** → 记录裁决与理由,该用例按 KNOWN_FAILURES 隔离,提醒用户另立 DTS 单跟踪。
中断恢复:UT 文件与 commit 在盘上,报告在会话里——状态不确定就重启 agent(无状态幂等:
已有 UT 会被识别复用不重写),按新报告继续。
(本步无文件证据——UT agent 无固定产物;约束来自 SubagentStop 对 UT_RESULT 契约的硬校验与向用户展示的报告,展示不可省略。)
