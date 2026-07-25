执行 `python "{MAEFLOW_PATH}" spec archive`：
内置引擎按 ADDED/MODIFIED/REMOVED/RENAMED 语义把规格条目(change.md;在途旧布局单为 delta spec)
合并进真相源，并把 change 目录**移动**至 archive/(v5 单目录里只有一个 change.md,即"只移一个文件")；
不调用外部 Skill 或全局 CLI。
**收尾自查**(done 前):openspec/changes/{CHANGE_NAME}/ 原目录必须已消失(残留=假归档,会变僵尸,done 硬证据会拦)。
git commit -m "[单号][类型]归档 spec 变更"(本步提交只涉及 openspec/,禁止顺手 add 其他目录/宽 add)。
tweak/无 spec 变更**也要定稿**(定稿会移动变更目录,避免在建区残留干扰后续单);
仅用户明确弃单时才 skip --reason,并提醒用户该 change 将保持活跃。

──── 本步骤内嵌方法原文（已固定版本） ────
{{CAPABILITY_PACK:archive}}
