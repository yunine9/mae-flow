#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mae-flow statusline — 状态栏一行:单号 │ 当前步骤 │ 分支。

接入(settings.json,会话重启生效):
  "statusLine": {"type": "command", "command": "python \"<插件>/scripts/statusline.py\""}
读 stdin 的会话 JSON(取 cwd),向上定位 .mae-flow.json 或退出标记。
状态栏高频刷新:必须快——纯文件读,零子进程,任何异常都降级输出而不是报错。
"""
import json, os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    try:
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        raw = stream.read()
        if isinstance(raw, bytes):
            text = None
            for enc in ("utf-8-sig", "gb18030"):
                try:
                    text = raw.decode(enc, errors="strict")
                    break
                except UnicodeDecodeError:
                    pass
            d = json.loads(text or "{}")
        else:
            d = json.loads(raw or "{}")
    except Exception:
        d = {}
    cwd = ((d.get("workspace") or {}).get("current_dir")) or d.get("cwd") or os.getcwd()
    base = os.path.basename(os.path.abspath(cwd)) or cwd

    root, exited, probe = None, False, os.path.abspath(cwd)
    while True:
        if os.path.exists(os.path.join(probe, ".mae-flow.json.exited")):
            root, exited = probe, True
            break
        if os.path.exists(os.path.join(probe, ".mae-flow.json")):
            root = probe
            break
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent

    if not root:
        hint = " · mae-flow 空闲" if (os.path.isdir(os.path.join(cwd, "openspec"))
                                      or os.path.isdir(os.path.join(cwd, ".comet"))) else ""
        print(f"📁 {base}{hint}")
        return

    if exited:
        print(f"📁 {base} · mae-flow 已退出 │ 普通开发")
        return

    try:
        st = json.load(open(os.path.join(root, ".mae-flow.json"), encoding="utf-8"))
    except Exception:
        print(f"📁 {base} · mae-flow 状态读取失败(doctor 排障)")
        return

    cfg = st.get("config", {})
    sid = st.get("current", "?")
    dan = cfg.get("单号", "未配置")
    moonlight = bool((st.get("moonlight") or {}).get("enabled"))
    if sid == "end":
        print(f"✅ {dan} 交付完成 · 下一单直接说需求")
        return

    title = sid
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        flow = json.load(open(os.path.join(here, "..", "flow", "flow.json"), encoding="utf-8"))
        title = flow["steps"].get(sid, {}).get("title", sid)
    except Exception:
        pass
    if len(title) > 22:
        title = title[:21] + "…"

    parts = [f"{'🌙' if moonlight else '🚦'} {dan}", title]
    if moonlight:
        unresolved = len([
            x for x in ((st.get("moonlight") or {}).get("issues") or [])
            if not x.get("resolved_at")
        ])
        parts.append("无人值守" + (f"·遗留{unresolved}" if unresolved else ""))
    if cfg.get("分支名"):
        parts.append(cfg["分支名"])
    print(" │ ".join(parts))


if __name__ == "__main__":
    main()
