---
name: mae-flow
description: Use when 用户明确要求用 Mae-Flow 交付需求、修复缺陷或启动 Moonlight；普通问答或直接改码不自动接管。
---

# Mae-Flow

全程用简体中文交流。目标是高效率、高质量；在需要人介入时聪明地让人介入。

Mae-Flow 只管理交付语义和恢复游标，专业能力由配置的 Skill/Agent 自己负责。不要解析私有工具输出，不要为证明工具工作而增加格式、凭证或重复执行。

## 入口

插件命令统一用 Windows 可用的 `python`：

```text
python "<插件目录>/scripts/mae-flow.py" current
```

已有状态先 `current`。新需求由用户确认推荐路线后启动：

```text
python "<插件目录>/scripts/mae-flow.py" start --ticket <单号> --path <full|focused> --pace <continuous|staged> --request "<需求摘要>"
```

用户可直接用自然语言改方案。把决定一次写入并推进，例如：

```text
python "<插件目录>/scripts/mae-flow.py" decision startup-confirmed "用户选择 Focused，因为问题已定位且没有跨模块风险。"
```

机器事实或普通阶段事件用 `advance`。遇到用户明确退出，立即执行 `exit --reason "<自然语言>"`；退出不回滚业务文件，也不要求再次确认。

## 两条交付路径

- Full：Startup → Spec → Story → Construction → Quality → Delivery。适合行为尚需澄清、跨模块设计、公共接口、兼容性、安全、数据、共享状态或并发风险。
- Focused：Startup → Construction → Quality → Delivery。适合已定位缺陷、局部修改和评审意见修复。判断只看语义风险，不看行数或文件数；实现中出现上述风险就 `advance upgrade-to-full --decision "<依据>"`。

Full 的五个高价值用户介入点是 Startup、Spec、Story、CP 和 Delivery。Focused 只固定停 Startup 与 Delivery。其余只有真实歧义、设计偏离、Reviewer 取舍、不可逆风险或昂贵能力重试才找用户。每次给用户一张短卡：当前结论、影响、推荐选择和可直接自然语言修改的内容。

## 六个阶段

### Startup

阅读需求、仓库事实和初始脏文件，推荐 Full/Focused 与 Continuous/Staged。用户确认一次即可；不要求固定话术。

### Spec

Spec 只定义 WHAT：可观察行为、边界、失败语义、兼容性和非目标。Full 在呈审前调用 `grill-critic-agent` 做 one read-only pass；CLEAR 直接继续，只有真实待决分支交用户。Spec 位于 `docs/mae-flow/requirements/<ticket>/spec.md`。

### Story

Story 按 `skills/mae-flow/assets/STORY-TEMPLATE.md` 定义 HOW：代码落点、类/接口、依赖与数据流、错误和资源语义、CP、验证意图及可测性 seam。调用 `story-generator-agent` 一次，再调用 Design Reviewer 一次。普通意见直接修正；只有真实取舍交用户。Story 默认写本地 `.mae-flow-work/<ticket>/story.md`，用户明确要求纳入版本库时才选 durable 路径。

### Construction

按用户确认的 Story 或 Focused 范围完成业务代码。编码时就创建测试所需的生产语义 seam，把稳定框架编排与可变业务判断分开；CP 只累计自然语言 UT handoff，不正式写或跑 UT。

每个 CP 的 CODE Reviewer at most once per CP，只读本 CP diff 和直接集成边界，不形成复查循环。用 `advance cp-ready --key <CP>` 打开下一 CP，每个 CP 的用户确认独立保存。对本 CP 的 exact changed code 运行一次 `lightcheck --file <exact file>...`；安全、局部、高置信问题由主 Agent 顺手修，风险高或范围外的只记录，不为 Lightcheck 触发编译或再次检查。没有 exact scope 时 Lightcheck 直接 fail-open，不扫启动前用户现场。

### Quality

根据语义影响和用户选择决定质量能力。Full 的通常建议顺序是 CodeCheck → Build → UT，但用户可删减、改序或承担明确风险。

- CodeCheck：调用 `codecheck-advisor-agent` 一次，只给 exact changed production files/functions。它只请求一次正式 fullcheck。主 Agent修安全项；每条结构化意见都要有去向，raw-only 结果原样保留，不自动复验。
- Build：直接调用配置的 `build-fix` Skill 一次。该 Skill 对自己的编译负责；Mae-Flow 不再另派编译角色，也不猜内部 Maven/g++ 封装的输出。
- UT：调用 `ut-generator-agent` 一次。它拥有 write + compile + run，输入 final Spec、final Story（若有）、current diff 和 cumulative construction hints。Mae-Flow 不推断语言、测试框架、计数或 disabled 文案。

能力返回只记录 `returned | failed-to-start | timed-out | not-observed`：

```text
python "<插件目录>/scripts/mae-flow.py" capability-record <kind> <outcome> --source <语义上下文> --environment <环境上下文> --summary "<观察摘要>"
```

真正的 attempt slot 由 Mae-Flow 按当前阶段和 exact CP 派生；`--source/--environment` 是兼容性调用参数，改它们不会创建新 slot。Design Reviewer 和每个 CP Reviewer 是不同 slot。同 slot 不自动重试，不等待、不轮询、不转后台。确需再试，先记录用户自然语言决定 `capability.retry.<kind>`；下一次真实调用消费一次授权。

### Delivery

先展示 exact files、初始脏文件归属、质量观察、提交说明和目标分支。只暂存逐个文件，禁止目录、glob、`git add .` 或夹带 Mae-Flow 控制文件。
交付清单包含启动时已脏文件时，对每个文件使用 `--adopt-dirty "<file>=<用户自然语言归属决定>"`。Delivery 确认会绑定当前 exact manifest；manifest 改变后必须重新向用户展示。

- Continuous：最终一个 `[单号][feat|fix]描述` 提交，one final push。
- Staged：每个用户已确认 CP 先记录该 CP exact manifest 和提交说明，再做一个本地提交；同一文件可在后续 CP 继续演进。Delivery 记录所有 CP 的累计 union manifest，只做 one final push。

Spec/行为基线是长期真相源。Story、决策、工程笔记、Chain、Review/CodeCheck 台账和交付说明默认本地；只有用户明确点名该文件进入版本库，才通过 `--conditional-document <exact path>` 选择。

## Moonlight

Moonlight 是 Full/Focused 上的授权策略，不是另一套流程。用户明确开启时在 `start` 增加 `--moonlight`。只有用户同时点名 exact business files 并授权时，才记录 commit/push 权限；未形成精确 manifest、存在未归属脏文件、风险、能力异常或 push 失败时仍安全停下。

manifest 确定后，只有已启用 Moonlight 的流程可用 `--moonlight-refresh --allow-commit --allow-push --decision "<用户对当前 exact manifest 的自然语言授权>"` 刷新权限。条件文档仍必须独立点名。Moonlight 不允许强推、隐藏失败、删除测试或用重复调用碰运气。

## 独立工具箱

用户明确只要 UT、CodeCheck、Grill、Story 或 Chain 时，直接调用同名命令。它们是 one-shot，无流程状态、无交付副作用、无自动重试；停止使用就是结束。

## 不可破坏的交付行为

- Agent 只修改任务相关业务文件；用户已有脏文件保持可见，纳入交付前必须自然语言确认归属。
- 任何提交都使用 exact files 和原有 `[单号][feat|fix]描述` 格式；不提交 Mae-Flow 状态、本地过程目录或未点名条件文档。
- Reviewer 提供证据，不制造无休止反工；接受修复后不自动再派同一 Reviewer。
- Build/UT/CodeCheck 是工具箱能力。返回异常时说明事实和风险，让用户决定是否换环境、稍后再试或继续；流程本身不循环。
