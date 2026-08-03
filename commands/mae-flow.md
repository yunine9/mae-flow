# /mae-flow:mae-flow

使用 Mae-Flow 时全程用简体中文，并先读取 `skills/mae-flow/SKILL.md`。

## CLI 入口

所有 Mae-Flow CLI 调用都必须使用：

```text
python "${CODEAGENT3_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/mae-flow.py" <command>
```

下文省略入口的命令名只是协议后缀，不能脱离上述入口直接执行。禁止猜测或搜索插件安装目录；禁止使用旧式 skill 目录、版本化缓存路径或 `find` 定位入口。两个插件根变量都不可用时，报告“插件根目录环境变量缺失”并停止，不执行目录扫描。

## 分流

- 无参数或需求描述：已有 `.mae-flow.json` 就执行 `python "${CODEAGENT3_PLUGIN_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/mae-flow.py" current`；没有状态时，读取仓库预设和相关领域基线，向用户展示唯一一次完整配置卡。Build 必须按项目确认精确路由：C++ 可用配置的 `build-fix` Skill，Java/Maven 用确认的 Maven 命令，其他语言用仓库准确 Skill/命令。用户自然语言确认或修改后，一次执行 `start --ticket <单号> --ticket-type <feat|fix> --worker <工号> --requirement <需求来源> --base-branch <基线> --working-branch <工作分支> --build-method <精确Build路由> --ut-method <UT生成> --ut-command <UT入口> --quality-plan <自然语言质量组合> --path <full|focused> --pace <continuous|staged> --decision "<用户对完整配置卡的自然语言确认>"`；该命令创建/切换到确认的工作分支，原子记录 Startup 确认并进入下一阶段，不再重复询问。
- `exit`：立即执行 `exit --reason "用户选择直接开发"`。不再追问，不回滚业务文件。
- `ut|codecheck|grill|story|chain`：执行同名 one-shot toolbox 命令；不启动完整流程，不提交，不推送。
- `moonlight` / 月光宝盒：仍选择 Full 或 Focused，在 `start` 加 `--moonlight`。只有用户明确授权的 exact business files 才能附带 `--business-file`、`--allow-commit`、`--allow-push`。

## 主循环

每轮只做三件事：

1. `current` 读取完整启动配置、相关领域、Startup / Spec / Story / Construction / Quality / Delivery 的当前上下文。
2. 完成当前阶段最有价值的工作。调用所选 Grill、Story、Reviewer、CodeCheck、Build、UT 能力时，同一相关上下文至多一次，返回只记观察事实。
3. 用 `decision <event> "<用户自然语言>"` 或 `advance <event> --decision "<事实或依据>"` 推进。

Full Spec 必须先逐题执行 Interactive Grill，把质询树和确认结果写入本地 `grill.md`；全部收敛后才生成含“Grill 决策追溯”的 `spec.md`，随后调用一次 `grill-critic-agent` 检查两份文件的输入覆盖。质询结果是 Spec 的关键输入，不能用只读 Critic 或 `grill-clear` 替代。Focused 发现未决需求时先升级 Full。

不要要求用户背命令或固定话术。用户直接改文字、边界、设计、CP、质量选择或交付清单时，更新产物并记录其语义决定；`UserPromptSubmit` 或 `AskUserQuestion` 回答只证明本轮有真实用户输入，不要求 CLI 参数逐字复制用户原话。

这些 CLI 是 Agent 内部协议，不要把它们展示成用户必须执行的操作。用户只需
使用 `/mae-flow:mae-flow` 并自然语言表达确认、修改、返修或退出。

## 用户介入

Full 固定展示 Startup、Spec、Story、CP、Delivery 五张短卡；Focused 固定展示 Startup、Delivery。普通 Reviewer CLEAR、能力正常返回和机械阶段切换不中断用户。真实歧义、设计偏离、不可逆风险、Reviewer 取舍和昂贵重试必须展示证据、影响与推荐答案。

## 质量与交付

- Full Design 先调 `story-generator-agent`，再调 `craft-reviewer-agent`（Design Reviewer 角色）；每个 Construction CP 调 `craft-reviewer-agent` 一次（CODE Reviewer 角色）。
- Construction 用 `lightcheck --file <exact changed file>...` 检查一次精确本次代码，主 Agent顺手修安全项；无 exact scope 就 fail-open，不扫用户启动前现场。每个 CP 在 Reviewer 意见处置后同步调用一次开局确认的 Build 路由；不休眠等待、不轮询、不转后台、不自动重试。
- 正式 CodeCheck 调 `codecheck-advisor-agent` 一次；UT 调 `ut-generator-agent`，由它完成 write/compile/run。Quality 复用最后一次仍覆盖最终源码的 CP Build，不机械重复编译。
- 调用前先查看 `current` 的当前语义 slot 已有尝试；同一 slot 无用户重试决定就不再次调用，新的阶段/CP slot 首次调用正常执行。每次真实能力调用同步结束后立即记录一次：`advance capability-returned --key <kind> --decision "<简短不透明摘要>"`；启动失败、超时或无法观察返回时换用对应的 `capability-failed-to-start`、`capability-timed-out`、`capability-not-observed`。记录失败不触发能力重跑。
- Delivery 前记录最终 Spec/Story/范围 ↔ 代码/覆盖自然语言结论；只有存在语义跨 CP 耦合时才追加一次集成 Reviewer。
- Continuous 使用一个最终提交和 one final push。
- Staged 当前 CP 完成 Reviewer、Lightcheck 和 Build 后，先用 `manifest --checkpoint <当前CP> --file <exact files>... --commit-message "[单号][已确认类型]描述"` 形成只读提交计划，再用 `advance cp-ready --key <当前CP>` 展示完成卡。用户确认时执行 `decision cp-confirmed`，随后才做 exact add/commit；用户要求修改时执行 `decision cp-revise` 撤销未执行收据，修改并重新 Build/呈审。commit 被 Hook 观察后，用 `advance cp-opened --key <下一CP>` 进入下一批，该事件不打断用户。Delivery 用 `manifest --final --file <累计 union>...`，然后 one final push。同一文件可跨 CP 重复。
- 启动时已脏文件进入 manifest 时，每个都传 `--adopt-dirty "<file>=<用户自然语言归属决定>"`。Moonlight refresh 只用于已启用流程，并带 `--decision "<当前 exact manifest 授权>"`。
- 条件文档只有用户明确要求入库时才传 `--conditional-document <exact path>`。
- Delivery 前用 `domain-new|domain-updated|domain-unchanged --key docs/specs/<domain>.md` 记录相关领域的最终当前真相动作；只有实际变化的领域文件进入 exact manifest。

任何能力失败或超时都不自动重启、不等待、不轮询。能力事实由工作流命令写入，Hook 不解析 Agent/Skill 返回。Attempt slot 由阶段和 current CP 派生，改 caller 的 source/environment 不会绕过。同一 slot 只有 state 中已有本轮 `capability.retry.<kind>` 自然语言决定才再次尝试；新的计划 slot 不叫重试。

Quality 发现源码问题时，用用户自然语言绑定 `quality-defect-repair`；Delivery
检视发现问题时绑定 `delivery-defect-repair`。两者都打开新的 repair CP，保留已经
完成的 Staged commit 历史，清除过期的最终质量/交付授权。流程已经 complete
时，用同一 Slash Command 发起新的后续修复轮次，不尝试修改终态状态。
