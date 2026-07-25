按下方内嵌规则生成轻量提案。确认英文短名后执行
`python "{MAEFLOW_PATH}" capability openspec -- new change "<英文短名>"`，只生成动机、范围、简短实现说明和
不超过 3 个任务；随后执行：

1. `python "{MAEFLOW_PATH}" capability comet-state -- init "<英文短名>" tweak`
2. `python "{MAEFLOW_PATH}" capability comet-guard -- "<英文短名>" open --apply`

展示改动范围，等用户确认后 done --ack --set CHANGE_NAME=<change目录名>。
若触发升级条件(5+ 文件/多模块协调/需新 capability/需 delta spec)，停手展示原因并等用户确认；
确认升级后用内嵌 state 命令正规更新 workflow，再 goto design --force。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:tweak-open}}
