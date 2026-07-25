先执行 `python "{MAEFLOW_PATH}" capability comet-state -- check "{CHANGE_NAME}" verify`。
按下方内嵌的完成前验证、正确性审查和规格符合检查原文生成验证报告，不调用外部 Skill。
其中「分支处理」一律选**保持分支**——
合并/MR 由公司流程人工处理,推送在后面的 push 步统一做,禁止在此本地合并或创建 PR。
Spec 漂移等其余决策点照常展示、结束回复等用户裁决。裁决结果的两个去向:
- 判定 **spec 该改**(实现是对的)→ 经用户确认修订 delta spec 后重跑 comet-verify;
- 判定**代码该改**(实现偏了)→ 本步禁改源码不是死路:经用户确认 goto verify_ponytail --ack "用户原话",
  修复后重走 删→改→测→验(直接在本步改码会绕过 CodeCheck/UT,修复不被覆盖,禁止)。
报告完成后登记报告路径与分支处理结果，再推进状态：

1. `python "{MAEFLOW_PATH}" capability comet-state -- set "{CHANGE_NAME}" verification_report "<验证报告路径>"`
2. `python "{MAEFLOW_PATH}" capability comet-state -- set "{CHANGE_NAME}" branch_status handled`
3. `python "{MAEFLOW_PATH}" capability comet-state -- transition "{CHANGE_NAME}" verify-pass`

前面的 Mae-Flow 编译、CodeCheck、UT 与本步报告已经分别提供真实证据，因此第 3 条只推进内嵌状态，
不再重复执行项目验证命令。完成后 `.comet.yaml` 会写入 `verify_result: pass`，done 以此为证据。
展示验证结果摘要后 done。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:verify}}
