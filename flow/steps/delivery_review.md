质量链与领域归档已结束。执行 `manifest set` 生成当前尚未提交改动的精确交付清单。

普通模式：向用户展示清单，只确认一次；收到回答后执行 `messages`，再用
`manifest confirm --message-id <消息ID>` 绑定文件、提交说明和目标分支。

月光宝盒：禁止询问用户，使用 `manifest confirm --moonlight-auto` 绑定同一精确清单，并把自动裁决、
完整 diff 和质量证据写入晨间报告。

确认后执行清单给出的精确 `git add -- <文件...>`，再按 `[单号][feat|fix]描述` 创建一个提交；
禁止目录、glob、全量暂存、amend 或夹带过程文件。提交成功后执行 done；没有真实提交不能进入 push。
