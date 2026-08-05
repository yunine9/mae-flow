主 Agent 根据用户意见直接调整当前质量改动，不派实现子 Agent，不提交。

完成编辑后执行 `done`。Harness 根据检视上下文决定唯一恢复动作：源码/构建改动进入 compile-agent，
仅测试改动回到 UT。禁止自行跳转、重跑 Ponytail或绕过验证。
