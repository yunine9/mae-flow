存在 .mae-flow-work/survey-{单号}.md(grill 备课的代码勘察笔记)→ 先读它拿代码地图,只做增量探索,**禁止全量重读代码**;
不存在(跳过了 grill)→ 本步首次读码时顺手记一份到该路径,后续阶段共享。
执行 /comet-open(comet 技能,内部会经 comet-state 登记 .comet.yaml 状态),输入 = SE 设计文档(含内联需求)+ clarifications(如有)。
**禁止绕过技能手工创建产物**(手动 mkdir openspec 目录已被 gate 硬拦);若已手工补齐产物,状态登记必须走 comet 脚本
(comet-state init <change-name> <workflow>),.comet.yaml/.openspec.yaml 手写会被 gate 拦截——这不是故障,是纠偏。
**/comet-open 调不起来 / 报技能不存在 → 别 mkdir 手搓顶替**:十有八九是 .claude→.cac 迁移后没重启会话、skill 未加载。
先重启会话(有 .mae-flow-need-reload 标记时环境步就会拦你),回来说"继续";仍不行则环境未就绪,回退查 env。
有 clarifications 时明确告知 comet-open:需求澄清已在 Grill 完成(附文档路径),其 Step 1 勿重复质询,直接进入产物生成。
若需把 clarifications 移入 change 目录:**用 git mv**(change 目录内非白名单文件,comet hook 拦 Write 但放行 git mv;
且 git mv 保留历史)——绝不用 Write 重建或 cp,那会撞 COMET PHASE GUARD。
确认产物:proposal.md、design.md、tasks.md、specs/<domain>/spec.md(delta spec)。
delta spec 的 Scenario 用 EARS 句式表述(WHEN <条件> THE SYSTEM SHALL <可观测行为>,每条独立可测;
clarifications 里已是 EARS 的答案直接沿用)——UT 阶段将按这些条目逐条对照覆盖,含糊句式=测不了=白写。
逐条比对 delta spec 与 SE 文档,不一致则修正;记录 CHANGE_NAME;确认 .comet.yaml phase=open。
**规格呈审协议(spec 是后面写码/补测/验收的唯一合同,代码质量的上限在这一步就定了)**:
展示用「决策摘要卡」而非甩全文——共 N 条 Scenario/EARS,按来源分三类:
①有需求文档/澄清答案依据的(报条数,引导用户抽查边界值与错误语义);
②**AI 自行推断、没有需求依据的**(逐条列出+推断理由);③AI 拿不准的。
**②③类必须用 AskUserQuestion 逐条呈用户拍板**——done 硬校验本步内真实问过(ASKUSER 令牌),
无脑回车在这一步机器上过不去;用户改判的当场改 spec。
若用户已真实逐条回答,但宿主没有签发 ASKUSER 令牌,按 done 报错展示风险并让用户选择是否
`accept-risk askuser`;该兜底只替代交互令牌,②③类的规格修订、提交和其他证据仍必须完成。
确认后 git add openspec/(clarifications 尚在 docs/ 未随迁的,精确补 git add docs/clarifications-{单号}.md;
**禁止 git add docs/ 或 -A**)&& git commit -m "[单号][类型]提案与规格",
再 done --ack --set CHANGE_NAME=<change目录名>(校验本 change 的 proposal/delta spec/.comet.yaml 存在)。
