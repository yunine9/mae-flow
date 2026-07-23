#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mae-flow 插件自检 — 发版/打包前必跑(工程习惯抄自上游 comet 的 check-* 脚本)。
检查:语法、JSON、流程图连通性、证据类型注册、占位符合法性、步骤文档齐全、
agent 契约与 dispatch 识别名同步、关键文件存在。任何 ❌ 退出码 1。"""
import importlib.util, json, os, py_compile, re, subprocess, sys, tempfile, time, types

from comet_compat import BEGIN as COMET_COMPAT_BEGIN, ensure_direct_mode_compat

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
fails = []


def check(name, ok, detail=""):
    print(("✅ " if ok else "❌ ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


# 1. 语法
for f in ("scripts/mae-flow.py", "scripts/comet_compat.py", "hooks/dispatch.py",
          "scripts/statusline.py", "scripts/setup.py"):
    try:
        py_compile.compile(os.path.join(ROOT, f), doraise=True)
        check(f"语法 {f}", True)
    except Exception as e:
        check(f"语法 {f}", False, str(e))

# 2. JSON
flow = hooks = None
for f in ("flow/flow.json", "hooks/hooks.json", "skills/mae-flow/assets/settings-baseline.json",
          "skills/mae-flow/assets/env-profile.json"):
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

    # 4.5 review-fix 质量链必须保持拆分，禁止退化回一个 rf_verify 大步骤
    review_chain = ["rf_fix", "rf_compile", "rf_codecheck", "rf_ut", "push"]
    got, cur = [], "rf_fix"
    for _ in range(len(review_chain)):
        got.append(cur)
        cur = steps.get(cur, {}).get("next")
    check("review-fix 质量链分阶段", got == review_chain, str(got))
    check("review 编译只接受 OK",
          steps.get("rf_compile", {}).get("evidence", [{}])[0].get("statuses") == ["OK"])
    check("review UT 只接受 PASS",
          steps.get("rf_ut", {}).get("evidence", [{}])[0].get("statuses") == ["PASS"])
    check("review UT 改源码后回流编译链",
          steps.get("rf_ut", {}).get("source_change_recheck") == "rf_compile")
    check("主流程 UT 改源码后回流专用编译节点",
          steps.get("verify_ut", {}).get("source_change_recheck") == "verify_recompile"
          and steps.get("verify_recompile", {}).get("next") == "verify_ponytail")
    tweak_chain = ["tw_change", "tw_compile", "tw_codecheck", "tw_ut", "archive_confirm"]
    got, cur = [], "tw_change"
    for _ in range(len(tweak_chain)):
        got.append(cur)
        cur = steps.get(cur, {}).get("next")
    check("小改流程也经过编译、规范检查和 UT", got == tweak_chain, str(got))
    check("小改规范检查不可直接跳过", not steps.get("tw_codecheck", {}).get("skippable"))
    check("精简改源码后自动进入专用编译步骤",
          steps.get("verify_ponytail", {}).get("source_change_next") == "verify_post_ponytail_compile"
          and steps.get("verify_post_ponytail_compile", {}).get("next") == "verify_codecheck")
    check("三条流程共用 CodeCheck 机器协议",
          all(steps.get(x, {}).get("evidence", [{}])[0].get("type") == "review_codecheck"
              for x in ("verify_codecheck", "tw_codecheck", "rf_codecheck")))

    # CodeCheckCLI 的成功退出码/文案不稳定，至少守住三种已知输出
    parser_cases = [
        ("💡 提示: 共有 2 条告警。", "", 2),
        ("[CodeCheck] 代码检查完成", "| **总计** | **0** | **0** |", 0),
        ("[CodeCheck] 代码检查完成! 未发现代码告警", "", 0),
    ]
    check("CodeCheck 告警数多格式解析",
          all(mf._parse_codecheck_count(a, b) == n for a, b, n in parser_cases))
    real_run, real_which = mf.subprocess.run, mf.shutil.which
    try:
        sample = """[CodeCheck] 代码检查完成!\n### 1. [Minor] R.ONE 示例\n- **文件**: `Foo.cpp`\n- **规则**: R.ONE 示例\n💡 提示: 共有 1 条告警。"""
        mf.shutil.which = lambda _: "/fake/codecheck"
        mf.subprocess.run = lambda *a, **k: types.SimpleNamespace(
            stdout=sample, stderr="", returncode=1)
        result, err = mf._run_codecheck(["src/Foo.cpp"])
        check("CodeCheck 成功不依赖退出码 0",
              not err and result["total"] == 1 and result["pairs"] == [("R.ONE", "src/Foo.cpp")])
    finally:
        mf.subprocess.run, mf.shutil.which = real_run, real_which
    win_argv, win_shell, _ = mf._codecheck_launch(
        ["src/My File.cpp"], executable=r"C:\Users\dev\AppData\Roaming\npm\codecheck.cmd", windows=True)
    check("Windows CodeCheck 沿用已验证的 shell/PATHEXT 路径",
          win_shell and isinstance(win_argv, str) and "codecheck fullcheck" in win_argv
          and '"src/My File.cpp"' in win_argv)
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False) as f:
        json.dump({"issues": [{"uuid": "1", "rule": "R.ONE", "file": "a/Foo.cpp"},
                              {"uuid": "2", "rule": "R.TWO", "file": "b/Foo.cpp"}]}, f)
        codecheck_json = f.name
    try:
        count, pairs = mf._parse_codecheck_json(codecheck_json)
        check("CodeCheck JSON 兜底解析", count == 2 and len(pairs) == 2)
    finally:
        os.unlink(codecheck_json)

    mf.FLOW = flow
    source_cases = {
        "include/Foo.hpp": True,
        "lib/core.cpp": True,
        "app/generated/no_extension": True,
        "CMakeLists.txt": True,
        "pom.xml": True,
        "docs/readme.md": False,
    }
    check("跨仓源码识别不依赖 service/src",
          all(mf._is_source_path(p, {}, flow) == want for p, want in source_cases.items())
          and mf._is_source_path("vendor/private/schema",
                                 {"config": {"源码路径": r"(^|/)vendor/private/"}}, flow))
    check("dt_tests 与 C++ Test 文件不会进入 CodeCheck",
          mf._is_test_file("service/probe/dt_tests/Foo.cpp", {})
          and mf._is_test_file("service/probe/FooTest.cpp", {})
          and mf._is_test_file("service/probe/dt_tests/Foo.cpp",
                               {"config": {"测试路径": r"(^|/)private_ut/"}}))
    check("评审空模板不会误判为待修代码",
          not mf._review_has_confirmed_fix("合法值: 修复(已确认)\n| # | 意见 | 定性 | 裁决 |\n|---|---|---|---|")
          and mf._review_has_confirmed_fix("| 1 | 空指针 | 属实 | 修复(已确认) |"))
    check("配置只能在声明步骤写入",
          mf._allowed_set_keys(steps["config_confirm"]) >= {"基线分支", "分支名", "编译方式"}
          and not mf._allowed_set_keys(steps["verify_codecheck"]))
    check("同名文件豁免键不会碰撞",
          mf._approval_key("R", "a/Foo.cpp") != mf._approval_key("R", "b/Foo.cpp"))
    check("豁免规则与文件必须在同一条记录",
          not mf._exemption_text_has_pair("- R.ONE | a/Foo.cpp\n- R.TWO | b/Bar.cpp", "R.ONE", "b/Bar.cpp")
          and mf._exemption_text_has_pair("- R.ONE | a/Foo.cpp", "R.ONE", "a/Foo.cpp"))

    # 退出必须保留业务现场、归档状态并使直接模式标记立即可见。
    old_cwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            open("keep.cpp", "w", encoding="utf-8").write("int keep = 1;\n")
            subprocess.run(["git", "init", "-q"], check=True)
            subprocess.run(["git", "config", "user.email", "mae-flow@test.invalid"], check=True)
            subprocess.run(["git", "config", "user.name", "MAE Flow Test"], check=True)
            subprocess.run(["git", "add", "keep.cpp"], check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], check=True)
            now = "2026-07-22 20:00:00"
            st = {"current": "config_confirm", "config": {"单号": "REQEXIT1"},
                  "choices": {}, "history": [], "started": now}
            mf.save_state(st)
            with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
                response = json.dumps({"answers": {"exit": "确认退出流程并保留代码"}}, ensure_ascii=False)
                json.dump([{"text": response, "step": "config_confirm", "at": now}],
                          f, ensure_ascii=False)
            mf.cmd_exit(flow, st, types.SimpleNamespace(ack="", reason=""))
            check("exit 只预览时不会解除门禁",
                  os.path.isfile(mf.STATE_PATH) and not os.path.exists(mf.EXIT_PATH))
            mf.cmd_exit(flow, st, types.SimpleNamespace(
                ack="确认退出流程并保留代码", reason="改为直接开发"))
            rec = json.load(open(mf.EXIT_PATH, encoding="utf-8"))
            snap = rec.get("snapshot", "")
            check("exit 保留业务文件并归档流程现场",
                  open("keep.cpp", encoding="utf-8").read() == "int keep = 1;\n"
                  and not os.path.exists(mf.STATE_PATH)
                  and os.path.isfile(os.path.join(snap, mf.STATE_PATH))
                  and os.path.isfile(os.path.join(snap, "exit-record.json")))
            check("exit 记录步骤、原因与旧证据失效边界",
                  rec.get("step") == "config_confirm" and rec.get("reason") == "改为直接开发"
                  and bool(re.fullmatch(r"[0-9a-f]{40}", rec.get("head", ""))))
            reenable_blocked = False
            try:
                mf._resume_direct_mode()
            except SystemExit as exc:
                reenable_blocked = exc.code == 2
            check("Agent 不能自行重新启用流程",
                  reenable_blocked and os.path.exists(mf.EXIT_PATH))
            rec["direct_messages"] = [{"text": "重新使用 mae-flow 交付新需求"}]
            mf._write_json_atomic(mf.EXIT_PATH, rec)
            restored = mf._resume_direct_mode("重新使用 mae-flow 交付新需求")
            check("用户明确确认后恢复原断点且清空旧令牌",
                  not os.path.exists(mf.EXIT_PATH) and restored.get("current") == "config_confirm"
                  and os.path.isfile(mf.STATE_PATH) and not os.path.exists(mf.STATE_PATH + ".tokens"))

            # 晚阶段退出后直接改过源码：恢复时不得回到原步骤继续吃旧证据。
            restored["current"] = "verify_ut"
            restored["choices"] = {"workflow": "full"}
            restored["quality"] = {"codecheck_scan": {"total": 0}}
            restored["agent_tasks"] = {"UT": {"head": rec["head"]}}
            mf.save_state(restored)
            with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
                json.dump([{"text": "确认再次退出", "step": "verify_ut", "at": now}], f,
                          ensure_ascii=False)
            mf.cmd_exit(flow, restored, types.SimpleNamespace(ack="确认再次退出", reason="临时直接修复"))
            open("keep.cpp", "a", encoding="utf-8").write("int changed = 2;\n")
            rec2 = json.load(open(mf.EXIT_PATH, encoding="utf-8"))
            rec2["direct_messages"] = [{"text": "重新接回 mae-flow"}]
            mf._write_json_atomic(mf.EXIT_PATH, rec2)
            resumed2 = mf._resume_direct_mode("重新接回 mae-flow")
            check("退出期间改过源码会回退质量链并废弃旧证据",
                  resumed2.get("current") == "verify_recompile"
                  and "quality" not in resumed2 and "agent_tasks" not in resumed2
                  and not os.path.exists(mf.STATE_PATH + ".tokens"))
    finally:
        os.chdir(old_cwd)

    # 用户风险放行：只替代当前步骤的 Agent 令牌，必须真实 ack，代码变化/推进后立即失效。
    old_cwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            os.makedirs("src/test")
            open("src/test/FooTest.cpp", "w", encoding="utf-8").write("int test_value = 1;\n")
            subprocess.run(["git", "init", "-q"], check=True)
            subprocess.run(["git", "config", "user.email", "mae-flow@test.invalid"], check=True)
            subprocess.run(["git", "config", "user.name", "MAE Flow Test"], check=True)
            subprocess.run(["git", "add", "src/test/FooTest.cpp"], check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], check=True)
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            risk_ack = "确认承担UT结果未被harness核实的风险并继续"
            risk_state = {"current": "rf_ut", "config": {}, "choices": {"workflow": "review"},
                          "history": [], "started": now}
            mf.save_state(risk_state)
            with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
                json.dump([{"text": risk_ack, "step": "rf_ut", "at": now}], f, ensure_ascii=False)
            fake_blocked = False
            try:
                mf.cmd_accept_risk(flow, risk_state, types.SimpleNamespace(
                    agent="ut", reason="UT 未核实", ack="模型代答确认"))
            except SystemExit as exc:
                fake_blocked = exc.code == 2
            check("Agent 令牌风险放行必须匹配用户真实原话", fake_blocked)
            mf.cmd_accept_risk(flow, risk_state, types.SimpleNamespace(
                agent="ut", reason="UT 结果未被 harness 核实", ack=risk_ack))
            risk_state = mf.load_state()
            risk_ok, _ = mf.ev_agent_ran({"agent": "UT", "statuses": ["PASS"]}, risk_state)
            check("用户确认可只放行当前步骤的 UT 令牌", risk_ok
                  and not os.path.exists(mf.STATE_PATH + ".tokens")
                  and any(h.get("result") == "accept-risk:UT" for h in risk_state["history"]))
            wrong_kind = False
            try:
                mf.cmd_accept_risk(flow, risk_state, types.SimpleNamespace(
                    agent="compile", reason="编译未核实", ack=risk_ack))
            except SystemExit as exc:
                wrong_kind = exc.code == 2
            check("风险放行不能预授权本步骤不需要的令牌", wrong_kind)
            open("src/test/FooTest.cpp", "a", encoding="utf-8").write("int changed = 2;\n")
            fresh, fresh_why = mf.ev_agent_ran({"agent": "UT", "statuses": ["PASS"]}, risk_state)
            check("代码变化后用户风险放行立即失效",
                  not fresh and "风险确认后代码发生变化" in fresh_why)
            open("src/test/FooTest.cpp", "w", encoding="utf-8").write("int test_value = 1;\n")

            # CodeCheck 的风险放行只替代 Agent 令牌，不得跳过最后的机器复核。
            cc_ack = "确认承担CodeCheck修复Agent令牌缺失风险并继续"
            cc_state = {"current": "rf_codecheck", "config": {},
                        "choices": {"workflow": "review"}, "history": [], "started": now,
                        "quality": {"codecheck_scan": {"step": "rf_codecheck", "count": 1}}}
            mf.save_state(cc_state)
            with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
                json.dump([{"text": cc_ack, "step": "rf_codecheck", "at": now}],
                          f, ensure_ascii=False)
            mf.cmd_accept_risk(flow, cc_state, types.SimpleNamespace(
                agent="codecheck", reason="CodeCheck 修复 Agent 令牌未签发", ack=cc_ack))
            cc_state = mf.load_state()
            old_clean = mf.ev_codecheck_clean
            try:
                mf.ev_codecheck_clean = lambda _spec, _st: (False, "现场复核仍有 1 条告警")
                cc_ok, cc_why = mf.ev_review_codecheck({}, cc_state)
            finally:
                mf.ev_codecheck_clean = old_clean
            check("放行 CodeCheck Agent 令牌仍会执行真实结果复核",
                  not cc_ok and "现场复核仍有 1 条告警" in cc_why)

            mf.advance(flow, risk_state, "rf_ut", flow["steps"]["rf_ut"], "done")
            check("进入下一步后用户风险放行不再保留",
                  "risk_acceptances" not in mf.load_state())
    finally:
        os.chdir(old_cwd)

    # 月光宝盒：普通门禁不变；仅显式启用后替代在线确认，质量失败留痕推进，
    # push 后停在晨间检查，并可按报告重新进入完整质量链。
    old_cwd = os.getcwd()
    try:
        # 全新项目没有 .mae-flow.json：UserPromptSubmit 先留下十分钟内的一次性授权，
        # 脚本消费后再创建状态，保证“一句话开启”不是鸡生蛋。
        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-q", td], check=True)
            child = os.path.join(td, "service", "module")
            os.makedirs(child)
            payload = json.dumps({
                "cwd": child,
                "prompt": "今晚开启月光宝盒，把这个需求尽力开发完并推送",
            }, ensure_ascii=False) + "\n"
            hook = subprocess.run(
                [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "userprompt"],
                cwd=child, input=payload, text=True, capture_output=True, timeout=10)
            os.chdir(td)
            intent_at_root = os.path.isfile(mf.MOONLIGHT_INTENT_PATH)
            mf.cmd_moonlight(flow, None, types.SimpleNamespace(
                action="on", ack="月光宝盒", reason=None))
            fresh = mf.load_state()
            check("全新项目可从子目录一句话开启月光宝盒",
                  hook.returncode == 0 and intent_at_root and mf._moonlight(fresh)
                  and not os.path.exists(mf.MOONLIGHT_INTENT_PATH))

        # 已明确退出的项目也可切到月光宝盒；恢复旧断点但清空旧质量凭证。
        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            subprocess.run(["git", "init", "-q"], check=True)
            subprocess.run(["git", "config", "user.email", "mae-flow@test.invalid"], check=True)
            subprocess.run(["git", "config", "user.name", "MAE Flow Test"], check=True)
            open("biz.cpp", "w", encoding="utf-8").write("int value = 1;\n")
            subprocess.run(["git", "add", "biz.cpp"], check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], check=True)
            head = subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                                  capture_output=True, text=True).stdout.strip()
            snapshot = os.path.join(".mae-flow-work", "exited", "fixture")
            os.makedirs(snapshot)
            direct_state = {
                "current": "rf_codecheck", "config": {"单号": "REQMOON0"},
                "choices": {"workflow": "review"}, "history": [],
                "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                "agent_tasks": {"CODECHECK": {"old": True}},
            }
            with open(os.path.join(snapshot, mf.STATE_PATH), "w", encoding="utf-8") as f:
                json.dump(direct_state, f)
            with open(mf.EXIT_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "snapshot": snapshot, "head": head,
                    "direct_messages": [{"text": "切换月光宝盒继续做"}],
                }, f)
            mf.cmd_moonlight(flow, None, types.SimpleNamespace(
                action="continue", ack="月光宝盒", reason=None))
            resumed = mf.load_state()
            check("普通开发模式可由用户明确切换到月光宝盒",
                  mf._moonlight(resumed) and resumed.get("current") == "rf_codecheck"
                  and "agent_tasks" not in resumed and not os.path.exists(mf.EXIT_PATH))

        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            subprocess.run(["git", "init", "-q"], check=True)
            subprocess.run(["git", "config", "user.email", "mae-flow@test.invalid"], check=True)
            subprocess.run(["git", "config", "user.name", "MAE Flow Test"], check=True)
            open("biz.cpp", "w", encoding="utf-8").write("int value = 1;\n")
            subprocess.run(["git", "add", "biz.cpp"], check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], check=True)
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            ml_state = {
                "current": "rf_codecheck", "config": {"单号": "REQMOON1"},
                "choices": {"workflow": "review"}, "history": [], "started": now,
            }
            mf.save_state(ml_state)
            with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
                json.dump([{"text": "开启月光宝盒继续开发", "step": "rf_codecheck", "at": now}],
                          f, ensure_ascii=False)
            mf.cmd_moonlight(flow, ml_state, types.SimpleNamespace(
                action="on", ack="月光宝盒", reason=None))
            ml_state = mf.load_state()
            ask_ok, _ = mf.ev_agent_ran({"agent": "ASKUSER"}, ml_state)
            check("月光宝盒必须由真实用户消息开启且替代在线确认",
                  mf._moonlight(ml_state) and ask_ok)

            defer_reason = "CodeCheck仍有1条环境相关告警，已复查并尝试修复两次，继续会重复消耗"
            mf.cmd_moonlight(flow, ml_state, types.SimpleNamespace(
                action="defer", ack=None, reason=defer_reason))
            deferred = mf.load_state()
            unresolved = mf._moonlight_unresolved(deferred)
            check("月光宝盒质量失败留痕后继续而不伪装通过",
                  deferred.get("current") == "rf_ut"
                  and len(unresolved) == 1
                  and unresolved[0].get("kind") == "codecheck"
                  and os.path.isfile(mf.MOONLIGHT_REPORT_PATH))

            # UT 发现源码缺陷可用夜间自查结论解锁，仍由 done 自动回流质量链。
            mf.cmd_moonlight(flow, deferred, types.SimpleNamespace(
                action="unlock-source", ack=None,
                reason="失败用例TestA与规格场景A冲突，最小复现确认断言无误，倾向源码缺陷"))
            unlocked = mf.load_state()
            check("月光宝盒可记录UT自查后解锁源码修复",
                  (unlocked.get("unlock") or {}).get("moonlight") is True
                  and (unlocked.get("unlock") or {}).get("step") == "rf_ut")

            # 模拟 UT 已尽力但仍有遗留，随后 push 成功应停在晨间检查而不是 end。
            unlocked.pop("unlock", None)
            mf.save_state(unlocked)
            mf.cmd_moonlight(flow, unlocked, types.SimpleNamespace(
                action="defer", ack=None,
                reason="UT仍有1个历史环境失败，已重跑并排除本次代码逻辑问题，记录后继续推送"))
            before_push = mf.load_state()
            check("评审月光轮质量链最终进入push", before_push.get("current") == "push")
            mf.cmd_moonlight(flow, before_push, types.SimpleNamespace(
                action="push-failed", ack=None,
                reason="远端认证临时失败，已重新登录并重试一次仍未恢复"))
            push_waiting = mf.load_state()
            check("月光宝盒不会把push失败伪装成远端成功",
                  push_waiting.get("current") == "push"
                  and any(x.get("kind") == "push"
                          for x in mf._moonlight_unresolved(push_waiting)))
            mf.advance(flow, push_waiting, "push", flow["steps"]["push"], "done")
            morning = mf.load_state()
            check("月光宝盒push后停在晨间检查且暂不归档",
                  morning.get("current") == "moonlight_review"
                  and (morning.get("moonlight") or {}).get("pushed_head")
                  and not any(x.get("kind") == "push"
                              for x in mf._moonlight_unresolved(morning))
                  and os.path.isfile(mf.MOONLIGHT_REPORT_PATH))

            env_morning = json.loads(json.dumps(morning))
            env_morning["moonlight"]["issues"].append({
                "id": "ML-003", "kind": "environment", "step": "env_setup",
                "at": now, "head": mf.sh("git rev-parse --verify HEAD"),
                "reason": "夜间环境安装后需要人工刷新插件，尚未完成现场复验",
            })
            mf.save_state(env_morning)
            mf.cmd_moonlight(flow, env_morning, types.SimpleNamespace(
                action="repair", ack=None, reason=None))
            env_repair = mf.load_state()
            env_route_ok = (
                env_repair.get("current") == "env_setup"
                and (env_repair.get("moonlight") or {}).get("repair_after_environment")
                == "rf_compile")
            mf.advance(flow, env_repair, "env_setup", flow["steps"]["env_setup"], "done")
            check("晨间修复会先处理环境遗留再回到质量链而不重跑需求流程",
                  env_route_ok and mf.load_state().get("current") == "rf_compile")

            mf.save_state(morning)
            mf.cmd_moonlight(flow, morning, types.SimpleNamespace(
                action="repair", ack=None, reason=None))
            repairing = mf.load_state()
            check("月光宝盒按报告从工作流编译入口开启修复轮",
                  repairing.get("current") == "rf_compile"
                  and (repairing.get("moonlight") or {}).get("cycle") == 2
                  and "agent_tasks" not in repairing and "quality" not in repairing)
            mf._moonlight_resolve_kind(repairing, "codecheck")
            mf._moonlight_resolve_kind(repairing, "ut")
            repairing["current"] = "moonlight_review"
            mf.save_state(repairing)
            mf.cmd_moonlight(flow, repairing, types.SimpleNamespace(
                action="finalize", ack=None, reason=None))
            finalized = mf.load_state()
            check("评审返工晨间修复完成后可直接结束",
                  finalized.get("current") == "end" and not mf._moonlight(finalized))

            # full/tweak/hotfix 的夜间路径跳过不可逆归档，晨间 finalize 才恢复归档确认。
            full_state = {
                "current": "verify_comet", "config": {"单号": "REQMOON2", "CHANGE_NAME": "moon"},
                "choices": {"workflow": "full"}, "history": [], "started": now,
                "moonlight": {"enabled": True, "activated_at": now, "cycle": 1, "issues": []},
            }
            mf.save_state(full_state)
            mf.advance(flow, full_state, "verify_comet", flow["steps"]["verify_comet"], "done")
            skipped_archive = mf.load_state()
            check("标准交付月光轮先跳过归档进入push",
                  skipped_archive.get("current") == "push"
                  and any(h.get("result") == "moonlight:archive-deferred"
                          for h in skipped_archive.get("history", [])))
            mf.advance(flow, skipped_archive, "push", flow["steps"]["push"], "done")
            full_morning = mf.load_state()
            mf.cmd_moonlight(flow, full_morning, types.SimpleNamespace(
                action="finalize", ack=None, reason=None))
            full_finalized = mf.load_state()
            check("标准交付晨间finalize恢复普通规格定稿",
                  full_finalized.get("current") == "archive_confirm"
                  and not mf._moonlight(full_finalized))
    finally:
        os.chdir(old_cwd)

    # 5. 占位符白名单
    KNOWN = {"单号", "CHANGE_NAME", "工号", "基线分支", "分支名", "单号类型", "STORY入库", "需求文档"}
    ph = set()
    for s in steps.values():
        for e in s.get("evidence", []):
            for p in e.get("any", []) + e.get("paths", []) + ([e["file"]] if "file" in e else []):
                ph |= set(re.findall(r"\{([^}]+)\}", p))
    check("证据占位符均为已知配置键", ph <= KNOWN, str(ph - KNOWN))
    token_types = {"agent_ran", "agent_or_no_source", "review_agent_or_no_code"}
    token_requirements = [
        (step, "CODECHECK" if e.get("type") == "review_codecheck"
         else str(e.get("agent", "")).upper())
        for step in steps.values() for e in step.get("evidence", [])
        if e.get("type") in token_types or e.get("type") == "review_codecheck"
    ]
    all_token_steps_covered = all(
        kind in mf._step_agent_kinds(step) and kind in mf.RISK_AGENT_LABELS
        for step, kind in token_requirements)
    check("所有流程 Agent 令牌证据都能识别统一风险放行", all_token_steps_covered)

# 6. agent 契约与 dispatch 识别同步
dp = open(os.path.join(ROOT, "hooks", "dispatch.py"), encoding="utf-8").read()
dspec = importlib.util.spec_from_file_location("dispatch", os.path.join(ROOT, "hooks", "dispatch.py"))
dispatch = importlib.util.module_from_spec(dspec)
dspec.loader.exec_module(dispatch)
for f in sorted(os.listdir(os.path.join(ROOT, "agents"))):
    if f.endswith(".md"):
        name = f[:-3]
        check(f"dispatch 识别 {name}", name in dp)
        txt = open(os.path.join(ROOT, "agents", f), encoding="utf-8").read()
        check(f"{name} 契约含 _RESULT 标记", "_RESULT:" in txt)
        if name in ("compile-agent", "codecheck-fix-agent", "ut-generator-agent"):
            check(f"{name} 契约绑定任务卡", "TASK_CARD_SHA256" in txt)

check("dispatch 校验任务卡指纹", "_task_card_contract" in dp and "TASK_CARD_SHA256" in dp)
check("dispatch 校验 UT 配置", "GENERATOR_USED" in dp and "EXECUTED_UT" in dp)
check("dispatch 校验真实 Skill/Bash 调用", "_skill_called" in dp and "_bash_called" in dp)
check("Bash 证据不接受 echo 冒充",
      dispatch._bash_call([{"name": "Bash", "input": {"command": "echo codecheck fullcheck -f a.cpp"}}],
                          "codecheck fullcheck") is None
      and dispatch._bash_call([{"name": "Bash", "input": {"command": "codecheck fullcheck -f a.cpp"}}],
                              "codecheck fullcheck") is not None)
old_cwd = os.getcwd()
old_dispatch_paths = (dispatch.STATE, dispatch.REJECTION_STATE, dispatch.EVIDENCE_STATE)
try:
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(["git", "config", "user.email", "mae-flow@test.invalid"], check=True)
        subprocess.run(["git", "config", "user.name", "MAE Flow Test"], check=True)
        open("biz.cpp", "w", encoding="utf-8").write("int value = 1;\n")
        subprocess.run(["git", "add", "biz.cpp"], check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], check=True)
        dispatch.STATE = ".mae-flow.json"
        dispatch.REJECTION_STATE = dispatch.STATE + ".agent-rejections"
        dispatch.EVIDENCE_STATE = dispatch.STATE + ".agent-evidence"
        body = "# CODECHECK TASK CARD\n"
        digest = __import__("hashlib").sha256(body.encode("utf-8")).hexdigest()
        open("task.md", "w", encoding="utf-8").write(body + "TASK_CARD_SHA256: " + digest + "\n")
        head = subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
        task = {"step": "rf_codecheck", "sha256": digest, "path": os.path.abspath("task.md"),
                "head": head, "allowed_files": ["biz.cpp"]}
        json.dump({"current": "rf_codecheck", "config": {"编译方式": "build-fix skill"},
                   "agent_tasks": {"CODECHECK": task},
                   "quality": {"codecheck_scan": {"step": "rf_codecheck", "count": 1}}},
                  open(dispatch.STATE, "w", encoding="utf-8"), ensure_ascii=False)
        build_calls = [{"name": "Skill", "input": {"skill": "build-fix"},
                        "result_seen": True, "is_error": False, "result": "BUILD_ERRORS: 0"}]
        receipt = dispatch._record_codecheck_build_receipt(task, build_calls)
        check("CodeCheck 报告重答可复用同版本真实编译凭证",
              bool(receipt) and bool(dispatch._reusable_codecheck_build_receipt(task)))
        open("biz.cpp", "a", encoding="utf-8").write("int changed = 2;\n")
        check("源码变化后 CodeCheck 编译凭证立即失效",
              dispatch._reusable_codecheck_build_receipt(task) is None)
        open("biz.cpp", "w", encoding="utf-8").write("int value = 1;\n")
        check("CodeCheck 编译凭证不能跨任务卡复用",
              dispatch._reusable_codecheck_build_receipt(
                  {"step": "rf_codecheck", "sha256": "b" * 64}) is None)
        retry_report = "\n".join([
            "CODECHECK_RESULT: CLEAN",
            "TASK_CARD_SHA256: " + digest,
            "EXECUTED_COMMAND: codecheck fullcheck -f biz.cpp",
            "EXECUTED_BUILD: 无需",
            "FOUND: 1", "FIXED: 1", "REMAINING_COUNT: 0",
            "复验锚点: 共有 0 条告警",
        ])
        retry_calls = [{"name": "Bash", "input": {"command": "codecheck fullcheck -f biz.cpp"},
                        "result_seen": True, "is_error": False, "result": "共有 0 条告警"}]
        retry_ok = True
        try:
            dispatch._codecheck_contract("CLEAN", retry_report, retry_calls, soft=True)
        except SystemExit:
            retry_ok = False
        check("CodeCheck 格式重答无需重复长编译", retry_ok)
        dispatch._record_rejection("CODECHECK", "缺少真实编译证据（测试原因）")
        rejected_ok, rejected_why = mf.ev_agent_ran(
            {"agent": "CODECHECK", "statuses": ["CLEAN"]},
            {"current": "rf_codecheck", "started": "2000-01-01 00:00:00", "history": []})
        check("done 会显示子 Agent 的真实拒签原因",
              not rejected_ok and "缺少真实编译证据（测试原因）" in rejected_why
              and "首行" not in rejected_why)

        # UT:真实工具证据优先于摘要排版；同 HEAD 的报告重答可复用，过滤失败测试仍必须拦。
        open("biz_test.cpp", "w", encoding="utf-8").write("int test_value = 1;\n")
        subprocess.run(["git", "add", "biz_test.cpp"], check=True)
        subprocess.run(["git", "commit", "-qm", "ut fixture"], check=True)
        ut_body = "# UT TASK CARD\n"
        ut_digest = __import__("hashlib").sha256(ut_body.encode("utf-8")).hexdigest()
        open("ut-task.md", "w", encoding="utf-8").write(
            ut_body + "TASK_CARD_SHA256: " + ut_digest + "\n")
        ut_head = subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                                 capture_output=True, text=True).stdout.strip()
        ut_task = {"step": "rf_ut", "sha256": ut_digest, "path": os.path.abspath("ut-task.md"),
                   "head": ut_head}
        json.dump({"current": "rf_ut",
                   "config": {"UT生成方式": "mae-flow:AutoUT Skill", "UT运行命令": "mcde test --ut"},
                   "agent_tasks": {"UT": ut_task}},
                  open(dispatch.STATE, "w", encoding="utf-8"), ensure_ascii=False)
        ut_report = "\n".join([
            "UT_RESULT: PASS",
            "TASK_CARD_SHA256: " + ut_digest,
            "GENERATOR_USED: AutoUT EXECUTED_UT: mcde test --ut",
            "- TESTS_TOTAL: 77, TESTS_PASSED: 77, TESTS_FAILED: 0",
            "AC_COVERAGE:", "- 场景A -> TestA", "- 场景B -> TestB",
        ])
        ut_calls = [
            {"name": "Skill", "input": {"skill": "mae-flow:AutoUT"},
             "result_seen": True, "is_error": False, "result": "generated"},
            {"name": "Bash", "input": {"command": "cd build && mcde test --ut"},
             "result_seen": True, "is_error": False, "result": "77 passed, 0 skipped"},
        ]
        ut_first_ok = True
        try:
            dispatch._ut_contract("PASS", ut_report, ut_calls, soft=False)
        except SystemExit:
            ut_first_ok = False
        check("UT 真实 Skill/命令优先于摘要名称且兼容同行数字字段", ut_first_ok)

        # “随 AutoUT 生成”是运行策略，不是要与真实命令逐字相同的字符串。
        json.dump({"current": "rf_ut",
                   "config": {"UT生成方式": "mae-flow:AutoUT Skill", "UT运行命令": "随AutoUT生成"},
                   "agent_tasks": {"UT": ut_task}},
                  open(dispatch.STATE, "w", encoding="utf-8"), ensure_ascii=False)
        dynamic_ut_ok = True
        try:
            dispatch._ut_contract("PASS", ut_report, ut_calls, soft=False)
        except SystemExit:
            dynamic_ut_ok = False
        check("UT 动态运行策略不再与实际命令逐字比较", dynamic_ut_ok)

        fake_run_calls = [ut_calls[0], dict(
            ut_calls[1], input={"command": "echo tests are fine"}, result="77 passed")]
        fake_run_blocked = False
        try:
            dispatch._ut_contract("PASS", ut_report, fake_run_calls, soft=False)
        except SystemExit as exc:
            fake_run_blocked = exc.code == 2
        check("UT 报告命令必须对应 transcript 真实 Bash 调用", fake_run_blocked)

        json.dump({"current": "rf_ut",
                   "config": {"UT生成方式": "mae-flow:AutoUT Skill", "UT运行命令": "mcde test --ut"},
                   "agent_tasks": {"UT": ut_task}},
                  open(dispatch.STATE, "w", encoding="utf-8"), ensure_ascii=False)
        ut_retry_ok = True
        try:
            dispatch._ut_contract("PASS", ut_report, [], soft=True)
        except SystemExit:
            ut_retry_ok = False
        check("UT 报告重答复用同版本生成和测试凭证", ut_retry_ok)
        open("biz_test.cpp", "a", encoding="utf-8").write("int changed_test = 2;\n")
        check("源码或测试变化后 UT 执行凭证立即失效",
              dispatch._reusable_ut_receipt("UT_GENERATOR", ut_task, "mae-flow:AutoUT Skill") is None
              and dispatch._reusable_ut_receipt("UT_RUN", ut_task, "mcde test --ut") is None)
        open("biz_test.cpp", "w", encoding="utf-8").write("int test_value = 1;\n")

        risky_report = ut_report.replace(
            "EXECUTED_UT: mcde test --ut",
            "EXECUTED_UT: mcde test --ut (NeighborCalculatorTest disabled to avoid pre-existing segfault)")
        risky_blocked = False
        try:
            dispatch._ut_contract("PASS", risky_report, ut_calls, soft=False)
        except SystemExit as exc:
            risky_blocked = exc.code == 2
        check("禁用或跳过失败测试不能冒充 UT PASS", risky_blocked)

        filtered_calls = [ut_calls[0], dict(
            ut_calls[1], input={"command": "cd build && mcde test --ut --gtest_filter=ProbeGv*"})]
        filter_blocked = False
        try:
            dispatch._ut_contract("PASS", ut_report, filtered_calls, soft=False)
        except SystemExit as exc:
            filter_blocked = exc.code == 2
        check("任务卡外追加测试过滤参数不能冒充全量 PASS", filter_blocked)

        no_skill_blocked = False
        try:
            dispatch._ut_contract("PASS", ut_report, ut_calls[1:], soft=False)
        except SystemExit as exc:
            no_skill_blocked = exc.code == 2
        rejection = json.load(open(dispatch.REJECTION_STATE, encoding="utf-8")).get("UT", {})
        check("只写 GENERATOR_USED 不能冒充真实 AutoUT 调用",
              no_skill_blocked and "没有成功调用" in rejection.get("reason", ""))
finally:
    os.chdir(old_cwd)
    dispatch.STATE, dispatch.REJECTION_STATE, dispatch.EVIDENCE_STATE = old_dispatch_paths
check("空的精简豁免不能绕过净删检查",
      dispatch._empty_section("无") and dispatch._empty_section("none")
      and not dispatch._empty_section("删除重复分支，行为不变"))
check("空配置不能冒充已执行命令", not dispatch._same_config("", "mcde build -i"))
check("子 Agent 令牌和用户确认均绑定当前步骤",
      '"step": step' in dp and 'm.get("step") == sid' in open(
          os.path.join(ROOT, "scripts", "mae-flow.py"), encoding="utf-8").read())
check("dispatch 在直接模式完整停止旧流程接管",
      "direct mode: bypass" in dp and "不要运行 current/done" in dp)

# 6.1 Comet 阶段门禁只增加一个幂等标记检查；从子目录调用也能找到项目根退出标记。
with tempfile.TemporaryDirectory() as td:
    guard = os.path.join(td, ".cac", "skills", "comet", "scripts", "comet-hook-guard.sh")
    os.makedirs(os.path.dirname(guard), exist_ok=True)
    open(guard, "w", encoding="utf-8").write(
        "#!/bin/bash\nset -euo pipefail\necho blocked >&2\nexit 2\n")
    found1, patched1, errors1 = ensure_direct_mode_compat(td)
    found2, patched2, errors2 = ensure_direct_mode_compat(td)
    os.makedirs(os.path.join(td, "src", "nested"))
    open(os.path.join(td, ".mae-flow.json.exited"), "w", encoding="utf-8").write("{}\n")
    direct = subprocess.run(["bash", guard], cwd=os.path.join(td, "src", "nested"),
                            capture_output=True, text=True)
    os.remove(os.path.join(td, ".mae-flow.json.exited"))
    managed = subprocess.run(["bash", guard], cwd=td, capture_output=True, text=True)
    guard_text = open(guard, encoding="utf-8").read()
    check("Comet Hook 退出兼容幂等且可从子目录识别",
          len(found1) == 1 and len(patched1) == 1 and not errors1
          and len(found2) == 1 and not patched2 and not errors2
          and guard_text.count(COMET_COMPAT_BEGIN) == 1
          and direct.returncode == 0 and managed.returncode == 2)

mf_src = open(os.path.join(ROOT, "scripts", "mae-flow.py"), encoding="utf-8").read()
check("tests_only 缺配置时仍有默认硬边界",
      "def _effective_test_patterns" in mf_src
      and mf_src.count('_effective_test_patterns(st) if step.get("tests_only") else []') >= 2)
check("UT 被测源码变更由 done 自动回流",
      "source_change_recheck" in mf_src and "source-recheck:" in mf_src)
check("旧版 UT 在途状态可安全恢复入口 HEAD",
      "def _ensure_step_entry_head" in mf_src and "recover-step-head" in mf_src
      and "禁止拿当前 HEAD 补位" in mf_src)
check("CodeCheck 解析失败有绑定现场的恢复入口",
      "def cmd_codecheck_record" in mf_src and "diagnostic_sha256" in mf_src
      and "代码一变自动失效" in mf_src)
check("CodeCheck 三个步骤都先首检再决定是否派 Agent",
      'st["current"] not in ("verify_codecheck", "tw_codecheck", "rf_codecheck")' in mf_src
      and 'expected_steps = {"COMPILE"' in mf_src)
check("Bash 任意解释器不能直碰流程状态文件",
      "禁止经 Bash 直接访问" in mf_src and "mae-flow status/current/doctor" in mf_src)
check("STORY 不入库会在推送前检查提交树", "git ls-tree -r --name-only HEAD" in mf_src)
check("STORY 不入库由 done 自动移入过程区",
      'if sid == "story"' in mf_src and 'os.path.join(".mae-flow-work", "story")' in mf_src)

# 6.5 模板与 dispatch 章节校验同步(posttooluse 路由里必须引用同名模板)
for tpl in ("STORY-TEMPLATE.md", "CHAIN-TEMPLATE.md", "GRILL-PREP-TEMPLATE.md", "REVIEW-TEMPLATE.md"):
    check(f"dispatch 模板校验引用 {tpl}", tpl in dp)

# 6.6 PostToolUse matcher 必须覆盖令牌/校验所需工具(漏了 = ASKUSER/UTRUN 令牌静默失效)
if hooks:
    m = ""
    for h in (hooks.get("hooks", {}).get("PostToolUse", []) or []):
        m = h.get("matcher", "") or m
    for need in ("AskUserQuestion", "Bash", "Write"):
        check(f"PostToolUse matcher 含 {need}", need in m)
    pre = " ".join(
        h.get("matcher", "") or ""
        for h in (hooks.get("hooks", {}).get("PreToolUse", []) or []))
    check("月光宝盒可在工具层禁止 AskUserQuestion",
          "AskUserQuestion" in pre and "月光宝盒处于无人值守模式" in dp)

# 7. 关键文件
for f in ("skills/mae-flow/SKILL.md", "skills/mae-flow/assets/STORY-TEMPLATE.md",
          "skills/mae-flow/assets/CHAIN-TEMPLATE.md",
          "skills/mae-flow/assets/GRILL-PREP-TEMPLATE.md",
          "skills/mae-flow/assets/REVIEW-TEMPLATE.md",
          "skills/mae-flow/assets/settings-baseline.json",
          "skills/mae-flow/assets/env-profile.json", "scripts/setup.py", "scripts/comet_compat.py",
          "flow/steps/moonlight_review.md", "commands/mae-flow.md", "README.md", "MAINTAINERS.md"):
    check(f"存在 {f}", os.path.exists(os.path.join(ROOT, f)))

print(f"\n{'全部通过 ✅' if not fails else f'失败 {len(fails)} 项 ❌'}")
sys.exit(1 if fails else 0)
