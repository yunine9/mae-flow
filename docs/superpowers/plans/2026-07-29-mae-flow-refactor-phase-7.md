# Mae-Flow Refactor Phase 7 Plan

1. 先写 delivery policy 单测并实现 Checkpoint/Moonlight 纯规则。
2. 让 monolith 的 Checkpoint 查询桥接到单一策略。
3. 逐个抽取 Moonlight 动作适配器，保持原顺序与文案。
4. 增加复杂度、自测和旧基线差分。
5. 运行全量验证并冻结 phase 7。
