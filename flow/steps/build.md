主 Agent 直接读取本单 `spec.md` 与 `story.md`，一次完成需求涉及的全部生产代码。不要派实现子 Agent，
不要拆开发批次，不要创建额外的编码前计划或实现任务文档。

实现完成后执行 `python "{MAEFLOW_PATH}" agent-task compile --scope "本需求完整代码增量"`，按任务卡启动
compile-agent。编译成功后执行 `done`。此时保持代码未提交，供用户统一检视。
如果任务卡已经启动但没有收到返回，先检查已记录的 Agent 生命周期；禁止自动重派或重复编译。
