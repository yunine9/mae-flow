质量链与领域归档已结束。执行 `manifest set` 生成精确交付清单，向用户展示后用
`manifest confirm --message-id <消息ID>` 绑定文件、提交说明和目标分支。

确认后只可 `git add --` 清单内的精确文件；禁止目录、glob 或全量暂存。月光宝盒自动旁路本步骤。
