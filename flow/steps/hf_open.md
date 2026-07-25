按下方内嵌规则创建精简变更：先确认英文短名和范围，再执行
`python "{MAEFLOW_PATH}" spec new "<英文短名>"`，生成问题、根因、修复目标、
修复方案和任务清单；行为规格确有变化时才补 delta spec。
随后执行：

1. `python "{MAEFLOW_PATH}" spec init`

展示提案摘要(问题定位+修复思路)，用 AskUserQuestion 提供“确认范围并继续 / 需要调整”按钮。
用户点选确认后提交产物，再 done --set CHANGE_NAME=<change目录名>；不再要求输入确认句。
若触发升级条件(3+ 文件/架构变更/DB schema/新 public API)，停手展示原因并等用户确认；
确认升级后用内嵌 state 命令正规更新 workflow，再进入 design，禁止手写状态。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:hotfix-open}}
