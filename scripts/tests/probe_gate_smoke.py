#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针①：gate 冒烟 + v5 改动面的证据全路径。

与 test_*.py 的单元测试互补，两部分：
1. gate 拦/放黑盒抽样（真实 CLI 子进程）：源码步放行/非源码步拦、真相源
   只读、定稿步 specs 可写、变更单 change.md 可写。
2. 证据函数全路径（selftest 同款 importlib 直调）：spec_validate 八路、
   tasks_checked 四路、glob/glob_absent 双布局。

风格同 selftest（check 打印 + 退出码），selftest 点名跑本探针。
注意：第 2 部分会 os.chdir 进临时仓，探针独立进程跑，不污染调用方。
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAE = os.path.join(SCRIPTS, "mae-flow.py")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
PASS = 0
FAIL = []


def check(name, ok, detail=""):
    global PASS
    print(("✅ " if ok else "❌ ") + name + ((" — " + detail) if detail and not ok else ""))
    if ok:
        PASS += 1
    else:
        FAIL.append(name)


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def make_repo(base, name, current, cn="probe-x", workflow="full"):
    root = os.path.join(base, name)
    os.makedirs(root, exist_ok=True)
    subprocess.run(["git", "init", "-q", root], check=True, capture_output=True)
    write(root, ".mae-flow.json", json.dumps({
        "current": current,
        "config": {"CHANGE_NAME": cn, "单号": "REQ probe"},
        "choices": {"workflow": workflow},
        "history": [],
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False))
    return root


def gate(root, kind, target):
    return subprocess.run([sys.executable, MAE, "gate", kind, target],
                          cwd=root, text=True, capture_output=True, timeout=120)


DELTA = ("## ADDED Requirements\n\n### Requirement: Probe rule\n"
         "The system SHALL do the probed thing.\n\n"
         "#### Scenario: Works\n- **WHEN** probed\n- **THEN** it works\n")
GOOD_DOC = ("# 变更：probe-x\n\n# 为什么\n\n动机。\n\n# 规格条目：dom\n\n"
            + DELTA + "\n# 方案\n\n方案结论。\n\n# 实现清单\n\n- [x] 1. 完成\n")


def main():
    base_ctx = tempfile.TemporaryDirectory(prefix="mae-probe-gate ")
    base = base_ctx.name

    # ---------- 1. gate 拦/放 ----------
    root = make_repo(base, "g1", "build")
    r = gate(root, "edit", "src/foo.c")
    check("build 步改源码放行", r.returncode == 0, r.stdout + r.stderr)
    r = gate(root, "edit", "openspec/specs/dom/spec.md")
    check("build 步改真相源被拦", r.returncode != 0)
    r = gate(root, "edit", "openspec/changes/probe-x/change.md")
    check("build 步改本单 change.md 放行", r.returncode == 0, r.stdout + r.stderr)
    root = make_repo(base, "g2", "open")
    r = gate(root, "edit", "src/foo.c")
    check("open 步改源码被拦", r.returncode != 0)
    r = gate(root, "edit", "openspec/changes/probe-x/change.md")
    check("open 步写 change.md 放行", r.returncode == 0, r.stdout + r.stderr)
    root = make_repo(base, "g3", "archive")
    r = gate(root, "edit", "openspec/specs/dom/spec.md")
    check("定稿步写真相源放行", r.returncode == 0, r.stdout + r.stderr)

    # ---------- 2. 证据全路径（importlib 直调，selftest 同款） ----------
    spec_mod = importlib.util.spec_from_file_location("mf", MAE)
    mf = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(mf)

    def st(cn="probe-x"):
        return {"config": {"CHANGE_NAME": cn}, "choices": {"workflow": "full"}}

    root = make_repo(base, "ev", "open")
    os.chdir(root)
    write(root, "openspec/config.yaml", "schema: spec-driven\n")

    # spec_validate 八路
    write(root, "openspec/changes/probe-x/change.md",
          "# 为什么\n\nx\n\n# 实现清单\n\n- [ ] 1. x\n")
    ok, why = mf.ev_spec_validate({}, st())
    check("spec_validate: full 无 delta 拒", not ok and "change.md" in why, why)
    write(root, "openspec/changes/probe-x/change.md", GOOD_DOC)
    ok, why = mf.ev_spec_validate({}, st())
    check("spec_validate: 合法 v5 过", ok, why)
    write(root, "openspec/changes/probe-x/change.md",
          GOOD_DOC.replace("动机。", "（待填：动机）"))
    ok, why = mf.ev_spec_validate({}, st())
    check("spec_validate: （待填 残留拒", not ok and "待填" in why, why)
    write(root, "openspec/changes/probe-x/change.md",
          GOOD_DOC.replace("方案结论。", "（待设计：xx）"))
    ok, why = mf.ev_spec_validate({}, st())
    check("spec_validate: 默认不拦（待设计", ok, why)
    ok, why = mf.ev_spec_validate({"placeholders": ["（待填", "（待设计"]}, st())
    check("spec_validate: design 步配置拦（待设计", not ok and "待设计" in why, why)
    write(root, "openspec/changes/probe-x/change.md",
          "# 为什么\n\nx\n\n# 实现清单\n\n- [x] 1. x\n")
    ok, why = mf.ev_spec_validate({"allow_empty": True}, st())
    check("spec_validate: allow_empty 无 delta 过", ok, why)
    write(root, "openspec/changes/probe-x/change.md",
          "# 为什么\n\nx\n\n# 规格条目：dom\n\n## ADDED Requirements\n\n"
          "### Requirement: Bad\nNo keyword here.\n\n#### Scenario: s\n- x\n\n"
          "# 实现清单\n\n- [x] 1. x\n")
    ok, why = mf.ev_spec_validate({"allow_empty": True}, st())
    check("spec_validate: allow_empty 有非法 delta 仍拒", not ok, why)
    write(root, "openspec/changes/probe-x/tasks.md", "- [ ] 1. old\n")
    write(root, "openspec/changes/probe-x/change.md", GOOD_DOC)
    ok, why = mf.ev_spec_validate({}, st())
    check("spec_validate: 布局混用拒", not ok and "混用" in why, why)
    os.remove(os.path.join(root, "openspec/changes/probe-x/tasks.md"))
    # 坏编码 change.md:证据必须"拒+可读指引"而不是裸 traceback(核心原则:
    # 流畅易用,不能因 hook/证据卡死;done 连拒自动亮 goto --force 出口)
    with open(os.path.join(root, "openspec/changes/probe-x/change.md"),
              "wb") as fh:
        fh.write("# 为什么\n\n动机".encode("gbk") + b"\xff\xfe\n")
    try:
        ok, why = mf.ev_spec_validate({}, st())
        check("spec_validate: 坏编码不 crash 且给指引",
              not ok and "UTF-8" in why, why)
        ok, why = mf.ev_tasks_checked({}, st())
        check("tasks_checked: 坏编码不 crash", not ok, why)
    except Exception as exc:
        check("spec_validate: 坏编码不 crash 且给指引", False, repr(exc))
        check("tasks_checked: 坏编码不 crash", False, repr(exc))
    r = subprocess.run([sys.executable, MAE, "spec", "validate"],
                       cwd=root, text=True, capture_output=True, timeout=120)
    check("CLI validate: 坏编码优雅报错(退出码 2 非 traceback)",
          r.returncode == 2 and "Traceback" not in r.stderr, r.stderr[-300:])
    write(root, "openspec/changes/probe-x/change.md", GOOD_DOC)

    # tasks_checked 四路
    write(root, "openspec/changes/probe-x/change.md",
          GOOD_DOC.replace("- [x] 1. 完成", "- [ ] 1. 未完成"))
    ok, why = mf.ev_tasks_checked({}, st())
    check("tasks_checked: v5 未勾拒且指向实现清单节",
          not ok and "实现清单" in why, why)
    write(root, "openspec/changes/probe-x/change.md", GOOD_DOC)
    ok, why = mf.ev_tasks_checked({}, st())
    check("tasks_checked: v5 全勾过", ok, why)
    write(root, "openspec/changes/legacy-x/tasks.md", "- [ ] 1. a\n- [x] 2. b\n")
    ok, why = mf.ev_tasks_checked({}, st("legacy-x"))
    check("tasks_checked: legacy 未勾拒且指向 tasks.md",
          not ok and "tasks.md" in why, why)
    ok, why = mf.ev_tasks_checked({}, st("no-such-change"))
    check("tasks_checked: 单不存在拒", not ok, why)

    # glob 双认 + glob_absent
    ok, why = mf.ev_glob({"any": ["openspec/changes/probe-x/change.md",
                                  "openspec/changes/probe-x/proposal.md"]}, st())
    check("glob: v5 change.md 命中双认清单", ok, why)
    ok, why = mf.ev_glob_absent(
        {"any": ["openspec/changes/probe-x/change.md",
                 "openspec/changes/probe-x/proposal.md",
                 "openspec/changes/probe-x/tasks.md"]}, st())
    check("glob_absent: change.md 残留拒(假定稿拦截)", not ok, why)
    import shutil as _sh
    _sh.rmtree(os.path.join(root, "openspec/changes/probe-x"))
    ok, why = mf.ev_glob_absent(
        {"any": ["openspec/changes/probe-x/change.md",
                 "openspec/changes/probe-x/proposal.md",
                 "openspec/changes/probe-x/tasks.md"]}, st())
    check("glob_absent: 移走后过", ok, why)

    os.chdir(os.path.expanduser("~"))
    base_ctx.cleanup()
    print("\n探针①通过 %d 项, 失败 %d 项" % (PASS, len(FAIL)))
    if FAIL:
        print("失败: " + ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
