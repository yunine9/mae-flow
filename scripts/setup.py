#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mae-flow 环境安装器 — 确定性流水线(装东西不动脑,幂等可重跑)。

分工(2026-07-20 实战定型):A 类确定性安装全在本脚本;C 类诊断归 env-setup-agent
(修环境参数后重跑本脚本,不自己装);B 类交互项(基础件/comet init)只给三要素话术。
环境常量读 assets/env-profile.json(换代理/镜像只改那一个文件)。

用法:
  python setup.py               在项目根执行(含项目级配置);其他目录执行只做机器级
  python setup.py --dry-run     只打印将执行的动作,不改任何东西
  python setup.py --offline 目录  npm 包改从该目录的 .tgz 安装(内网全不通时)

输出:每步 ✅ / ⚠人工 / ❌;日志 %TEMP%\\mae-flow-setup.log(发维护人只发这一个文件)。
退出码:0 全绿;2 存在 ⚠人工 或 ❌(需诊断)。
"""
import argparse, glob, json, os, re, subprocess, sys, tempfile, time

from comet_compat import comet_guard_paths, ensure_direct_mode_compat

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILE_PATH = os.path.join(HERE, "..", "skills", "mae-flow", "assets", "env-profile.json")
BASELINE_PATH = os.path.join(HERE, "..", "skills", "mae-flow", "assets", "settings-baseline.json")
LOG = os.path.join(tempfile.gettempdir(), "mae-flow-setup.log")
CONFIG_BACKUP = os.path.join(
    tempfile.gettempdir(),
    "mae-flow-setup-config-before-%s-%s.json" %
    (time.strftime("%Y%m%d-%H%M%S"), os.getpid()))
DRY = False
RESULTS = []   # (状态, 步骤名, 详情) 状态: OK|FIXED|PLAN|MANUAL|FAIL
CONFIG_BEFORE = {}


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg
    print(msg)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def sh(cmd, timeout=300, mutate=False):
    """执行并回收全部输出；dry-run 仍做只读探测，只跳过明确标记的修改命令。"""
    if DRY and mutate:
        log("  [dry-run] " + cmd)
        return 0, ""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write("$ %s\nrc=%s\n%s\n" % (cmd, r.returncode, out.strip()[-2000:]))
        except Exception:
            pass
        return r.returncode, out
    except Exception as e:
        log("  执行异常: %s" % e)
        return 1, str(e)


def mark(status, name, detail=""):
    RESULTS.append((status, name, detail))
    icon = {
        "OK": "✅",
        "FIXED": "✅(已配置)",
        "PLAN": "📝(计划修改)",
        "MANUAL": "⚠人工",
        "FAIL": "❌",
    }[status]
    log("%s %s%s" % (icon, name, ("" if not detail else " — " + detail.splitlines()[0][:120])))


def remember_config(name, value):
    """Persist pre-setup global config with owner-only permissions before mutation."""
    if DRY or name in CONFIG_BEFORE:
        return
    CONFIG_BEFORE[name] = value
    fd = os.open(CONFIG_BACKUP, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(CONFIG_BEFORE, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def ensure_cli_config(name, get_cmd, set_cmd, expected):
    """Reconcile one npm/git config value instead of trusting one sentinel key."""
    rc, out = sh(get_cmd, timeout=30)
    current = out.strip() if rc == 0 else ""

    def normalized(value):
        return str(value).strip().rstrip("/").lower()

    if normalized(current) == normalized(expected):
        return False, ""
    remember_config(name, current)
    rc, out = sh(set_cmd, timeout=30, mutate=True)
    if rc != 0:
        return False, (out.strip().splitlines()[-1][:160] if out.strip() else "设置失败")
    if not DRY:
        verify_rc, verify_out = sh(get_cmd, timeout=30)
        if verify_rc != 0 or normalized(verify_out) != normalized(expected):
            return False, "设置命令返回成功，但复验值仍为 %s" % (
                verify_out.strip() or "(空)")
    return True, ""


def need_reload(reason):
    """打"待重启"标记:任何"磁盘变了但会话没加载"的动作(装插件/迁移目录)都要调。
    只有 SessionStart(重启会话)能清它,env 步的 path_absent 证据据此在最开始拦住,
    不重启不放行——否则 skill/plugin 没加载就往下走,AI 会手搓空壳绕过(2026-07-20 实战)。"""
    if DRY:
        return
    try:
        old = open(".mae-flow-need-reload", encoding="utf-8").read() if os.path.exists(".mae-flow-need-reload") else ""
        if reason not in old:
            open(".mae-flow-need-reload", "a", encoding="utf-8").write(reason + "\n")
    except Exception:
        pass


def npm_install(name, spec, offline_dir):
    """幂等安装一个全局 npm 包:失败 → 清缓存重试 → EPERM 换用户级 prefix 重试 → FAIL(带诊断线索)。"""
    if offline_dir:
        cand = glob.glob(os.path.join(offline_dir, "*%s*.tgz" % name))
        if not cand:
            mark("FAIL", name, "离线目录无 %s 的 .tgz 包: %s" % (name, offline_dir))
            return
        spec = '"%s"' % cand[0]
    rc, out = sh("npm install -g %s" % spec, timeout=600, mutate=True)
    if rc != 0:
        sh("npm cache clean --force", timeout=120, mutate=True)
        rc, out = sh("npm install -g %s" % spec, timeout=600, mutate=True)
    if rc != 0 and re.search(r"EPERM|EACCES", out) and os.environ.get("APPDATA"):
        sh('npm config set prefix "%s"' % os.path.join(os.environ["APPDATA"], "npm"),
           mutate=True)
        rc, out = sh("npm install -g %s" % spec, timeout=600, mutate=True)
    if rc == 0:
        mark("PLAN" if DRY else "FIXED", name)
    else:
        hint = "代理要求认证(407):需要提供代理凭据,交用户/诊断 agent" if "407" in out else \
               "网络/镜像不通?核对 env-profile.json 的 registry 与 proxy" if re.search(r"ETIMEDOUT|ENOTFOUND|ECONNREFUSED|network", out, re.I) else \
               "见日志 " + LOG
        mark("FAIL", name, hint + " | " + out.strip().splitlines()[-1][:160] if out.strip() else hint)


def ensure_yaml_value(path, key, value):
    """Ensure one top-level scalar has the requested value and remove duplicates."""
    txt = open(path, encoding="utf-8", errors="replace").read() if os.path.exists(path) else ""
    newline = "\r\n" if "\r\n" in txt else "\n"
    lines = txt.splitlines()
    pattern = re.compile(r"^%s\s*:" % re.escape(key))
    matches = [i for i, line in enumerate(lines) if pattern.match(line)]
    wanted = "%s: %s" % (key, value)
    if len(matches) == 1 and lines[matches[0]].strip() == wanted:
        return False
    if matches:
        first = matches[0]
        lines[first] = wanted
        lines = [line for i, line in enumerate(lines)
                 if i == first or i not in set(matches[1:])]
    else:
        lines.append(wanted)
    if not DRY:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        updated = newline.join(lines) + newline
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(updated)
    return True


def merge_settings(scripts_dir):
    """settings 合并:statusLine(缺则加)+ permissions 基线(追加缺失)。读-改-写,其他键原样保留。"""
    root = ".cac" if os.path.isdir(".cac") else ".claude"
    p = os.path.join(root, "settings.json")
    try:
        s = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    except Exception:
        mark("FAIL", "settings 合并", p + " 已存在但不是合法 JSON,先修复它")
        return
    changed = False
    if "statusLine" not in s:
        s["statusLine"] = {"type": "command",
                           "command": 'python "%s"' % os.path.join(scripts_dir, "statusline.py")}
        changed = True
    try:
        base = json.load(open(BASELINE_PATH, encoding="utf-8")).get("permissions", {})
    except Exception:
        base = {}
    perms = s.setdefault("permissions", {})
    for k in ("deny", "allow"):
        have = perms.setdefault(k, [])
        for item in base.get(k, []):
            if item not in have:
                have.append(item)
                changed = True
    if changed and not DRY:
        os.makedirs(root, exist_ok=True)
        tmp = p + ".tmp"
        json.dump(s, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    mark(("PLAN" if DRY else "FIXED") if changed else "OK",
         "settings(statusline+权限基线)", "重启会话生效" if changed else "")


def main():
    global DRY
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--offline", default="")
    args = ap.parse_args()
    DRY = args.dry_run
    prof = json.load(open(PROFILE_PATH, encoding="utf-8"))
    offline = args.offline or prof.get("offline_dir", "")
    log("═══ mae-flow 环境安装器 %s═══" % ("(dry-run) " if DRY else ""))

    # ---- 基础件(不代装,缺了立即停:后续全部依赖它们) ----
    base_missing = []
    for name, cmd in (("Git Bash", "bash --version"), ("Git", "git --version")):
        rc, _ = sh(cmd, timeout=20)
        mark("OK" if rc == 0 else "MANUAL", name, "" if rc == 0 else "请自行安装 Git for Windows")
        if rc != 0:
            base_missing.append(name)
    rc, out = sh("node --version", timeout=20)
    m = re.match(r"v(\d+)\.(\d+)\.(\d+)", out.strip())
    node_ok = bool(m) and tuple(map(int, m.groups())) >= tuple(map(int, prof["node_min"].split(".")))
    mark("OK" if node_ok else "MANUAL", "Node.js >= " + prof["node_min"],
         "" if node_ok else "请自行安装 Node.js(当前: %s)" % (out.strip() or "未安装"))
    if not node_ok:
        base_missing.append("Node.js")
    if base_missing and not DRY:
        return finish()

    # ---- npm / git 网络配置(逐项收敛；修改前备份，不能只看 registry/http.proxy 一个哨兵) ----
    npm_items = [
        ("npm.registry", "npm config get registry",
         "npm config set registry " + prof["npm_registry"], prof["npm_registry"]),
        ("npm.proxy", "npm config get proxy",
         "npm config set proxy " + prof["proxy"], prof["proxy"]),
        ("npm.https-proxy", "npm config get https-proxy",
         "npm config set https-proxy " + prof["proxy"], prof["proxy"]),
        ("npm.strict-ssl", "npm config get strict-ssl",
         "npm config set strict-ssl " + str(prof.get("npm_strict_ssl", False)).lower(),
         str(prof.get("npm_strict_ssl", False)).lower()),
    ]
    git_items = [
        ("git.http.proxy", "git config --global --get http.proxy",
         "git config --global http.proxy " + prof["proxy"], prof["proxy"]),
        ("git.https.proxy", "git config --global --get https.proxy",
         "git config --global https.proxy " + prof["proxy"], prof["proxy"]),
        ("git.http.sslVerify", "git config --global --get http.sslVerify",
         "git config --global http.sslVerify "
         + str(prof.get("git_ssl_verify", False)).lower(),
         str(prof.get("git_ssl_verify", False)).lower()),
    ]
    for label, items in (("npm 镜像源+代理", npm_items), ("git 代理", git_items)):
        changed, errors = False, []
        for name, get_cmd, set_cmd, expected in items:
            item_changed, err = ensure_cli_config(name, get_cmd, set_cmd, expected)
            changed = changed or item_changed
            if err:
                errors.append(name + ":" + err)
        detail = ("修改前配置备份: " + CONFIG_BACKUP) if changed and not DRY else ""
        mark("FAIL" if errors else (("PLAN" if DRY else "FIXED") if changed else "OK"),
             label, "；".join(errors) if errors else detail)

    # ---- scoped registries(私有 scope,如 @baize 的 codecheckcli 走 centralrepo,与主镜像不同) ----
    scoped = prof.get("npm_scoped_registries", {})
    if scoped:
        scoped_changed, scoped_errors = False, []
        for scope, reg in scoped.items():
            changed, err = ensure_cli_config(
                "npm.%s:registry" % scope,
                "npm config get %s:registry" % scope,
                "npm config set %s:registry=%s" % (scope, reg),
                reg)
            scoped_changed = scoped_changed or changed
            if err:
                scoped_errors.append(scope + ":" + err)
        mark("FAIL" if scoped_errors else (
            ("PLAN" if DRY else "FIXED") if scoped_changed else "OK"),
             "npm scoped registries",
             "；".join(scoped_errors) if scoped_errors else "、".join(scoped))

    # ---- CLI 安装(幂等:有则跳过) ----
    # 已装判据:openspec/comet 用 --version 退出码;codecheck 别赌退出码(help/version 常非零退出),
    # 也别用命令名(未装报错含命令名会误判)——用 fullcheck --help 输出含 "fullcheck"(未装报错不含它)
    for name, key, probe, pat in (("OpenSpec CLI", "openspec", "openspec --version", None),
                                  ("Comet CLI", "comet", "comet --version", None),
                                  ("CodeCheck CLI", "codecheck", "codecheck fullcheck --help", "fullcheck")):
        rc, out = sh(probe, timeout=30)
        ok = (rc == 0) if pat is None else bool(re.search(pat, out or "", re.I))
        if ok:
            mark("OK", name)
        else:
            npm_install(key, prof["npm_packages"][key], offline)
    if not DRY:
        _, installed_versions = sh(
            "npm list -g --depth=0 @fission-ai/openspec @rpamis/comet @baize/codecheckcli",
            timeout=60)
        log("已安装 npm 工具版本:\n" + (installed_versions.strip() or "(无法读取)"))

    # ---- codeagent 插件(幂等:装没装只认 plugin list 的复验结果) ----
    rc, listed = sh(prof["plugin_cli"] + " plugin list", timeout=60)
    for pl in prof["plugins"]:
        if pl["name"].lower() in listed.lower():
            mark("OK", "插件 " + pl["name"])
            continue
        for c in pl["cmds"]:
            sh(c, timeout=600, mutate=True)  # 单条命令报错不当致命,成败以复验为准
        if DRY:
            mark("PLAN", "插件 " + pl["name"], "实际安装后需重启会话")
            continue
        rc, listed2 = sh(prof["plugin_cli"] + " plugin list", timeout=60)
        if pl["name"].lower() in listed2.lower():
            mark("FIXED", "插件 " + pl["name"], "需重启会话生效")
            need_reload("新装插件 %s,需重启会话加载" % pl["name"])
            listed = listed2
        else:
            mark("FAIL", "插件 " + pl["name"],
                 "装后复验仍不在 plugin list;常见根因是 git 代理不通,见日志 " + LOG)

    # ---- 项目级(仅在项目根执行时;顺序:先验 init,未初始化则全部跳过——没地基不装修) ----
    if os.path.isdir(".git"):
        comet_skills = [
            os.path.join(base, "skills", "comet")
            for base in (".cac", ".claude")
        ]
        inited = (any(os.path.isdir(path) for path in comet_skills)
                  or any(os.path.isfile(path) for path in comet_guard_paths(os.getcwd())))
        if not inited:
            mark("MANUAL", "comet 项目初始化",
                 "交互式命令必须人工执行(自动化会初始化全部 agent 平台,已被禁止)。三要素:"
                 "①目录 %s ②命令 comet init --language zh --scope project ③平台只选 Claude Code。"
                 "跑完重跑本脚本,其余项目级配置(comet 开关/状态栏/权限/目录迁移)届时自动补齐" % os.getcwd())
        else:
            mark("OK", "comet 项目初始化")
            if DRY:
                guards = [p for p in comet_guard_paths(os.getcwd()) if os.path.isfile(p)]
                mark("OK" if guards else "FAIL", "直接开发逃生通道",
                     "将为项目阶段门禁加入退出标记兼容" if guards else "未找到 comet-hook-guard.sh")
            else:
                guards, patched, errors = ensure_direct_mode_compat(os.getcwd())
                if errors or not guards:
                    mark("FAIL", "直接开发逃生通道",
                         "；".join(errors) if errors else "未找到项目级 comet-hook-guard.sh，请重新执行 comet init/update")
                else:
                    mark("FIXED" if patched else "OK", "直接开发逃生通道",
                         "已让阶段门禁识别 mae-flow 退出标记" if patched else "")
            ch = ensure_yaml_value(
                os.path.join(".comet", "config.yaml"), "auto_transition", "false")
            ch = ensure_yaml_value(
                os.path.join(".comet", "config.yaml"), "review_mode", "standard") or ch
            mark(("PLAN" if DRY else "FIXED") if ch else "OK",
                 ".comet/config.yaml(auto_transition+review_mode)")
            if os.path.isdir(".claude") and not os.path.isdir(".cac"):
                if not DRY:
                    os.rename(".claude", ".cac")
                need_reload("skill 迁移到 .cac,需重启会话加载")
                mark("MANUAL", ".claude → .cac 迁移",
                     "⚠ skill 已迁移但会话未加载:**重启会话**(最稳;/reload-skills 后若仍提示也请重启),回来说\"继续\"")
            elif os.path.isdir(".claude") and os.path.isdir(".cac"):
                mark("MANUAL", "目录合并", ".claude 与 .cac 并存,请人工确认合并后删除 .claude(有覆盖风险,不自动做)")
            merge_settings(HERE)
    else:
        log("(当前目录无 .git,跳过项目级配置——在项目根重跑本脚本可补齐)")

    return finish()


def finish():
    plans = [r for r in RESULTS if r[0] == "PLAN"]
    manual = [r for r in RESULTS if r[0] == "MANUAL"]
    fail = [r for r in RESULTS if r[0] == "FAIL"]
    log("──── 汇总 ────")
    log("✅ %d 项就绪/已配置;📝计划修改 %d 项;⚠人工 %d 项;❌ %d 项。日志: %s" % (
        len(RESULTS) - len(plans) - len(manual) - len(fail),
        len(plans), len(manual), len(fail), LOG))
    if manual:
        log("⚠人工项(处理完重跑本脚本):")
        for _, n, d in manual:
            log("   - %s:%s" % (n, d))
    if fail:
        log("❌ 失败项(交 env-setup-agent 诊断,或把日志发维护人):")
        for _, n, d in fail:
            log("   - %s:%s" % (n, d))
    if not manual and not fail and not DRY:
        # 终验与缓存刷新走 mae-flow envcheck(唯一事实源),不在此重复实现
        rc, out = sh('python "%s" envcheck' % os.path.join(HERE, "mae-flow.py"), timeout=120)
        log(out.strip())
        return sys.exit(0 if rc == 0 else 2)
    sys.exit(2 if (manual or fail) else 0)


if __name__ == "__main__":
    main()
