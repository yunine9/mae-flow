存在 .mae-flow-work/survey-{单号}.md(grill 备课的代码勘察笔记)→ 先读它拿代码地图,只做增量探索,**禁止全量重读代码**;
不存在(跳过了 grill)→ 本步首次读码时顺手记一份到该路径,后续阶段共享。
本步骤使用插件内嵌的需求探索与规格生成规则，不调用外部 Skill，也不要求 reload。
输入 = SE 设计文档(含内联需求)+ clarifications(如有)。有 clarifications 时，需求澄清已经完成，
不得重复质询已经拍板的内容。
先按下方内嵌规则完成探索和名称确认，再执行：

`python "{MAEFLOW_PATH}" capability openspec -- new change "<用户确认的英文短名>"`

随后通过内嵌 CLI 的 `status` / `instructions` 获取真实模板和规则，逐项生成 proposal、specs、design、tasks。
禁止手工猜模板；下方原文里的 `openspec` 命令已经自动改写为内嵌 CLI。
**specs 的格式指令必须显式取一次**(下方原文循环只列了 proposal/design/tasks 三条,而 specs 是格式合同
最重的一份——标题结构、`#### Scenario:` 恰好四个井号、MODIFIED 须整段复制,漏取=凭感觉手写规格,
病灶潜伏到规格定稿才爆):
`python "{MAEFLOW_PATH}" capability openspec -- instructions specs --change "<英文短名>" --json`
每条 `### Requirement:` 正文须含 SHALL/MUST 关键词(上游校验认英文关键词;中文正文中英混写即可,
如「系统 SHALL 在…时返回…」)。
四类产物齐后、done 之前先结构自检——错误当步就修,不许潜伏到定稿:
`python "{MAEFLOW_PATH}" capability openspec -- validate "<英文短名>"`
产物骨架存在后执行：

`python "{MAEFLOW_PATH}" capability comet-state -- init "<英文短名>" full`

状态登记必须走该内嵌命令，`.comet.yaml/.openspec.yaml` 禁止手写——这不是故障，是为了让恢复和校验可信。
若需把 clarifications 移入 change 目录:**用 git mv**(change 目录内非白名单文件,comet hook 拦 Write 但放行 git mv;
且 git mv 保留历史)——绝不用 Write 重建或 cp,那会撞 COMET PHASE GUARD。
确认产物:proposal.md、design.md、tasks.md、specs/<domain>/spec.md(delta spec)。
delta spec 的 Scenario 用 EARS 句式表述(WHEN <条件> THE SYSTEM SHALL <可观测行为>,每条独立可测;
clarifications 里已是 EARS 的答案直接沿用)——UT 阶段将按这些条目逐条对照覆盖,含糊句式=测不了=白写。
逐条比对 delta spec 与 SE 文档,不一致则修正;记录 CHANGE_NAME;确认 .comet.yaml phase=open。
**规格呈审协议(spec 是后面写码/补测/验收的唯一合同,代码质量的上限在这一步就定了)**:
展示用「决策摘要卡」而非甩全文——共 N 条 Scenario/EARS,按来源分三类:
①有需求文档/澄清答案依据的(报条数,引导用户抽查边界值与错误语义;**这些在质询/文档里已经
拍板过,禁止逐条重新提问**——重问一遍是用户最烦的重复劳动);
②**AI 自行推断、没有需求依据的**(逐条列出+推断理由);③AI 拿不准的。
**②③类必须用 AskUserQuestion 逐条呈用户拍板**——done 硬校验本步内真实问过(ASKUSER 令牌),
无脑回车在这一步机器上过不去;用户改判的当场改 spec。
若用户已真实逐条回答,但宿主没有签发 ASKUSER 令牌,按 done 报错展示风险并让用户选择是否
`accept-risk askuser`;该兜底只替代交互令牌,②③类的规格修订、提交和其他证据仍必须完成。
确认后先执行：

`python "{MAEFLOW_PATH}" capability comet-guard -- "<英文短名>" open --apply`

确认状态已进入 design，再 git add openspec/(clarifications 尚在 docs/ 未随迁的,精确补 git add docs/clarifications-{单号}.md;
**禁止 git add docs/ 或 -A**)&& git commit -m "[单号][类型]提案与规格",
再 done --set CHANGE_NAME=<change目录名>(校验本 change 的 proposal/delta spec/.comet.yaml 存在)。
需求缺口已经在本步骤逐项让用户裁决，产物齐全后无需再索要一次“确认本阶段完成”。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:open}}
