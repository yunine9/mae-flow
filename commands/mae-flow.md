# /mae-flow

你已进入 mae-flow 交付工作流。**全程使用简体中文与用户交流。不要自由发挥,严格按以下步骤执行:**

1. 定位插件目录(定位不了就 Glob 搜 `**/mae-flow.py`),通读 skills/mae-flow/SKILL.md 并全程遵守其铁律。
2. 按参数分流:
   - **moonlight / 月光宝盒** — 无人值守交付。若后续参数是 `report|repair|finalize|off`，直接执行对应
     `mae-flow.py moonlight <动作>`；其中 report/repair 不询问用户，finalize 发现仍有遗留时才展示报告并
     等用户明确接受后携带原话重试。其他参数视为本次需求描述：
     - 从用户本条消息取真实出现的 `月光宝盒` 或 `moonlight` 作为短 `--ack`，执行
       `mae-flow.py moonlight on --ack "<原词>"`；没有状态会自动初始化，有在途状态会从当前步骤切换；
     - 将本条消息中的单号、需求描述和已有文档作为后续 config_confirm 输入，不再反问；
     - 随后持续执行 current → 当前步骤 → done，禁止 AskUserQuestion、禁止结束回复等待；
     - 选择项按不扩大范围原则自动决定：明显评审意见选 review，明确缺陷选 hotfix，极小局部改动选 tweak，
       其余选 full；full 默认做需求质询，STORY 仅在用户明确要求或需求涉及测试协同时生成；
     - 质量步骤真实尝试后仍失败，使用 current 输出的 `moonlight defer` 留痕继续，最终必须尝试 push；
       build 只有实现 tasks 全部完成并提交后才能 defer；push 后停在晨间检查，不自动定稿规格；
     - 需求材料、权限或外部依赖客观缺失且无法自行补齐时，执行 current 给出的 `moonlight blocked`
       保存完整现场后结束；禁止反复重试或编造输入。主 Agent 在其他步骤提前结束会被 Stop Hook 打回。
   - **exit** — 退出当前在途流程、保留现有代码并改为普通开发。用户输入 `/mae-flow exit` 本身就是
     明确授权，UserPromptSubmit Hook 会直接保存现场并退出，**禁止再追问一次确认**。若 Hook 已异常，
     先且只重试一次
     `mae-flow.py exit --reason "用户明确执行 /mae-flow exit" --ack "/mae-flow exit"`；
     仍失败就将 `python "<插件>/scripts/mae-flow.py" exit --interactive --reason "切换为普通开发"`
     原样交给用户在真实终端手动运行，禁止再次询问。Agent 不得用 Bash 管道代答。
     成功后禁止继续 current/done。
     没有在途流程时插件本来就完全旁路，只说明当前无需退出，不创建新流程。
   - **无参数** — 完整交付流程:项目根已有 .mae-flow.json → `python "<插件>/scripts/mae-flow.py" current` 续跑;
     有 `.mae-flow.json.exited` → 当前是普通开发模式。只有用户本条消息明确要求重新接回/重新使用 Mae-Flow
     时，先执行 `messages` 取得本条真实消息 ID：恢复原流程执行 `init --message-id <ID>`；
     保留旧现场并明确开启另一流程执行 `init --new --message-id <ID>`。普通改码请求不要 init；
     `.mae-flow.json.exited` 只是退出指针、真正状态在 snapshot 目录，**严禁移动/改名/复制成
     `.mae-flow.json`**；不同单并行仍建议另开 worktree；
     两者都没有 → **不要接管普通开发**；仅当用户明确要求 mae-flow 交付且已给出单号/需求时 `init`,
     否则照常执行用户的直接改码/补 UT 请求，不得为了使用插件而 init。
   - **ut** — 只补并执行单元测试，**不 init 完整流程**。如果项目还有 `.mae-flow.json` 在途状态，
     先说明不能叠加两套控制状态，让用户发送 `/mae-flow exit` 后重试；禁止自行退出。
     从命令剩余文字提取目标文件/功能和验收说明；若用户只说了功能，先定向查找并定位至少一个被测
     业务文件。用重复的 `--files` 明确传入业务文件（可同时带相关测试文件），完整用户描述用
     `--request` 原样传入。执行：
     `mae-flow.py action start ut --request "<用户描述>" --files "<被测业务文件>"`
     脚本会从项目预设或上次现场继承 UT 生成/运行/编译方式；缺项时只问缺失配置，不启动环境流程、不猜命令。
     `start` 只会冻结并展示文件清单，不会立即派 Agent。必须用 AskUserQuestion 让用户选择
     「确认以上范围 / 需要调整范围」；确认后执行
     `mae-flow.py action confirm-scope --ack "确认以上范围"`，调整则 `action cancel` 后按新清单重开。
     只有确认成功后，才按输出的唯一话术启动 `ut-generator-agent`，不得添加自编参数。
     Agent 收尾后执行 `action finish`。
     PASS 必须真实生成并运行测试；疑似源码缺陷先展示自查报告让用户裁决。独立模式默认不 commit、不 push。
   - **codecheck** — 只做代码规范检查和安全修复，**不 init 完整流程**。在途完整流程的处理同 ut。
     默认范围=当前工作区改动中的业务代码；用户点名文件时用 `--files`。执行：
     `mae-flow.py action start codecheck --request "<用户描述>" [--files "<路径>"]`
     只想看报告时增加 `--check-only`。修复模式缺编译方式时只问这一项。
     `start` 同样只展示过滤后的业务文件清单，用户二次确认后执行
     `action confirm-scope --ack "确认以上范围"`；确认前禁止扫描，调整时取消后按新范围重开。
     确认后脚本才真实 fullcheck：0 告警直接结束，不派 Agent；有告警才按输出任务卡启动
     `codecheck-fix-agent`。Agent 收尾后执行 `action finish`。测试文件自动排除，剩余告警只报告，
     禁止自动豁免；默认不 commit、不 push。
   - **grill** — 只把需求问清楚并生成澄清结果，**不 init、不进入设计和编码**。在途完整流程的处理同 ut。
     执行 `mae-flow.py action start grill --request "<用户原话>"`；已有文本材料用
     `--source "<路径>"`。按输出路径完成八维备课和定向代码勘察，然后执行
     `action critic --stage prep --document "<备课文件>"`，启动只读 `grill-critic-agent` 找第一轮遗漏。
     此后主 Agent 一次只问一个问题，每个答案先检查模糊词、新名词、矛盾和衍生边界，再问下一题；
     子 Agent 无权替用户回答。收敛后把澄清文档交
     `action critic --stage final --document "<澄清文档>"` 再审一次，吸收或如实记录剩余风险，
     最后 `action finish --report "<澄清文档>"`。默认不提交文档。
   - **cancel / task cancel** — 仅取消当前独立 UT/CodeCheck/Grill 任务：
     `mae-flow.py action cancel`。保留已经产生的代码和报告，不回滚，也不影响普通开发。
   - **chain** — 跨仓需求的链路分解,**不 init 流程**,先于任何仓的交付执行。由你(主模型)亲自做,
     禁止外包给子 agent(全程需要与用户问答)。步骤:
     ① 按 config_confirm 的同一套纪律确定单号与需求文档;
     ② 让用户给出涉及仓清单与本地路径,建议用户 /add-dir 拉入各仓获得跨仓视野;
     ③ **事实自查**(读代码,不问人),质量纪律四条:
       - **多角度搜索防漏**:按关键词、按接口调用链、按配置/路由三条路各扫一遍,单一角度=必漏;
       - **触点必须带证据**:每个触点=仓+文件+符号名+一句为什么相关,禁止"XX 仓可能涉及"式散文;
       - **宁滥勿缺**:拿不准的触点标"低置信"列出来交用户裁决,禁止自行过滤——误报用户一眼划掉,
         漏检要到联调才爆;
       - 现有接口盘点带定义文件出处(proto/头文件/API 声明的具体路径);
     ④ **决策问人**(AskUserQuestion 逐项,grill 同款纪律:每题带推荐+依据,禁止代拍板):
       功能边界怎么切到各仓、新增/变更接口的契约(**形态/字段/错误语义三要素齐全,错误语义最易含糊,禁空**)、
       依赖方向与交付顺序;
     ⑤ **逐仓反向核查**(落盘前,防"糊"):对每个仓自问——只看它的职责描述+契约,能独立开发吗?
       字段够吗?错误场景定义了吗?答不上的回到④补问;
       然后**引用自验**(防"幻"):文档所引的每个 文件/符号 逐条实测存在,幻觉引用=返工重查;
       落盘 docs/chain/CHAIN-<单号>.md(存放在当前会话所在仓,仅为存放地),
       **结构按 `mae-flow template chain` 输出的模板**(七章齐全;结构由 hook 硬校验,缺章节会被打回)。
       展示时**引导用户重点抽查**(防橡皮图章):触点清单有无漏仓漏模块、契约的错误语义,
       这两处是历史错误高发区;经用户确认后定稿。
     ⑥ 收尾输出**各仓启动卡**(用户复制即用,逐仓一张):
       仓路径、启动话术「交付 <单号>,需求文档=<CHAIN 文档绝对路径>」、建议 workflow、
       并行性说明(契约已冻结,可并行开发;合入按依赖顺序:<顺序>)。
     此后**每个仓平等地**独立跑交付流程(同一单号):需求文档=CHAIN 文档(+原需求),
     该仓是否再做本仓 grill/STORY 按其复杂度自定,不强制跳过。
   - **help** — 新手指南,**不 init 流程**:读插件根目录的 README.md(与 scripts/ 同级),输出:
     ① 30 秒上手(用户只做三件事:发起「交付 <单号>+SE 文档」、在确认点拍板、最后去平台建 MR;
     开新局敲命令,进行中直接说话);② 常见问题标题清单(用户点名哪条再展开);③ README 完整路径。
     用户后续追问,一律以 README 内容为准作答。
   - **envcheck / doctor** — 只诊断，不安装：检查 Mae-Flow 随插件内嵌的运行时是否完整。
     CodeCheck 缺失只提示“首次使用时会尽力安装”，不把插件判成不可用；禁止引导用户运行 setup、
     迁移 `.claude/.cac`、执行 reload 或全局初始化。
   - **story** — 仅补生成 STORY,**不 init 流程**。单号按此顺序确定,拿不到就问,禁止瞎猜:
     ① 命令参数里带了单号(如 `/mae-flow story REQ2026071801`)→ 直接用;
     ② 没带,但项目根 .mae-flow.json(或 .mae-flow.json.last)里有单号 → 向用户确认"是给 <单号> 补吗?";
     ③ 都没有 → 问用户要单号。
     确定后先执行 `mae-flow template` 拿模板绝对路径,再启动 story-generator-agent
     (模式=补生成,传入单号、该单的 change/archive 产物路径、模板绝对路径)。
     agent 返回后照流程内 story 步的同一套确认纪律执行(本模式没有 done 硬校验兜底,全靠你自觉):
     待确认项用 AskUserQuestion 逐项拿用户拍板 → 你亲自把"(待确认)"改写为"(已确认)"(agent 无权)
     → 文档零"待确认"残留 → 用 AskUserQuestion 问是否入库 → 展示路径与章节概览收尾。
   - **review-fix** — 处理评审意见:本单已交付(MR 已建),处理评审/走读/流水线门禁意见。
     单号确定同 story 模式(参数带→直接用;.mae-flow.json 或 .last 里有→向用户确认;都没有→问)。
     用户本条 `/mae-flow review-fix ...` 已经是明确使用 Mae-Flow 开启评审修复轮的授权，禁止再问
     “是否重新启用”。若项目有 `.mae-flow.json.exited`，执行 `messages` 找到本条命令的 ID，再执行
     `init --new --message-id <ID>`；旧退出现场会保留。禁止把 `.exited` 改名成主状态文件。
     确认后走标准 init(上一单终态自动备份;存在**非终态**在途单则先问用户续跑还是放弃,禁止直接覆盖),
     config_confirm 以上轮配置为预填,workflow_select 选 review(同单号→同分支名→commit 自动追加进原 MR);
     此后按 rf_triage / rf_fix / rf_compile / rf_codecheck / rf_ut 的 current 指令走。红线:review 轮次**不碰规格**,
     涉及行为/规格变更的意见在 rf_triage 分诊转 hotfix/full 轮次。
     用户开场粘贴的意见清单先留存,进 rf_triage 步时原文照录进 REVIEW 文档。
3. 此后所有流程动作只来自 `mae-flow current` 的输出,禁止预判、禁止跳步。
4. 进入流程后的**第一条回复**末尾附一句:「新手可随时敲 /mae-flow help 查看使用指南」(全程仅提示这一次)。
