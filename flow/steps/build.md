仓库存在 docs/delivery-notes.md 时先通读(往单沉淀的仓库事实:构建陷阱/告警高发点/mock 策略),写码时主动规避。
**中断/上下文重置(/clear)后恢复,先按序重读再动手**:①superpowers 计划文档 ②tasks.md(勾选与备注=进度真相)
③design.md 与 delta spec ④git log {基线分支}..HEAD 与最近 diff。禁止只凭本条指令闷头续写。
执行 /comet-build 生成实现计划。comet-build「选择工作方式」阻塞点按公司标准回答,禁止现场即兴:
- 隔离方式=branch(分支已在 branch_create 建好,直接沿用,不新建、不用 worktree);
- 执行方式=executing-plans(如用户明确要求 subagent-driven,派发契约中必须注明 commit 格式为 [单号][类型]描述,否则子 agent 的提交会被拦截);
- tdd_mode=direct 且 direct_override=true(公司用 AutoUT 在 verify 阶段事后补测,不走 TDD);
- review_mode=standard(comet 审查查的是**正确性/漏洞/边界**,与 CodeCheck 的规范、Ponytail 的复杂度
  维度不同、互不替代,这一维只有它管;高风险变更经用户同意可升 thorough)。
开工自查(计划评审通过后、写第一行码前,自己过一遍不问用户):tasks.md 逐项能指到 design/delta spec 的出处吗?
三者有矛盾或遗漏 → 走上面的回流通道,**不带病开工**——现在对齐五分钟,verify 阶段返工半天。
executing-plans 的**批次检查点不等用户**:每批完成展示简报后直接继续
(build 结束有 mae-flow 统一确认点,后面还有四道 verify,中途碎片化等待没有价值);
仅遇 CRITICAL 问题/编译测试失败/发现需偏离计划时才停下等用户。
每批 commit 后是**安全的 /clear 点**:会话已明显冗长时主动向用户提议"/clear 后说继续";
批次交接必须**盘上自足**——本批的结论/偏离/踩坑写进 tasks.md 对应任务的缩进备注行,
让 /clear 后(或换会话)的你只靠磁盘就能无损接续。
superpowers 技能若坚持"先写测试":回应 tdd_mode=direct 已获 direct_override 授权,UT 由 verify 阶段 AutoUT 统一补,继续执行。
按计划迭代,每完成一个任务:实现 → 按配置编译方式编译修复 → delta spec 同步检查(有偏差立即修) → 勾选 tasks.md → git commit -m "[单号][类型]描述"(拒绝 comet 建议的 fix:/tweak:/设计意图式 message)。
**编译是你的职责,不是用户的**:必须按 config_confirm 配置的编译方式亲自编译并修复,**禁止让用户"自行编译"**。
若不知道怎么编译(配置为空/是个你调不起来的 skill),那是配置问题——回 config_confirm 与用户确认可用的编译方式,不是把编译甩给用户。
编译/测试失败的修复纪律(systematic-debugging,superpowers 有此 skill 则启用,没有也按此执行):
**先复现、读全报错、定位根因,再动手**;同一错误第一轮修复无效 → 停止盲试,写出根因假设与验证方法再改——
"改一下试试"的乱枪打鸟只会把一个错改成三个错。根因假设与验证结果**写进 tasks.md 对应任务的备注行**,
不能只留在会话里——/clear 后调试中态全靠它。
**编译反复卡住(自己修 3 轮仍不过,或大批链接/依赖类报错)→ 派 build-fix-agent 专项修复**
(契约见 agents/build-fix-agent.md,传入:单号类型、编译方式、当前编译报错):它只修编译、不碰功能逻辑与测试,
修到编译通过(OK)你再继续;它 BLOCKED(含疑似源码设计缺陷 SUSPECTED_ISSUES)→ 停下带诊断报告用户,
禁止你自己乱改逻辑绕过编译错误。大多数顺手的编译错自己修即可,派 agent 是卡住时的 offload,不是每次编译都派。
**Ponytail(full 档)写码时全程生效**——每段代码先走 the ladder:已有实现可复用?>标准库?>平台原生?>
已装依赖?>一行能写完?>最少代码。写得少,后面 Ponytail-review 删得少、CodeCheck 告警少、UT 补得少,整条 verify 链都轻。
两条边界:**YAGNI 不得砍 delta spec 要求的行为**(spec 是合同,只作用于怎么写,不作用于写什么);
**禁用 ultra 档**(ultra 会质疑需求本身——那是 grill 阶段的事,不是写码时的事)。
约束:小步提交禁积攒;只改本 change 相关代码;仅改 changes/ 下 delta spec,真相源只读;
未提交改动按 comet 的 dirty-worktree 协议归因,来源不明禁止覆盖/回滚;
comet 提示工作流升级条件(hotfix→full)时,停手展示原因,等用户确认后 goto design --force。
实现中发现**设计或 delta spec 本身有误**(实现揭出的矛盾/遗漏/做不到)——这是实现阶段的正常发现,不是事故:
停手,呈报用户(问题+影响+建议修法),经确认后 goto design(设计误)或 goto open(spec 误)--ack "用户原话"
回流修订,修订后顺流回来;**禁止不吭声地偏离设计"先做出来再说"**——偏离没有记录,评审和 verify 都会被骗过。
全部完成且 comet-guard 通过后,展示任务状态与产物摘要,结束回复等用户确认。
done --ack "用户原话"(同时自动校验 tasks 全勾选 + 最新 commit 带单号)。
