# Mae-Flow Refactor Phase 6 Plan

1. 先写 `test_quality_task_cards.py`，锁定正文、摘要、允许步骤与记录纯函数。
2. 实现 `quality/task_cards.py` 并通过纯单测。
3. 将 `cmd_agent_task` 拆成 observe/render/store 命名阶段，逐段搬移原逻辑。
4. 运行 task scope、Checkpoint、CodeCheck logging 与全量单测。
5. 添加架构复杂度、自测入口和固定旧实现任务卡 golden。
6. 运行 phase 6 全量验证并冻结独立分支。
