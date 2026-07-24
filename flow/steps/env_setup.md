先执行 mae-flow envcheck 查看环境实测结果(✅/❌ 逐项)。
全部 ✅ → 直接 done(done 会再次实测,谎报无效;全绿结果缓存 24 小时,envcheck 命令始终全量实测)。
done 报"**环境有变更待生效**"(有 .mae-flow-need-reload 标记:装了插件/迁移了目录但会话没加载)→
  **不要派 agent、不要重装**。给用户两条路(最优先分流):
  ① **当前会话刷新**(不重启,更轻):请用户执行 /reload-skills(装了插件的再 /reload-plugins,若支持),
     用户**明确说一声**刷新好了后,你执行 `mae-flow reloaded --ack "用户原话"` 清标记 → current 继续;
  ② **重启会话**(SessionStart 自动清标记):回来说"继续"。
  两条都不行/技能仍报不存在 → 以重启为准。
有 ❌(非 reload 类)→ **三层分流,顺序固定**:
1. **先跑确定性安装器**(你直接执行,一条命令,不派 agent——装东西的活全在它里面,幂等可重跑):
   python "<插件scripts目录>/setup.py"
   (逐步输出 ✅/⚠人工/❌,完整日志在 %TEMP%\mae-flow-setup.log)
2. 安装器结果分流:
   - 全 ✅(退出码 0)→ done;
   - 有 **⚠人工项**(基础件缺失 / comet init 三要素 / 目录合并)→ 原样展示给用户,语气按
     "差一步手动操作"而非报错;用户处理完说"好了"→ **重跑安装器**,如此循环;
   - 有 **❌**(安装失败)→ 启动 env-setup-agent **诊断**(传入:❌ 项清单、日志路径
     %TEMP%\mae-flow-setup.log、插件 scripts 目录绝对路径)。它的职责是修环境参数后重跑安装器,
     不是自己装东西;READY → done,BLOCKED → 展示 PENDING_DECISIONS 等用户,处理完重启全新实例。
3. **禁止你手工逐项安装**(拼 npm/plugin 命令绕过安装器=不可复现,下一台机器继续炸);
   **comet init 你和子 agent 都严禁执行**(gate 硬拦,管道喂输入等变体同禁——非交互跑会把
   全部 agent 平台初始化出来污染仓库),安装器会给三要素(目录/命令/平台)话术,原样转给用户。
注意:检查项含「auto_transition 已关闭」和「review_mode=standard」——项目 `.comet/config.yaml`
  必须分别为 `auto_transition: false`、`review_mode: standard`，已有错误值由安装器自动纠正。
  安装器若修改全局 npm/Git 网络配置，会先在 `%TEMP%` 保存修改前备份并输出路径。
新手引导(首次使用大概率发生,不是故障):
- 首次全 ❌ 属正常,如实告知用户"首次初始化,自动安装约需几分钟";
- 安装器/agent 报告"完成 .claude → .cac 迁移"→ 告知用户执行 **/reload-skills**(会话内命令,谁都无法代跑)或重启会话;
- 报告"本次新装了插件"→ 告知用户**重启会话**,重启后说一声继续即可(current 自动回到断点,进度不丢)。
注意:done 的放行标准是"环境实测就绪",与谁跑了什么、怎么说的无关。
