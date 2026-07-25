按下方内嵌规则创建精简变更：先确认英文短名和范围，再执行
`python "{MAEFLOW_PATH}" spec new "<英文短名>"`——它创建 **v5 四合一 change.md 骨架**(hotfix 档,
本单唯一入库产物)。把问题、根因、修复目标与修复思路写进「# 为什么」节,修复任务写进「# 实现清单」节,
「（待填…」占位全部替换;行为规格确有变化时才补「# 规格条目：<域名>」节(格式合同用
`python "{MAEFLOW_PATH}" spec instructions change` 取,禁止手工猜格式)。
下方原文里的 proposal/tasks/delta spec 产物话术一律以本页 change.md 小节为准。
在途旧布局单(已有 proposal.md/tasks.md 的)继续按旧产物补齐走完,不要新建 change.md。
交付登记已由 spec new 自动完成(在途旧单缺登记时补一条 `python "{MAEFLOW_PATH}" spec init`)。
展示提案摘要(问题定位+修复思路)，用 AskUserQuestion 提供“确认范围并继续 / 需要调整”按钮。
用户点选确认后提交产物，再 done --set CHANGE_NAME=<change目录名>；不再要求输入确认句
(done 硬校验:写了规格条目则格式必须过、占位不得残留)。
若触发升级条件(3+ 文件/架构变更/DB schema/新 public API)，停手展示原因并等用户确认；
确认升级后用内嵌 state 命令正规更新 workflow，再进入 design，禁止手写状态。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:hotfix-open}}
