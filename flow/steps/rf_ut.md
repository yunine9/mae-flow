评审意见处理阶段的独立增量 UT 步骤。harness 已冻结本轮基点，任务卡只列本轮文件。

先直接尝试 done：本轮没有业务代码改动时机器自动放行；有业务代码改动则必须拿到 UT PASS。
需要 UT 时：
1. 执行 `python "{MAEFLOW_PATH}" agent-task ut`；
2. 把命令输出的**唯一一句启动话术原样**交给 ut-generator-agent，禁止自行拼任务；
3. Agent 必须读取任务卡并按其中 `UT生成方式` 调用 Mae-Flow 插件自带的
   AutoUT/java-autout Skill 或既有写法，参考 `UT运行命令` 真实执行测试；
   该项写“随生成方式自带”时由对应 Skill 按项目决定；
4. 只有 `UT_RESULT: PASS`、TASK_CARD_SHA256 和 GENERATOR_USED 合法，且 EXECUTED_UT 能对应到
   本轮真实成功的测试调用，done 才放行。NEEDS_INPUT/FAIL 不能当通过。

PENDING_QUESTIONS / SUSPECTED_BUGS 仍按主流程协议呈用户裁决；未经用户确认，UT agent 和主会话都不得修改被测源码。源码经 unlock 修复后执行 done，harness 会自动回流 rf_compile，强制重跑编译 → CodeCheck → UT；不接受仅重跑 UT 就推送。未经 unlock 却检测到被测源码变化会直接判越权。

本仓未配「测试路径」时也不再放开任意源码写入：harness 使用 tests/、test/、src/test/、*_test.*、*Test.java 等保守默认规则。本仓是非标准测试目录时，先在 `.mae-flow-defaults.json` 补「测试路径」，不要用 unlock 长期绕过。
