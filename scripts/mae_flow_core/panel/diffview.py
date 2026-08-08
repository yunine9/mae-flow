"""统一 diff → 左右双排对照 HTML。

双排的理由:改写型变更(把 A 换成 B)在单排里是两条相隔很远的红绿行,
左右并排才能一眼看出"换了什么"。删除与新增按出现顺序在同一行配对,
多出来的一侧留空——于是"纯新增"和"改写"在版面上天然可分。

截断必须报数:显示不全却看着像全部,是最坏的一种"通过"。
"""

import re

from .markdown import escape

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
NOISE = ("index ", "--- ", "+++ ", "new file mode", "deleted file mode",
         "similarity index", "rename from", "rename to", "old mode",
         "new mode")
MAX_LINES = 700


def _cell(number, body, kind):
    if kind == "nil":
        return '<span class="ln"></span><code class="c nil"></code>'
    return ('<span class="ln">%s</span><code class="c %s">%s</code>'
            % (number, kind, escape(body)))


def _hunk_row(match):
    tail = (match.group(5) or "").strip()
    return ('<div class="dr hk"><code class="c span">@@ %s</code></div>'
            % escape("-%s,%s +%s,%s%s" % (
                match.group(1), match.group(2) or "1",
                match.group(3), match.group(4) or "1",
                ("  " + tail) if tail else "")))


class _Pairs(object):
    """攒着删除行与新增行,遇到上下文或 hunk 边界时逐行配对落地。"""

    def __init__(self):
        self.rows, self.shown, self.cut = [], 0, 0
        self.removed, self.added = [], []

    def flush(self):
        for index in range(max(len(self.removed), len(self.added))):
            if self.shown >= MAX_LINES:
                self.cut += 1
                continue
            left = self.removed[index] if index < len(self.removed) else None
            right = self.added[index] if index < len(self.added) else None
            self.rows.append(
                '<div class="dr">%s%s</div>'
                % (_cell(left[0], left[1], "del") if left
                   else _cell("", "", "nil"),
                   _cell(right[0], right[1], "add") if right
                   else _cell("", "", "nil")))
            self.shown += 1
        del self.removed[:]
        del self.added[:]

    def context(self, old, new, body):
        self.flush()
        if self.shown >= MAX_LINES:
            self.cut += 1
            return
        self.rows.append('<div class="dr">%s%s</div>'
                         % (_cell(old, body, "ctx"), _cell(new, body, "ctx")))
        self.shown += 1


def render(patch):
    """一份文件的 patch → 双排 HTML。"""
    pairs, old, new = _Pairs(), 0, 0
    lines = (patch or "").split("\n")
    if lines and lines[-1] == "":
        del lines[-1]          # patch 末尾换行不是一行上下文,别凭空多一行空白
    for body in lines:
        if body.startswith(NOISE) or body.startswith("\\"):
            continue
        hunk = HUNK_RE.match(body)
        if hunk:
            pairs.flush()
            pairs.rows.append(_hunk_row(hunk))
            old, new = int(hunk.group(1)), int(hunk.group(3))
        elif body.startswith("+"):
            pairs.added.append((new, body))
            new += 1
        elif body.startswith("-"):
            pairs.removed.append((old, body))
            old += 1
        else:
            pairs.context(old, new, body)
            old += 1
            new += 1
    pairs.flush()
    if pairs.cut:
        pairs.rows.append(
            '<div class="dr cut"><code class="c span">… 还有 %d 行未显示'
            '（面板上限 %d 行，完整内容看源文件）</code></div>'
            % (pairs.cut, MAX_LINES))
    return ('<div class="diff"><div class="dhead"><span>变更前</span>'
            '<span>变更后</span></div>%s</div>' % "".join(pairs.rows))


def split_patch(text):
    """整份 patch → {路径: 该文件的 patch}。"""
    files, path, buffer = {}, None, []
    for body in (text or "").splitlines():
        if body.startswith("diff --git "):
            if path:
                files[path] = "\n".join(buffer)
            match = re.search(r" b/(.+)$", body)
            path, buffer = (match.group(1) if match else body), []
            continue
        if path is not None:
            buffer.append(body)
    if path:
        files[path] = "\n".join(buffer)
    return files


def numstat(text):
    """`git diff --numstat` → {路径: (新增, 删除)};二进制文件记 0。"""
    stats = {}
    for body in (text or "").splitlines():
        columns = body.split("\t")
        if len(columns) == 3:
            added = 0 if columns[0] == "-" else int(columns[0])
            removed = 0 if columns[1] == "-" else int(columns[1])
            stats[columns[2]] = (added, removed)
    return stats
