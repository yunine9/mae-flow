执行 `python "{MAEFLOW_PATH}" codecheck-scan`。纯文案/配置改动会得到 0 个业务代码文件并直接放行，
不再使用人工 `skip`；这样“小改”只要真改了代码，就不可能靠一句理由跳过检查。
若 scan 列出 W1/W2 等“疑似范围外”候选，机器不能直接当存量排除：用 AskUserQuestion 分批展示，
让用户选择哪些涉及本次修改，再严格按输出执行 `codecheck-scope --include ...` 或
`codecheck-scope --none`。确认前禁止生成修复任务卡或 done。
**0 告警直接 done,不派 agent**(codecheck-fix-agent 是修复工,没告警别派它空跑);有告警才执行
`python "{MAEFLOW_PATH}" agent-task codecheck`，把唯一启动话术原样交给它。
可用性只认 `codecheck fullcheck` 能否跑,裸 codecheck 报"不可用"不算数、别据此派 agent。
REMAINING 时展示一次遗留摘要后直接 done，作为建议项进入交付报告；不逐条询问、不要求
插件内豁免、不重启长任务。done 不再第三次现场复核。解析失败时保存完整输出到
`.mae-flow-work/codecheck-diagnostics/` 并绑定当前源码，直接留痕继续。
