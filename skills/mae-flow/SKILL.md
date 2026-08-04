---
name: mae-flow
description: Use when 用户明确要求用 Mae-Flow 交付需求、修复缺陷或启动 Moonlight；普通问答或直接改码不自动接管。
---

# Mae-Flow

全程用简体中文交流。目标是高效率、高质量；在需要人介入时聪明地让人介入。

Mae-Flow 只管理交付语义和恢复游标，专业能力由配置的 Skill/Agent 自己负责。不要解析私有工具输出，不要为证明工具工作而增加格式、凭证或重复执行。

## 入口

SessionStart 会利用 Hook 中真实的 CodeAgent 插件根，在当前仓库安装一个本地启动器。统一使用：

```text
python ".mae-flow-work/bin/mae-flow.py" current
```

所有后续 CLI 调用都必须使用同一 `python ".mae-flow-work/bin/mae-flow.py"` 前缀。禁止猜测或搜索插件安装目录，禁止使用版本化缓存路径、`find`、`python -c`/`importlib` 反射加载入口脚本，或依赖 Main Agent 中为空的插件根变量。启动器不存在时报告“Mae-Flow SessionStart 尚未生成项目启动器，请刷新插件后重开会话”并停止。

已有状态先执行完整命令。新需求先持久化配置草稿：

```text
python ".mae-flow-work/bin/mae-flow.py" start --ticket <单号> --path <full|focused> --pace <continuous|staged> --request "<需求摘要>"
```

用户可直接用自然语言改方案。把决定一次写入并推进；命令中的文字可以是忠实的语义摘要，不必逐字复制用户原话，例如：

```text
python ".mae-flow-work/bin/mae-flow.py" decision startup-confirmed "用户选择 Focused，因为问题已定位且没有跨模块风险。"
```

机器事实或普通阶段事件使用完整的 `python ".mae-flow-work/bin/mae-flow.py" advance ...`。遇到用户明确退出，立即执行 `python ".mae-flow-work/bin/mae-flow.py" exit --reason "<自然语言>"`；退出不回滚业务文件，也不要求再次确认。

## 两条交付路径

- Full：Intake → Spec → Design → Construction → Quality → Delivery。适合行为尚需澄清、跨模块设计、公共接口、兼容性、安全、数据、共享状态或并发风险。
- Focused：Intake → Construction → Quality → Delivery。适合已定位缺陷、局部修改和评审意见修复。判断只看语义风险，不看行数或文件数；实现中出现上述风险就 `python ".mae-flow-work/bin/mae-flow.py" decision upgrade-to-full "<用户确认的依据>"`。

Full 的五个高价值用户介入点是 Intake、Spec、Design、CP 和 Delivery。Focused 只固定停 Intake 与 Delivery。其余只有真实歧义、设计偏离、Reviewer 取舍、不可逆风险或昂贵能力重试才找用户。每次给用户一张短卡：当前结论、影响、推荐选择和可直接自然语言修改的内容。

## 六个阶段

### Intake

先读取 `.mae-flow-defaults.json` 的稳定预设、需求来源、仓库事实、当前分支和初始脏文件。读取 `docs/specs/index.md`（不存在也可继续），按业务能力选择并只读取相关领域文档；领域不按目录、类、服务、行数或文件数划分。复杂存量领域只建立本次证据覆盖的增量基线，未记载行为视为未知。

先用完整的 `python ".mae-flow-work/bin/mae-flow.py" start ...` 持久化 Startup 草稿并向用户展示一张完整配置卡：工号、单号及 `feat/fix` 类型、需求来源、Full/Focused、Continuous/Staged、基线分支、按 `{基线分支}_{工号}_{单号}` 派生的工作分支、精确 Build 路由、UT 生成方式、UT 运行入口和自然语言质量组合。Build 路由按项目确认：C++ 可选择配置好的 `build-fix` Skill；Java/Maven 使用确认的 Maven 命令（通常为 `mvn compile -q`）；其他语言使用仓库的准确 Skill 或命令，禁止把 `build-fix` 当通用方案。用户一次确认并可自然语言修改；不要求固定话术。`python ".mae-flow-work/bin/mae-flow.py" start --decision` 会被拒绝，因为配置卡尚未绑定当前用户输入；拿到对已展示卡片的真实确认后，使用 `python ".mae-flow-work/bin/mae-flow.py" decision startup-confirmed "<忠实语义摘要>"` 消费该输入，随后才创建或切换到精确工作分支并进入下一阶段。恢复值和确认事件仍使用稳定的 `startup` / `startup-confirmed`。Moonlight 的显式启动授权是唯一免常规 Startup 问询的例外。

如果用户修改卡片，使用 `python ".mae-flow-work/bin/mae-flow.py" configure ... --decision "<用户修改决定的忠实摘要>"`；该命令只接受绑定当前 Startup 状态的真实 UserPromptSubmit 或 AskUserQuestion 回答，并重新展示完整卡片。工号或基线分支改变而未显式指定工作分支时会重新派生分支；Full/Focused 改变时会同步重建草稿文档清单。修改后必须等待一条针对新卡片的新用户输入，再执行 `python ".mae-flow-work/bin/mae-flow.py" decision startup-confirmed`，不能复用修改配置时的输入。

### Spec

Spec 只定义 WHAT：可观察行为、边界、失败语义、兼容性和非目标。每次 CLI 调用都会把插件只读资源同步到 `.mae-flow-work/plugin-resources/`，`current` 会列出精确路径。Full 必须完整读取 `.mae-flow-work/plugin-resources/guidance/grill.md` 和 `.mae-flow-work/plugin-resources/assets/GRILL-PREP-TEMPLATE.md`，执行完整 Interactive Grill；不得在业务仓搜索 `runtime/`、`skills/`、`flow/` 或同名模板，不得读取已退休的旧步骤资源，也不得用两三个临时问题代替。定向查需求、行为基线和相关代码。`current` 还会输出经过 Windows 安全编码的精确 Grill 工作目录；把共享代码地图写为该目录中 `survey.md`，把本地资源模板复制为同目录 `grill-prep.md`，禁止按原始单号自行拼路径。状态机、边界值、并发时序、失败清理、数据一致性、存量兼容、规模性能、可观测性八维必须逐项写出“有缺口的候选题”或“有代码/文档定位的不适用依据”；任何占位残留都不得开始或收敛质询。问题数量由真实缺口和回答衍生分支决定，不设两问之类的默认上限；超过 15 题只向用户报告规模并由用户选择是否继续。

旧 `grill.md`、`grill-prep.md`、Spec 草稿只能作为历史线索。只有当前 `.mae-flow.json` 中已有且与当前问题/回答收据匹配的 `GQ-*` 才算本轮已确认；新流程状态没有对应收据时必须重新查证和质询，禁止把旧文档当本轮答案或收敛依据。

每题必须先持久化，再向用户提问：`python ".mae-flow-work/bin/mae-flow.py" advance grill-question --key <GQ-ID> --parent <ROOT|已回答GQ-ID> --evidence "<代码或文档证据>" --impact "<实现/验收影响>" --recommendation "<推荐答案及理由>"`。随后通过自然对话或 AskUserQuestion 一次问一个，拿到真实回答后执行 `python ".mae-flow-work/bin/mae-flow.py" decision grill-answer --key <GQ-ID> "<忠实语义摘要>"`。如果宿主已经先返回了 AskUserQuestion 答案，用同一条完整 decision 命令加上上述四个元数据参数，原子补登记问题并消费答案，不重问用户。每个答案都必须执行完整 Grill 的衍生检查：模糊词追到具体条件；新名词、新状态、新场景追问定义与边界；矛盾当场对质；被推翻的维度重新打开。所有候选题及衍生题关闭后，把八维证据、问题树、EARS 行为答案、确认的 WHAT 和留给设计的技术分歧写入 `current` 输出的精确 `grill.md`，再执行 `python ".mae-flow-work/bin/mae-flow.py" advance grill-converged`。

质询结果是下游 Spec 生成的关键输入，不是可选审计材料。只有收敛后才能生成 `current` 输出的精确 `spec.md`；Spec 必须包含“Grill 决策追溯”，把每个 `GQ-*` 映射到 Spec 章节或可观察验收标准。随后调用 `grill-critic-agent` one read-only pass；它同时读取 Grill/Spec，检查输入覆盖、语义未被弱化、遗漏分支和 WHAT/HOW 混杂，不编辑、不提问、不替用户决定。调用前只看本次 `current` 的动态能力区；真实返回后只执行匹配结果的一条命令，该命令原子登记调用事实和当前文件收据，不再执行 `grill-clear` 等第二条收尾命令。启动失败、超时或未观察到返回时也只复制动态能力区的匹配命令，不得猜测事件或重跑 Critic。Critic 后普通修正不触发复核；最终用户确认记录当前 Grill/Spec 摘要，摘要只用于审计，不作为回退门禁。只有真实待决分支交用户。用户明确要求保留时才选择 `docs/specs/requirements/<ticket>/spec.md`。工作流生成的 Markdown 首行使用 `<!-- generated-by: mae-flow -->` 作为来源水印；它不是 Hook、parser 或格式门禁。

### Design

Story 严格沿用 `current` 输出的精确 `.mae-flow-work/plugin-resources/assets/STORY-TEMPLATE.md`，不得在业务仓搜索模板；把确认后的客户场景、性能规格、功能验收标准、软件详细设计和测试设计整理成可独立交给开发与测试的文档。性能规格只写容量、最大并发、时延、吞吐、资源占用、兼容性和限制等可度量约束，不复制 Spec 的业务行为规格；接口设计只写 REST、CORBA、RPC、消息或开放 SDK 等对外/跨组件公开契约，内部函数和方法写入独立的关键函数/方法设计小节。Story 不是逐行编码计划。`story-generator-agent` 和 Design Reviewer 各调用一次；每次调用前只看 `current` 动态能力区，真实返回后只执行匹配结果的一条命令。Reviewer 的调用事实和当前 Story 收据原子登记，不存在隐藏的第二条命令；Hook 在重复 Reviewer Task 启动前直接拒绝，CLI 也不接受同槽位 Reviewer 重试授权。旧会话已有 Reviewer 尝试但缺少收据时，最终 Story 确认直接补齐审计事实，不再次检视。普通意见直接修正，只有真实取舍交用户；最终用户确认记录当前 Story 摘要，摘要只用于审计，不作为回退门禁。Story 写到 `current` 输出的精确本地 `story.md`；用户明确要求纳入版本库时才选 `docs/specs/requirements/<ticket>/story.md`。

### Construction

按用户确认的 Story 或 Focused 范围完成业务代码。编码时就创建测试所需的生产语义 seam，把稳定框架编排与可变业务判断分开；CP 只累计自然语言 UT handoff，不正式写或跑 UT。

Story 末尾承载全部轻量 CP 简报，不另建详细编码计划文件。每个 Full CP 保存简报、实际结果、一次 CODE Reviewer 结论和 UT 增量；同一确认卡展示本批实际结果及下一 CP，用户可直接修改后续设计。

每个 CP 调用 `craft-reviewer-agent` 一次并明确角色为 CODE Reviewer；Task 必须逐行提供 `Spec path (exact): <current中的精确路径>`、`Story path (exact): <current中的精确路径>` 和 `Changed production files (exact):` 文件清单，Hook 在 Agent 启动前校验。Reviewer 只对该清单运行只读 `git diff` 并检查直接集成边界，不形成复查循环。Design 阶段的 `craft-reviewer-agent` 负责设计检视，Construction 阶段的同名 Agent 负责代码检视，两者各自只占用一个语义槽位。调用前只看 `current` 动态能力区，真实返回后只执行匹配结果的一条命令，该命令原子登记 Reviewer 事实和本 CP 检视结论。Reviewer 提供的每条意见都由主 Agent给出去向：已修复、证据不足不采纳、设计取舍或超出范围；只写自然语言，不交验固定表格。对本 CP 的 exact changed code 运行一次 `python ".mae-flow-work/bin/mae-flow.py" lightcheck --file <exact file>...`；活跃 Construction 缺少 `--file` 必须失败，禁止空范围放行。安全、局部、高置信问题由主 Agent 顺手修，风险高或范围外的只记录，不为 Lightcheck 单独触发编译或再次检查。随后同步启动一次 `compile-agent`，Task 逐行提供 `CP (exact)`、`Build method (exact)`、`Build directory (exact)` 和 `Changed production files (exact)`；配置为 `build-fix` 时由子 Agent 调用该 Skill，配置为 Maven/其他命令时由子 Agent 执行精确命令。Hook 只把真实 `compile-agent` Task 记为 Build 调用，主 Agent 直接 Skill/Bash 或只有事实命令时 `cp-ready` 拒绝。子 Agent 返回后只执行 `current` 动态能力区匹配结果的一条命令。其他返回状态同理；已显示“当前语义位置已记录一次”时禁止再次调用，禁止休眠等待、轮询、转后台或自动重试。Full 的每个 CP 都必须独立停下让用户检视，Continuous 仅表示最后统一提交，绝不表示合并 CP。当前 CP 一旦记录 Build 尝试，源码编辑立即冻结；必须形成 exact manifest 提案并用 `python ".mae-flow-work/bin/mae-flow.py" advance cp-ready --key <当前CP>` 展示完成卡。用户要求修改时用完整 decision 命令绑定 `cp-revise`，开放当前 CP 的一次修改与重建窗口；用户确认后，Continuous 用 `cp-opened` 进入下一 CP，Staged 则先 exact commit，观察到 commit 后再 `cp-opened`。不得提前修改下一 CP，也不得提前展示空 CP 卡。

### Quality

根据语义影响和用户选择决定质量能力。Full 的通常建议顺序是 CodeCheck → UT；每个 CP 已完成一次配置的 Build。若最后一次 CP Build 之后源码没有再变化，Quality 不重复 Build；若后续修复使它失效，只展示事实并让用户决定是否重跑配置的 Build 路由。

- CodeCheck：调用 `codecheck-advisor-agent` 一次，只给 exact changed production files/functions。它只请求一次正式 fullcheck。主 Agent修安全项；每条结构化意见都要有去向，raw-only 结果原样保留，不自动复验。调用后只执行 `current` 动态能力区匹配结果的一条命令。
- UT：调用 `ut-generator-agent` 一次。它拥有 write + compile + run，输入 final Spec、final Story（若有）、current diff 和 cumulative construction hints。Mae-Flow 不推断语言、测试框架、计数或 disabled 文案。调用后只执行 `current` 动态能力区匹配结果的一条命令。

调用能力前先看 `current`，即完整 current 命令输出的当前语义 slot 已有尝试；同一语义 slot 已有记录且没有本轮用户重试决定就不要调用。新的阶段或新的 CP 是新的计划 slot，其首次调用正常执行，不让用户重复授权。该规则由主 Agent 遵守，Hook 不拦截或证明能力调用。真实能力调用同步结束后，主 Agent 只记录一次轻量恢复事实，并执行本次 `current` 在当前阶段同屏列出的一个完整事实命令：事件只允许 `capability-returned`、`capability-failed-to-start`、`capability-timed-out`、`capability-not-observed`，key 只允许 `build`、`ut`、`codecheck`、`reviewer`、`grill`、`story`。不得使用 `capability-attempt`、`capability.<代理名>`、`--note` 或位置参数猜测语法。这条事实不是质量报告，不解析返回值，也不要求固定格式；记录失败时不得为了补状态而重跑昂贵能力。确需重试同一 slot，使用 `current` 给出的精确重试决定 key；下一次匹配 slot 的真实调用消费一次授权。流程不等待、不轮询、不转后台。

Quality 收尾时记录一条自然语言的最终 Spec/Story/范围 ↔ 代码/覆盖对照结论。只有 Construction 记录了跨 CP 耦合、共享状态、接口变化或晚期设计漂移，`current` 才列出一次集成边界 Reviewer；其匹配事实命令同时原子记录集成结论，没有触发就不显示也不调用。

### Delivery

先展示 exact files、初始脏文件归属、质量观察、提交说明和目标分支。只暂存逐个文件，禁止目录、glob、`git add .` 或夹带 Mae-Flow 控制文件。
同时把每个相关领域对账为 `new`、`updated` 或 `unchanged`：行为文档只保留当前业务真相，新领域更新轻量 index；不物理归档历史 Spec，不扫描无关领域。发生变化的领域文件在 Delivery 卡中展示后进入 exact manifest。
交付清单包含启动时已脏文件时，对每个文件使用 `--adopt-dirty "<file>=<用户自然语言归属决定>"`。Delivery 确认会绑定当前 exact manifest；manifest 改变后必须重新向用户展示。

- Continuous：最终一个 `[单号][feat|fix]描述` 提交，one final push。
- Staged：每个 CP 在完成卡前记录 exact manifest 和提交说明；用户确认后才做该 CP 的本地提交。同一文件可在后续 CP 继续演进。Delivery 记录所有 CP 的累计 union manifest，只做 one final push。

Quality 或 Delivery 发现问题时，分别绑定用户自然语言
`quality-defect-repair` / `delivery-defect-repair`，打开新的 repair CP；不要覆写
已经检视并提交的 CP。流程已 complete 时，通过 `/mae-flow:mae-flow` 启动一轮
新的后续修复，复用原 Spec/Story 作为输入并重新确认配置卡。

领域行为基线是长期当前真相源，路径为 `docs/specs/<domain>.md`，新领域同时轻量更新 `docs/specs/index.md`。Spec、Story、决策、Chain、Review/CodeCheck 台账和交付说明默认本地；只有用户明确点名该文件进入版本库，才通过 `--conditional-document <exact path>` 选择 `docs/specs/requirements/<ticket>/` 下对应的 durable copy。工作流生成的 Spec、Story 和领域 Markdown 水印只标识来源，不参与格式校验。

Git Hook 只在提交这一低成本确定性边界校验确认的工作分支、单号和类型；失败只修正当前 Git 命令，不回退阶段，也不触发 Build、UT 或 CodeCheck。

Focused 启动不声明 Grill、Spec、Story 或 UT handoff；发现未决需求先用 `upgrade-to-full` 进入 Full Spec，成功后才补入这四条 Full 产物路径并执行 Interactive Grill。

## Moonlight

Moonlight 是 Full/Focused 上的授权策略，不是另一套流程。用户明确开启时在 `start` 增加 `--moonlight`。只有用户同时点名 exact business files 并授权时，才记录 commit/push 权限；未形成精确 manifest、存在未归属脏文件、风险、能力异常或 push 失败时仍安全停下。

manifest 确定后，只有已启用 Moonlight 的流程可用 `--moonlight-refresh --allow-commit --allow-push --decision "<用户对当前 exact manifest 的自然语言授权>"` 刷新权限。条件文档仍必须独立点名。Moonlight 不允许强推、隐藏失败、删除测试或用重复调用碰运气。

## 独立工具箱

用户明确只要 UT、CodeCheck、独立 Grill 或 Story 时，直接调用同名命令。它们是 one-shot，无流程状态、无交付副作用、无自动重试；停止使用就是结束。Chain 不属于独立工具箱。

## Cross-Repository Chain

Chain 是可恢复的跨仓需求调查、接口契约、依赖编排和启动卡生成流程，不是 Full/Focused 的一个阶段，也不是 one-shot。它必须由主 Agent 持有，因为仓间决策需要直接与用户逐题交互；子 Agent 只能并行检查边界明确的仓库事实，不得向用户提问、独立修改契约或推进 Chain 状态。

启动前确认锚点仓没有活动 `.mae-flow.json`。新 Chain 用 `python ".mae-flow-work/bin/mae-flow.py" chain start --ticket <单号> --request "<用户请求>" --requirement <需求来源>`；已有 `.mae-flow-work/chain-current.json` 时只用完整 chain current 命令恢复，不扫描目录猜状态。先请用户给出完整仓清单和精确本地路径；路径未加入宿主工作区时建议用户使用 `/add-dir`，路径可读后才继续。

对每个仓做三路只读查证：需求关键词、接口调用链、配置/路由。每个候选触点必须记录仓、文件、符号、相关原因、置信度和证据角度；用带项目启动器前缀的完整 chain record 命令保存事实。不得编辑任何仓的业务代码，也不得启动交付、暂存、提交或推送。

只问跨仓产品语义或接口契约决策。每题必须包含证据、影响和推荐答案：先用 `python ".mae-flow-work/bin/mae-flow.py" chain question --key CQ-<N> --parent <ROOT|已回答CQ-ID> --evidence "<证据>" --impact "<影响>" --recommendation "<推荐>"` 登记，一次只问一个；拿到真实回答后用完整 chain answer 命令消费。若 AskUserQuestion 答案已先返回，就在 chain answer 后附同一组四个元数据参数，原子补登记问题并消费答案，不重问用户。回答出现新状态、矛盾、模糊边界或派生分支时继续逐题关闭，不允许跳过开放问题。

用完整 chain record 命令固化接口契约、依赖方向、可并行范围、合入顺序和联调时点。随后对每个仓反向检查：只给该仓职责和契约，新的交付会话能否独立启动和验证；通过后用完整 chain record reverse-check 命令记录，不能独立启动就重新打开问题。

文档严格使用 chain current 输出的精确 `.mae-flow-work/plugin-resources/assets/CHAIN-TEMPLATE.md` 七节结构，不得在业务仓搜索模板；写入 chain current 输出的精确文档路径。同路径旧文件没有当前 rendered 收据时只作历史线索。先执行完整 chain verify 命令逐一验证所有引用的仓路径、文件和符号，再执行完整 chain rendered 命令绑定当前文档摘要；向用户呈现触点完整性、接口形态、字段和错误语义并取得自然语言确认后，才执行完整 chain confirm 命令。任何仓、触点、问题、契约、依赖、引用文件或文档变化都要重新校验、渲染和确认。

第 7 节为每个仓生成自包含启动卡：精确本地路径、精确启动话术、建议 Full/Focused 路径及依据、职责、契约 ID、上游依赖、下游消费者、合入/联调时点和仓内验证边界。Chain 只产生本地设计与交接，不改业务代码、不启动仓内交付、不 commit/push。用户明确要求持久化时才复制到 `docs/specs/requirements/<ticket>/chain.md`；退出用完整 chain exit 命令，只归档本地 Chain 状态。

## 不可破坏的交付行为

- Agent 只修改任务相关业务文件；用户已有脏文件保持可见，纳入交付前必须自然语言确认归属。
- 任何提交都使用 exact files 和原有 `[单号][feat|fix]描述` 格式；不提交 Mae-Flow 状态、本地过程目录或未点名条件文档。
- Reviewer 提供证据，不制造无休止反工；接受修复后不自动再派同一 Reviewer。
- Build、UT、CodeCheck 是工作流按需调用的工具能力；独立 CLI 工具箱只暴露 UT、CodeCheck、Grill 和 Story，Chain 使用单独的可恢复生命周期。返回异常时说明事实和风险，让用户决定是否换环境、稍后再试或继续；流程本身不循环。
