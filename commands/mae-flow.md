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

不要要求用户背命令或固定话术。用户直接改文字、边界、设计、CP、质量选择或交付清单时，更新产物并记录其自然语言决定。

## 用户介入

Full 固定展示 Startup、Spec、Story、CP、Delivery 五张短卡；Focused 固定展示 Startup、Delivery。普通 Reviewer CLEAR、能力正常返回和机械阶段切换不中断用户。真实歧义、设计偏离、不可逆风险、Reviewer 取舍和昂贵重试必须展示证据、影响与推荐答案。

## 质量与交付

- Construction 对 changed code 运行一次 `lightcheck`，主 Agent顺手修安全项；它不是门禁，也不触发 Build 或复查。
- 正式 CodeCheck 调 `codecheck-advisor-agent` 一次；Build 直接调 `build-fix`；UT 调 `ut-generator-agent`，由它完成 write/compile/run。
- Continuous 使用一个最终提交和 one final push。
- Staged 每个已确认 CP 用 `manifest --checkpoint <CP> --file <exact files>... --commit-message "[单号][feat|fix]描述" --decision "<用户检视>"` 后本地提交；Delivery 用 `manifest --final --file <累计 union>...`，然后 one final push。同一文件可跨 CP 重复。
- 条件文档只有用户明确要求入库时才传 `--conditional-document <exact path>`。

任何能力失败或超时都不自动重启、不等待、不轮询。先报告事实；只有 state 中已有本轮 `capability.retry.<kind>` 自然语言决定，才进行同上下文下一次尝试。
