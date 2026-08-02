# Mae-Flow 更新记录

高效率、高质量；在需要人介入时聪明地让人介入。

## 2026-08-02：Lean operating model

本次发布只保留 Full 与 Focused 两条路径，以及 Intake → Spec → Design → Construction → Quality → Delivery 六阶段。路径由语义风险决定，不使用文件数或行数阈值；Focused 发现真实语义风险时升级 Full/Spec。

用户停点收敛为：Full 的 Startup、Spec、Story、每个 CP、Delivery；Focused 的 Startup、Delivery；歧义、设计偏差、用户级 Reviewer 取舍、昂贵能力再次调用、不可逆动作和 manifest 变化按需找人。

Build、UT、CodeCheck、Grill、Story、Reviewer 现在统一为一次性 opaque capabilities。Host 同步返回即完成，不解析私有输出，不后台等待，不自动重试；结果随恢复状态复用。

状态与平台边界同步收口：

- 生产只有 `SessionStart`、`UserPromptSubmit`、`PreToolUse`、`PostToolUse` 四个 Hooks，Host Hook 是唯一写者；
- Story 和其他条件文档默认保留在本地，用户明确选择后才进入 exact manifest；
- Git 交付使用逐文件 manifest 和 `[ticket][feat|fix]description`；
- Moonlight 使用精确文件与 commit/push 预授权，同时保留透明 Delivery 卡；
- Windows 发布覆盖 drive、UNC、反斜杠、大小写、UTF-8 BOM、GB18030、CRLF、有界锁冲突、`python` command discovery 和同步 capability return；
- CI 在真实 Windows 与 Ubuntu runner 运行，无需公司私有工具。

新增 `test_lean_semantic_scenarios.py` 与 `test_windows_lean_runtime.py`，并加入 exact release contract。

## 历史发布（非当前操作指南）

以下内容只以过去式记录迁移背景，不构成当前操作说明。

- 早期版本曾提供 Hotfix、Tweak 和 Review 模式；这些入口后来被 Full/Focused 取代。
- 早期版本曾要求 exact ACK、任务卡、evidence ledger 与 archive command，并把多轮质量动作串成反复质量链；这些机制后来从当前 operating model 移除。
- 早期版本曾把多种走读与质量动作建成长期状态；当前版本改为一次性 opaque capability 与最小恢复游标。
