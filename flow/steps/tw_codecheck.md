执行 `python "{MAEFLOW_PATH}" codecheck-scan`。纯文案/配置改动会得到 0 个业务代码文件并直接放行，
不再使用人工 `skip`；这样“小改”只要真改了代码，就不可能靠一句理由跳过检查。
**0 告警直接 done,不派 agent**(codecheck-fix-agent 是修复工,没告警别派它空跑);有告警才执行
`python "{MAEFLOW_PATH}" agent-task codecheck`，把唯一启动话术原样交给它。
可用性只认 `codecheck fullcheck` 能否跑,裸 codecheck 报"不可用"不算数、别据此派 agent。
REMAINING 时同 verify_codecheck:流水线门禁必拦,没有"忽略"选项——逐项要么修(单独派实例)
要么 AskUserQuestion 取得用户裁决后执行 `python "{MAEFLOW_PATH}" approve-exemption ...`，
由 harness 登记审批并落盘 docs/codecheck-exempt-{单号}.md，再精确 commit(口头/手写豁免无效)。
done 会再次现场复核；解析失败时保存完整输出到 `.mae-flow-work/codecheck-diagnostics/`，
这是工具兼容问题，不会被误判成“有告警”并乱派修复 Agent。
