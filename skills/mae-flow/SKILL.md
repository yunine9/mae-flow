---
name: mae-flow
description: Use when 用户明确要求用 Mae-Flow 交付需求、修复缺陷或启动 Moonlight；普通问答或直接改码不自动接管。
---

# Mae-Flow

全程用简体中文交流。目标是高效率、高质量；在需要人介入时聪明地让人介入。

Mae-Flow 只管理交付语义和恢复游标，专业能力由配置的 Skill/Agent 自己负责。不要解析私有工具输出，不要为证明工具工作而增加格式、凭证或重复执行。

## 入口

插件命令统一用 Windows 可用的 `python`，并通过宿主提供的插件根目录变量定位：

```text
python "${CODEAGENT3_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/mae-flow.py" current
```

所有后续 CLI 调用都必须沿用同一入口前缀。下文省略入口的命令名只是协议后缀，不能脱离该前缀直接执行。禁止猜测或搜索插件安装目录；禁止使用旧式 skill 目录、版本化缓存路径或 `find` 定位入口。两个插件根变量都不可用时，报告“插件根目录环境变量缺失”并停止，不执行目录扫描。

已有状态先 `current`。新需求由用户确认推荐路线后启动：

```text
python "${CODEAGENT3_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/mae-flow.py" start --ticket <单号> --path <full|focused> --pace <continuous|staged> --request "<需求摘要>" --decision "<用户对完整配置卡的自然语言确认>"
```

用户可直接用自然语言改方案。把决定一次写入并推进；命令中的文字可以是忠实的语义摘要，不必逐字复制用户原话，例如：

```text
python "${CODEAGENT3_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/mae-flow.py" decision startup-confirmed "用户选择 Focused，因为问题已定位且没有跨模块风险。"
```

机器事实或普通阶段事件用 `advance`。遇到用户明确退出，立即执行 `exit --reason "<自然语言>"`；退出不回滚业务文件，也不要求再次确认。

## 两条交付路径

- Full：Intake → Spec → Design → Construction → Quality → Delivery。适合行为尚需澄清、跨模块设计、公共接口、兼容性、安全、数据、共享状态或并发风险。
- Focused：Intake → Construction → Quality → Delivery。适合已定位缺陷、局部修改和评审意见修复。判断只看语义风险，不看行数或文件数；实现中出现上述风险就 `advance upgrade-to-full --decision "<依据>"`。

Full 的五个高价值用户介入点是 Intake、Spec、Design、CP 和 Delivery。Focused 只固定停 Intake 与 Delivery。其余只有真实歧义、设计偏离、Reviewer 取舍、不可逆风险或昂贵能力重试才找用户。每次给用户一张短卡：当前结论、影响、推荐选择和可直接自然语言修改的内容。

## 六个阶段

### Intake

先读取 `.mae-flow-defaults.json` 的稳定预设、需求来源、仓库事实、当前分支和初始脏文件。读取 `docs/specs/index.md`（不存在也可继续），按业务能力选择并只读取相关领域文档；领域不按目录、类、服务、行数或文件数划分。复杂存量领域只建立本次证据覆盖的增量基线，未记载行为视为未知。

向用户展示一张完整配置卡：工号、单号及 `feat/fix` 类型、需求来源、Full/Focused、Continuous/Staged、基线分支、按 `{基线分支}_{工号}_{单号}` 派生的工作分支、精确 Build 路由、UT 生成方式、UT 运行入口和自然语言质量组合。Build 路由按项目确认：C++ 可选择配置好的 `build-fix` Skill；Java/Maven 使用确认的 Maven 命令（通常为 `mvn compile -q`）；其他语言使用仓库的准确 Skill 或命令，禁止把 `build-fix` 当通用方案。用户一次确认并可自然语言修改；不要求固定话术。启动命令必须带上确认后的配置、`--quality-plan` 和 `--decision`，原子记录 Startup 确认并进入下一阶段；不要再调用一次 `startup-confirmed`。确认后立即创建或切换到精确工作分支，不拖到提交阶段。恢复值和确认事件仍使用稳定的 `startup` / `startup-confirmed`，兼容不带 `--decision` 的既有调用。

### Spec

Spec 只定义 WHAT：可观察行为、边界、失败语义、兼容性和非目标。主 Agent 先形成候选 Spec，再在呈审前调用 `grill-critic-agent` 做 one read-only pass；它只找歧义、遗漏和隐藏取舍，不编辑 Spec、不替用户决定。主 Agent直接吸收明确修正，CLEAR 直接继续，只有真实待决分支交用户。Spec 默认位于 `.mae-flow-work/<ticket>/spec.md`，用户明确要求保留审计材料时才生成并选择 `docs/specs/requirements/<ticket>/spec.md`。工作流生成的 Markdown 首行使用 `<!-- generated-by: mae-flow -->` 作为来源水印；它不是 Hook、parser 或格式门禁。

### Design

Story 严格沿用 `skills/mae-flow/assets/STORY-TEMPLATE.md`，把确认后的客户场景、业务规格、功能验收标准、软件详细设计和测试设计整理成可独立交给开发与测试的文档。它不是逐行编码计划。调用 `story-generator-agent` 一次，再调用 `craft-reviewer-agent` 一次并明确角色为 Design Reviewer。普通意见直接修正；只有真实取舍交用户。Story 默认写本地 `.mae-flow-work/<ticket>/story.md`，用户明确要求纳入版本库时才选 `docs/specs/requirements/<ticket>/story.md`。

### Construction

按用户确认的 Story 或 Focused 范围完成业务代码。编码时就创建测试所需的生产语义 seam，把稳定框架编排与可变业务判断分开；CP 只累计自然语言 UT handoff，不正式写或跑 UT。

Story 末尾承载全部轻量 CP 简报，不另建详细编码计划文件。每个 Full CP 保存简报、实际结果、一次 CODE Reviewer 结论和 UT 增量；同一确认卡展示本批实际结果及下一 CP，用户可直接修改后续设计。

每个 CP 调用 `craft-reviewer-agent` 一次并明确角色为 CODE Reviewer；它只读本 CP diff 和直接集成边界，不形成复查循环。Reviewer 提供的每条意见都由主 Agent给出去向：已修复、证据不足不采纳、设计取舍或超出范围；只写自然语言，不交验固定表格。对本 CP 的 exact changed code 运行一次 `lightcheck --file <exact file>...`；安全、局部、高置信问题由主 Agent 顺手修，风险高或范围外的只记录，不为 Lightcheck 单独触发编译或再次检查。随后同步调用开局确认的 Build 路由一次并记录该 CP 的不透明 Build 事实；禁止休眠等待、轮询、转后台或自动重试。Build 完成后先形成当前 CP 的 exact manifest 提案，再用 `advance cp-ready --key <当前CP>` 展示完成卡。用户要求修改时用自然语言绑定 `cp-revise`，撤销未执行提交收据并重新修改、Build、呈审；用户确认后才 exact commit。commit 被观察后用 `advance cp-opened --key <下一CP>` 进入下一批，不提前展示空 CP 卡。没有 exact scope 时 Lightcheck 直接 fail-open，不扫启动前用户现场。

### Quality

根据语义影响和用户选择决定质量能力。Full 的通常建议顺序是 CodeCheck → UT；每个 CP 已完成一次配置的 Build。若最后一次 CP Build 之后源码没有再变化，Quality 不重复 Build；若后续修复使它失效，只展示事实并让用户决定是否重跑配置的 Build 路由。

- CodeCheck：调用 `codecheck-advisor-agent` 一次，只给 exact changed production files/functions。它只请求一次正式 fullcheck。主 Agent修安全项；每条结构化意见都要有去向，raw-only 结果原样保留，不自动复验。
- UT：调用 `ut-generator-agent` 一次。它拥有 write + compile + run，输入 final Spec、final Story（若有）、current diff 和 cumulative construction hints。Mae-Flow 不推断语言、测试框架、计数或 disabled 文案。

调用能力前先看 `current` 中当前语义 slot 的已有尝试；同一语义 slot 已有记录且没有本轮用户重试决定就不要调用。新的阶段或新的 CP 是新的计划 slot，其首次调用正常执行，不让用户重复授权。该规则由主 Agent 遵守，Hook 不拦截或证明能力调用。真实能力调用同步结束后，主 Agent 只记录一次轻量恢复事实：正常返回执行 `advance capability-returned --key <kind> --decision "<简短不透明摘要>"`；启动失败、超时或无法观察返回时分别使用 `capability-failed-to-start`、`capability-timed-out`、`capability-not-observed`。这条事实不是质量报告，不解析返回值，也不要求固定格式；记录失败时不得为了补状态而重跑昂贵能力。确需重试同一 slot，先记录用户自然语言决定 `capability.retry.<kind>`；下一次匹配 slot 的真实调用消费一次授权。流程不等待、不轮询、不转后台。

Quality 收尾时记录一条自然语言的最终 Spec/Story/范围 ↔ 代码/覆盖对照结论。只有 Construction 记录了跨 CP 耦合、共享状态、接口变化或晚期设计漂移，才调用 `craft-reviewer-agent` 一次做集成边界走读并记录自然语言结论；没有触发就不增加检视。

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

Focused 启动不声明 Spec、Story 或 UT handoff；只有 `upgrade-to-full` 成功时才补入这三条 Full 产物路径。

## Moonlight

Moonlight 是 Full/Focused 上的授权策略，不是另一套流程。用户明确开启时在 `start` 增加 `--moonlight`。只有用户同时点名 exact business files 并授权时，才记录 commit/push 权限；未形成精确 manifest、存在未归属脏文件、风险、能力异常或 push 失败时仍安全停下。

manifest 确定后，只有已启用 Moonlight 的流程可用 `--moonlight-refresh --allow-commit --allow-push --decision "<用户对当前 exact manifest 的自然语言授权>"` 刷新权限。条件文档仍必须独立点名。Moonlight 不允许强推、隐藏失败、删除测试或用重复调用碰运气。

## 独立工具箱

用户明确只要 UT、CodeCheck、Grill、Story 或 Chain 时，直接调用同名命令。它们是 one-shot，无流程状态、无交付副作用、无自动重试；停止使用就是结束。

## 不可破坏的交付行为

- Agent 只修改任务相关业务文件；用户已有脏文件保持可见，纳入交付前必须自然语言确认归属。
- 任何提交都使用 exact files 和原有 `[单号][feat|fix]描述` 格式；不提交 Mae-Flow 状态、本地过程目录或未点名条件文档。
- Reviewer 提供证据，不制造无休止反工；接受修复后不自动再派同一 Reviewer。
- Build、UT、CodeCheck 是工作流按需调用的工具能力；独立 CLI 工具箱只暴露 UT、CodeCheck、Grill、Story 和 Chain。返回异常时说明事实和风险，让用户决定是否换环境、稍后再试或继续；流程本身不循环。
