执行 /comet-tweak 生成轻量提案。展示改动范围,结束回复等用户确认后 done --ack --set CHANGE_NAME=<change目录名>。
comet 判定触发升级条件(tweak→full:5+ 文件/多模块协调/需新 capability/需 delta spec)时:
停手展示原因,等用户确认;确认升级则先 done --ack --set CHANGE_NAME(comet 侧会置 workflow=full、phase=design),再 goto design --force。
