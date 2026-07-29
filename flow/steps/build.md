仓库存在 docs/delivery-notes.md 时先通读(往单沉淀的仓库事实:构建陷阱/告警高发点/mock 策略),写码时主动规避。
代码事实先查 .mae-flow-work/survey-{单号}.md(勘察笔记),只做增量探索,禁止全量重读代码。
**中断/上下文重置(/clear)后恢复,先按序重读再动手**:①superpowers 计划文档 ②change.md 实现清单(勾选与备注=进度真相)
③change.md 方案节与规格条目(在途旧布局单为 tasks.md/design.md/delta spec) ④git log {基线分支}..HEAD 与最近 diff。禁止只凭本条指令闷头续写。
按下方内嵌的实现计划与连续执行规则生成计划并实施，不调用外部 Skill；禁止手工编辑流程状态文件。
计划由主会话**亲自**按内嵌 writing-plans 方法生成——禁止把"制定计划"派给子代理:子代理上下文里
没有本页能力包文本,产出会丢失 bite-sized/No Placeholders 纪律(下方原文如出现"派发计划子代理"
字样,以本条为准)。计划的任务步骤**不包含写测试步骤**:测试统一由 verify 阶段 AutoUT 按 EARS
条目补齐(tdd_mode=direct 已获授权),计划里织入"先写失败测试"步骤=与验证台账失配。
原方法中的执行方式选择按公司标准固定，禁止现场即兴:
- 隔离方式=branch(分支已在 branch_create 建好,直接沿用,不新建、不用 worktree);
- 执行方式=executing-plans(如用户明确要求 subagent-driven,派发契约中必须注明 commit 格式为 [单号][类型]描述,否则子 agent 的提交会被拦截);
- tdd_mode=direct 且 direct_override=true(公司用 AutoUT 在 verify 阶段事后补测,不走 TDD);
- 正确性审查(查**正确性/漏洞/边界**,与 CodeCheck 的规范、Ponytail 的复杂度
  维度不同、互不替代,这一维只有它管;高风险变更经用户同意可升 thorough)。
开工自查(计划评审通过后、写第一行码前,自己过一遍不问用户):实现清单逐项能指到方案节/规格条目的出处吗?
三者有矛盾或遗漏 → 走上面的回流通道,**不带病开工**——现在对齐五分钟,verify 阶段返工半天。
批次边界严格沿用编码前已经确认的 CP1/CP2…方案，不按行数、文件数或每个 commit 临时切分。
每批提交后执行 `agent-task compile --checkpoint CPn --scope "<本批模块/任务>"`，compile-agent OK 后执行
`checkpoint ready CPn`：分阶段模式会要求普通 push，并在 `checkpoint status` 验真远端后等待用户检视；
一次完成模式只记录批次范围，直接进入下一批，不 push、不等待。
每批 commit 后是**安全的 /clear 点**:会话已明显冗长时主动向用户提议"/clear 后说继续";
批次交接必须**盘上自足**——本批的结论/偏离/踩坑写进实现清单对应任务的缩进备注行,
让 /clear 后(或换会话)的你只靠磁盘就能无损接续。
superpowers 技能若坚持"先写测试":回应 tdd_mode=direct 已获 direct_override 授权,UT 由 verify 阶段 AutoUT 统一补,继续执行。
按计划迭代,每完成一个任务:实现 → 规格条目同步检查(有偏差立即修) → 勾选实现清单 →
git commit -m "[单号][类型]描述"(拒绝方法原文建议的 fix:/tweak:/设计意图式 message;
**先 commit 后编译**是定死的顺序:任务代码可以带着编译错误入库,compile-agent 的修复另行 commit)。
提交候选先收窄到你通过 Edit/Write 实际改过的文件，再逐个看 diff 决定是否提交；
“改过”不等于“必须提交”，编译/格式化/生成命令顺带产生的文件默认不纳入。
**积累到模块/批次边界(一个 CMakeLists 模块完成,或一批相关任务)→ 先执行
`python "{MAEFLOW_PATH}" agent-task compile --checkpoint CPn --scope "<本批模块/任务>"`，把输出的唯一启动话术原样交给 compile-agent**
(任务卡由 harness 带齐单号、编译方式和本批范围):OK → 继续下一批;BLOCKED(含 SUSPECTED_ISSUES
疑似要改接口/逻辑)→ 停下呈用户裁决,走既有回流通道,禁止自己乱改绕过。
mcde 单模块 5-10 分钟,别每个小任务都派;也别攒到最后一把梭(错误堆成山难定位)。
**build 收尾铁序**:最后一次改码之后必须再派一次 compile-agent 收尾——新鲜度绑定会强制这一点
(编译令牌绑签发时代码状态,编译后再改码令牌即作废,done 过不去)。
**编译总策略**:只要本轮存在源码、测试或构建入口变化，编译只有一条路——**派 compile-agent(编译隔离舱)**；
纯文档/台账任务在实现清单和提交证据完成后直接尝试 done，由机器按真实文件范围自动放行，不生成空任务卡。
需要编译时，compile-agent 按配置的编译方式执行(插件自带 build-fix Skill 或明确命令)。
**你(主会话)永不直接执行编译命令、永不自行猜测编译方式、
更不许让用户"自行编译"**;done 默认硬校验本步内 compile-agent 真实收尾过(COMPILE 令牌)。
如果 agent 已长时间执行但令牌因宿主/收尾兼容问题始终签不出,不要自动无限重跑;把「无可验证编译结果,代码可能无法构建」的风险
告知用户,由用户选择重跑或按 done 报错执行 `accept-risk compile`;这次放行会明确留痕,后续代码变化即失效。
配置为空/调不起来 → 那是配置问题,回 config_confirm 与用户确认,不是现场即兴。
编译/测试失败的修复纪律(systematic-debugging,superpowers 有此 skill 则启用,没有也按此执行):
**先复现、读全报错、定位根因,再动手**;同一错误第一轮修复无效 → 停止盲试,写出根因假设与验证方法再改——
"改一下试试"的乱枪打鸟只会把一个错改成三个错。根因假设与验证结果**写进实现清单对应任务的备注行**,
不能只留在会话里——/clear 后调试中态全靠它。
(编译错误的修复全在 compile-agent 舱内完成,其契约自带 systematic-debugging 纪律与防掏空不变量;
主会话的调试纪律只适用于**非编译类**失败——脚本、工具、流程问题。)
**Ponytail(full 档)写码时全程生效**——每段代码先走 the ladder:已有实现可复用?>标准库?>平台原生?>
已装依赖?>一行能写完?>最少代码。写得少,后面 Ponytail-review 删得少、CodeCheck 告警少、UT 补得少,整条 verify 链都轻。
两条边界:**YAGNI 不得砍规格条目要求的行为**(spec 是合同,只作用于怎么写,不作用于写什么);
**禁用 ultra 档**(ultra 会质疑需求本身——那是 grill 阶段的事,不是写码时的事)。
约束:小步提交禁积攒;只改本 change 相关代码;规格修订仅改本单 change.md 的规格条目(在途旧布局单为 changes/ 下 delta spec),真相源只读;
未提交改动必须先归因(本单产出/用户原有/来源不明),来源不明禁止覆盖或回滚;
发现需要升级工作流(hotfix→full,如实现揭出跨模块设计变更)时,停手展示原因,等用户确认后 goto design --force；状态机会同步 workflow 与规格阶段。
实现中发现**设计或规格条目本身有误**(实现揭出的矛盾/遗漏/做不到)——这是实现阶段的正常发现,不是事故:
停手,呈报用户(问题+影响+建议修法),经确认后 goto design(设计误)或 goto open(spec 误)--ack "用户原话"
回流修订,修订后顺流回来;**禁止不吭声地偏离设计"先做出来再说"**——偏离没有记录,评审和 verify 都会被骗过。
计划文档写到 **.mae-flow-work/plan-{单号}.md**(过程件不入库,git 本地排除已覆盖;禁止写进 docs/ 或 openspec/),生成后执行：
`python "{MAEFLOW_PATH}" spec set plan ".mae-flow-work/plan-{单号}.md"`

全部完成、任务全勾选且最后一轮 compile-agent 已 OK 后:
展示任务状态与产物摘要后执行 done(状态机以任务清单、提交和编译令牌为证据,不重跑长编译)。
新启动的普通流程按编码前选择执行检查点：分阶段模式的每批已经完成远端检视，一次完成模式留到质量链后统一检视；
旧版在途流程仍进入原有 build_review，不会被升级强行改轨。所有普通流程在规格定稿前还会核对质量阶段是否产生
未检视代码增量。月光宝盒完全旁路人工检视。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:build}}
