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
  真的 `codecheck fullcheck` 本身跑不起来(报错/命令不存在)→ 保存诊断并按建议项留痕，
  不派 agent、不重复长跑，直接 done；源码变化后才重新尝试一次。
- 如果 CLI 完成了但输出格式暂时无法解析，harness 会把完整现场保存到
  `.mae-flow-work/codecheck-diagnostics/` 并绑定当前 HEAD。它属于工具兼容建议，
  不要求用户人工填数，也不因为解析器不认识新版本输出封死流程。
- 读输出的「共有 N 条告警」:

**N = 0(干净)→ 不派任何 agent,直接 done**(源码变化会让首检失效)。
这是最常见的正常路径,别把它走成"派个 agent 空跑一趟"。

**N > 0(有告警)→ 才派 codecheck-fix-agent 去修**:
执行 `python "{MAEFLOW_PATH}" agent-task codecheck`，把输出的唯一启动话术原样交给 agent；
传入单号类型、基线分支、编译方式配置原文、项目根绝对路径、测试路径配置(如有);
**喂到嘴边**:把上面算好的文件清单 + 首检告警明细直接附进任务提示(省它重算的轮次,与复核同口径);
docs/delivery-notes.md 存在时把告警/规范相关条目一并附上。
**大批量分批**:告警 >30 条或文件 >15 个 → 任务卡按文件划批，仍只派一轮修复；
不要为每条告警重启全新实例。
(本步在 Ponytail 之后——不给已删代码修规范;在 UT 之前——拆大函数等重构在此定稿,UT 才能覆盖到最终形态。)
(FOUND/FIXED/REMAINING_COUNT 三数对账、复验摘录一致性、fullcheck 已由 SubagentStop hook 硬校验,打回会自动重答。)
CLEAN→done；REMAINING→展示一次遗留摘要并直接 done，写入最终交付风险，不逐条询问、
不要求插件内豁免、不重启长任务。FAIL 且没有留下未验证源码改动时同样作为工具建议项收尾；
若 FAIL 后留有源码变化，必须回退或完成编译后再收尾。
done 只核对首检/Agent 证据仍绑定当前源码，不再第三次现场重跑 CodeCheck。
