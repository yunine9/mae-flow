纯文案/配置改动 → skip --reason 说明。
改动涉及业务代码 → **先自己跑一次** `codecheck fullcheck -f <变更业务代码清单>`(同 verify_codecheck 的先检查后分岔):
**0 告警直接 done,不派 agent**(codecheck-fix-agent 是修复工,没告警别派它空跑);有告警才派它去修。
可用性只认 `codecheck fullcheck` 能否跑,裸 codecheck 报"不可用"不算数、别据此派 agent。
REMAINING 时同 verify_codecheck:流水线门禁必拦,没有"忽略"选项——逐项要么修(单独派实例)
要么用户裁决豁免并**落盘 docs/codecheck-exempt-{单号}.md + commit**(口头豁免无效)。
done 硬校验(codecheck_clean):状态机现场重跑 fullcheck 亲数遗留,0 条或全在豁免文件内才放行。
