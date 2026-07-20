直接实现改动 → 按配置的编译方式**亲自编译修复**(禁止让用户自行编译;编译反复卡住可派 build-fix-agent 专项)→ git commit -m "[单号][类型]描述"。done 校验 commit 格式。
实现中发现超出 tweak 范围(触发升级条件)→ 停手展示原因,等用户确认后 goto design --force 转 full 流程。
