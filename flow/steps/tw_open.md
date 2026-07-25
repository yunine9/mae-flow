按下方内嵌规则生成轻量提案。确认英文短名后执行
`python "{MAEFLOW_PATH}" spec new "<英文短名>"`，只生成动机、范围、简短实现说明和
不超过 3 个任务；随后执行：

1. `python "{MAEFLOW_PATH}" spec init`

展示改动范围，用 AskUserQuestion 提供“确认范围并继续 / 需要调整”按钮；
用户点选确认后 done --set CHANGE_NAME=<change目录名>，不再要求输入确认句。
若触发升级条件(5+ 文件/多模块协调/需新 capability/需 delta spec)，停手展示原因并等用户确认；
确认升级后用内嵌 state 命令正规更新 workflow，再 goto design --force。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:tweak-open}}
