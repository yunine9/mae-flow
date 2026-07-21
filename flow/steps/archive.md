执行 /comet-archive:delta spec 合并进真相源,change 目录**移动**(git mv,非 cp)至 archive/;
**收尾自查**(done 前):openspec/changes/{单号对应 CHANGE_NAME}/ 原目录必须已消失(残留=假归档,会变僵尸,done 硬证据会拦)。
git commit -m "[单号][类型]归档 spec 变更"(本步提交只涉及 openspec/,禁止顺手 add 其他目录/宽 add)。
tweak/无 spec 变更**也要归档**(归档会移动 change 目录,防止僵尸活跃 change 干扰 comet 下次的阶段自动检测);
仅用户明确弃单时才 skip --reason,并提醒用户该 change 将保持活跃。
