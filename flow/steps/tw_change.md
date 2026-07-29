按编码前确认的 CP 顺序实现改动。分阶段模式在 CP 内保持代码未提交；一次完成模式仍小步提交。每个检查点完成后执行
`python "{MAEFLOW_PATH}" agent-task compile --checkpoint CPn --scope "<本批范围>"`，
compile-agent OK 后执行 `checkpoint ready CPn`。
分阶段模式先让用户在 IDE 检视未提交 diff，确认后按输出精确 commit、普通 push，并用
`checkpoint status` 核对提交内容与检视快照完全一致；一次完成模式会直接记录范围并进入下一批。
全部检查点闭环后再 done。
done 不再只看“最新提交长得像不像”，而是确认本步骤之后确实产生了新提交；随后自动进入独立编译步骤。
纯文案改动会由下一步机器判断为无需编译；涉及源码、测试或构建文件时必须由 compile-agent 编译。
实现中发现超出 tweak 范围(触发升级条件)→ 停手展示原因,等用户确认后 goto design --force；状态机会同步转为 full 流程及 design 规格阶段。

写码时直接执行下方已经内嵌的最小实现与系统化调试规则，不调用外部 Skill。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:tweak-build}}
