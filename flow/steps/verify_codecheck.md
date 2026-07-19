启动 codecheck-fix-agent(契约见 agents/codecheck-fix-agent.md,fullcheck -f,禁 increcheck;
docs/delivery-notes.md 存在时把其中告警/规范相关条目附进任务提示,高发告警提前规避)。
(本步在 Ponytail 之后——不给已删代码修规范;在 UT 之前——拆大函数等重构在此定稿,UT 才能覆盖到最终形态。)
返回后先校验 EXECUTED_COMMAND:必须含 "fullcheck";含 "increcheck" 或缺失该字段 → 视同 FAIL,指出违规原因重新启动该 agent。
(FOUND/FIXED/REMAINING_COUNT 三数对账与 fullcheck 已由 SubagentStop hook 硬校验,打回的 agent 会自动重答。)
CLEAN→done;REMAINING→展示遗留告警清单并**明确告知用户:线上流水线门禁会拦截同样的告警,
不在这里处理,MR 必然被打回——所以没有"忽略"这个选项**。
逐项用 AskUserQuestion 让用户裁决(每项两选项:修(附 agent 建议方案摘要)/正式豁免;工具不可用才纯文本),去向:
- **修** → 逐项单独派 codecheck-fix-agent 实例:每个实例只传入这一条告警
  (文件/行号/规则/agent 建议的方案),全部轮次预算集中在一个问题上——复杂重构(如拆大函数)靠这个;
- **正式豁免** → 用户确认走公司豁免流程的项,记录豁免理由与用户原话,随报告展示。
REMAINING 清单未清零(每项要么修掉、要么用户明确豁免)之前,禁止 done。
中断恢复:遗留清单与裁决进展只在会话里——重启 agent 重新 fullcheck(幂等:已修的不会再报),
对新清单重新走裁决;此前用户已给的豁免拿不准就重新确认,禁止凭印象补记。
(本步无文件证据——codecheck 无固定产物;报告展示不可省略。)
