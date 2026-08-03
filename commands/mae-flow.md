# /mae-flow:mae-flow

使用 Mae-Flow 时全程用简体中文，并遵循本命令随插件加载的 Mae-Flow Skill；
不得在业务仓中搜索插件的 `skills/`、`runtime/` 或 `flow/` 目录。

## CLI 入口

所有 Mae-Flow CLI 调用都必须使用：

```text
python ".mae-flow-work/bin/mae-flow.py" <command>
```

SessionStart 利用 Hook 中真实可用的 `CODEAGENT3_PLUGIN_ROOT` 在当前仓库生成该启动器。禁止猜测或搜索插件安装目录，禁止使用版本化缓存路径、`find`、`python -c`/`importlib`，或 Main Agent 中为空的插件根变量。启动器不存在时报告“Mae-Flow SessionStart 尚未生成项目启动器，请刷新插件后重开会话”并停止。

## 分流

- 无参数或需求描述：已有 `.mae-flow.json` 就执行完整 current 命令；没有状态时，先执行完整 start 命令持久化并展示完整配置卡。用户修改时执行完整 configure 命令并重新展示；用户对当前卡确认后执行完整 decision startup-confirmed 命令。不得把 start 中的 decision 参数当成未展示配置卡的确认。
- `exit`：立即执行带项目启动器前缀的完整 exit 命令。不再追问，不回滚业务文件。
- `ut|codecheck|grill|story`：执行同名 one-shot toolbox 命令；不启动完整流程，不提交，不推送。
- `chain` / 跨仓：Chain 是可恢复的跨仓流程；新任务执行完整 chain start 命令，存在 `.mae-flow-work/chain-current.json` 时执行完整 chain current 命令，不得退回 one-shot。
- `moonlight` / 月光宝盒：仍选择 Full 或 Focused，在 `start` 加 `--moonlight`。只有用户明确授权的 exact business files 才能附带 `--business-file`、`--allow-commit`、`--allow-push`。

## 主循环

每轮只做三件事：

1. 用完整 current 命令读取启动配置、相关领域、Startup / Spec / Story / Construction / Quality / Delivery 的当前上下文。
2. 完成当前阶段最有价值的工作。调用所选 Grill、Story、Reviewer、CodeCheck、Build、UT 能力时，同一相关上下文至多一次，返回只记观察事实。
3. 用带项目启动器前缀的完整 decision 或 advance 命令推进。

Full Spec 必须读取 `current` 输出的精确 `.mae-flow-work/plugin-resources/guidance/grill.md` 和 `.mae-flow-work/plugin-resources/assets/GRILL-PREP-TEMPLATE.md`，执行完整 Grill；禁止在业务仓搜索同名资源，也禁止读取已退休的旧步骤资源。在 current 输出的精确 Grill 目录写 `survey.md` 和八维 `grill-prep.md`，逐维形成候选题或带定位的不适用依据，再让问题树随每个答案生长。旧 Grill/Spec 文件只作历史线索；没有当前状态收据时不得当作本轮已确认内容。每题先用完整 `advance grill-question` 命令登记，再 AskUserQuestion；若答案先到，使用带相同元数据的完整 `decision grill-answer` 命令原子补登记并消费。全部候选题和衍生题关闭后才写精确 `grill.md`、收敛并生成含“Grill 决策追溯”的 `spec.md`，随后调用一次 `grill-critic-agent` 检查两份文件的输入覆盖。质询结果是 Spec 的关键输入，不能用只读 Critic 或 `grill-clear` 替代。Focused 发现未决需求时先升级 Full。

不要要求用户背命令或固定话术。用户直接改文字、边界、设计、CP、质量选择或交付清单时，更新产物并记录其语义决定；`UserPromptSubmit` 或 `AskUserQuestion` 回答只证明本轮有真实用户输入，不要求 CLI 参数逐字复制用户原话。

这些 CLI 是 Agent 内部协议，不要把它们展示成用户必须执行的操作。用户只需
使用 `/mae-flow:mae-flow` 并自然语言表达确认、修改、返修或退出。

## Chain 主循环

Chain 由主 Agent 直接持有。先收集完整仓列表和路径，不可读时建议 `/add-dir`；再按需求关键词、接口调用链、配置/路由三路只读检查每个仓。触点记录精确仓、文件、符号、原因和置信度。

跨仓决策必须携带证据、影响和推荐答案，一次只问一个，并关闭回答产生的派生分支。完成接口形态、字段、错误语义、依赖方向、可并行范围、合入顺序和联调时点后，反向检查每个仓能否凭启动卡独立开工。

内部生命周期全部使用带项目启动器前缀的完整 Chain 命令：start/current → record/question/answer → verify → 写精确本地 `chain.md` → rendered → 用户确认 → confirm。所有引用必须在确认前验证。Chain 不编辑业务代码、不启动任何仓的交付、不 commit/push；每个仓最终得到一张自包含启动卡。若回答先于问题登记到达，answer 命令携带 parent/evidence/impact/recommendation，原子补登记并消费。

## 用户介入

Full 固定展示 Startup、Spec、Story、CP、Delivery 五张短卡；Focused 固定展示 Startup、Delivery。普通 Reviewer CLEAR、能力正常返回和机械阶段切换不中断用户。真实歧义、设计偏离、不可逆风险、Reviewer 取舍和昂贵重试必须展示证据、影响与推荐答案。

## 质量与交付

- Full Design 先调 `story-generator-agent`，再调 `craft-reviewer-agent`（Design Reviewer 角色）；每个 Construction CP 调 `craft-reviewer-agent` 一次（CODE Reviewer 角色）。
- Construction 使用带项目启动器前缀的完整 lightcheck 命令检查一次精确本次代码；无 exact scope 就 fail-open，不扫用户启动前现场。每个 CP 在 Reviewer 意见处置后同步调用一次开局确认的 Build 路由；不休眠等待、不轮询、不转后台、不自动重试。
- 正式 CodeCheck 调 `codecheck-advisor-agent` 一次；UT 调 `ut-generator-agent`，由它完成 write/compile/run。Quality 复用最后一次仍覆盖最终源码的 CP Build，不机械重复编译。
- 调用前先查看完整 current 命令输出的当前语义 slot 已有尝试；同一 slot 无用户重试决定就不再次调用，新的阶段/CP slot 首次调用正常执行。每次真实能力调用同步结束后立即使用带项目启动器前缀的完整 advance 命令记录一次；记录失败不触发能力重跑。
- Delivery 前记录最终 Spec/Story/范围 ↔ 代码/覆盖自然语言结论；只有存在语义跨 CP 耦合时才追加一次集成 Reviewer。
- Continuous 使用一个最终提交和 one final push。
- Staged 当前 CP 完成 Reviewer、Lightcheck 和 Build 后，使用带项目启动器前缀的完整 manifest/advance/decision 命令形成只读提交计划、展示完成卡并消费确认。用户要求修改时用完整 decision cp-revise 命令撤销未执行收据。commit 被 Hook 观察后，用完整 advance cp-opened 命令进入下一批；Delivery 使用完整 final manifest 命令，然后 one final push。同一文件可跨 CP 重复。
- 启动时已脏文件进入 manifest 时，每个都传 `--adopt-dirty "<file>=<用户自然语言归属决定>"`。Moonlight refresh 只用于已启用流程，并带 `--decision "<当前 exact manifest 授权>"`。
- 条件文档只有用户明确要求入库时才传 `--conditional-document <exact path>`。
- Delivery 前用 `domain-new|domain-updated|domain-unchanged --key docs/specs/<domain>.md` 记录相关领域的最终当前真相动作；只有实际变化的领域文件进入 exact manifest。

任何能力失败或超时都不自动重启、不等待、不轮询。能力事实由工作流命令写入，Hook 不解析 Agent/Skill 返回。Attempt slot 由阶段和 current CP 派生，改 caller 的 source/environment 不会绕过。同一 slot 只有 state 中已有本轮 `capability.retry.<kind>` 自然语言决定才再次尝试；新的计划 slot 不叫重试。

Quality 发现源码问题时，用用户自然语言绑定 `quality-defect-repair`；Delivery
检视发现问题时绑定 `delivery-defect-repair`。两者都打开新的 repair CP，保留已经
完成的 Staged commit 历史，清除过期的最终质量/交付授权。流程已经 complete
时，用同一 Slash Command 发起新的后续修复轮次，不尝试修改终态状态。
