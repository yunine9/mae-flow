直接实现改动 → git commit -m "[单号][类型]描述" → 涉及代码改动则**派 compile-agent 编译**
(编译总策略同 build:主会话永不直接编译、不猜编译命令、不让用户自行编译;纯文案/配置改动无需编译)。done 校验 commit 格式。
实现中发现超出 tweak 范围(触发升级条件)→ 停手展示原因,等用户确认后 goto design --force 转 full 流程。
