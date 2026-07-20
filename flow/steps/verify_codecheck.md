启动 codecheck-fix-agent(契约见 agents/codecheck-fix-agent.md;传入:单号类型、基线分支、
编译方式配置原文、项目根绝对路径、测试路径配置(如有))。
**派发喂到嘴边**:把「变更业务代码文件清单」直接算好附进任务提示(git diff 过滤代码文件、排除测试后的
最终清单)——省它自己拼清单的轮次,也保证与 done 现场复核完全同一口径;
docs/delivery-notes.md 存在时把告警/规范相关条目一并附上,高发告警提前规避。
检查口径:**独立 CLI `codecheck fullcheck -f`,项目根执行,只查本单变更的业务代码(不查 UT/测试文件)**,
禁 increcheck——细则在 agent 契约里,你只需按上面清单传全。
(本步在 Ponytail 之后——不给已删代码修规范;在 UT 之前——拆大函数等重构在此定稿,UT 才能覆盖到最终形态。)
(FOUND/FIXED/REMAINING_COUNT 三数对账、复验摘录一致性、fullcheck 已由 SubagentStop hook 硬校验,打回会自动重答。)
CLEAN→done;REMAINING→展示遗留清单并**明确告知用户:线上流水线门禁会拦截同样的告警,
不在这里处理,MR 必然被打回——所以没有"忽略"这个选项**。
逐项用 AskUserQuestion 让用户裁决(每项两选项:修(附 agent 建议方案摘要)/正式豁免;工具不可用才纯文本),去向:
- **修** → 逐项单独派 codecheck-fix-agent 实例:每个实例只传这一条告警(文件/行号/规则/建议方案),
  全部轮次预算集中在一个问题上——复杂重构(如拆大函数)靠这个;
- **正式豁免** → **当场落盘**:把「规则ID + 文件名 + 用户裁决原话 + 理由」逐行追加进
  docs/codecheck-exempt-{单号}.md,git add && commit -m "[单号][类型]规范告警豁免记录"。
  口头豁免无效——done 的现场复核按这份文件放行,没落盘的豁免等于没豁免。
**done 硬校验(codecheck_clean,骗不过)**:状态机现场重跑 fullcheck 亲数遗留——
0 条,或每条都在豁免文件内,才放行;agent 说什么不作数。首次复核约十几秒/文件级,耐心等。
中断恢复:豁免记录在盘上(exempt 文件);遗留清单重启 agent 重新 fullcheck 即重建(幂等:已修的不会再报)。
