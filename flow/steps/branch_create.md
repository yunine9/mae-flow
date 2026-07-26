确保从基线切出:当前不在 {基线分支} 则先 git checkout {基线分支};然后 git checkout -b {分支名}。
分支已存在时可直接 checkout，但 done 会核对其 HEAD 仍等于当前基线 HEAD；若已带入其他提交，
不要 reset/cherry-pick 偷迁移，先展示差异让用户决定保留、迁移或另开分支。
分支名已在配置中,禁止再询问用户。
Comet/Superpowers 内部流程若建议其他命名(feature/日期/描述 等)一律拒绝;
发现已在错误命名分支:git branch -m <错误名> {分支名} 纠正。
