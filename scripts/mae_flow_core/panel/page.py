"""快照 → 自包含单文件 HTML。

页面是快照的**消费者**,不是第二个真相源:所有事实都来自 snapshot.build();
页面自己不读状态、不写状态、不提供任何"推进到下一步"的入口——那种按钮
是绕过证据的官方通道,看起来还完全合法。
"""

import io
import os

from . import assets, diffview, markdown, plantuml
from .markdown import escape

STATUS_LABEL = {"PASS": "t-ok", "CLEAN": "t-ok", "OK": "t-ok",
                "TOOL_ERROR": "t-deg", "UNAVAILABLE": "t-deg",
                "FAIL": "t-bad", "BLOCKED": "t-bad"}


def _fence_hook(language, body):
    """md 里的 plantuml 块就地出图;出不了就显示源码并说清为什么。"""
    if language != "plantuml":
        return None
    drawn, kind = plantuml.render(body)
    source = ('<details class="pumls"><summary>PlantUML 源码</summary>'
              '<pre><code>%s</code></pre></details>' % escape(body))
    if drawn:
        return ('<figure class="pfig">%s<figcaption>%s · 内置轻渲染</figcaption>'
                '%s</figure>'
                % (drawn, plantuml.KIND_LABEL.get(kind, kind), source))
    why = "识别不出图类型" if not kind else "%s 解析失败" % kind
    return ('<figure class="pfig bad"><span class="fn">未出图：%s —— '
            '源码原样保留</span><pre class="praw"><code>%s</code></pre>'
            '</figure>' % (why, escape(body)))


def _document_panes(documents):
    rows, tabs, panes = [], [], []
    for doc in documents:
        key = "doc-" + doc["kind"]
        try:
            with io.open(doc["path"], encoding="utf-8", errors="replace") as fh:
                body = markdown.render(fh.read(), _fence_hook)
        except OSError as exc:
            body = '<p>读取失败：%s</p>' % escape(str(exc))
        rows.append(
            '<div class="doc"><span class="k">%s</span>'
            '<button class="open" onclick="show(\'%s\')">%s</button>'
            '<span class="s">%s · %s</span>'
            '<a class="raw" href="file://%s">源文件 ↗</a></div>'
            % (escape(doc["label"]), key, escape(doc["relative"]),
               _size(doc["bytes"]), escape(doc["updated_at"]),
               escape(doc["path"])))
        tabs.append('<button data-group="doc" data-key="%s" '
                    'onclick="show(\'%s\')">%s</button>'
                    % (key, key, escape(doc["label"])))
        panes.append(
            '<div class="pane" data-group="doc" data-key="%s" '
            'data-title="%s" data-raw="file://%s" data-rel="%s">'
            '<div class="md">%s</div></div>'
            % (key, escape(doc["label"]), escape(doc["path"]),
               escape(doc["relative"]), body))
    return rows, tabs, panes


def _size(count):
    return "%.1fk" % (count / 1024.0) if count >= 1024 else "%dB" % count


def _bar(added, removed):
    total = max(1, added + removed)
    green = 46.0 * added / total
    return ('<span class="bar"><i class="g" style="width:%.1fpx"></i>'
            '<i class="r" style="width:%.1fpx"></i></span>'
            % (green, 46.0 - green))


def _change_sections(groups, root):
    blocks, tabs, panes, index = [], [], [], 0
    for group in groups:
        added = sum(item["added"] for item in group["files"])
        removed = sum(item["removed"] for item in group["files"])
        blocks.append('<div class="gtitle"><b>%s</b><span>%s · %d 个文件 · '
                      '+%d / −%d</span></div><div class="chg list">'
                      % (escape(group["title"]), escape(group["note"]),
                         len(group["files"]), added, removed))
        for item in group["files"]:
            key = "chg-%d" % index
            index += 1
            folder, _, base = item["path"].rpartition("/")
            blocks.append(
                '<button class="f" onclick="show(\'%s\')">'
                '<span class="p"><i>%s</i>%s</span>'
                '<span class="n"><span class="a">+%d</span> '
                '<span class="d">−%d</span></span>%s'
                '<span class="go">diff ›</span></button>'
                % (key, escape(folder + "/" if folder else ""), escape(base),
                   item["added"], item["removed"],
                   _bar(item["added"], item["removed"])))
            tabs.append('<button data-group="diff" data-key="%s" '
                        'onclick="show(\'%s\')">%s</button>'
                        % (key, key, escape(base)))
            panes.append(
                '<div class="pane" data-group="diff" data-key="%s" '
                'data-title="%s" data-raw="file://%s" data-rel="%s（%s）">'
                '<div class="dwrap">%s</div></div>'
                % (key, escape(base),
                   escape(os.path.join(root, item["path"])),
                   escape(item["path"]), escape(group["title"]),
                   diffview.render(item["patch"]) if item["patch"]
                   else '<p>这份 patch 取不到（可能是二进制文件）。</p>'))
        blocks.append("</div>")
    return "".join(blocks), tabs, panes


def _pending_section(pending):
    if not pending:
        return ('<section class="decide"><h2>待你裁决</h2><div class="card">'
                '<div class="quiet"><span class="dot"></span>'
                '当前没有需要你拍板的事项。</div></div></section>')
    cards = []
    for item in pending:
        rows = "".join("<dt>%s</dt><dd>%s</dd>"
                       % (escape(entry["label"]), escape(entry["value"]))
                       for entry in item["items"])
        cards.append(
            '<div class="ask-title">%s</div>'
            '<div class="ask-sub">%s · 需要你逐项过目后确认</div>'
            '<dl class="kv">%s</dl>'
            '<div class="hint">python .mae-flow-work/bin/mae-flow.py done ...'
            '\n<em># 给人复制到终端用 —— 面板不提供执行按钮</em></div>'
            % (escape(item["title"] or item["step"]), escape(item["step"]),
               rows))
    return ('<section class="decide has"><h2>待你裁决</h2>'
            '<div class="card">%s</div></section>' % "".join(cards))


def _evidence_rows(evidence):
    rows, degraded = [], False

    def row(name, tag, cls, why):
        rows.append('<div class="row"><span class="name">%s</span>'
                    '<span><i class="tag %s">%s</i></span>'
                    '<span class="why">%s</span></div>'
                    % (escape(name), cls, escape(tag), escape(why)))

    for key in ("compile", "reviewer"):
        item = evidence.get(key)
        if item:
            row(item["name"], "已完成", "t-ok",
                "%s · %d 个文件" % (item["at"], item["files"]))
    ponytail = evidence.get("ponytail")
    if ponytail:
        row(ponytail["name"], "已完成", "t-ok",
            "第 %s 轮" % ponytail["rounds"])
    check = evidence.get("codecheck")
    if check:
        degraded = check["degraded"]
        row(check["name"],
            "工具未就绪" if degraded else (check["status"] or "已完成"),
            STATUS_LABEL.get(check["status"], "t-ok"),
            "%s · %d 个文件%s" % (check["at"], check["files"],
                                  "未扫描" if degraded else ""))
    unit = evidence.get("ut")
    if unit:
        row(unit["name"], "已完成" if unit["complete"] else "进行中",
            "t-ok" if unit["complete"] else "t-run",
            "%s · 批次 %d/%d" % (unit["phase"], unit["completed_batches"],
                                 unit["batches"]))
    note = ('<div class="deg-note"><b>「工具未就绪」不是通过。</b>'
            '这些文件至今没有被静态检查扫过——工具恢复前，这一格不能当绿灯。'
            '</div>') if degraded else ""
    return "".join(rows), note


def _progress_section(progress):
    """一行字,不是一面墙——那串步骤药丸是全页最大的杂乱源,退役。"""
    total = progress["steps_total_estimate"]
    current = escape(progress["step"])
    if progress["step_title"]:
        current += " · " + escape(progress["step_title"])
    return ('<section class="prog"><h2>进度</h2><div class="line">'
            '<span>第 <b>%d</b> 步%s</span>'
            '<span>当前 <span class="cur">%s</span></span>'
            '<span>起始 <b>%s</b></span>'
            '<span>回退 <b>%d</b> 次</span></div></section>'
            % (len(progress["steps_done"]) + 1,
               (" / 约 <b>%d</b> 步" % total) if total else "",
               current,
               escape(progress["started_at"]),
               progress["revisits"]["goto"]))


def render(snapshot, changes=(), root="."):
    """快照(+变更组) → 完整 HTML 文本。"""
    doc_rows, doc_tabs, doc_panes = _document_panes(
        snapshot["artifacts"]["documents"])
    change_html, change_tabs, change_panes = _change_sections(changes, root)
    evidence_rows, degraded_note = _evidence_rows(snapshot["evidence"])
    advisories = snapshot["advisories"]
    context = {
        "css": assets.CSS + plantuml.SVG_CSS,
        "js": assets.JS,
        "ticket": escape(snapshot["delivery"]["ticket"] or "（无在途单）"),
        "branch": escape(snapshot["repo"]["branch"]),
        "baseline": escape(snapshot["repo"]["baseline"]),
        "head": escape(snapshot["repo"]["head"]),
        "stamp": escape(snapshot["generated_at"]),
        "revision": snapshot["state_revision"] or 0,
        "pending": _pending_section(snapshot["pending"]),
        "docs": "".join(doc_rows) or
                '<div class="doc"><span class="k">—</span>'
                '<span>本单尚无文档</span><span></span><span></span></div>',
        "commits": "".join(
            '<div class="commit"><code>%s</code><span>%s</span>'
            '<span class="t">%s</span></div>'
            % (escape(item["sha"]), escape(item["subject"]),
               escape(item["at"]))
            for item in snapshot["artifacts"]["commits"]) or "<div>（无提交）</div>",
        "changes": change_html or "<div>（本单暂无代码变更）</div>",
        "logs": "".join('<li><a href="file://%s">%s</a></li>'
                        % (escape(path), escape(name))
                        for name, path in
                        sorted(snapshot["artifacts"]["logs"].items())),
        "evidence": evidence_rows or "<div class=\"row\"><span>（暂无证据）</span></div>",
        "degraded": degraded_note,
        "advisories": "".join(
            "<li><code>%s</code> %s</li>"
            % (escape(item.get("kind", "")), escape(item.get("message", "")))
            for item in advisories) or
            '<li class="quiet"><span class="dot"></span>本轮无待处理建议。</li>',
        "progress": _progress_section(snapshot["progress"]),
        "warnings": "".join("<li>%s</li>" % escape(text)
                            for text in snapshot["warnings"]),
        "tabs": "".join(doc_tabs + change_tabs),
        "panes": "".join(doc_panes + change_panes),
    }
    return TEMPLATE % context


TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mae-Flow 交付现场 · %(ticket)s</title>
<style>%(css)s</style></head><body><div class="wrap">
<header><h1>交付现场 · <span class="tick">%(ticket)s</span></h1>
<div class="hd-meta"><span>%(branch)s</span><span>基线 %(baseline)s</span>
<span>HEAD %(head)s</span>
<span class="stamp">快照 %(stamp)s · rev %(revision)s</span></div></header>
%(pending)s
<section><h2>文档 <span class="n">· 点名字就地阅读</span></h2>
<div class="list">%(docs)s</div></section>
<section><h2>代码变更 <span class="n">· 点文件看双排 diff</span></h2>
<div class="list">%(commits)s</div>
%(changes)s</section>
<section><h2>证据</h2><div class="list">%(evidence)s</div>
%(degraded)s</section>
<section><h2>本轮建议 <span class="n">· 非阻断</span></h2>
<ul class="adv">%(advisories)s</ul></section>
%(progress)s
<details class="note"><summary>日志与任务卡</summary>
<ul class="paths">%(logs)s</ul></details>
<details class="note"><summary>出口自述（快照自己的降级说明）</summary>
<ul>%(warnings)s<li>百分比故意留空：flow 有分支和回退，算出来必然是编的。</li>
<li>图形为内置轻渲染，与公司评审工具的 PlantUML 输出可能有差异。</li></ul></details>
<footer>只读快照 · 由 <code>mae-flow.py panel</code> 生成 ·
数据源 <code>panel --json</code>；本页不含任何写入入口。</footer>
</div>
<div id="viewer"><div class="vbox"><div class="vbar">
<span class="vt" id="vtitle">文档</span><span class="vp" id="vpath"></span>
<span class="sp"><a id="vraw" href="#">源文件 ↗</a>
<button onclick="hide()">关闭 Esc</button></span></div>
<div class="vtabs">%(tabs)s</div>%(panes)s</div></div>
<script>%(js)s</script></body></html>
"""
