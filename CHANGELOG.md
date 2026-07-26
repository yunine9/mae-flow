# 更新记录

## 2026-07-26：工作流透明化与裁剪——steps 全景、环节白名单裁剪、升级阈值机器化

- **`mae-flow steps`**:四条交付方式的完整步骤链全景(每步标题/硬证据/可裁性/
  用户确认点,有在途单时高亮当前位置)——用户选档与裁剪前先看得见全貌;
- **环节裁剪(白名单制)**:仓根 `.mae-flow-defaults.json` 新键「跳过环节」,
  可裁仅限 需求质询/STORY/代码精简 三个可选环节——质量门禁(编译/CodeCheck/
  UT/规格符合/定稿)永不开放,非法值可见地忽略。推进落点命中预设时机器代跳
  并逐步留痕(choice 步代选保守分支),团队提交进仓全员生效;
- **升级阈值机器化**:新证据 `tier_scope`——tweak>5/hotfix>3 个业务文件时
  done 硬拦(此前升级条件是纯提示词约束,模型不自查就静默滑过,审计定性的
  软层缺口)。出路两条:正规升级工作流,或用户确认确属轻量修改后
  `accept-risk tier_scope`(绑 HEAD,代码再变即失效);full/review 不限;
- 探针①28→35(阈值三路、代跳留痕、白名单外忽略、质量门禁永不代跳)。

## 2026-07-26：覆盖口径拍板——CodeCheck/UT 只针对本次修改的函数,一单不背存量债

用户拍板:检查/测试对象=**本次修改的函数**,不是整个变更文件。此前 fullcheck 对
变更文件全文件报告警,改一行老文件就要修/豁免文件里全部历史告警;UT 同理会为
整个文件补测——存量债转嫁给每一单。

- **范围数据源**:`_changed_lines`(git diff -U0 的 +侧行集合,与文件清单同一
  scope_diff 口径);"函数"用变更行 ±3 窗口近似——函数级规则(超长/圈复杂度)
  告警常报在函数签名行,窗口外扩把"改动所在函数"兜进来,纯存量行滤除;
- **CodeCheck**:告警解析层新增行号提取(JSON 宽键名 + Markdown 明细行);
  `_scope_filter_codecheck` 在 codecheck-scan 与 done 的 codecheck_clean 现场
  复核**同源同口径**过滤;存量数如实展示("另有 N 条存量告警未计入本单");
  明细缺行号/总数与明细对不上时**保守全算并明示**(宁可多报不静默漏);
  豁免粒度(规则+文件)不变;
- **UT**:任务卡自动携带"本次修改行范围"(每文件行区间摘要);划批口径从
  "变更文件"改为"变更函数";agent 契约明令禁止为文件中未修改的存量函数补测,
  存量测试缺口如实记录不在本单处理;
- 探针①25→28(真实 git 仓构造 diff:变更行解析/窗口保留/存量滤除/缺行号保守);
  selftest 的 pairs 断言同步三元组。全套回归全绿。

## 2026-07-26：流畅性优化批次——六视角实测扫描后的第一二梯队落地

六视角测量型扫描(摩擦计数/token 成本/已知局限重估/Windows CI/架构健康/v5 深化)
产出 19 项机会+3 项有据"不做";本批落地 10 项:

### 摩擦削减(每单命令数实测下降)

- **spec new 吞并 init**:init 只剩可推导字段且全仓 3 处调用全部紧跟 new——new
  成功即自动初始化(幂等守卫:不重置已推进 phase);init 保留为在途兼容幂等别名,
  顺手关闭"重复 init 把 phase 拉回 open"的旧隐坑。
  实现时踩雷并修复:save_versioned_json 保存后 clear+deepcopy 重建 st,先前取出
  的 spec 段引用成孤儿,连续两次 save 的第二次静默写空——合并为单次保存,教训
  注释留在现场;
- **verify-pass --report** 合并"登记+判定"两连(set verification_report 全仓只在
  verify-pass 前一行出现);history 双记录与逐条执行逐字等价;
- **轻量单 phase verify 快进**:hotfix/tweak 从 open 一条命令直达 verify(机器代劳
  逐格推进逐格留痕——防跳跃墙的报错本来就教模型机械连打三条,仪式改由机器执行);
  full 单不放行,verify-pass 三重校验不动;
- 合计:tweak/hotfix 的验证收尾 7 条压到 4 条,三条工作流每单再各省 1-2 条。

### 上下文成本(实测 148.3KB → 131.0KB)

- 三个整篇 FULL 注入的上游 SKILL 加选段(机制现成,方法原文一字未改只调选段范围):
  openspec-explore 裁掉与"不得重复质询"矛盾的模糊入场对话示例;systematic-debugging
  ×3 pack 保留 Iron Law/四阶段/Red Flags/速查裁掉人际结对语境;ponytail×3 裁掉已被
  步骤钉死的档位表。build 步单次注入 38.7KB→34.7KB,每批 /clear 恢复都省;
- build.md 清掉两处指向 v3 已删命令的化石文本("随后执行"后无命令的困惑点,
  git 考古确认来源)。

### 体验与暗区

- **Windows CI 落地**:.github/workflows/selftest.yml(windows-latest+ubuntu 双矩阵
  跑发版门全套,含 node 差分对拍)——唯一生产目标从零真机验证变为每次 push 自动验;
- selftest+两探针补 dispatch 同款 stdout 自愈:非 UTF-8 控制台(公司 GBK 机器典型
  形态)不再第一行编码崩,发版门开箱即跑;
- spec show 对已归档单不再误报"change 不存在",改报归档去向;
- 归档新建域 Purpose=TBD 时 warnings 明确提醒,archive 步指令要求从 change.md
  「为什么」节浓缩补写后同 commit 入库(真相源不积累占位空洞;引擎不代写,
  与 CLI 逐字节对拍语义不变)。

### 明确不做(有数据的否决)

clarifications 不并入 change.md(保 grill 断点恢复与审计粒度);STORY/REVIEW 不动
(外部契约/已最小);mae-flow.py 不拆(零 bug 基线上的投机重构,以增长红线代替);
预答选择步自动消费**暂缓**——动 done 推进主路径且预答链路依赖 harness 确认账,
本机无法真实验证,留给公司机批次与 Windows 实测同批。

回归:specengine 66、capabilities 12、探针 25+30、selftest 全绿。

## 2026-07-26：v5 完备性审计——六维 12-agent 对抗验证,31 项实锤清零

对 v5+dogfood 全部改动面做六维审计(旧引用残留/引擎双布局/dogfood 三修边界/
证据链正反路径/文档一致性/测试缺口),每维 findings 经独立对抗验证(实跑复现才
判真),31 项确认、2 项驳回,全部修复:

### 高危功能修复

- **full 单 phase 链断裂**(v3 删 comet-guard 时丢链,两批重写都没发现):open.md
  「确认后先执行:」后补回 `spec phase design`,design.md 括注改正为 design→build
  ——此前每张 full 单走到 design 步必撞跳跃墙;
- **v5 任务卡缺规格依据**:`_requirement_sources` 只按旧布局 glob specs/,v5 单的
  COMPILE/CODECHECK/UT 任务卡永远看不到规格条目——补 change.md 双布局六路 glob;
- **doctor 误报每张新单**:change 健康行仍查 v3 已废的 .comet.yaml(phase 也从它
  读)——改为按布局探测产物 + 从 .mae-flow.json spec 段读 phase;
- **legacy 坏编码裸崩五处**:delta spec/主 spec 非 UTF-8 时 has_delta/validate/
  archive 裸 UnicodeDecodeError 穿透到 CLI traceback——新增 _read_text_utf8 统一
  收口(dogfood 单只修了 tasks.md 一处,同类成片残留);tasks_source v5 分支原先把
  坏编码吞成"源缺失"引导补节而非修编码,改为传播带 UTF-8 指引的引擎错误。

### 机制缺口接线

- **V5_TIER_REQUIRED 死常量接线**:新增 check_required_sections,ev_spec_validate
  按 workflow 档位查必须节——此前"full=四节"合同零机器校验,整节删除可静默过全部
  门禁(占位检查随节头一起消失);
- **instructions 布局门**:v5 单取旧制品拒并引导 change,legacy 在途单取 change 拒
  并引导旧四件套——此前引擎会亲口指示制造它自己随后拒绝的布局混用;
- **phase 跳跃命令链两修**:止步 verify(原链会引导 `spec phase archive` 绕过
  verify-pass 三重校验并推进死胡同)+ 用脚本真实绝对路径(原字面量 mae-flow.py
  照抄必失败);并新增 phase archive 直推拒(与 archived 同理,只能由 verify-pass
  产生);
- tasks_source 混用拒(与 has_delta 同判据;原静默偏向 change.md 无视 tasks.md)。

### 文档过时清零(v3/v4 换轨欠账)

FIELD-TEST 1.1/1.2(.comet/config.yaml、版本号检查项按 v4 现实重写)、
CLEAN-ROOM §3/§4(Node 改可选、初始化产物清单)、README 宿主依赖段(Node 降级)、
MAINTAINERS 四处(spec_field 转正、prepare_project 三点、comet 集成合同表改
"思想源合同"现行落点、阶段互锁哨兵段改存活现状)、story agent 设计文档兜底改
双布局、cli help 补 change 制品、MAINTAINERS 过程区住户清单补 design/plan。

### 测试补齐

specengine 60→66(域名占位拒、布局门双向、必须节三档、legacy 坏编码全 API 优雅、
混用清单拒、零任务语义固化);探针① 24→25(必须节证据路径)、探针② 22→26(跳跃
命令链绝对路径断言、archived 链止步 verify、new 异名警告不覆盖、phase archive
直推拒);capabilities 布局门断言换轨。全套回归+selftest 全绿。

## 2026-07-26：v5 首单 dogfood——真实 hotfix 走全链 + 三处流畅性实锤修复

拿真实小缺陷(legacy tasks.md 坏编码穿透,DTS2026072501)在本仓走完 v5 hotfix 全链:
spec new(hotfix 骨架)→ change.md(为什么+规格条目 evidence 域+实现清单)→ validate
→ init → 修码+UT+单号 commit → phase 链 → verify-pass → archive。验证实锤:档案里
只有一个 change.md;evidence 域真相源由归档自动新建合并;规格条目两条 EARS Scenario
与新增测试逐条对照。

dogfood 抓到并当场修复三处(核心原则:流畅易用,报错即出路):

- **spec new 自动登记 CHANGE_NAME**(为空才写,done --set 幂等仍是权威;提示走
  stderr——stdout 是 JSON 契约面,探针会拦混写):此前 init 要 CHANGE_NAME、
  记录动作 done --set 又排在 init 之后,真实链路要撞两次墙才绕通;
- **phase 跳跃报错给依序命令链**:hotfix/tweak 单不经 design/build 步骤、阶段停在
  open,verify 步一条 `spec phase verify` 必撞"不能跳跃"墙且原文案无出路;
- **verify_comet/tw_verify 步骤指令补轻量单的逐级推进命令**(tw_verify 原文"从
  build 推进"对 tweak 单从来就不成立,v3 引入的文档断裂),顺带清掉 tw_verify
  残留的 proposal/tasks 旧话术。

本单交付:specengine legacy 分支坏编码收口(tasks_source 报带 UTF-8 指引的引擎错、
_count_tasks 保持 CLI 同款宽容)+ 回归用例。specengine 60、探针 24+22、selftest
全绿。已知手感遗留(未修,待实际痛再动):无 harness 环境 config_confirm 的确认账
无法建立(设计如此,公司环境不存在);新建域真相源 Purpose 为 TBD 需归档后人工补。

## 2026-07-25：v5 单据轻量化——四合一 change.md，每单入库 7-9 件 → 1 件

目标:完整开发单入库 7-9 个文件(proposal/design/tasks/delta spec/.openspec.yaml/
superpowers plan/…)、局部修改 4 个,降到"change.md 一个为主"。方法:改"内容从哪来"
与"定稿移什么",**delta 解析与合并核心(_parse_delta_spec/_build_updated_spec)一行未动**,
13 个差分对拍原样全绿。

### 四合一 change.md(每单唯一入库产物)

- 四个固定小节用一级标题分隔:「# 为什么」(原 proposal 浓缩)/「# 规格条目：<域>」
  (每域一节,**节体=标准 delta spec 原格式**,二级 delta 分节头自然嵌套在一级小节下,
  层级零冲突)/「# 方案」(原 design 结论)/「# 实现清单」(原 tasks 复选框);
- 按工作流分档:full 四节齐全;hotfix 免方案节(修复思路并入为什么);tweak 只要
  为什么+实现清单,无规格变化不写规格条目。`spec new` 按 workflow 自动产对应骨架,
  **不再写 .openspec.yaml**(schema 走项目 config 回退,日期由归档名承载);
- `spec instructions change`:一次取全四合一结构说明+规格条目格式合同(specs 制品的
  vendored instruction/template 原文嵌入,格式真源不出第二份);
- 骨架占位分两档:「（待填」open 当步必须消,「（待设计」design 步才消——open 步
  不会被还没到期的方案节拦住。

### 引擎双布局(在途单照原样走完)

- 布局按 change.md 存在性探测;validate/任务计数/归档合并/status 全部双路,
  legacy 路径与 CLI 的对拍语义分毫未动;**两种布局标志并存判混用、validate 报
  ERROR、archive 在任何写盘前拒绝**——无 delta 的混用单若放行,会把未合并的旧
  delta 悄悄埋进档案;
- 域名从文本提取,新增路径安全门(禁 / \ .. 与未替换占位符);小节内一级标题会
  切断小节,validate 给 INFO 指出(围栏代码块里的 # 注释不算边界);
- 定稿移动逻辑不动(整目录原子移动+半成功免疫),v5 目录里只有 change.md,
  效果即"只移一个文件";旧单四件套照旧随目录进档案;
- 新守护:**等价性测试**——同一 delta 内容(多域、四种操作齐全)在 legacy 与 v5
  两种布局下归档,主 specs 真相源逐字节一致、totals/merged 一致。

### 流程与证据

- 新证据 `spec_validate`:内置引擎 validate 通过成为 open/hf_open/tw_open/design
  的 done 硬证据(open 步原 specs glob 只查文件存在,现在查格式合法);hotfix/tweak
  配 `allow_empty`(无规格轻量单直接过,声明了规格就必须过全套);占位残留机器拦;
- `tasks_checked`/verify-pass/moonlight defer 的实现清单来源改由引擎 `tasks_source`
  统一裁决(v5=change.md 实现清单节,legacy=tasks.md,计数正则各自语义不变);
- open 步 glob 双认 change.md|proposal.md;archive 步 glob_absent 加 change.md
  (v5 假定稿同样拦);
- 过程件全面下沉 .mae-flow-work/(git 本地排除已有):superpowers 设计文档改写到
  .mae-flow-work/design-{单号}.md 并由 design_doc 指针登记,设计结论浓缩进
  change.md 方案节;design 步 clean_paths 去掉 docs/superpowers;survey 笔记本就
  在 .mae-flow-work/。clarifications 与 STORY 是需求级正式记录,保持入库;
- 步骤文档 open/hf_open/tw_open/design/build/verify_ponytail/verify_comet/archive
  同步改写,均带"在途旧布局单照旧走"救济句;CAPABILITY_PACKS 方法原文一字未动
  (以"本页为准"覆盖声明处理,沿用 openspec 命令改写的先例)。

### 测试

- specengine 46→59:V5LayoutTests 13 项(三档骨架、v5 校验正反、布局混用、
  等价性逐字节、单文件归档、纯移动、任务计数、status、instructions、围栏边界);
- capabilities 11→12:生命周期用例换轨 v5(骨架断言、档案单文件断言),新增
  legacy 四件套全链兼容用例(tasks.md 计数、specs 合并、四件套进档案);
- selftest 212→213:新增"v5 规格校验硬证据在位"防回退(open/hf_open/tw_open/
  design 的 spec_validate 被删即红);
- 探针**入库常驻**(结束"历次会话临时重建 92+17 项"的浪费):
  `scripts/tests/probe_gate_smoke.py` 24 项(gate 拦/放抽样+spec_validate 八路+
  tasks_checked 四路+glob/glob_absent 双布局+坏编码三路)、
  `scripts/tests/probe_spec_semantics.py` 21 项(三档端到端、混用、阶段机、
  伪造通道),selftest 点名跑、发版门覆盖;
- 流畅性收口(核心原则:流畅易用,不能因 hook/证据卡死):v5 全部新校验都在
  done/spec 命令层,hook 热路径零新增;证据函数宽兜底——任何异常(含
  UnicodeDecodeError 坏编码,它不是 OSError,原本会裸 traceback 穿透)一律转
  "拒+可执行指引",done 可重试、连拒两次自动亮 goto --force 用户裁决出口;
  _read_change_doc 把编码错误收口为 SpecEngineError,CLI validate 优雅报错。

回归:state_core 7、specengine 59(含 13 差分对拍)、capabilities 12、selftest 215
(213+2 探针纳管)、gate 冒烟探针 24、spec 语义探针 21,全绿。

## 2026-07-25：v3+v4 引擎内化——单一状态机、零 Node 依赖

目标:阶段状态只有一个裁决源;宿主前置从四件套(Python/Git/Node/Git Bash)减为三件
(Node 降级为可选,仅开发期对拍用)。方法论文本继续以固定源码随包提供,一字未改。

### v3 去 comet:第二状态机摘除

- 交付阶段、验证结论、产物指针从外部 `.comet.yaml` 收归 `.mae-flow.json` 的 `spec` 段:
  同一把锁、同一份 gate 保护、同一套 revision/CAS。因此彻底消失的整类问题:phase 掉队、
  僵尸 change 抽奖、`.comet.yaml` 的 Bash/Edit 不对称伪造面、CRLF 双脑分裂、
  `COMET_FORCE_PHASE` 逃生口、阶段互锁哨兵(它存在的唯一目的就是对账两个状态机);
- 新增 `mae-flow spec <init|show|new|instructions|validate|set|phase|verify-pass|archive>`,
  三条硬点比被取代者更严:指针字段**登记时校验文件真实存在**;阶段不可跳跃/回退/直达
  archived;`verify_result` **不可直写**,只能由 verify-pass 在「阶段已在 verify + 报告
  文件存在 + 实现清单全勾」三重校验后产生——旧 `comet-state set verify_result pass`
  一条命令伪造验证的通道关闭;
- 证据 `yaml_field` → `spec_field`(旧名保留为别名,在途单兼容),并新增指针**现场复核**
  (登记后文件被删/改名即失效);design/archive 步补 phase 硬闸(comet 时代根本没有);
- 退出后接回流程的定稿回退不再依赖外部引擎(旧实现只找 `.cac/.claude` 旧脚本,
  纯内嵌项目上必死),改为改自家阶段字段并作废验证结论;
- 20 处步骤指令的 `capability comet-*` 全部改写为 `spec ...`;SKILL.md comet 话术清零。

### v4 去 Node:规格引擎纯 Python 内化

- 新增 `scripts/mae_flow_core/specengine.py`(1861 行):建配置/建变更目录/发格式指令/
  结构校验/定稿合并/状态查询六项全部内化。实现方式是**直读内嵌 bundle 未混淆的
  esbuild 源码逐条移植**(关键处注释标注上游函数名),schema、模板、指令正文实时读
  vendored 数据文件,零硬编码;
- `scripts/tests/test_specengine.py`:46 项测试,含 **13 个与内嵌 CLI 的差分对拍**——
  ADDED/MODIFIED/REMOVED/RENAMED、多域、单文件多 requirement、中文 SHALL 混写、
  三种非法格式、全链路,要求 `openspec/` 目录树逐字节一致 + validate/archive 判决一致;
- **顺带修上游 CLI 一个真 bug**:CLI 先写真相源后查归档冲突,同日同名二次归档会把 delta
  二次并进主 spec 才报错,留下脏真相源+未移走的变更目录(已实测复现)。引擎把冲突检查
  (含主 specs 残留检查)提前到任何写盘之前,移动失败回滚已写文件——"归档半成功不可
  重入"这个老痛点从根上消除;
- `prepare_project` 改用引擎创建规格配置,不再调 Node CLI、不再写 `.comet/config.yaml`;
  `_host_runtime_checks` 必需项只剩 Python/Git/Git Bash,Node 移入可选检查(缺失也 ok);
  诊断新增「内置规格引擎」项;open/hf_open/tw_open 三步的 `capability openspec` 全部
  改为 `spec new|instructions|validate`——**Node 彻底离开运行路径**;
- 清理随之失效的死代码:`configure_comet_build`、`_ensure_yaml_scalar`、
  `capability comet-build-defaults`(留着等于留一条会重新写出 `.comet/config.yaml` 的双源)。

### 测试体系换轨(不弱化断言)

- `test_capabilities.py` 9→11 项:诊断契约按新必需/可选项断言并加四条防回退(Node 不得
  回到必需、`内置规格引擎` 不得消失、`OpenSpec 可执行`/`内嵌 Comet 脚本` 不得复活);
  生命周期用例改走 `spec` 子命令端到端,保留中文+空格路径覆盖,并**在 PATH 剥掉 node
  的子进程里跑**——v4 承诺有测试守护;新增 prepare_project 契约与「无 Node 仍成功」用例;
- `selftest.py` 新增四条防回退:步骤与流程图不得再出现 `capability comet-`、证据全部
  spec_field、**AST 级**检查流程代码不再直接驱动外部引擎(子串匹配会误报文档字符串)、
  透传调用面不得扩张;并把规格引擎测试纳入自检清单。

回归:state_core 7 项、specengine 46 项、capabilities 11 项、selftest 211 项、
gate 冒烟 92 项、spec 语义探针 17 项,全绿。

## 2026-07-25：流程魔改——轻量化与质量的平衡批次

准则:轻量化只删"重复劳动"(同一决定问两遍/同一 agent 白跑),不删决策点与证据;
每项过三问——删的是重复还是必要冗余?错误还有没有另一层接住?用户能否退回重路径?

### 一卡合一(体验)

- 配置确认卡合并收集四个开场决策(配置确认/交付方式/是否质询/是否 STORY,各带推荐):
  完整开发的用户停顿从 5 次降到 2 次(开场一卡 + 定稿确认);
- workflow_select/grill_ask/story_ask 直接消费配置卡捕获的真实答案(`_current_ack_messages`
  预答通道,仍验真、改选仍被抓、预答缺失自动回退逐步提问)。

### grill 与 brainstorming 去重(体验)

用户实感的重复有三处,病根不是"两步该合并"(WHAT 在规格前、HOW 在规格后,时序正确):

- open 决策摘要卡①类(有质询/文档依据的 Scenario)明确**禁止逐条重问**——已拍板的事再确认
  一遍是最烦的重复劳动;②③类(AI 推断/拿不准)照旧逐条呈审;
- design 步明确**跳过 brainstorming 原文的"理解问题/发现"提问阶段**——WHAT 层已由质询+规格
  覆盖,问题清单直接=「留给设计阶段」清单+规格开放点;
- 需求级新缺口回流质询的通道原样保留(去重不去防线)。

### 质量补强(与轻量化对冲)

- `agent-task` 生成任务卡时统一注入 delivery-notes 沉淀经验(≤40 行,冲突时任务卡优先):
  一处改动,主流程/评审/小改三条质量链的 agent 全部拿到踩坑经验(原先 rf/tw 链拿不到);
- 独立质询补链:备课表纳入 hook 章节校验(路径正则放宽至 standalone 目录)、start 给出模板
  绝对路径、finish 硬校验 prep 轮 critic 执行过(README"开始和结束各查一次"落为机制);
- verify_ponytail 出界的 correctness 发现必须落盘 tasks.md 备注(只留会话里=一次 /clear 蒸发);
- 拍板两项悬案:tweak 线 comet review 判"有意 off"(tw_verify 的 verify 包+三重质量链兜底,
  文档同步);comet review 定为 verify 单点(五维表修正,不再声称 build 收尾双点)。

### 明确拒绝的轻量化(质量优先)

- verify 链保持 删→改→测→验 串行(各步顺序理由成立,融合会破坏任务卡隔离与令牌语义);
- current 保持全量重印方法文本(弱模型中断恢复不赌记忆,这是保命绳不是浪费)。

## 2026-07-25：误拦治理与月光/comet 集成加固

目标：把硬拦截收敛到"只拦真违规"，误拦弹回是最大的 token 浪费源；同时补上月光宝盒
与 comet 集成审计发现的真实质量洞。done 侧证据体系未做任何放松。

### 误拦六修（流畅性）

- gate 源码判定统一"项目根相对+正斜杠"匹配（原始与 realpath 双口径）：仓库祖先目录名
  含 src/app/lib 时全仓 Edit 被误判源码、defaults 锚定正则(`^ut/`)永不命中，两者同根修复；
- Bash 写盘检测强弱分层：`2>&1` 等裸重定向不再算写盘，改为解析真实落盘目标；
  `git format-patch` 不再命中 `patch`；cp/mv/tee/patch 弱启发降为软提醒（按 3.3 软层定位），
  重定向写源码与 sed -i 等强动词照拦；
- **修复"openspec 路径被判手动创建"黑事件**：`(mkdir|md|new-item)` 左侧未锚定，
  `git add openspec/.../proposal.md` 里 "proposal.md" 命中 "md" 被拦，而 clean_paths 证据
  又要求必须提交——门禁与证据互锁卡死。动词改为命令位锚定且只检查其自身参数；
- 分支 gate 排除 `checkout HEAD -- 文件` / `checkout .` / sha 游离检出等文件恢复形态；
- choice 验真从全文子串搜索改为"全等或标签前缀"（ASCII 代号只认全等）：
  "这次不是 hotfix，走完整开发" 不再被误判为 Agent 替用户改选；
- SubagentStop 多标记打回放宽：同名同值重复标记视为无歧义直接接受，矛盾标记才打回，
  且打回话术如实说明"标记互相矛盾"而非误导性的"第一行必须是标记"。

### break-glass 兜底：一次性放行令 + 三振熔断（gate 误报的优雅出口）

gate 的误报不可能降到零(静态文本判断动态行为)。兜底纪律:

- **规则分两类**:绝对类(密钥/危险命令/状态文件/伪造通道)永远没有放行令,用户手动
  执行就是它们的逃生口;裁决类(源码步骤判定/测试路径/分支与提交约定/openspec 目录等
  全部可能误报的启发式,共 14 条)接入统一 break-glass 出口;
- **三振熔断**:同一规则同一步骤连拦 3 次,拦截消息自动升级,附本次动作的放行令编号
  与签发指引——出口平时不广告,卡死的那一刻自己出现;
- **一次性放行令** `mae-flow allow <编号> --ack "用户原话"`:与 accept-risk 同级强验真;
  只豁免触发的那一条规则、只对这一个动作生效一次,绑定当前代码版本与步骤,
  用后即废、代码变化即废,签发与消费全部进历史账本;
- **月光模式**下没有用户,放行令天然签不出来:三振升级改为指向 moonlight blocked/defer
  留痕停在安全点,早晨由用户裁决——夜间完整性零妥协;
- **兜底同时是误报采集器**:三振记录进 doctor(「疑似误拦」条目),反复出现即修规则的
  工单,残余误报从事故变成带标签的 bug 报告;
- **done 证据连拒 ≥2 次时亮出用户裁决出口**:用户明确说"跳过吧/可以了"时,拒绝消息
  直接给出 `goto <下一步> --force --ack "用户原话"` 的整步跳过命令(留痕审计)——
  该通道一直存在但只写在维护文档里,"用户说跳过、hook 不听"的体验源于不可发现,
  不是不可为。没有用户原话时 Agent 仍不得自行跳过。

### 拦截时机前移（拦截时机 = 错误发生时机）

不在对的时机拦不如不拦：检测点离错误点越远，积累的重做成本越高，late 拒绝只会让
Agent 面对无法归因的证据错误然后罢工。两处重灾区前移：

- **质量 agent 派发前验任务卡**（PreToolUse 新增 Task 匹配）：compile/codecheck/UT
  派发时任务卡缺失或 HEAD 过期立即拦下并给出重签命令——原来要跑完上百轮才在
  SubagentStop/done 被打回整只重来；story 等无任务卡机制的 agent 不受影响；
- **提交时验分支**：`git commit` 的 gate 在提交这一刻校验当前分支==约定分支——
  原来只在 done 时查，站错分支提交一整步才发现，返工要 cherry-pick。

### Hook 自身健壮性

- hooks.json 六命令加文件存在守卫（if/exec 保退出码）：插件根变量缺失/文件被隔离时
  旁路放行，不再以 exit 2 锁死整个会话；dispatch 对 mae-flow.py 缺失同样 fail-open，
  子进程退出码白名单化（非 0/2 按插件故障放行并留日志）；
- stdin 兜底线程超时后改走 os._exit 收尾：消除"Fatal Python error + exit 134"；
  statusline 同样补 stdin 超时守护；
- 状态写盘对杀软短锁做指数退避重试（os.replace/os.remove 全路径）；exit 删除主状态
  失败时如实报"退出未生效"（原实现谎报成功但门禁仍在）；
- hook 日志超 5MB 滚动；DIRECT/CORRUPT 每条消息的横幅改为每会话一次；
  UTRUN 探测收窄到 UT 步骤（FIELD-TEST 0.2 待办）。

### 月光宝盒（按场景化审计修复）

- Stop 反收工护栏从"链级一发"改为无进展计数：状态 revision 有推进就继续拦，
  连续三次零进展才 fail-open——修复"第一次打回后任何收工都放行"的静默白夜；
- `moonlight off` 与 on 对称要求用户原话授权，夜间 Agent 不能自行拆除约束；
  off 后 moonlight_review 的 repair/finalize 不再要求"已开启"（消除互相踢皮球）；
- defer 复用 done 的源码回流纪律：UT 步内改过被测源码后 defer 自动回流重新编译，
  不再出现"改过源码未复验就推送"；
- `moonlight on` 冷启动补 prepare_project 前检（环境问题启动即报，不留到凌晨）；
  在已完成的终态单上开月光会先按 init 规则换单滚动，不再整夜停在"交付完成"；
- `init --ack` 接回流程时清除月光标记，恢复普通交互不再被 Ask 拦截。

### comet 集成收口（按上游 0.3.9 对照审计）

- tw_verify 证据键 `value` 改为 `equals`（原写法被静默忽略，pending/fail 也能过）；
  ev_yaml 兼容 value 别名并保持 equals 语义；
- `.comet.yaml/.openspec.yaml` 的 Bash 写路与 Edit 对称拦截；`comet-state set` 禁止直写
  verify_result/phase/archived/verified_at（transition 专属）；拦 COMET_FORCE_PHASE 与
  直接执行内嵌脚本；run_comet 环境剔除 COMET_FORCE_PHASE；
- 阶段互锁哨兵补齐 tweak/hotfix 线映射（原先全裸）；
- 项目 .gitattributes 自动补 `openspec/** text eol=lf`，插件自身 vendor 目录加 `-text`
  （CRLF 检出会让 comet bash 侧读到 `pass\r` 全线报错、四组件哈希全部误报损坏）。

### OpenSpec/Superpowers/轻量思想源继承收口（按上游逐源对照审计）

- `capability openspec` 透传通道加策略：`archive` 钉在 archive 步——它曾是真相源写保护之外
  的第三条未设防写路，verify 链任意步一条命令即可绕过验证与用户定稿确认合并真相源；
  `init` 指向 capability prepare。gate 增拦裸调全局 `openspec` 与 `runtime/bin/openspec`
  直执（"禁止调用机器全局版本"从宣示落为机制）；
- open 步三连修（规格格式合同断供）：显式取 `instructions specs`（原循环只列
  proposal/design/tasks 三条）、done 前 `validate` 结构自检（错误当步修，不潜伏到定稿）、
  Requirement 正文 SHALL/MUST 关键词提示（上游校验认英文，纯中文正文会卡死归档）；
- build 步：计划由主会话亲自按 writing-plans 生成——派"制定计划"子代理拿不到能力包文本，
  产出丢失 bite-sized/No Placeholders 纪律；计划任务不含写测试步骤（TDD 弃用与验证台账对齐）；
- 上游 SKILL 目录内相对引用统一改写为内嵌绝对路径（评审模板 code-reviewer.md 与
  systematic-debugging 三份支撑技术，此前渲染语境不可达）；
- end 步经验回顾增加 `ponytail:` 天花板标记盘点（上游 debt 收割意图的最小承接）；
  end 沉淀纪律零机器锚点登记进 MAINTAINERS 已知局限清单（完成"有意接受"程序）。

### 其他

- 团队预设 `.mae-flow-defaults.json` 纳入 gate 黑名单（它决定门禁口径），JSON 读取统一
  utf-8-sig 且解析失败可见（BOM/GBK 不再静默让源码/测试路径失效）；
- `_ensure_review_base` 的 rev-parse 补 `--verify --quiet`（root commit 场景不再产生
  伪基点导致 review 质量链静默全过）；CodeCheck 拒绝含 cmd 元字符/逗号的文件名；
- 归档回退优先走内嵌 comet-state（原实现只找 `.cac/.claude` 旧目录，纯内嵌项目必死）；
  用户仓 .gitignore 按 errors=replace 读（GBK 注释不再让 init 崩栈）；
- grill_ask 按钮别名与步骤文案对齐；archive.md 修正永不替换的占位符；
  selftest 的 Stop 护栏用例更新为无进展计数语义。

## 2026-07-25：Windows 与确认流程修正

- 修复 Windows 插件路径中的 `\U` 被 `re.sub` 当作转义序列，导致 `envcheck` 和阶段能力加载失败；
- 路径注入改用回调返回原文，并增加真实 `C:\Users\...` 路径回归测试；
- 配置确认改为“完整配置确认单 + 一次性收据 + 需求文档指纹”，单项回答不能替整单背书；
- 多问题结构化回答只认最终确认；宿主不回传选择时可用一条普通消息恢复，不需要退出重开；
- 连续 ACK 失败不再称为熔断，也不会引导 Agent 删除状态或重新初始化；
- 人工确认改为按风险分层：普通选择点一次按钮即可，设计/编码/编译/检查/测试完成由机器证据自动推进；
- 删除 grill、build、评审裁决汇总和评审修复结束处的重复签字，强 ACK 仅保留给豁免、风险和强制回流；
- `envcheck` 现在显式检查 Python、Git、Node.js 和 Git Bash，输出实际版本与路径；
- 完整流程初始化复用同一套前检，基础依赖异常时不会创建状态或激活 Hook；
- Git 仓库识别改为真实执行 `git rev-parse`，支持 `.git` 为文件的 worktree；
- 项目编译器、测试框架继续留在实际编译/测试阶段验证，不重新引入项目级 setup。

## 2026-07-25：安装即用重构

这一版把项目级 setup 整体拿掉了，目标是安装插件以后直接能用。

### 开源能力真正随插件运行

- 固定内嵌 OpenSpec 1.6.0、Comet 0.3.9、Superpowers 和 Ponytail，不再依赖用户机器上的同名版本；
- Comet 的状态、守卫、交接和归档脚本直接运行，阶段规则从固定上游原文按需加载；
- OpenSpec CLI、schema、模板和官方方法一起打包，修复打包入口重复执行导致归档半成功的问题；
- 四个组件增加目录级 SHA-256，自检可以发现发布包缺文件或源码损坏。

### 不再有项目安装阶段

- 删除 setup、环境修复 Agent、项目 Skill 迁移、reload 和个人 settings 修改；
- 首次发起流程时只确定性准备规格目录，不创建 `.cac/.claude` 或其他 Agent 平台目录；
- 旧版本停在环境步骤的在途状态会自动迁移到配置确认；
- 初始化自身失败时不会创建流程状态，Hook 继续旁路，普通开发不会被锁住。

### 编译、UT 和 CodeCheck 边界重新收口

- build-fix、AutoUT、java-autout 保持为内网插件自带的真实 Skill，任务卡和 transcript 校验机制不变；
- 完整流程的 Comet 构建选择改由单条确定性命令一次写入，避免后半程因为漏字段无法推进；
- CodeCheck 只在首次真正使用时尽力安装，使用一次性内网 registry 参数，不修改用户 npm 配置；
- CodeCheck 安装或工具本身失败时可留痕继续，不会误派修复 Agent或形成无限重试。

### 回归与兼容

- 增加中文、空格路径下的新建、设计交接、构建、验证、规格合并和归档完整生命周期测试；
- 小改流程补齐最终规格对照和状态闭环；
- 保留旧状态迁移、旧项目 Comet Hook 退出兼容、独立任务、月光宝盒和人工风险出口；
- 自检改为只读语法编译，不再因为发布目录禁止写 `__pycache__` 而误报失败。

## 2026-07-22 至 2026-07-25：质量链与逃生通道

这两天主要做了下面这些事：

### 质量检查不再让主 Agent 自己猜

- 编译统一交给编译 Agent，并要求使用项目配置好的编译方式；
- CodeCheck 先真实扫描，零告警就继续，有告警才启动修复 Agent；
- CodeCheck 不再因为退出码不是 0 就误判失败，也不会检查 UT 文件；
- UT 必须真实生成和运行，支持由 AutoUT 决定实际测试命令；
- 子 Agent 没有正常签发令牌时，可以让用户确认风险后继续，避免一直重跑。

### 工作流不再把人卡死

- 增加 `/mae-flow exit`，中途可以随时退出，直接让 AI 改代码；
- 退出后想继续使用，可以从原来的断点重新接回；
- 只安装插件但没有启动流程时，所有 Hook 都会旁路，不影响普通开发；
- 状态损坏、确认信息没捕获到等异常场景也保留了退出办法。

### 增加几种更轻的使用方式

- 增加月光宝盒模式，晚上无人值守尽力开发、检查、测试和推送，早上再看报告；
- 支持根据夜间报告继续修复，不需要重新跑需求分析；
- 可以单独补 UT、单独做 CodeCheck、单独梳理需求，不必启动完整流程；
- 单项任务执行前会展示文件范围，让用户确认后再开始。

### 底层重新整理了一遍

- 完整流程、普通开发、单项任务和月光宝盒共用一套运行状态判断；
- 状态栏、CLI 和 Hook 对“当前到底是什么模式”的判断保持一致；
- 修复父目录旧状态误接管子仓、确认短词误命中、结构化选项误当成确认等问题；
- 安装脚本可以纠正错误配置，修改全局配置前会备份，`dry-run` 不会真的写入。

### 发版整理

- 使用更容易理解的开发方式名称；
- 固定 OpenSpec 1.6.0 和 Comet 0.3.9；
- 补充 README、分享 PPT、现场验证清单和维护说明；
- 清理 Python 缓存，发布源码包不再携带分享图片等大文件。

CodeCheck CLI 来自公司内网仓库，具体版本仍由内网仓库管理，安装结果会写入 setup 日志。
