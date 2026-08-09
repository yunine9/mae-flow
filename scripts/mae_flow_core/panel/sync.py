"""检视文档落盘 → 面板刷新:第四个感知时机。

前三个时机(init/裁决点/跨阶段)都拍在**进步的瞬间**,但 open/story 这类
步骤是"进了步才生成文档、同一步内请用户确认"——进步瞬间的快照拍不到
文档,用户被请去确认 spec 时,面板上却没有 spec.md(实战反馈原文)。

文档落盘即重新生成面板。失败一律静默:hook 绝不因面板受伤。
"""

import json
import os
import time

REVIEW_DOC_NAMES = frozenset({
    "spec.md", "story.md", "implementation.md", "grill.md",
    "grill-prep.md", "survey.md", "decisions.md", "review.md",
})


def is_review_doc(written_path):
    normalized = "/" + str(written_path or "").replace("\\", "/")
    return (normalized.rsplit("/", 1)[-1] in REVIEW_DOC_NAMES
            and "/.mae-flow-work/" in normalized)


def _rebuild(state_path):
    from mae_flow_core.panel import page, snapshot
    from mae_flow_core.workflow import definition
    root = os.getcwd()
    with open(state_path, encoding="utf-8") as stream:
        state = json.load(stream)
    plugin_root = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", ".."))
    flow = definition.load_definition(
        os.path.join(plugin_root, "flow", "flow.json"))
    data = snapshot.build(root, state, flow)
    changes = snapshot.changes(
        root, state.get("implementation_base_head", ""))
    page.write_page(
        os.path.join(root, ".mae-flow-work", "panel.html"),
        data, changes, root)
    return True


def refresh_on_commit(state_path, command):
    """提交落地即重生成面板:第五个感知时机。

    实战反馈:领域归档提交后,面板仍把 docs/specs 显示在"未提交"——
    提交发生在步内,既不跨阶段也不是检视文档落盘,四个时机都不覆盖,
    用户看到的是提交前的旧快照。而"刚提交完"恰恰是最想复核的时刻之一。
    """
    text = str(command or "")
    if "git" not in text or "commit" not in text:
        return False
    try:
        return _rebuild(state_path)
    except Exception:                      # noqa: BLE001 —— 软失败铁律
        return False


def refresh_on_doc_write(state_path, written_path):
    """写的是检视文档才动手;返回是否真的重生成了面板。"""
    if not is_review_doc(written_path):
        return False
    try:
        return _rebuild(state_path)
    except Exception:                      # noqa: BLE001 —— 软失败铁律
        return False


# 整页重生成的节流窗口。实测(fieldtest,7 份文档 + 全量 diff)约 72ms:
# 快照 29ms + 变更 39ms + 渲染 3ms,比预估的"几百毫秒"便宜得多,
# 所以密集刷新负担得起。但内网 Java 大仓的 git diff 会慢得多,
# 因此窗口按上一次实测耗时自适应:花得越久,下次等得越久。
_MIN_PAGE_INTERVAL = 8.0
_MAX_PAGE_INTERVAL = 90.0
_COST_MULTIPLIER = 40          # 花 72ms → 约 8s 一次;花 1s → 40s 一次


def _page_path(root):
    return os.path.join(root, ".mae-flow-work", "panel.html")


def _due(root):
    """离上次整页重生成是否已过节流窗口(窗口由上次耗时自适应)。"""
    try:
        marker = os.path.join(root, ".mae-flow-work", ".panel-cost")
        cost = 0.072
        if os.path.isfile(marker):
            with open(marker, encoding="utf-8") as stream:
                cost = float(stream.read().strip() or cost)
        window = min(max(cost * _COST_MULTIPLIER, _MIN_PAGE_INTERVAL),
                     _MAX_PAGE_INTERVAL)
        return (time.time() - os.path.getmtime(_page_path(root))) >= window
    except OSError:
        return True
    except ValueError:
        return True


def _remember_cost(root, seconds):
    try:
        with open(os.path.join(root, ".mae-flow-work", ".panel-cost"),
                  "w", encoding="utf-8") as stream:
            stream.write("%.3f" % seconds)
    except OSError:
        pass


def on_tool_event(state_path, root, written_path="", command=""):
    """Hook 侧面板同步的唯一入口。

    三档:脉冲每次都写(几毫秒);检视文档落盘与提交落地立刻整页重生成
    (那是用户马上要看的);其余工具事件按自适应节流也重生成——
    实测 72ms 的代价换"面板始终是当前现场",值。
    """
    from mae_flow_core.panel import pulse
    pulse.write_pulse(state_path, root=root)
    if written_path and refresh_on_doc_write(state_path, written_path):
        return
    if command and refresh_on_commit(state_path, command):
        return
    if not _due(root):
        return
    started = time.time()
    try:
        _rebuild(state_path)
    except Exception:                      # noqa: BLE001 —— 软失败铁律
        return
    _remember_cost(root, time.time() - started)

