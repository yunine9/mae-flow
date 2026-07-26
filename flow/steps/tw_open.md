按下方内嵌规则生成轻量提案。确认英文短名后执行
`python "{MAEFLOW_PATH}" spec new "<英文短名>"`——它创建 **v5 四合一 change.md 骨架**(tweak 档,
本单唯一入库产物)。「# 为什么」节写动机、范围和简短实现说明,「# 实现清单」节不超过 3 个任务,
「（待填…」占位全部替换;无规格变化不写规格条目节(tweak 触碰规格即达升级条件)。
下方原文里的 proposal/tasks 产物话术一律以本页 change.md 小节为准。
在途旧布局单(已有 proposal.md/tasks.md 的)继续按旧产物补齐走完,不要新建 change.md。
交付登记已由 spec new 自动完成(在途旧单缺登记时补一条 `python "{MAEFLOW_PATH}" spec init`)。
展示改动范围，用 AskUserQuestion 提供“确认范围并继续 / 需要调整”按钮；
用户点选确认后 done --set CHANGE_NAME=<change目录名>，不再要求输入确认句(done 硬校验占位不得残留)。
若触发升级条件(5+ 文件/多模块协调/需新 capability/需规格条目)，停手展示原因并等用户确认(文件数这一条由 done 的 tier_scope 证据机器亲数,超限硬拦并给升级/accept-risk 两条出路)；
确认升级后用内嵌 state 命令正规更新 workflow，再 goto design --force。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:tweak-open}}
