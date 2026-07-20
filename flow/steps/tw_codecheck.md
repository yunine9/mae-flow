改动涉及业务代码 → 启动 codecheck-fix-agent(契约与传入清单同 verify_codecheck:CLI fullcheck、
项目根执行、只查业务代码不查测试);纯文案/配置改动 → skip --reason 说明。
REMAINING 时同 verify_codecheck:流水线门禁必拦,没有"忽略"选项——逐项要么修(单独派实例)
要么用户裁决豁免并**落盘 docs/codecheck-exempt-{单号}.md + commit**(口头豁免无效)。
done 硬校验(codecheck_clean):状态机现场重跑 fullcheck 亲数遗留,0 条或全在豁免文件内才放行。
