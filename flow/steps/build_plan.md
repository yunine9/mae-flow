编码前先形成全局可见、局部精确的实现计划；本步骤禁止修改业务源码。

生成：

- `.mae-flow-work/roadmap-{单号}.md`：全部 CP 的业务目标、完成合同、非目标、Scenario 归属、
  模块职责、状态所有权、前后接口、延后事项精确落点和风险；
- `.mae-flow-work/plan-{单号}.md`：CP1 全量细粒度 Task；后续 CP 先保留合同、接口和 Task 摘要。

执行顺序：

1. 主 Agent 先生成全局 roadmap，执行
   `python "{MAEFLOW_PATH}" quality-artifact register roadmap ".mae-flow-work/roadmap-{单号}.md"`；
2. 执行 `python "{MAEFLOW_PATH}" role-task task-analysis --checkpoint CP1`，用新鲜 CP Task Analyst
   把 CP1 写入任务卡指定 plan；每个 Task 必须回答“去哪写什么代码”，包含文件、符号与签名、
   行为和错误语义、控制流、状态所有权、复用、禁止事项、注释计划、蓝图场景和定向检查。
   Task 只能落到生产代码/配置文件；蓝图场景只做可追踪引用，禁止新增 UT、测试文件、
   Fixture、Fake/Mock 或测试用例 Task，这些统一由 verify_ut 技术落位；
3. 校验并执行
   `python "{MAEFLOW_PATH}" quality-artifact register plan ".mae-flow-work/plan-{单号}.md"`；
4. 登记成功后执行 `python "{MAEFLOW_PATH}" role-task craft-plan --checkpoint CP1`，用新鲜
   Craft Reviewer 的 PLAN 模式只读检查；每轮最多五条，必须有位置、依据、证据、影响和最小改法；
5. 主 Agent 核实每条意见并标记为修改、验证后修改、人工裁决或拒绝/暂缓，Reviewer 不得直接改计划；
   需要修订时交回 Task Analyst，修订后重新登记 plan、重新签发 craft-plan，旧任务卡和 Review 均失效；
6. Reviewer 闭环后执行：
   - `python "{MAEFLOW_PATH}" spec set plan ".mae-flow-work/plan-{单号}.md"`
7. 执行 `python "{MAEFLOW_PATH}" quality-artifact present plan`，冻结当前 roadmap、
   plan、CP1 PLAN Review 和回答游标；
8. 向用户展示该收据绑定的完整 CP 地图、CP1 Task 摘要、Scenario 覆盖和全部延后落点。

用户直接提出修改时，复述理解、修订、做一致性检查并重新登记；涉及 plan 时必须重新签发
PLAN Reviewer 任务卡并复查，后续展示差异和受影响部分。
任何“后续处理”都必须指向具体 `CPn / Task`，无法定位就是计划缺口。修改轮次不设上限。
每次 roadmap、plan 或 PLAN Review 变化后都必须重新执行 `quality-artifact present plan`；
旧回答不能确认新版本。

用户明确继续后执行 `python "{MAEFLOW_PATH}" done --choice continue`；要求修改时执行
`python "{MAEFLOW_PATH}" done --choice revise`。`done` 会校验 CP1 PLAN Reviewer 任务卡、
Review 信封和当前已登记 plan 摘要，缺失或漂移时拒绝推进。月光宝盒真实执行 Task 分析和
PLAN 走读后保守继续。
