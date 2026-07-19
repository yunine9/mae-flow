评审修复的增量验证,两件事:
1. 启动 codecheck-fix-agent(契约同 verify_codecheck:fullcheck -f 禁 increcheck,三数对账 hook 硬校验;
   REMAINING 同样逐项裁决"修/正式豁免",清单不清零禁止 done——门禁标准不因返工轮次而降低);
2. 本轮修复若改动了函数行为/新增分支 → 启动 ut-generator-agent 二轮
   (任务注明"评审修复轮次:只对本轮 diff 补/改用例",传入基线分支与 UT 配置);
   纯注释/命名/格式类修复 → 可不派,但判断依据要写进展示("哪些 commit 为何不需要补测")。
展示验证摘要(codecheck 结果 + UT 增量情况)→ done(硬校验本步内 CODECHECK 令牌)。
中断恢复:agent 无状态幂等,状态不确定就重启对应 agent。
