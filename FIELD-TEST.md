# Mae-Flow 现场验证

高效率、高质量；在需要人介入时聪明地让人介入。

本清单验证当前 Full/Focused 模型和唯一阶段序列 Intake → Spec → Design → Construction → Quality → Delivery。使用一次性 fake Host capability，不调用真实内部 Build、UT 或 CodeCheck；所有 Git 副作用在一次性演练仓和本地 fake remote 完成。

## 0. 环境记录

- [ ] Windows 版本、CodeAgent 版本和 `python --version` 已记录。
- [ ] 演练仓路径至少包含空格和中文；另准备一个 drive path 与一个可访问的 UNC fixture。
- [ ] `git status --short` 的初始结果已保存，包含一个明确“不采用”的脏文件。
- [ ] Host 可向 Hook 发送 UTF-8 BOM JSON、GB18030 UserPromptSubmit 和普通 UTF-8 payload。
- [ ] capability fake 会同步返回 `returned`、`failed-to-start`、`timed-out`、`not-observed`，且不会启动内部工具。

## 1. Full 场景

### 1.1 small Full

- [ ] 一个只改少量业务行为的需求可以由用户选择 Full；界面没有用文件数或行数劝退。
- [ ] Intake 展示路径、范围、提交节奏和初始脏文件归属，普通自然语言即可确认。
- [ ] Spec 只固定 WHAT；Grill fake 只调用一次，不透明返回后停在 Spec 用户卡。
- [ ] Design 只固定 HOW、可测性和 CP；Story/Reviewer fake 各只调用一次，不透明返回后停在 Design 用户卡。
- [ ] 每个 CP 只出现一次用户检视；普通进度不会增加停点。
- [ ] Quality 不重复先前能力，Delivery 展示精确文件、提交说明和推送选择。

### 1.2 complex Full

- [ ] 至少三个 CP 依次可见，CP1 未确认时不能静默打开 CP2。
- [ ] 跨 CP 接口/共享状态集成会记录原因，但已明确的工作不会额外找人签字。
- [ ] 真实歧义或有意义的设计偏差会停下，并保留可恢复风险事实。
- [ ] 会话重启后 `SessionStart` 只注入当前阶段、CP、关键产物、风险和最后一次 capability；不回放长历史。

## 2. Focused review-fix

- [ ] Focused 只有 Intake 与 Delivery 两个固定停点，启动时不声明 Spec、Story 或 UT handoff。
- [ ] Reviewer/CodeCheck 的未知输出原样作为 opaque summary 保存，不解析成 clean/fail。
- [ ] 首次调用后，源码 revision、阶段、CP 或环境变化都不自动产生新调用；当前用户决定绑定新 slot 后才能再次调用。
- [ ] 若评审揭示接口、兼容性、数据、安全、共享状态或并发风险，记录自然语言原因并升级 Full/Spec。

## 3. Capability 边界

- [ ] Build fake 的同步 success、failure、timeout 各产生一条事实；Host 返回后没有后台任务。
- [ ] 同一 Build context 的第二次调用被阻止并要求用户选择；没有自动重试。
- [ ] 弱 C++/gtest UT fake 无法证明执行数量时，系统只报告观察到的返回，不编造通过。
- [ ] unknown CodeCheck payload 含未来字段、数字和 `PASS` 文本时，系统不推断 verdict。
- [ ] 恢复后复用已保存的 capability result，不再次调用 fake Host。

## 4. 文档与工作区

- [ ] Spec、Story、决策和工程说明按同一需求分组。
- [ ] Story 和其他条件文档默认保留在本地；仅当用户明确选择入库时加入 manifest。
- [ ] 未采用的初始脏文件可以留在工作区，但不会进入自动 Delivery。
- [ ] 用户采用的初始脏文件同时出现在 adoption facts 和 exact manifest。
- [ ] 损坏恢复状态不会被覆盖；普通开发 fail-open，明确退出仍保存坏现场并释放控制。

## 5. Git 与 Moonlight

- [ ] manifest 逐文件展示；反斜杠/大小写别名不能生成重复文件。
- [ ] 暂存结果必须与 manifest 完全相等，额外文件或缺少文件都拒绝。
- [ ] 提交说明匹配 `[ticket][feat|fix]description`。
- [ ] Continuous 只有一个最终提交；Staged 的 CP manifests 并集恰好等于最终 manifest；最终只推送一次。
- [ ] Moonlight 只对用户点名的业务文件和 commit/push 布尔值生效。
- [ ] 未点名条件文档、manifest 变化、能力失败、未拥有脏文件和 push 失败会安全停下。
- [ ] Moonlight 下 Delivery 卡仍完整显示精确文件与副作用。

## 6. 生产 Hook 边界

- [ ] `SessionStart`：每会话最多一次最小恢复摘要。
- [ ] `UserPromptSubmit`：原始自然语言与扩展字段保留；明确 exit 原子保存现场。
- [ ] `PreToolUse`：危险动作在副作用前裁决；`WriteStdin` 复用会话被阻止；不会为能力调用预留等待中的 slot。
- [ ] `PostToolUse`：只记录已授权 Git 副作用，不解析 Agent/Skill 返回。
- [ ] `SubagentStop`、`Stop` 保持兼容注册并直接放行，不恢复旧状态机。
- [ ] 真实 capability 同步返回后，主 Agent 用一次 `advance capability-<outcome> --key <kind>` 保存轻量事实；记录失败不重跑能力。
- [ ] 工作流命令与 Hook 写入都通过项目锁串行，没有丢失更新。

## 7. Windows 专项

- [ ] drive、UNC、反斜杠、大小写 identity 与保留名称均按 Windows 语义处理。
- [ ] UTF-8 BOM 状态可读，GB18030 Hook 中文不损坏，CRLF phase resource 正常渲染。
- [ ] 模拟杀软锁住 replace/delete 时，达到固定 attempt 上限后返回，不无限等待。
- [ ] 所有发布命令通过 `python` 发现；没有依赖其他解释器命令名。
- [ ] 同步 fake capability subprocess 在正常返回和短 timeout 两端都可控，不依赖 POSIX signal。

## 8. 发布检查

```text
python scripts/tests/test_lean_semantic_scenarios.py
python scripts/tests/test_windows_lean_runtime.py
python -m unittest discover -s scripts/tests -p 'test_*.py'
python scripts/selftest.py
git diff --check
```

- [ ] 两套 targeted suites 通过。
- [ ] discover 只运行一次并通过。
- [ ] selftest 只运行一次并通过，包含全部注册 suite。
- [ ] `git diff --check` 无输出。
- [ ] 除本次批准文件外没有意外变化。
