向用户展示当前完整未提交 diff、修改文件和编译结果，让用户直接在 IDE 中检视。

用 AskUserQuestion 只询问一次：

- `我已认真检视并完成自验证，继续`
- `需要调整代码`

用户点选后同轮执行 `done --choice continue|revise`。Agent 预检只是可选辅助，不代替本次人工检视。
该规则同样适用于后续质量阶段产生的源码、测试或构建改动；质量阶段通过统一检视节点执行，不在各 Agent 内提交。

本步的取舍依据（检视关注点与返工边界），见 `.mae-flow-work/plugin-resources/guidance/review.md`。
