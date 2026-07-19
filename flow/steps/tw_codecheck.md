改动涉及代码文件 → 启动 codecheck-fix-agent(契约见 agents/codecheck-fix-agent.md);
返回后校验 EXECUTED_COMMAND 含 "fullcheck",含 "increcheck" 或缺失 → 视同 FAIL 重新启动。
纯文案/配置改动 → skip --reason 说明。
REMAINING 时同 verify_codecheck:流水线门禁必拦,没有"忽略"选项——逐项要么修(单独派实例)
要么用户明确豁免,清单不清零禁止 done。
