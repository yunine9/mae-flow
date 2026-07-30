设计结论已经稳定。现在先确定“代码最终必须能证明哪些行为”，不要进入测试文件、Fixture 或 Mock API。

执行：

1. `python "{MAEFLOW_PATH}" role-task test-design` 生成最小上下文任务卡；
2. 用新鲜 Test Design Agent 读取任务卡，生成
   `.mae-flow-work/test-blueprint-{单号}.md`；
3. 执行
   `python "{MAEFLOW_PATH}" quality-artifact register blueprint ".mae-flow-work/test-blueprint-{单号}.md"`；
4. 对照全部规格 Scenario 检查覆盖和内部一致性；
5. 首轮向用户展示完整蓝图，并提供：
   - `UT 行为蓝图已确认，继续`
   - `需要调整 UT 行为蓝图`

用户可以直接提出修改，不必先点“需要调整”。收到反馈后先复述本轮理解，再把用户原话和旧蓝图路径
交给新鲜 Test Design 修订实例；重新校验、登记，只展示差异和受影响场景。修改轮次不设上限。

蓝图只写场景来源、前置状态、动作、可观察结果、禁止副作用、分类、测试层级和依赖策略；
禁止出现具体类名、函数名、测试文件、Fixture、Mock API 或 private 调用。

用户明确继续后执行：

`python "{MAEFLOW_PATH}" done --choice continue`

用户要求修改时执行：

`python "{MAEFLOW_PATH}" done --choice revise`

月光宝盒同样真实生成并校验蓝图，但按已授权的保守结论自动继续并留痕。
