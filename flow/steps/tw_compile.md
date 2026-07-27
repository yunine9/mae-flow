小改的编译步骤。纯文档改动直接尝试 done，机器确认没有源码或构建文件变化后会自动放行。

只要改过源码、测试代码或构建文件：
1. 执行 `python "{MAEFLOW_PATH}" agent-task compile --scope "本次小改"`；
2. 把输出的唯一启动话术原样交给 compile-agent；
3. compile-agent 只按已确认的编译方式执行，主会话不编译、不猜命令；
4. 只有 `COMPILE_RESULT: OK` 才能 done。BLOCKED/FAIL 要展示实际原因，处理后重新派新实例。

这一步按真实文件变化判断，不再只认 C++/Java 扩展名；CMakeLists、构建脚本以及其他语言源码也算。
任务卡生成前若还有未提交源码，先精确提交；harness 不会把工作区里看不见的改动交给子 Agent 猜。
done 后普通模式先进入用户代码检视节点，不会直接走 CodeCheck；月光宝盒直接旁路人工检视。
