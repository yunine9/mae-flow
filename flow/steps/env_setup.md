先执行 mae-flow envcheck 查看环境实测结果(✅/❌ 逐项)。
全部 ✅ → 直接 done(done 会再次实测,谎报无效;全绿结果缓存 24 小时,envcheck 命令始终全量实测)。
有 ❌ → 启动 env-setup-agent(契约见 agents/env-setup-agent.md)修复:
  传入:失败项清单 + **插件 scripts 目录的绝对路径**(就是你执行 mae-flow.py 的那个目录,
  agent 在项目树里搜不到插件,必须由你传);
  **修复动作(安装/配置)一律由 env-setup-agent 执行,禁止在主会话直接动手**(污染主上下文,违背 offload 设计);
  agent 返回 READY → done;返回 BLOCKED → 展示未通过项与 PENDING_DECISIONS,结束回复等用户处理。
  用户处理完回来 → **重新启动一个全新的 env-setup-agent**(子 agent 无状态,步骤幂等,
  新实例会基于磁盘现状跳过已就绪项、接着装剩下的),如此循环直至 READY。
注意:检查项含「auto_transition 已关闭」——项目 .comet/config.yaml 必须含 auto_transition: false,
  由 mae-flow 独占流程节奏,禁止 comet 阶段间自动衔接(该文件缺失时由 env-setup-agent 创建)。
新手引导(首次使用大概率发生,不是故障):
- 首次全 ❌ 属正常,如实告知用户"首次初始化,自动安装约需几分钟";
- comet init 是交互式命令,**你和子 agent 都严禁执行**(gate 硬拦,echo/yes 管道喂输入等变体同禁——
  非交互跑会把全部 agent 平台初始化出来污染仓库):BLOCKED 时把三要素完整贴给用户
  (①执行目录=项目根绝对路径 ②命令原文 ③平台只选 Claude Code),语气按"差一步手动操作"而非报错;
- agent 报告"完成 .claude → .cac 迁移"→ 告知用户执行 **/reload-skills**(会话内命令,你和子 agent 都无法代跑)或重启会话;
- agent 报告"本次新装了插件"→ 告知用户**重启会话**,重启后说一声继续即可(current 自动回到断点,进度不丢)。
注意:done 的放行标准是"环境实测就绪",与 agent 跑没跑、怎么说的无关。
