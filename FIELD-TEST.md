# 公司 Windows 实机测试清单(2026-07-20)

目的:插件从"macOS 沙箱实证"到"实战可信"的最后一公里。按序执行,每项记录 现象/日志/结论;
发现问题记三元组:现象 + hook 日志片段 + 所在步骤。**验收线:整单 gate 误拦次数应为个位数。**

## 阶段 0 — 开机金丝雀(约 15 分钟,全部通过才进阶段 1)

- [ ] **0.1 hook 存活**:启动会话发一条消息,开 `%TEMP%\mae-flow-hook.log`:
  - start/end 成对、耗时几十 ms 级 → 通过;
  - 文件不存在 → harness 不支持 exec form:把 hooks.json 五个 hook 的 `"command"+"args"` 改回
    shell form(`python "${CODEAGENT3_PLUGIN_ROOT}/hooks/dispatch.py" <事件>`),重启会话再测;
  - 有 start 无 end / WATCHDOG 行 → 有挂起,收集日志全文发维护人,暂停实测。
- [ ] **0.2 PostToolUse-Bash 延迟**:让 AI 连跑几条 Bash 命令,看日志里 posttooluse 的耗时与频度
  (Windows python 冷启动 + 杀软扫描可能放大)。不可接受 → 待办:把 UTRUN 检测收窄到 verify_ut 步。
- [ ] **0.3 payload 字段三查**(决定三个机制的激活/降级状态):
  - UserPromptSubmit 有无 `prompt` 字段:开单后发条消息,`mae-flow doctor` 看「ack 验真存储」条数(>0 = 激活);
  - AskUserQuestion 有无 `tool_response`:任一确认点弹框后,doctor 存储条数是否 +1(记录了应答);
  - **子 agent 的 Bash 是否触发 PostToolUse**:跑过 UT 后 doctor 看 UTRUN 行。**是 → 回头在
    flow.json 的 verify_ut evidence 加一行 `{"type":"agent_ran","agent":"UTRUN"}` 转硬证据**;否 → 保持观测。
- [ ] **0.4 statusline**:状态栏是否常驻"单号│步骤(中文标题)│分支";顺带看 statusline 收到的 JSON
  是否带上下文用量字段(有 → 立"水位仪表"待办)。
- [ ] **0.5 编码底线**:确认中文 Windows 控制台下 current/done 输出无乱码不炸(✅/emoji 显示为 ? 可接受)。
- [ ] **0.7 子 agent 尸检观测**(Skill 可用性已确认 ✓ 2026-07-20):下一次任何子 agent"奇怪退出"时,
  看 `%TEMP%\mae-flow-agent-autopsy.log` 是否留下了尸检(轮数/临终输出/报错特征),打回消息里是否附了
  「尸检线索」——把那份尸检发维护人,弱模型自行了断 vs maxTurns 硬切 vs API 中断,一看便知。
  **轮次预算校准**(2026-07-20 实锤:UT agent 25 轮烧完仍在读文件,已调 UT=200/compile=100/codecheck=100):
  观察调后 UT agent 实际用多少轮收尾(尸检/日志 query_depth),200 不够或严重富余都回报,下版校准。
- [ ] **0.6 五事件实弹确认(hook 数据真到手的判定,~10 分钟)**——fail-open 设计下 payload 丢失不报错只降级,
  必须逐事件看"数据依赖行为"真实发生,日志干净不算数:
  - **PreToolUse**:流程未初始化时让 AI"在 src/ 下随便加一行"→ 必须被拦并提示先走流程(拦了=tool_input 到手);
  - **PostToolUse·A**:让 AI 写一个只有一章的 `docs/grill-prep-TEST.md` → 必须被打回"缺少章节"(测完删文件);
  - **UserPromptSubmit**:开单后随便发条消息,`mae-flow doctor` 看「ack 验真存储」≥1 条(=prompt 字段到手);
  - **PostToolUse·B**:任一确认点弹框选择后,让 AI 展示 `.mae-flow.json.tokens`(读不拦)→ 有 ASKUSER 条目且带 head;
  - **SubagentStop**:首单环境步派过 env-setup-agent 后,tokens 里出现 ENV 条目(=transcript 定位与契约校验活着);
  - **SessionStart**:重启会话,开场自动出现"存在进行中的交付流程"提示。
  加分项(最强确认,防线不但活着还咬人):在 story/定稿步故意不弹框直接让 AI done → 应被 ASKUSER 证据拒绝。

## 阶段 1 — 首单实跑校准(半天,选一个小需求,建议 小改快过/缺陷快修)

- [ ] **1.1 环境初始化链(新三层:安装器→诊断 agent→人工三要素)**:
  - 首选路径:终端直接跑 `python "<插件>/scripts/setup.py"`(会话外也行),看逐步 ✅/⚠/❌ 与汇总;
    幂等验证:连跑两遍,第二遍应全 ✅ 秒过;
  - **profile 校准**:安装失败先核对 `assets/env-profile.json` 的镜像/代理/插件命令与公司实际是否一致——
    对不上改这一个文件,不改代码;
  - ⚠人工项话术:comet init 三要素(目录/命令/平台)是否复制即用;处理完重跑安装器能续上;
  - ❌ 项:AI 派 env-setup-agent 诊断(它应重跑 setup.py 验证,而不是自己拼命令装);
  - **gate 验证**:让 AI 试跑 `comet init` 应被硬拦(实战修复:自动化执行会初始化全部平台);
  - 此前误自动化留下的多平台目录(.cursor/.windsurf 等):人工删除;
  - 老链路项照旧:.claude→.cac 迁移、/reload-skills 提示、新装插件重启提示、statusline+权限基线合并无损。
- [ ] **1.2 env-setup 三产物**:statusline 自动接入;**权限基线合并**(settings 其他键无损,deny/allow 追加);
  `.comet/config.yaml` 两键齐。
- [ ] **1.3 配置确认**:工号取"域\"后半段;需求文档三分支(给个 docx 试试"不可读格式"话术);
  确认后把恒定项写 `.mae-flow-defaults.json` 提交。
- [ ] **1.4 交付方式选择**:四选项是否以中文(标准交付/缺陷快修/小改快过/评审返工)展示,推荐+依据合理。
- [ ] **1.5 全程观感**:done 报错可读性;gate 每次拦截记下来(误拦/漏拦分类);comet-build 四选项口径与公司标准一致。
- [ ] **1.6 grill 工作表**(若走标准交付):缺章打回与「待填」残留拦截的报错观感。
- [ ] **1.7 定稿确认**:AskUserQuestion 令牌真能拿到(archive_confirm 硬校验不误拦)。
- [ ] **1.8 中文路径/内容**:造一个中文名源码文件走一遍(quotepath 修复验证);中文 commit message 无乱码。
- [ ] **1.9 终态**:交付总结自动输出;`.mae-flow-history.jsonl` 追加一行;`report` 与 `report --all` 数字合理。
- [ ] **1.10 第二单开局**:直接说新需求 → 旧状态自动备份;defaults 预填生效(配置确认一次点头)。

## 阶段 2 — 专项演练(视时间,可拆到后续几天)

- [ ] **2.1 /clear 恢复**:编码实现中途 /clear → 说"继续" → 看它是否按恢复清单先读 计划/tasks/设计/diff 再动手。
- [ ] **2.2 review-fix 全链**:对首单 MR 造 3-4 条评审意见(混入一条该反驳的、一条涉及行为变更的)→
  rf_triage 逐条"先查证再裁决"、反驳有依据、行为变更被分诊转常规轮次 → 修复 → 增量验证 → commit 进原 MR。
- [ ] **2.3 unlock 裁决通道**:人为造一个 UT 能揪出的源码 bug → agent 自查报告六要素齐全 →
  三选一裁决 → unlock(伪造 ack 应被拒)→ 修复 → 新鲜度绑定强制重跑 UT(旧令牌应被判过期)。
- [ ] **2.4 codecheck_clean 现场复核校准**(CLI 已确认、证据已实装,2026-07-20):
  真实单走到规范检查步,验证——done 时现场重跑的耗时(多文件时是否可接受,超时阈值 15min 够不够)、
  「共有 N 条告警」锚点在你们 CLI 版本上稳定、豁免落盘→复核放行的闭环、测试文件确实被排除。
- [ ] **2.4b compile-agent 实测**:mcde 后台执行+轮询是否顺畅(前台会撞工具超时上限)、
  单模块编译时长记录、COMPILE 令牌+新鲜度绑定的"最后改码后必须再编译"体感、
  numstat 防掏空不变量有无误拦(合理精简走 SHRINK_EXEMPT 声明)。
- [ ] **2.5 弱模型压测**:换最弱可用模型跑一单 小改快过,记录全部偏差(话术跑偏/跳步尝试/报错后的自愈质量)。
- [ ] **2.6 会话卫生**:改插件后不重启会话的行为漂移确认一次(应复现,验证文档警告属实)。

## 结果回填

| 项 | 结论(通过/问题) | 备注/日志 |
|---|---|---|

历史卡死主因怀疑:旧版 dispatch stdin 阻塞 × command hook 默认 600s 超时——0.1 是第一优先。
全部结果发维护人或直接回填本表;确认项同步销掉记忆里的悬案清单。
