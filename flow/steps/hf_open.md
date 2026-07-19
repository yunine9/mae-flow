执行 /comet-hotfix 生成轻量提案,记录 CHANGE_NAME。展示提案摘要(问题定位+修复思路),
结束回复等用户确认后 done --ack --set CHANGE_NAME=<change目录名>。
comet 判定触发升级条件(hotfix→full:3+ 文件/架构变更/DB schema/新 public API)时:
停手展示原因,等用户确认;确认升级则先 done --ack --set CHANGE_NAME(comet 侧会置 workflow=full、phase=design),再 goto design --force。
