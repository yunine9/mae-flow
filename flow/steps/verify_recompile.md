UT 经用户裁决后修改了被测源码，harness 已自动把流程送回质量链，禁止回到实现规划或直接跳过验证。
若旧状态异常进入本步但实际没有源码、测试或构建入口变化，先执行 done，机器会自动放行。

1. 执行 `python "{MAEFLOW_PATH}" agent-task compile --scope "UT裁决后的源码修复"`；
2. 把输出的唯一启动话术原样交给 compile-agent；主会话不编译、不猜命令；
3. 只有 `COMPILE_RESULT: OK` 才能 done。BLOCKED/FAIL 按报告处理后重启新实例；
4. done 后继续 Ponytail → CodeCheck → UT，确保源码修复没有绕过任何下游质量门。

这是回流专用编译节点，不重做已经完成的实现计划。
