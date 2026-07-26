先执行 `python "{MAEFLOW_PATH}" spec phase verify` 把交付阶段推进到 verify
(full 单此时在 build 一跳即达;hotfix 轻量单仍在 open,该命令会机器代劳逐级推进)。
按下方内嵌的完成前验证、正确性审查和规格符合检查原文生成验证报告，不调用外部 Skill。
其中「分支处理」一律选**保持分支**——
合并/MR 由公司流程人工处理,推送在后面的 push 步统一做,禁止在此本地合并或创建 PR。
Spec 漂移等其余决策点用 AskUserQuestion 呈用户裁决(工具不可用才结束回复等纯文本),选项:
「spec 该改(实现是对的,修订后重验) / 代码该改(确认后回流完整质量链) / 其他」。
裁决结果的两个固定去向:
- 判定 **spec 该改**(实现是对的)→ 经用户确认修订规格条目(change.md;在途旧布局单为 delta spec)后重做本步验证;
- 判定**代码该改**(实现偏了)→ 本步禁改源码不是死路:经用户确认 goto verify_ponytail --ack "用户原话",
  修复后重走 删→改→测→验(直接在本步改码会绕过 CodeCheck/UT,修复不被覆盖,禁止)。
报告完成后一条命令登记并推进状态（--report 等价于先 set verification_report）：

`python "{MAEFLOW_PATH}" spec verify-pass --report "<验证报告路径>"`

它不是口头声明:硬校验「阶段已在 verify」+「报告文件真实存在」+「实现清单全部完成」,
三者齐备才写入 `verify_result: pass` 并把阶段推进到 archive,done 以此为证据。
编译、CodeCheck、UT 的真实证据由前面各步分别提供,本步不重复执行项目验证命令。
展示验证结果摘要后 done。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:verify}}
