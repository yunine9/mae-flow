**本步结构是"先检查、后按结果分岔"——codecheck-fix-agent 是修复工,不是检查工,没告警就别派它。**

第 0 步执行 `python "{MAEFLOW_PATH}" codecheck-scan`，由 harness 统一计算文件并运行检查：
- 算「变更业务代码文件清单」:git diff --name-only 基线...HEAD 过滤代码文件、排除测试文件;
  **清单为空(本单没改业务代码)→ 无需检查,直接 done**;
- harness 在项目根执行 `codecheck fullcheck -f <清单>`(禁 increcheck),随后**按覆盖口径过滤**:
  只计本次修改范围(变更行±3,近似"改动所在函数")内的告警——**文件里的存量告警不是本单的债**
  (线上流水线同为增量口径,不会拦存量),scan 会报"另有 N 条存量告警未计入"供知情,
  存量治理另立单;告警明细缺行号时保守全算并明示;
  **可用性只认这一条命令能不能跑**——裸 `codecheck`、`codecheck --help` 之类报"不可用"一律不算数,
  别据此判定"codecheck 坏了"更别派 agent 去"修复 codecheck"(它是修代码规范的,不修工具);
  真的 `codecheck fullcheck` 本身跑不起来(报错/命令不存在)→ 这是环境问题,停下报告用户,不是派 agent。
- 如果 CLI 完成了但输出格式暂时无法解析，harness 会把完整现场保存到
  `.mae-flow-work/codecheck-diagnostics/`。先重试一次；仍失败时让用户看过报告后执行错误信息给出的
  `codecheck-record` 命令。记录绑定当前 HEAD 和文件清单，代码一变即失效；它是兼容恢复口，不是告警豁免。
- 读输出的「共有 N 条告警」:

**N = 0(干净)→ 不派任何 agent,直接 done**(源码变化会让首检失效)。
这是最常见的正常路径,别把它走成"派个 agent 空跑一趟"。

**N > 0(有告警)→ 才派 codecheck-fix-agent 去修**:
执行 `python "{MAEFLOW_PATH}" agent-task codecheck`，把输出的唯一启动话术原样交给 agent；
传入单号类型、基线分支、编译方式配置原文、项目根绝对路径、测试路径配置(如有);
**喂到嘴边**:把上面算好的文件清单 + 首检告警明细直接附进任务提示(省它重算的轮次,与复核同口径);
docs/delivery-notes.md 存在时把告警/规范相关条目一并附上。
**大批量分批**:告警 >30 条或文件 >15 个 → 按文件划批逐批派全新实例(每批附该批清单与告警,三数对账按批内计);
**不需要收口实例**——done 的 codecheck_clean 现场复核就是全量收口。
(本步在 Ponytail 之后——不给已删代码修规范;在 UT 之前——拆大函数等重构在此定稿,UT 才能覆盖到最终形态。)
(FOUND/FIXED/REMAINING_COUNT 三数对账、复验摘录一致性、fullcheck 已由 SubagentStop hook 硬校验,打回会自动重答。)
CLEAN→done;REMAINING→展示遗留清单并**明确告知用户:线上流水线门禁会拦截同样的告警,
不在这里处理,MR 必然被打回——所以没有"忽略"这个选项**。
逐项用 AskUserQuestion 让用户裁决(每项两选项:修(附 agent 建议方案摘要)/正式豁免;工具不可用才纯文本),去向:
- **修** → 逐项单独派 codecheck-fix-agent 实例:每个实例只传这一条告警(文件/行号/规则/建议方案),
  全部轮次预算集中在一个问题上——复杂重构(如拆大函数)靠这个;
- **正式豁免** → 用户拍板后执行
  `python "{MAEFLOW_PATH}" approve-exemption --rule "<规则ID>" --file "<文件>" --reason "<理由>" --ack "<用户原话>"`，
  由 harness 同时写审批账与 docs/codecheck-exempt-{单号}.md，再精确 git add/commit。
  口头豁免无效——done 的现场复核按这份文件放行,没落盘的豁免等于没豁免。
**done 硬校验(codecheck_clean,骗不过)**:状态机现场重跑 fullcheck 亲数遗留——
0 条,或每条都在豁免文件内,才放行;agent 说什么不作数。首次复核约十几秒/文件级,耐心等。
中断恢复:豁免记录在盘上(exempt 文件);遗留清单重启 agent 重新 fullcheck 即重建(幂等:已修的不会再报)。
