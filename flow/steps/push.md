git push -u origin HEAD(失败:git pull --rebase 后重试;仍失败保留本地 commit,展示报错等用户)。
展示:分支名、git log {基线分支}..HEAD --oneline 提交清单;
提示用户在代码平台用该分支创建 MR,流水线与合入由用户跟进。
done 证据校验:本地 HEAD 与远端上游一致(未推成谎报无效)。done 后流程结束。
