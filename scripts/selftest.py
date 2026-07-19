#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mae-flow 插件自检 — 发版/打包前必跑(工程习惯抄自上游 comet 的 check-* 脚本)。
检查:语法、JSON、流程图连通性、证据类型注册、占位符合法性、步骤文档齐全、
agent 契约与 dispatch 识别名同步、关键文件存在。任何 ❌ 退出码 1。"""
import importlib.util, json, os, py_compile, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
fails = []


def check(name, ok, detail=""):
    print(("✅ " if ok else "❌ ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


# 1. 语法
for f in ("scripts/mae-flow.py", "hooks/dispatch.py", "scripts/statusline.py"):
    try:
        py_compile.compile(os.path.join(ROOT, f), doraise=True)
        check(f"语法 {f}", True)
    except Exception as e:
        check(f"语法 {f}", False, str(e))

# 2. JSON
flow = hooks = None
for f in ("flow/flow.json", "hooks/hooks.json", "skills/mae-flow/assets/settings-baseline.json"):
    try:
        d = json.load(open(os.path.join(ROOT, f), encoding="utf-8"))
        if f == "flow/flow.json":
            flow = d
        elif f == "hooks/hooks.json":
            hooks = d
        check(f"JSON {f}", True)
    except Exception as e:
        check(f"JSON {f}", False, str(e))

if flow:
    steps = flow["steps"]
    # 3. 流程图连通 + 步骤文档
    bad = []
    for sid, s in steps.items():
        nxt = s.get("next")
        targets = list(nxt.values()) if isinstance(nxt, dict) else ([nxt] if nxt else [])
        bad += [f"{sid}->{t}" for t in targets if t not in steps]
    check("流程图 next 全部有效", not bad, str(bad))
    check("start 步骤存在", flow.get("start") in steps)
    miss_md = [sid for sid, s in steps.items()
               if not s.get("terminal") and not os.path.exists(os.path.join(ROOT, "flow", "steps", sid + ".md"))]
    check("非终态步骤均有指令文档", not miss_md, str(miss_md))

    # 4. 证据类型已注册
    spec = importlib.util.spec_from_file_location("mf", os.path.join(ROOT, "scripts", "mae-flow.py"))
    mf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mf)
    used = {e["type"] for s in steps.values() for e in s.get("evidence", [])}
    unreg = used - set(mf.EVIDENCE)
    check("证据类型全部注册", not unreg, str(unreg))

    # 5. 占位符白名单
    KNOWN = {"单号", "CHANGE_NAME", "工号", "基线分支", "分支名", "单号类型", "STORY入库", "需求文档"}
    ph = set()
    for s in steps.values():
        for e in s.get("evidence", []):
            for p in e.get("any", []) + e.get("paths", []) + ([e["file"]] if "file" in e else []):
                ph |= set(re.findall(r"\{([^}]+)\}", p))
    check("证据占位符均为已知配置键", ph <= KNOWN, str(ph - KNOWN))

# 6. agent 契约与 dispatch 识别同步
dp = open(os.path.join(ROOT, "hooks", "dispatch.py"), encoding="utf-8").read()
for f in sorted(os.listdir(os.path.join(ROOT, "agents"))):
    if f.endswith(".md"):
        name = f[:-3]
        check(f"dispatch 识别 {name}", name in dp)
        txt = open(os.path.join(ROOT, "agents", f), encoding="utf-8").read()
        check(f"{name} 契约含 _RESULT 标记", "_RESULT:" in txt)

# 6.5 模板与 dispatch 章节校验同步(posttooluse 路由里必须引用同名模板)
for tpl in ("STORY-TEMPLATE.md", "CHAIN-TEMPLATE.md", "GRILL-PREP-TEMPLATE.md"):
    check(f"dispatch 模板校验引用 {tpl}", tpl in dp)

# 6.6 PostToolUse matcher 必须覆盖令牌/校验所需工具(漏了 = ASKUSER/UTRUN 令牌静默失效)
if hooks:
    m = ""
    for h in (hooks.get("hooks", {}).get("PostToolUse", []) or []):
        m = h.get("matcher", "") or m
    for need in ("AskUserQuestion", "Bash", "Write"):
        check(f"PostToolUse matcher 含 {need}", need in m)

# 7. 关键文件
for f in ("skills/mae-flow/SKILL.md", "skills/mae-flow/assets/STORY-TEMPLATE.md",
          "skills/mae-flow/assets/CHAIN-TEMPLATE.md",
          "skills/mae-flow/assets/GRILL-PREP-TEMPLATE.md",
          "skills/mae-flow/assets/settings-baseline.json",
          "commands/mae-flow.md", "README.md", "MAINTAINERS.md"):
    check(f"存在 {f}", os.path.exists(os.path.join(ROOT, f)))

print(f"\n{'全部通过 ✅' if not fails else f'失败 {len(fails)} 项 ❌'}")
sys.exit(1 if fails else 0)
