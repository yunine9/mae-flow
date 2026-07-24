评审意见处理阶段的独立规范检查。主会话只负责触发机器首检和呈报裁决，**禁止亲自修告警**。

1. 执行 `python "{MAEFLOW_PATH}" codecheck-scan`。该命令按返工基点只检查本轮业务代码，并记录首检 HEAD/告警数。
2. 首检 0 告警 → 不派 agent，直接 done；首检后源码若变化，done 会判首检过期并要求重扫。
3. 首检有告警 → 执行 `python "{MAEFLOW_PATH}" agent-task codecheck`，把输出的唯一启动话术原样交给 codecheck-fix-agent。禁止主会话代修；任务卡已包含范围、配置和编译方式。
4. agent 返回 REMAINING 时逐项 AskUserQuestion，让用户选择「修复」或「正式豁免」：
   - 修复：重启 codecheck-fix-agent，只处理点名告警；
   - 正式豁免：用户确认后执行
     `python "{MAEFLOW_PATH}" approve-exemption --rule "<规则ID>" --file "<文件>" --reason "<理由>" --ack "<用户原话>"`，
     再精确提交生成的 `docs/codecheck-exempt-{单号}.md`。禁止手写豁免冒充审批。
5. done 会现场重跑 CodeCheck。0 告警，或每条遗留都同时具备「豁免文件 + 用户审批令牌」，才放行。

CodeCheck CLI 成功返回码不稳定，harness 从报告汇总表/提示文案取告警数，不再只认「共有 N 条告警」一句话。
如果 CLI 已完成但新版本输出仍无法解析，完整现场会保存在 `.mae-flow-work/codecheck-diagnostics/`。
重试仍失败时，由用户看过报告后按错误信息给出的 `codecheck-record` 命令登记人工确认数；记录绑定当前 HEAD，
源码变化即失效。不要把解析问题误当告警，更不要为了继续流程随便填 0。
