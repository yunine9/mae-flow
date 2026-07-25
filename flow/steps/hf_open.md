按下方内嵌规则创建精简变更：先确认英文短名和范围，再执行
`python "{MAEFLOW_PATH}" capability openspec -- new change "<英文短名>"`，生成问题、根因、修复目标、
修复方案和任务清单；行为规格确有变化时才补 delta spec。
随后执行：

1. `python "{MAEFLOW_PATH}" capability comet-state -- init "<英文短名>" hotfix`
2. `python "{MAEFLOW_PATH}" capability comet-guard -- "<英文短名>" open --apply`

展示提案摘要(问题定位+修复思路)并等用户确认；确认后提交产物，
再 done --ack --set CHANGE_NAME=<change目录名>。
若触发升级条件(3+ 文件/架构变更/DB schema/新 public API)，停手展示原因并等用户确认；
确认升级后用内嵌 state 命令正规更新 workflow，再进入 design，禁止手写状态。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:hotfix-open}}
