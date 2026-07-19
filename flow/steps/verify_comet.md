执行 /comet-verify 生成验证报告。comet 的「分支处理」决策点一律选**保持分支**——
合并/MR 由公司流程人工处理,推送在后面的 push 步统一做,禁止在此本地合并或创建 PR。
Spec 漂移等其余决策点照常展示、结束回复等用户裁决。裁决结果的两个去向:
- 判定 **spec 该改**(实现是对的)→ 经用户确认修订 delta spec 后重跑 comet-verify;
- 判定**代码该改**(实现偏了)→ 本步禁改源码不是死路:经用户确认 goto verify_ponytail --ack "用户原话",
  修复后重走 删→改→测→验(直接在本步改码会绕过 CodeCheck/UT,修复不被覆盖,禁止)。
comet-guard verify --apply 通过后 .comet.yaml 会写入 verify_result: pass,done 以此为证据,口头汇报无效。
展示验证结果摘要后 done。
