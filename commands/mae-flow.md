# /mae-flow:mae-flow

使用 Mae-Flow 时全程用简体中文，并先读取 `skills/mae-flow/SKILL.md`。

## 分流

- 无参数或需求描述：已有 `.mae-flow.json` 就执行 `python "<插件>/scripts/mae-flow.py" current`；没有状态时，分析语义风险并向用户展示 Full/Focused 与 Continuous/Staged 推荐卡，确认后执行 `start`。
- `exit`：立即执行 `exit --reason "用户选择直接开发"`。不再追问，不回滚业务文件。
- `ut|codecheck|grill|story|chain`：执行同名 one-shot toolbox 命令；不启动完整流程，不提交，不推送。
- `moonlight` / 月光宝盒：仍选择 Full 或 Focused，在 `start` 加 `--moonlight`。只有用户明确授权的 exact business files 才能附带 `--business-file`、`--allow-commit`、`--allow-push`。

## 主循环

每轮只做三件事：

1. `current` 读取 Startup / Spec / Story / Construction / Quality / Delivery 的当前上下文。
2. 完成当前阶段最有价值的工作。调用所选 Grill、Story、Reviewer、CodeCheck、Build、UT 能力时，同一相关上下文至多一次，返回只记观察事实。
3. 用 `decision <event> "<用户自然语言>"` 或 `advance <event> --decision "<事实或依据>"` 推进。

不要要求用户背命令或固定话术。用户直接改文字、边界、设计、CP、质量选择或交付清单时，更新产物并记录其语义决定；`UserPromptSubmit` 只证明本轮有真实用户输入，不要求 CLI 参数逐字复制用户原话。

## 用户介入

Full 固定展示 Startup、Spec、Story、CP、Delivery 五张短卡；Focused 固定展示 Startup、Delivery。普通 Reviewer CLEAR、能力正常返回和机械阶段切换不中断用户。真实歧义、设计偏离、不可逆风险、Reviewer 取舍和昂贵重试必须展示证据、影响与推荐答案。

## 质量与交付

- Full Design 先调 `story-generator-agent`，再调 `craft-reviewer-agent`（Design Reviewer 角色）；每个 Construction CP 调 `craft-reviewer-agent` 一次（CODE Reviewer 角色）。
- Construction 用 `lightcheck --file <exact changed file>...` 检查一次精确本次代码，主 Agent顺手修安全项；无 exact scope 就 fail-open，不扫用户启动前现场，也不触发 Build 或复查。
- 正式 CodeCheck 调 `codecheck-advisor-agent` 一次；Build 直接调 `build-fix`；UT 调 `ut-generator-agent`，由它完成 write/compile/run。
- 调用前先查看 `current` 的已有尝试；同 kind 已有记录且没有本轮用户重试决定就不调用。每次真实能力调用同步结束后立即记录一次：`advance capability-returned --key <kind> --decision "<简短不透明摘要>"`；启动失败、超时或无法观察返回时换用对应的 `capability-failed-to-start`、`capability-timed-out`、`capability-not-observed`。记录失败不触发能力重跑。
- Continuous 使用一个最终提交和 one final push。
- Staged 用 `advance cp-ready --key <CP>` 打开新 CP，当前 CP 独立确认后才用 `manifest --checkpoint <CP> --file <exact files>... --commit-message "[单号][feat|fix]描述" --decision "<用户检视>"` 本地提交；Delivery 用 `manifest --final --file <累计 union>...`，然后 one final push。同一文件可跨 CP 重复。
- 启动时已脏文件进入 manifest 时，每个都传 `--adopt-dirty "<file>=<用户自然语言归属决定>"`。Moonlight refresh 只用于已启用流程，并带 `--decision "<当前 exact manifest 授权>"`。
- 条件文档只有用户明确要求入库时才传 `--conditional-document <exact path>`。

任何能力失败或超时都不自动重启、不等待、不轮询。能力事实由工作流命令写入，Hook 不解析 Agent/Skill 返回。Attempt slot 由阶段和 current CP 派生，改 caller 的 source/environment 不会绕过。只有 state 中已有本轮 `capability.retry.<kind>` 自然语言决定，才进行同 slot 下一次尝试。
