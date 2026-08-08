"""检视文档落盘 → 面板刷新:第四个感知时机。

前三个时机(init/裁决点/跨阶段)都拍在**进步的瞬间**,但 open/story 这类
步骤是"进了步才生成文档、同一步内请用户确认"——进步瞬间的快照拍不到
文档,用户被请去确认 spec 时,面板上却没有 spec.md(实战反馈原文)。

文档落盘即重新生成面板。失败一律静默:hook 绝不因面板受伤。
"""

import json
import os

REVIEW_DOC_NAMES = frozenset({
    "spec.md", "story.md", "implementation.md", "grill.md",
    "grill-prep.md", "survey.md", "decisions.md", "review.md",
})


def is_review_doc(written_path):
    normalized = "/" + str(written_path or "").replace("\\", "/")
    return (normalized.rsplit("/", 1)[-1] in REVIEW_DOC_NAMES
            and "/.mae-flow-work/" in normalized)


def refresh_on_doc_write(state_path, written_path):
    """写的是检视文档才动手;返回是否真的重生成了面板。"""
    if not is_review_doc(written_path):
        return False
    try:
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
        html = page.render(data, changes, root)
        target = os.path.join(root, ".mae-flow-work", "panel.html")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as stream:
            stream.write(html)
        return True
    except Exception:                      # noqa: BLE001 —— 软失败铁律
        return False
