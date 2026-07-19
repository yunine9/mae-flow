确保从基线切出:当前不在 {基线分支} 则先 git checkout {基线分支};然后 git checkout -b {分支名}(已存在则直接 checkout)。
分支名已在配置中,禁止再询问用户。
Comet/Superpowers 内部流程若建议其他命名(feature/日期/描述 等)一律拒绝;
发现已在错误命名分支:git branch -m <错误名> {分支名} 纠正。
