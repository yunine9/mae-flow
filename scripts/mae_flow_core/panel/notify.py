"""阶段推进与"需要你确认"的主动通知。

两个真实痛点:交付常常跨小时甚至跨天,用户不可能一直盯着终端;
而流程真正需要人的时刻只有那么几个——错过它们,时间就白白躺在等待里。

三条自律:

- **只在两种时刻响**:到了需要用户裁决的步骤、进入了新阶段。其余一律安静,
  否则通知本身会变成噪声,而噪声化的通知等于没有通知。
- **绝不阻塞、绝不抛错**:通知失败就是没通知,不许影响流程一分一毫。
- **桌面弹窗按仓库预设开关**:默认只打印一行(模型会转述给用户),
  弹窗要在 .mae-flow-defaults.json 写「桌面通知": true」才启用——
  不问自取地弹系统通知是打扰,不是服务。
"""

import os
import subprocess
import sys

from mae_flow_core.file_io import load_json

DEFAULTS_PATH = ".mae-flow-defaults.json"
FIELD = "桌面通知"
ENV_OFF = "MAE_FLOW_NO_NOTIFY"

# 步骤 → 阶段。flow.json 里没有阶段字段,这里是唯一来源;
# 漏掉任何步骤都会被 test_panel_notify 的覆盖断言拦下,不会静默错标。
# 阶段名是给人看的,说人话:描述这一段在干什么,不用流程内部代号
# ("质量"对用户是黑话,"验证"才是这一段实际发生的事)。
PHASES = {
    "启动": ("config_confirm", "workflow_select", "code_reviewer_ask",
             "branch_create"),
    "澄清需求": ("grill", "grill_ask", "rf_triage"),
    "定规格": ("open", "hf_open", "tw_open", "design", "archive",
               "archive_confirm", "domain_archive"),
    "写设计": ("story", "story_ask"),
    "写代码": ("build", "build_agent_review", "build_review", "build_rework",
               "build_commit"),
    "验证": ("verify_comet", "verify_ponytail", "verify_post_ponytail_compile",
             "verify_codecheck", "verify_codecheck_compile", "verify_recompile",
             "verify_ut", "verify_spec", "quality_review", "quality_rework",
             "quality_recompile", "quality_commit",
             "tw_codecheck", "tw_ut", "tw_verify",
             "rf_codecheck", "rf_ut", "rf_verify"),
    "交付": ("delivery_review", "push", "moonlight_review", "end"),
}
_STEP_PHASE = {step: phase for phase, steps in PHASES.items()
               for step in steps}


def phase_of(step_id):
    return _STEP_PHASE.get(step_id, "")


def desktop_enabled(root="."):
    """默认关闭:不问自取地弹系统通知是打扰。"""
    if os.environ.get(ENV_OFF):
        return False
    try:
        defaults = load_json(os.path.join(root, DEFAULTS_PATH),
                             encoding="utf-8-sig") or {}
    except Exception:                      # noqa: BLE001
        return False
    return bool(defaults.get(FIELD))


def _command(title, body):
    if sys.platform == "darwin":
        return ["osascript", "-e",
                'display notification %s with title %s sound name "Ping"'
                % (_applescript(body), _applescript(title))]
    if os.name == "nt":
        # SystemIcons 在 System.Drawing 里,必须显式 Add-Type,不赌传递加载;
        # 弹完驻留几秒再退出——NotifyIcon 随进程销毁,立刻退出 toast 会一闪而没。
        # 弹窗进程不被等待(Popen),驻留不拖慢 done。Windows 腿在内网真机验证前
        # 视为未证实(军规:没跑过的代码不算能跑)。
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "Add-Type -AssemblyName System.Drawing;"
            "$n=New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon=[System.Drawing.SystemIcons]::Information;"
            "$n.Visible=$true;"
            "$n.ShowBalloonTip(8000,'%s','%s',"
            "[System.Windows.Forms.ToolTipIcon]::Info);"
            "Start-Sleep -Seconds 6;$n.Dispose()"
            % (title.replace("'", " "), body.replace("'", " ")))
        return ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                "-Command", script]
    return ["notify-send", title, body]


def _applescript(text):
    return '"%s"' % text.replace("\\", "").replace('"', "'")


def _popup(title, body):
    """弹窗进程发射后不管:通知永远不能拖慢流程推进。"""
    try:
        subprocess.Popen(_command(title, body), shell=False,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except Exception:                      # noqa: BLE001 —— 通知失败=没通知
        return False
    return True


def _reason(flow, step_id):
    """→ (标题, 详情) 或 None。只认两种时刻,其余安静。"""
    step = ((flow or {}).get("steps", {}) or {}).get(step_id) or {}
    title = step.get("title", step_id)
    if step.get("choice_key"):
        return "需要你选择", "%s（%s）" % (title, step_id)
    if step.get("user_ack"):
        return "需要你确认", "%s（%s）" % (title, step_id)
    return None


def announce(flow, previous_step, next_step, root=".", ticket=""):
    """在推进落地后调用。返回要打印的行(空表示这次不该响)。"""
    lines = []
    reason = _reason(flow, next_step)
    if reason:
        lines.append("🔔 %s: %s" % reason)
    before, after = phase_of(previous_step), phase_of(next_step)
    if after and after != before:
        lines.append("🔔 进入「%s」阶段" % after)
    if not lines:
        return []
    label = ("%s · " % ticket) if ticket else ""
    for line in lines:
        print("[mae-flow] " + line)
    try:
        sys.stderr.write("\a")             # 终端响一下,不占正文
        sys.stderr.flush()
    except Exception:                      # noqa: BLE001
        pass
    if desktop_enabled(root):
        _popup("Mae-Flow · " + label.rstrip(" ·· ").strip(),
               "；".join(item.replace("🔔 ", "") for item in lines))
    return lines
