执行 /ponytail-review,范围 = git diff {基线分支}..HEAD 的变更(只审本单 diff,禁止全库 audit)。
按其原生输出对待结果:逐条 tag(delete/stdlib/native/yagni/shrink)+ 净减行数;输出 "Lean already. Ship." → 直接 done。
有建议 → 逐条精简,但守住两条边界:
- **YAGNI 不得砍 delta spec 要求的行为**——spec 是合同,"这功能没人用"不是删除理由;YAGNI 只作用于实现方式(怎么写),不作用于需求范围(写什么)。
  若你认为某条 spec 要求**本身**有误(矛盾/过时/实现揭出的不可行),同样不许砍——呈报用户裁决,
  确认后 goto open --ack 回流修订 spec,再顺流回来(裁决通道,不是死路);
- correctness/security 类问题不归本步(ponytail-review 明确出界),记下来交 comet 审查
  (review_mode=standard 的最终审查/verify 阶段的轻量审查)处理。
精简后 → 重新编译、存量 UT(如有)跑一遍确认无回归 → git commit -m "[单号][类型]精简代码"。
(本步排在 CodeCheck 与 UT 之前:先删掉该死的代码,再修规范、再补测,不做无用功。)
