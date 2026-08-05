主 Agent 根据用户本轮检视意见直接修改代码，不派实现子 Agent，不重新执行可选 CODE Agent 预检。
修改完成后重新生成 COMPILE 任务卡并运行 compile-agent；编译通过后执行 `done`，回到用户检视。
