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
          "scripts/statusline.py", "scripts/setup.py",
          "scripts/mae_flow_core/__init__.py",
          "scripts/mae_flow_core/cli_parser.py",
          "scripts/mae_flow_core/runtime.py",
          "scripts/mae_flow_core/state_store.py",
          "scripts/mae_flow_core/standalone.py",
          "scripts/mae_flow_core/moonlight.py",
          "scripts/tests/test_state_core.py"):
    try:
        py_compile.compile(os.path.join(ROOT, f), doraise=True)
        check(f"语法 {f}", True)
    except Exception as e:
        check(f"语法 {f}", False, str(e))

# 1.5 共享状态内核使用独立测试文件，避免 selftest 再长成第二个单体。
core_tests = subprocess.run(
    [sys.executable, os.path.join(ROOT, "scripts", "tests", "test_state_core.py")],
    text=True, capture_output=True, timeout=90)
check("共享状态内核回归", core_tests.returncode == 0,
      (core_tests.stdout + core_tests.stderr)[-3000:])

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
    good_req = "# 需求\n\n支持中文输入。\n"
    with tempfile.TemporaryDirectory() as td:
        good_path = os.path.join(td, "req.md")
        bad_path = os.path.join(td, "bad.md")
        open(good_path, "w", encoding="utf-8").write(good_req)
        open(bad_path, "wb").write("我确认需求".encode("utf-16"))
        check("需求文本严格校验可识别 UTF-8 与错误编码",
              mf._validate_requirement_document(good_path)[0]
              and not mf._validate_requirement_document(bad_path)[0])

        old_cwd = os.getcwd()
        try:
            os.chdir(td)
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            config_state = {"current": "config_confirm", "config": {}, "choices": {},
                            "history": [], "started": now}
            mf.save_state(config_state)
            with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
                json.dump([{"text": "我确认以上配置", "step": "config_confirm", "at": now}],
                          f, ensure_ascii=False)
            short_ack_ok, _ = mf._ack_verified(config_state, "确认")
            check("主流程确认不接受用户原话中的局部短词", not short_ack_ok)
            with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
                json.dump([{"text": json.dumps({"answer": "我确认以上配置"},
                                               ensure_ascii=False),
                            "step": "config_confirm", "at": now}],
                          f, ensure_ascii=False)
            structured_ack_ok, _ = mf._ack_verified(config_state, "我确认以上配置")
            check("主流程确认兼容宿主结构化应答", structured_ack_ok)
            with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
                json.dump([{"text": json.dumps({
                    "options": ["我确认以上配置", "需要调整配置"],
                    "answer": "需要调整配置",
                }, ensure_ascii=False), "step": "config_confirm", "at": now}],
                          f, ensure_ascii=False)
            option_metadata_ok, _ = mf._ack_verified(config_state, "我确认以上配置")
            check("结构化应答中的候选选项不能冒充用户确认", not option_metadata_ok)
            with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
                json.dump([{"text": "我确认以上配置", "step": "config_confirm", "at": now}],
                          f, ensure_ascii=False)
            failed = False
            try:
                mf.cmd_done(flow, config_state, types.SimpleNamespace(
                    ack="我确认以上配置", choice=None,
                    set=["工号=u1", "基线分支=main", "单号=REQ1", "单号类型=feat",
                         "需求文档=" + bad_path, "编译方式=build-fix",
                         "UT生成方式=AutoUT", "UT运行命令=mcde test --ut"]))
            except SystemExit as exc:
                failed = exc.code == 2
            check("配置失败不会把半套或乱码值写入状态",
                  failed and mf.load_state().get("config") == {})
            with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
                json.dump([{"id": "msg001", "text": "支持中文基站名称查询",
                            "step": "config_confirm", "at": now}], f, ensure_ascii=False)
            mf.cmd_requirement_record(config_state, types.SimpleNamespace(
                ticket="REQ1", message_id="msg001", source=None, replace=False))
            recorded = os.path.join("docs", "req", "REQ-REQ1.md")
            check("需求原文由消息ID确定性写UTF-8并通过正文指纹",
                  os.path.isfile(recorded)
                  and mf._validate_requirement_document(recorded)[0]
                  and "支持中文基站名称查询" in open(recorded, encoding="utf-8").read())
            direct_req_edit_blocked = False
            direct_req_shell_blocked = False
            try:
                mf.cmd_gate(flow, config_state, types.SimpleNamespace(
                    what="edit", arg="docs/req/manual.md"))
            except SystemExit as exc:
                direct_req_edit_blocked = exc.code == 2
            try:
                mf.cmd_gate(flow, config_state, types.SimpleNamespace(
                    what="bash", arg="echo 中文需求 > docs/req/manual.md"))
            except SystemExit as exc:
                direct_req_shell_blocked = exc.code == 2
            check("配置阶段需求原文只能经确定性记录命令落盘",
                  direct_req_edit_blocked and direct_req_shell_blocked)
            mf._ack_verified(config_state, "错误确认")
            _, second_why = mf._ack_verified(config_state, "错误确认")
            check("同一确认通道连续失败两次会熔断并给独立退出路径",
                  "熔断" in second_why and "/mae-flow exit" in second_why)
        finally:
            os.chdir(old_cwd)
    setup_spec = importlib.util.spec_from_file_location(
        "mae_flow_setup", os.path.join(ROOT, "scripts", "setup.py"))
    setup_module = importlib.util.module_from_spec(setup_spec)
    setup_spec.loader.exec_module(setup_module)
    original_dry = setup_module.DRY
    original_run = setup_module.subprocess.run
    try:
        setup_module.DRY = True
        setup_module.subprocess.run = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("dry-run 修改命令不应进入 subprocess"))
        dry_rc, dry_out = setup_module.sh(
            "npm config set registry https://example.invalid", mutate=True)
        check("setup dry-run 不执行配置写入或安装命令",
              dry_rc == 0 and dry_out == "")
    finally:
        setup_module.DRY = original_dry
        setup_module.subprocess.run = original_run
    with tempfile.TemporaryDirectory() as td:
        config_path = os.path.join(td, "config.yaml")
        open(config_path, "w", encoding="utf-8").write(
            "auto_transition: true\nreview_mode: strict\nauto_transition: false\n")
        auto_changed = setup_module.ensure_yaml_value(
            config_path, "auto_transition", "false")
        review_changed = setup_module.ensure_yaml_value(
            config_path, "review_mode", "standard")
        config_text = open(config_path, encoding="utf-8").read()
        check("setup 会纠正错误 YAML 值并清理重复键",
              auto_changed and review_changed
              and config_text.count("auto_transition:") == 1
              and "auto_transition: false" in config_text
              and "review_mode: standard" in config_text)
    profile = json.load(open(
        os.path.join(ROOT, "skills", "mae-flow", "assets", "env-profile.json"),
        encoding="utf-8"))
    check("公开 npm 依赖固定为实测精确版本",
          profile["npm_packages"]["openspec"].endswith("@1.6.0")
          and profile["npm_packages"]["comet"].endswith("@0.3.9"))
    check("同名文件豁免键不会碰撞",
          mf._approval_key("R", "a/Foo.cpp") != mf._approval_key("R", "b/Foo.cpp"))
    check("豁免规则与文件必须在同一条记录",
          not mf._exemption_text_has_pair("- R.ONE | a/Foo.cpp\n- R.TWO | b/Bar.cpp", "R.ONE", "b/Bar.cpp")
          and mf._exemption_text_has_pair("- R.ONE | a/Foo.cpp", "R.ONE", "a/Foo.cpp"))

    # 独立能力：不创建主流程状态、支持未提交代码、默认不提交，完成/取消都不留下源码门禁。
    old_cwd = os.getcwd()
    try:
        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            subprocess.run(["git", "init", "-q"], check=True)
            subprocess.run(["git", "config", "user.email", "mae-flow@test.invalid"], check=True)
            subprocess.run(["git", "config", "user.name", "MAE Flow Test"], check=True)
            open("biz.cpp", "w", encoding="utf-8").write("int value = 1;\n")
            subprocess.run(["git", "add", "biz.cpp"], check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], check=True)
            base_head = mf.sh("git rev-parse HEAD")
            common = dict(source=None, build="build-fix skill", check_only=False)

            empty_scope_blocked = False
            try:
                mf.cmd_action_start(flow, None, types.SimpleNamespace(
                    kind="ut", request="补充单元测试", files=[],
                    generator="AutoUT", ut_command="mcde test --ut", **common))
            except SystemExit as exc:
                empty_scope_blocked = exc.code == 2
            os.makedirs("tests", exist_ok=True)
            open("tests/BizTest.cpp", "w", encoding="utf-8").write("int test_only = 1;\n")
            test_only_blocked = False
            try:
                mf.cmd_action_start(flow, None, types.SimpleNamespace(
                    kind="ut", request="补充单元测试", files=["tests/BizTest.cpp"],
                    generator="AutoUT", ut_command="mcde test --ut", **common))
            except SystemExit as exc:
                test_only_blocked = exc.code == 2
            os.remove("tests/BizTest.cpp")
            os.rmdir("tests")
            check("独立 UT 拒绝空范围和纯测试文件范围",
                  empty_scope_blocked and test_only_blocked
                  and not os.path.exists(mf.ACTION_PATH))

            open("biz.cpp", "a", encoding="utf-8").write("int changed = 2;\n")
            mf.cmd_action_start(flow, None, types.SimpleNamespace(
                kind="ut", request="为 biz.cpp 当前改动补充边界测试", files=["biz.cpp"],
                generator="AutoUT", ut_command="mcde test --ut", **common))
            action = mf._load_action()
            check("独立 UT 启动后只冻结并展示范围，不提前派 Agent",
                  action.get("status") == "awaiting_scope_confirmation"
                  and action.get("files") == ["biz.cpp"]
                  and not action.get("agent_tasks"))
            negative_scope_messages = (
                "我还没确认以上范围",
                "确认以上范围是什么意思？",
                "请问是不是点“确认以上范围”就开始？",
            )
            check("独立任务范围确认不接受否定句和询问句",
                  all(not mf._action_scope_ack_verified(
                      {"scope_proposed_epoch": 1, "user_messages": [
                          {"epoch": 2, "text": text}]},
                      mf.ACTION_SCOPE_ACK)[0]
                      for text in negative_scope_messages))
            forged_scope_ack_blocked = False
            try:
                mf.cmd_action_confirm_scope(
                    flow, types.SimpleNamespace(ack=mf.ACTION_SCOPE_ACK))
            except SystemExit as exc:
                forged_scope_ack_blocked = exc.code == 2
            check("独立任务范围确认不能由 Agent 只带命令参数伪造",
                  forged_scope_ack_blocked)
            scope_prompt = json.dumps(
                {"cwd": td, "prompt": mf.ACTION_SCOPE_ACK},
                ensure_ascii=False) + "\n"
            captured = subprocess.run(
                [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "userprompt"],
                cwd=td, input=scope_prompt, text=True, capture_output=True, timeout=10)
            mf.cmd_action_confirm_scope(
                flow, types.SimpleNamespace(ack=mf.ACTION_SCOPE_ACK))
            action = mf._load_action()
            ut_task = action.get("agent_tasks", {}).get("UT", {})
            check("用户二次确认后独立 UT 才生成任务卡",
                  captured.returncode == 0 and action.get("kind") == "ut"
                  and action.get("scope_confirmed_ack") == mf.ACTION_SCOPE_ACK
                  and ut_task.get("standalone")
                  and os.path.isfile(ut_task.get("path", ""))
                  and not os.path.exists(mf.STATE_PATH)
                  and mf.sh("git rev-parse HEAD") == base_head)
            action.setdefault("tokens", {})["UT"] = {
                "status": "PASS", "report_path": os.path.join(action["work_dir"], "result-ut.md")}
            mf._save_action(action)
            mf.cmd_action_finish(types.SimpleNamespace(report=None))
            check("独立 UT 完成后自动解除控制且不自动提交",
                  not os.path.exists(mf.ACTION_PATH) and mf.sh("git rev-parse HEAD") == base_head
                  and ".mae-flow-work" not in mf.sh("git status --short")
                  and not os.path.exists(".gitignore"))

            os.makedirs("tests", exist_ok=True)
            open("tests/CodeCheckTest.cpp", "w", encoding="utf-8").write(
                "int codecheck_test_only = 1;\n")
            codecheck_test_only_blocked = False
            try:
                mf.cmd_action_start(flow, None, types.SimpleNamespace(
                    kind="codecheck", request="只传测试文件", files=["tests/CodeCheckTest.cpp"],
                    generator=None, ut_command=None, **common))
            except SystemExit as exc:
                codecheck_test_only_blocked = exc.code == 2
            os.remove("tests/CodeCheckTest.cpp")
            os.rmdir("tests")
            check("独立 CodeCheck 排除测试文件且不会把空结果扩大到全仓",
                  codecheck_test_only_blocked and not os.path.exists(mf.ACTION_PATH))

            old_run = mf._run_codecheck
            try:
                calls = []
                mf._run_codecheck = lambda files: (
                    calls.append(list(files)) or
                    {"total": 0, "pairs": [], "commands": ["codecheck fullcheck -f " + ",".join(files)]}, "")
                mf.cmd_action_start(flow, None, types.SimpleNamespace(
                    kind="codecheck", request="检查当前业务改动", files=["biz.cpp"],
                    generator=None, ut_command=None, **common))
                pending_codecheck = mf._load_action()
                check("独立 CodeCheck 范围确认前不运行扫描",
                      pending_codecheck.get("status") == "awaiting_scope_confirmation"
                      and not calls)
                scope_prompt = json.dumps(
                    {"cwd": td, "prompt": mf.ACTION_SCOPE_ACK},
                    ensure_ascii=False) + "\n"
                captured_cc = subprocess.run(
                    [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "userprompt"],
                    cwd=td, input=scope_prompt, text=True, capture_output=True, timeout=10)
                mf.cmd_action_confirm_scope(
                    flow, types.SimpleNamespace(ack=mf.ACTION_SCOPE_ACK))
            finally:
                mf._run_codecheck = old_run
            check("独立 CodeCheck 经用户确认后首检为零不派 Agent",
                  captured_cc.returncode == 0 and calls == [["biz.cpp"]]
                  and not os.path.exists(mf.ACTION_PATH)
                  and not os.path.exists(mf.STATE_PATH)
                  and mf.sh("git rev-parse HEAD") == base_head)

            mf.cmd_action_start(flow, None, types.SimpleNamespace(
                kind="grill", request="支持按名称查询基站", files=[],
                generator=None, ut_command=None, **common))
            grill = mf._load_action()
            prep = grill["grill"]["prep"]
            clarification = grill["grill"]["clarifications"]
            open(prep, "w", encoding="utf-8").write("# 备课\n\n八维检查已完成。\n")
            open(clarification, "w", encoding="utf-8").write(
                "# 澄清结果\n\nWHEN 输入名称为空 THE SYSTEM SHALL 返回参数错误。\n")
            mf.cmd_action_critic(types.SimpleNamespace(
                stage="final", document=clarification))
            grill = mf._load_action()
            grill.setdefault("tokens", {})["GRILL"] = {
                "status": "CLEAR", "report_path": os.path.join(grill["work_dir"], "result-grill.md")}
            mf._save_action(grill)
            mf.cmd_action_finish(types.SimpleNamespace(report=clarification))
            check("独立 Grill 只产出澄清结果且不进入设计编码",
                  not os.path.exists(mf.ACTION_PATH)
                  and not os.path.exists(mf.STATE_PATH)
                  and mf.sh("git rev-parse HEAD") == base_head)
            os.makedirs(os.path.dirname(mf.ACTION_PATH), exist_ok=True)
            open(mf.ACTION_PATH, "w", encoding="utf-8").write("{broken")
            mf.cmd_action_cancel()
            check("独立任务状态损坏也能取消且不影响普通开发",
                  not os.path.exists(mf.ACTION_PATH) and not os.path.exists(mf.STATE_PATH))
            running = {"current": "config_confirm", "config": {}, "choices": {},
                       "history": [], "started": time.strftime("%Y-%m-%d %H:%M:%S")}
            mf.save_state(running)
            overlap_blocked = False
            try:
                mf.cmd_action_start(flow, running, types.SimpleNamespace(
                    kind="grill", request="测试需求", source=None, files=[],
                    build=None, generator=None, ut_command=None, check_only=False))
            except SystemExit as exc:
                overlap_blocked = exc.code == 2
            check("完整流程运行时不会叠加独立任务",
                  overlap_blocked and not os.path.exists(mf.ACTION_PATH))
            os.remove(mf.STATE_PATH)

            # 走真实 argparse/子进程入口，并模拟 Windows 中文控制台编码。
            cli_env = dict(os.environ)
            cli_env["PYTHONIOENCODING"] = "cp936"
            cli_request = "为中文类补充空名称和超长名称边界测试"
            cli = subprocess.run([
                sys.executable, os.path.join(ROOT, "scripts", "mae-flow.py"),
                "action", "start", "ut",
                "--request", cli_request,
                "--files", "biz.cpp",
                "--generator", "AutoUT",
                "--ut-command", "mcde test --ut",
            ], env=cli_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="cp936", errors="replace")
            cli_action = mf._load_action()
            cli_sources = cli_action.get("sources", []) if cli_action else []
            request_text = (open(cli_sources[0], encoding="utf-8").read()
                            if cli_sources and os.path.isfile(cli_sources[0]) else "")
            check("独立任务真实 CLI 在 Windows 中文编码下保持需求原文",
                  cli.returncode == 0 and cli_request in request_text
                  and cli_action.get("status") == "awaiting_scope_confirmation"
                  and not os.path.exists(mf.STATE_PATH), cli.stdout)
            cli_prompt = json.dumps(
                {"cwd": td, "prompt": mf.ACTION_SCOPE_ACK},
                ensure_ascii=False) + "\n"
            cli_capture = subprocess.run(
                [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "userprompt"],
                cwd=td, input=cli_prompt, text=True, capture_output=True, timeout=10)
            cli_confirm = subprocess.run([
                sys.executable, os.path.join(ROOT, "scripts", "mae-flow.py"),
                "action", "confirm-scope", "--ack", mf.ACTION_SCOPE_ACK,
            ], env=cli_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="cp936", errors="replace")
            cli_confirmed_action = mf._load_action()
            check("独立任务真实 CLI 可在 Windows 中文环境完成范围确认",
                  cli_capture.returncode == 0 and cli_confirm.returncode == 0
                  and cli_confirmed_action.get("status") == "active"
                  and cli_confirmed_action.get("agent_tasks", {}).get("UT"),
                  cli_confirm.stdout)
            cancel = subprocess.run([
                sys.executable, os.path.join(ROOT, "scripts", "mae-flow.py"),
                "action", "cancel",
            ], env=cli_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="cp936", errors="replace")
            check("独立任务真实 CLI 可取消并立即解除控制",
                  cancel.returncode == 0 and not os.path.exists(mf.ACTION_PATH),
                  cancel.stdout)
    finally:
        os.chdir(old_cwd)

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
            agent_interactive_blocked = False
            try:
                mf.cmd_exit(flow, st, types.SimpleNamespace(
                    ack="", reason="模拟 Agent 调用", intent=None, interactive=True))
            except SystemExit as exc:
                agent_interactive_blocked = exc.code == 2
            check("TTY 紧急出口不能由非交互 Agent 进程代答",
                  agent_interactive_blocked and os.path.isfile(mf.STATE_PATH))
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
            mf.advance(flow, risk_state, "rf_ut", flow["steps"]["rf_ut"], "done")
            check("进入下一步后用户风险放行不再保留",
                  "risk_acceptances" not in mf.load_state())

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
            subprocess.run(["git", "config", "user.email", "mae-flow@test.invalid"], cwd=td, check=True)
            subprocess.run(["git", "config", "user.name", "MAE Flow Test"], cwd=td, check=True)
            open(os.path.join(td, "biz.cpp"), "w", encoding="utf-8").write("int value = 1;\n")
            subprocess.run(["git", "add", "biz.cpp"], cwd=td, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=td, check=True)
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
                  and not os.path.exists(mf.MOONLIGHT_INTENT_PATH)
                  and "REQ" not in (fresh.get("moonlight") or {}).get("request", "")
                  and "这个需求" in (fresh.get("moonlight") or {}).get("request", ""))

            fresh["current"] = "config_confirm"
            mf.save_state(fresh)
            stop_payload = json.dumps({"cwd": td, "stop_hook_active": False}) + "\n"
            stopped = subprocess.run(
                [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "stop"],
                cwd=td, input=stop_payload, text=True, capture_output=True, timeout=10)
            recursive_stop = subprocess.run(
                [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "stop"],
                cwd=td, input=json.dumps({"cwd": td, "stop_hook_active": True}) + "\n",
                text=True, capture_output=True, timeout=10)
            check("月光宝盒非安全停点会由Stop Hook阻止主Agent提前结束",
                  stopped.returncode == 2 and "禁止提前结束" in stopped.stderr
                  and recursive_stop.returncode == 0)
            mf.cmd_moonlight(flow, fresh, types.SimpleNamespace(
                action="blocked", ack=None,
                reason="缺少公司远端环境访问权限，已检查本地配置仍无法取得，夜间不能继续"))
            blocked_state = mf.load_state()
            allowed_stop = subprocess.run(
                [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "stop"],
                cwd=td, input=stop_payload, text=True, capture_output=True, timeout=10)
            check("真实硬阻塞留痕后Stop Hook允许停止且晨间可原步骤恢复",
                  allowed_stop.returncode == 0
                  and bool((blocked_state.get("moonlight") or {}).get("hard_blocked")))
            mf.cmd_moonlight(flow, blocked_state, types.SimpleNamespace(
                action="repair", ack=None, reason=None))
            check("硬阻塞修复轮保留原步骤继续",
                  mf.load_state().get("current") == "config_confirm"
                  and not (mf.load_state().get("moonlight") or {}).get("hard_blocked"))

            build_state = mf.load_state()
            build_state["current"] = "build"
            build_state["config"].update({"单号": "REQMOONBUILD", "单号类型": "feat",
                                           "CHANGE_NAME": "moon-build"})
            build_state["choices"]["workflow"] = "full"
            build_state.setdefault("step_heads", {})["build"] = mf.sh("git rev-parse --verify HEAD")
            os.makedirs(os.path.join("openspec", "changes", "moon-build"))
            tasks_path = os.path.join("openspec", "changes", "moon-build", "tasks.md")
            open(tasks_path, "w", encoding="utf-8").write("- [ ] 实现功能\n")
            mf.save_state(build_state)
            premature_defer = False
            try:
                mf.cmd_moonlight(flow, build_state, types.SimpleNamespace(
                    action="defer", ack=None,
                    reason="编译暂时失败，已经检查日志但尚未完成全部实现任务"))
            except SystemExit as exc:
                premature_defer = exc.code == 2
            check("build不能借尽力而为跳过未完成实现", premature_defer)

            open(tasks_path, "w", encoding="utf-8").write("- [x] 实现功能\n")
            open("biz.cpp", "a", encoding="utf-8").write("int done = 2;\n")
            subprocess.run(["git", "add", "biz.cpp", tasks_path], check=True)
            subprocess.run(["git", "commit", "-qm", "[REQMOONBUILD][feat]完成需求实现"], check=True)
            mf.cmd_moonlight(flow, build_state, types.SimpleNamespace(
                action="defer", ack=None,
                reason="需求实现任务已全部完成并提交，仅剩公司编译环境不可用，已重试两次"))
            check("build实现完成后可仅对编译遗留尽力放行",
                  mf.load_state().get("current") == "verify_ponytail")
            quality_state = mf.load_state()
            quality_state["current"] = "rf_codecheck"
            mf.save_state(quality_state)
            wrong_blocked = False
            try:
                mf.cmd_moonlight(flow, quality_state, types.SimpleNamespace(
                    action="blocked", ack=None,
                    reason="规范检查失败但不想继续处理，尝试直接停止整个流程"))
            except SystemExit as exc:
                wrong_blocked = exc.code == 2
            check("质量失败不能滥用硬阻塞出口而应走defer", wrong_blocked)

            archive_now = time.strftime("%Y-%m-%d %H:%M:%S")
            archive_state = {
                "current": "archive",
                "config": {"单号": "REQMOONARCH", "CHANGE_NAME": "moon-archive"},
                "choices": {"workflow": "full"}, "history": [], "started": archive_now,
            }
            os.makedirs(os.path.join("openspec", "changes", "moon-archive"))
            mf.save_state(archive_state)
            with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
                json.dump([{"text": "现在切换月光宝盒", "step": "archive", "at": archive_now}], f)
            mf.cmd_moonlight(flow, archive_state, types.SimpleNamespace(
                action="on", ack="月光宝盒", reason=None))
            check("定稿尚未执行时中途切月光宝盒会先推送不自动定稿",
                  mf.load_state().get("current") == "push")

            partial_state = {
                "current": "archive",
                "config": {"单号": "REQMOONARCH2", "CHANGE_NAME": "missing-change"},
                "choices": {"workflow": "full"}, "history": [], "started": archive_now,
            }
            mf.save_state(partial_state)
            with open(mf.STATE_PATH + ".usermsg", "w", encoding="utf-8") as f:
                json.dump([{"text": "月光宝盒继续", "step": "archive", "at": archive_now}], f)
            mf.cmd_moonlight(flow, partial_state, types.SimpleNamespace(
                action="on", ack="月光宝盒", reason=None))
            partial = mf.load_state()
            check("定稿可能已开始时不自动回滚或补做而是记录硬阻塞",
                  partial.get("current") == "archive"
                  and bool((partial.get("moonlight") or {}).get("hard_blocked")))

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
                  and "切换月光宝盒继续做" in (resumed.get("moonlight") or {}).get("request", "")
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

            # 这里是在同一个临时仓库中构造另一条晨间修复分支，不是拿生产中的
            # 旧快照覆盖新状态；去掉 CAS 字段，明确表达“测试夹具重新装载”。
            morning_fixture = json.loads(json.dumps(morning))
            morning_fixture.pop("revision", None)
            morning_fixture.pop("updated_at", None)
            mf.save_state(morning_fixture)
            mf.cmd_moonlight(flow, morning_fixture, types.SimpleNamespace(
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
            check("评审意见处理晨间修复完成后可直接结束",
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
            check("完整开发月光轮先跳过归档进入push",
                  skipped_archive.get("current") == "push"
                  and any(h.get("result") == "moonlight:archive-deferred"
                          for h in skipped_archive.get("history", [])))
            mf.advance(flow, skipped_archive, "push", flow["steps"]["push"], "done")
            full_morning = mf.load_state()
            mf.cmd_moonlight(flow, full_morning, types.SimpleNamespace(
                action="finalize", ack=None, reason=None))
            full_finalized = mf.load_state()
            check("完整开发晨间finalize恢复普通规格定稿",
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
        if name in ("compile-agent", "codecheck-fix-agent", "ut-generator-agent",
                    "grill-critic-agent"):
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

old_cwd = os.getcwd()
try:
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        subprocess.run(["git", "init", "-q"], check=True)
        subprocess.run(["git", "config", "user.email", "mae-flow@test.invalid"], check=True)
        subprocess.run(["git", "config", "user.name", "MAE Flow Test"], check=True)
        open("biz.cpp", "w", encoding="utf-8").write("int value = 1;\n")
        subprocess.run(["git", "add", "biz.cpp"], check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], check=True)
        open("biz.cpp", "a", encoding="utf-8").write("int dirty_before_task = 2;\n")
        head = subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True).stdout.strip()
        body = "# STANDALONE UT TASK\n"
        digest = __import__("hashlib").sha256(body.encode("utf-8")).hexdigest()
        work = os.path.join(td, ".mae-flow-work", "standalone", "test-ut")
        os.makedirs(work, exist_ok=True)
        task_path = os.path.join(work, "ut-task.md")
        open(task_path, "w", encoding="utf-8").write(
            body + "TASK_CARD_SHA256: " + digest + "\n")
        task = {
            "step": "standalone_ut", "sha256": digest, "path": task_path,
            "head": head, "standalone": True,
            "initial_source_fingerprints": {"biz.cpp": dispatch._path_fingerprint("biz.cpp")},
        }
        action = {
            "id": "test-ut", "kind": "ut", "status": "active",
            "expires_epoch": time.time() + 3600, "work_dir": work,
            "config": {"UT生成方式": "AutoUT", "UT运行命令": "mcde test --ut"},
            "agent_tasks": {"UT": task}, "tokens": {}, "rejections": {},
        }
        os.makedirs(os.path.dirname(dispatch.ACTION_STATE), exist_ok=True)
        json.dump(action, open(dispatch.ACTION_STATE, "w", encoding="utf-8"), ensure_ascii=False)
        open("biz_test.cpp", "w", encoding="utf-8").write("int test_value = 1;\n")
        report = "\n".join([
            "UT_RESULT: PASS", "TASK_CARD_SHA256: " + digest,
            "GENERATOR_USED: AutoUT", "EXECUTED_UT: mcde test --ut",
            "TESTS_TOTAL: 1", "TESTS_PASSED: 1", "TESTS_FAILED: 0",
            "AC_COVERAGE: 当前改动 -> TestValue",
            "PENDING_QUESTIONS: 无", "KNOWN_FAILURES: 无", "SUSPECTED_BUGS: 无",
        ])
        calls = [
            {"name": "Skill", "input": {"skill": "AutoUT"},
             "result_seen": True, "is_error": False, "result": "generated"},
            {"name": "Bash", "input": {"command": "mcde test --ut"},
             "result_seen": True, "is_error": False, "result": "1 passed"},
        ]
        standalone_ok = True
        try:
            dispatch._ut_contract("PASS", report, calls, soft=False)
            dispatch._record_agent_token("UT", "PASS", report)
        except SystemExit:
            standalone_ok = False
        saved_action = json.load(open(dispatch.ACTION_STATE, encoding="utf-8"))
        check("独立 UT 契约允许原有未提交源码但只接受测试改动",
              standalone_ok and saved_action.get("tokens", {}).get("UT", {}).get("status") == "PASS"
              and not os.path.exists(dispatch.STATE))
        grill_body = "# STANDALONE GRILL TASK\n"
        grill_digest = __import__("hashlib").sha256(grill_body.encode("utf-8")).hexdigest()
        grill_task_path = os.path.join(work, "grill-final-task.md")
        open(grill_task_path, "w", encoding="utf-8").write(
            grill_body + "TASK_CARD_SHA256: " + grill_digest + "\n")
        grill_task = {
            "step": "standalone_grill", "sha256": grill_digest,
            "path": grill_task_path, "head": head, "standalone": True, "stage": "final",
            "initial_source_fingerprints": {
                "biz.cpp": dispatch._path_fingerprint("biz.cpp"),
                "biz_test.cpp": dispatch._path_fingerprint("biz_test.cpp"),
            },
        }
        action.update({
            "kind": "grill", "config": {}, "agent_tasks": {"GRILL": grill_task},
            "tokens": {}, "rejections": {},
        })
        json.dump(action, open(dispatch.ACTION_STATE, "w", encoding="utf-8"), ensure_ascii=False)
        grill_report = "\n".join([
            "GRILL_RESULT: CLEAR", "TASK_CARD_SHA256: " + grill_digest,
            "STAGE: final", "GAPS_FOUND: 0", "MISSING_BRANCHES: 无",
        ])
        grill_ok = True
        try:
            dispatch._grill_contract("CLEAR", grill_report, [], soft=False)
        except SystemExit:
            grill_ok = False
        check("独立 Grill critic 契约接受 CLEAR 并核对阶段与缺口数", grill_ok)
finally:
    os.chdir(old_cwd)

check("空的精简豁免不能绕过净删检查",
      dispatch._empty_section("无") and dispatch._empty_section("none")
      and not dispatch._empty_section("删除重复分支，行为不变"))
check("空配置不能冒充已执行命令", not dispatch._same_config("", "mcde build -i"))
check("子 Agent 令牌和用户确认均绑定当前步骤",
      '"step": step' in dp and 'm.get("step") == sid' in open(
          os.path.join(ROOT, "scripts", "mae-flow.py"), encoding="utf-8").read())
check("dispatch 在直接模式完整停止旧流程接管",
      "direct mode: bypass" in dp and "不要运行 current/done" in dp)
check("明确自然语言退出会触发、询问退出不会误触发",
      dispatch._explicit_exit_prompt("不想用这个工作流了，后面直接让 AI 补 UT")
      and not dispatch._explicit_exit_prompt("这个工作流能不能退出？"))

# 插件全局安装不得接管未 init 的普通项目；Windows 控制台代码页也不得污染 Hook 的 UTF-8 JSON。
with tempfile.TemporaryDirectory() as td:
    subprocess.run(["git", "init", "-q", td], check=True)
    payload = json.dumps({
        "cwd": td,
        "tool_name": "Edit",
        "tool_input": {"file_path": os.path.join(td, "src", "普通代码.cpp")},
    }, ensure_ascii=False) + "\n"
    inactive = subprocess.run(
        [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "pretooluse"],
        cwd=td, input=payload, text=True, capture_output=True, timeout=10)
    check("仅安装插件、未 init 时所有工具门禁完整旁路", inactive.returncode == 0)

    state = {"current": "config_confirm", "config": {}, "choices": {},
             "history": [], "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(td, ".mae-flow.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)
    user_payload = json.dumps({
        "cwd": td, "prompt": "我确认中文需求：支持基站名称查询"
    }, ensure_ascii=False) + "\n"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp936"
    captured = subprocess.run(
        [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "userprompt"],
        cwd=td, input=user_payload.encode("utf-8"), capture_output=True, timeout=10, env=env)
    messages = json.load(open(os.path.join(td, ".mae-flow.json.usermsg"), encoding="utf-8"))
    check("Windows 非 UTF-8 控制台下 Hook 仍按原始 UTF-8 捕获中文",
          captured.returncode == 0
          and messages[-1]["text"] == "我确认中文需求：支持基站名称查询"
          and messages[-1].get("input_encoding") == "utf-8-sig")

with tempfile.TemporaryDirectory() as td:
    subprocess.run(["git", "init", "-q", td], check=True)
    action_dir = os.path.join(td, ".mae-flow-work", "standalone", "test-action")
    os.makedirs(action_dir)
    action_path = os.path.join(td, ".mae-flow-work", "standalone-action.json")
    json.dump({"id": "test-action", "kind": "ut", "status": "active",
               "expires_epoch": time.time() + 3600, "work_dir": action_dir,
               "config": {}, "agent_tasks": {}, "tokens": {}},
              open(action_path, "w", encoding="utf-8"))
    ordinary_payload = json.dumps({
        "cwd": td, "tool_name": "Edit",
        "tool_input": {"file_path": os.path.join(td, "src", "ordinary.cpp")},
    }) + "\n"
    internal_payload = json.dumps({
        "cwd": td, "tool_name": "Edit",
        "tool_input": {"file_path": os.path.join(action_dir, "ut-task.md")},
    }) + "\n"
    ordinary = subprocess.run(
        [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "pretooluse"],
        cwd=td, input=ordinary_payload, text=True, capture_output=True, timeout=10)
    internal = subprocess.run(
        [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "pretooluse"],
        cwd=td, input=internal_payload, text=True, capture_output=True, timeout=10)
    check("独立任务只保护任务卡而不拦普通源码编辑",
          ordinary.returncode == 0 and internal.returncode == 2)
    # 完整流程退出记录会长期保留；独立任务提示必须覆盖旧的普通开发提示。
    json.dump({"snapshot": "old-flow"},
              open(os.path.join(td, ".mae-flow.json.exited"), "w", encoding="utf-8"))
    prompt_payload = json.dumps({"cwd": td, "prompt": "继续补单元测试"},
                                ensure_ascii=False) + "\n"
    injected = subprocess.run(
        [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "userprompt"],
        cwd=td, input=prompt_payload, text=True, capture_output=True, timeout=10)
    check("退出完整流程后独立任务状态仍优先注入",
          injected.returncode == 0
          and "当前有独立 UT 任务 test-action" in injected.stdout
          and "不要运行 current/done" not in injected.stdout)

with tempfile.TemporaryDirectory() as td:
    # 父目录的旧状态不能越过最近 .git 边界接管一个独立子仓。
    with open(os.path.join(td, ".mae-flow.json"), "w", encoding="utf-8") as f:
        json.dump({"current": "verify_ut", "config": {}, "choices": {},
                   "history": [], "started": "2026-07-23 20:00:00"}, f)
    nested = os.path.join(td, "independent-repo")
    subprocess.run(["git", "init", "-q", nested], check=True)
    child = os.path.join(nested, "src", "module")
    os.makedirs(child)
    root, has_state = mf.find_project_root(child)
    payload = json.dumps({
        "cwd": child,
        "tool_name": "Edit",
        "tool_input": {"file_path": os.path.join(child, "ordinary.cpp")},
    }) + "\n"
    isolated = subprocess.run(
        [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "pretooluse"],
        cwd=child, input=payload, text=True, capture_output=True, timeout=10)
    check("父目录陈旧状态不会越过独立仓边界误接管",
          root == nested and not has_state and isolated.returncode == 0)

with tempfile.TemporaryDirectory() as td:
    subprocess.run(["git", "init", "-q", td], check=True)
    subprocess.run(["git", "config", "user.email", "mae-flow@test.invalid"], cwd=td, check=True)
    subprocess.run(["git", "config", "user.name", "MAE Flow Test"], cwd=td, check=True)
    open(os.path.join(td, "biz.cpp"), "w", encoding="utf-8").write("int value = 1;\n")
    subprocess.run(["git", "add", "biz.cpp"], cwd=td, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=td, check=True)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(td, ".mae-flow.json"), "w", encoding="utf-8") as f:
        json.dump({"current": "env_setup", "config": {}, "choices": {},
                   "history": [], "started": now}, f, ensure_ascii=False)
    exit_payload = json.dumps({"cwd": td, "prompt": "/mae-flow exit"},
                              ensure_ascii=False) + "\n"
    exited = subprocess.run(
        [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "userprompt"],
        cwd=td, input=exit_payload, text=True, capture_output=True, timeout=15)
    exit_record = json.load(open(os.path.join(td, ".mae-flow.json.exited"), encoding="utf-8"))
    check("明确 /mae-flow exit 由用户事件直接退出且不依赖 ack 账本",
          exited.returncode == 0
          and not os.path.exists(os.path.join(td, ".mae-flow.json"))
          and exit_record.get("authorization") == "userprompt-hook")

with tempfile.TemporaryDirectory() as td:
    subprocess.run(["git", "init", "-q", td], check=True)
    open(os.path.join(td, ".mae-flow.json"), "w", encoding="utf-8").write('{"current":')
    exit_payload = json.dumps({"cwd": td, "prompt": "/mae-flow exit"},
                              ensure_ascii=False) + "\n"
    escaped = subprocess.run(
        [sys.executable, os.path.join(ROOT, "hooks", "dispatch.py"), "userprompt"],
        cwd=td, input=exit_payload, text=True, capture_output=True, timeout=15)
    corrupt_record = json.load(open(os.path.join(td, ".mae-flow.json.exited"), encoding="utf-8"))
    saved_bad = os.path.join(td, corrupt_record["snapshot"], ".mae-flow.json")
    check("状态 JSON 损坏时用户仍可一键逃生且坏现场被保留",
          escaped.returncode == 0
          and corrupt_record.get("authorization") == "userprompt-hook-corrupt-state"
          and os.path.isfile(saved_bad))

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
check("带短横线的一次性退出凭据也在状态黑名单内",
      r"(?:\.[\w-]+)*" in mf_src and "EXIT_INTENT_PATH" in mf_src)
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
    stop_hooks = hooks.get("hooks", {}).get("Stop", []) or []
    check("月光宝盒注册主Agent安全停点Stop Hook",
          bool(stop_hooks) and "def ev_stop" in dp and "moonlight blocked" in dp)

# 7. 关键文件
for f in ("skills/mae-flow/SKILL.md", "skills/mae-flow/assets/STORY-TEMPLATE.md",
          "skills/mae-flow/assets/CHAIN-TEMPLATE.md",
          "skills/mae-flow/assets/GRILL-PREP-TEMPLATE.md",
          "skills/mae-flow/assets/REVIEW-TEMPLATE.md",
          "skills/mae-flow/assets/settings-baseline.json",
          "skills/mae-flow/assets/env-profile.json", "scripts/setup.py", "scripts/comet_compat.py",
          "flow/steps/moonlight_review.md", "commands/mae-flow.md", "README.md",
          "MAINTAINERS.md", "VERSION", "CHANGELOG.md", ".gitattributes"):
    check(f"存在 {f}", os.path.exists(os.path.join(ROOT, f)))

version = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
changelog = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
check("VERSION、README 与 CHANGELOG 版本一致",
      bool(re.fullmatch(r"\d+\.\d+\.\d+", version))
      and ("## " + version) in changelog
      and ("`" + version + "`") in readme)

print(f"\n{'全部通过 ✅' if not fails else f'失败 {len(fails)} 项 ❌'}")
sys.exit(1 if fails else 0)
