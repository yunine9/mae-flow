先把交付阶段推进到 verify(轻量单一条命令,机器代劳逐级推进):

`python "{MAEFLOW_PATH}" spec phase verify`

然后按下方内嵌方法做一次与“小改”相称的最终核对，不扩大成全仓走读：

1. 逐条对照本 change 的 change.md（「# 为什么」与「# 实现清单」;在途旧布局单为 proposal/tasks）和用户确认过的范围，检查有没有漏做、做偏或顺手增加需求；
2. 查看最终 diff，确认异常路径、兼容性和已有行为没有被无意改变；
3. 把结论写入 `.mae-flow-work/verification-{CHANGE_NAME}.md`；
4. 登记并完成状态(一条命令,--report 等价于先 set verification_report)：

```text
python "{MAEFLOW_PATH}" spec verify-pass --report ".mae-flow-work/verification-{CHANGE_NAME}.md"
```

发现实现问题时不要在这里偷改：回到 `tw_change` 修复，之后重新走编译、CodeCheck、UT 和本检查。
verify-pass 会硬校验阶段、报告文件与实现清单，三者齐备才写入 `verify_result: pass`；写入后再 done。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:verify}}
