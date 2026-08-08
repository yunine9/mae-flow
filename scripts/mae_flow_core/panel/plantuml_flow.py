"""活动图与组件/类图渲染。

活动图:start/stop、:动作;、if/else/endif、while/endwhile(单层分支)。
组件类图:分层摆放 + 重心排序,继承用空心三角,其余用实心箭头。
两者都只求"看得懂、不误导",不追求与 plantuml 像素一致。
"""

import re

from .plantuml import (
    FS_S, GRAPH_DECL_RE, GRAPH_EDGE, clean, line, rect, svg, text,
    text_width, unquote)

NODE_H = 36.0
GAP_X = 34.0
GAP_Y = 62.0


def _steps(body):
    out = []
    for raw in body:
        low = raw.lower()
        if low == "start":
            out.append(("start", ""))
        elif low in ("stop", "end"):
            out.append(("stop", ""))
        elif raw.startswith(":") and raw.endswith(";"):
            out.append(("act", raw[1:-1].strip()))
            continue
        condition = re.match(r"^if\s*\((?P<c>.*?)\)\s*then\s*\((?P<t>.*?)\)",
                             raw, re.I)
        if condition:
            out.append(("if", (condition.group("c"), condition.group("t"))))
            continue
        branch = re.match(r"^else\s*\((?P<t>.*?)\)", raw, re.I)
        if branch:
            out.append(("else", branch.group("t")))
        elif low.startswith("else"):
            out.append(("else", ""))
        elif low.startswith("endif"):
            out.append(("endif", ""))
        elif low.startswith("endwhile"):
            out.append(("endwhile", ""))
        elif low.startswith("while"):
            loop = re.match(r"^while\s*\((?P<c>.*?)\)", raw, re.I)
            out.append(("while", loop.group("c") if loop else ""))
    return out


def _diamond(parts, center, y, label):
    half = max(70.0, text_width(label, FS_S) / 2 + 34)
    parts.append('<path d="M%.1f,%.1f L%.1f,%.1f L%.1f,%.1f L%.1f,%.1f z" '
                 'class="pd"/>'
                 % (center, y, center + half, y + 22, center, y + 44,
                    center - half, y + 22))
    parts.append(text(center, y + 26, label, "pt-m", "middle", FS_S))
    return half


def _action(parts, x, y, label):
    width = max(120.0, text_width(label) + 30)
    parts.append(rect(x - width / 2, y, width, 30, "pa", 14))
    parts.append(text(x, y + 20, label, "pt", "middle"))
    return width


class _Activity(object):
    """把活动图的游标状态收在一个对象里,免得画法函数互相传六七个参数。"""

    def __init__(self, title):
        self.center = 168.0
        self.right = 378.0
        self.y = (34 if title else 14) + 8
        self.parts = []
        self.width = 400.0
        self.prev = None
        self.branch = None
        self.merge = []

    def _link(self, x):
        if self.prev:
            self.parts.append(line(self.prev[0], self.prev[1], x, self.y,
                                   "ps"))

    def start(self):
        self.parts.append('<circle cx="%.1f" cy="%.1f" r="9" class="pf"/>'
                          % (self.center, self.y + 9))
        self.prev = (self.center, self.y + 18)
        self.y += 34

    def stop(self):
        x = self.prev[0] if self.prev else self.center
        self._link(x)
        self.parts.append('<circle cx="%.1f" cy="%.1f" r="10" class="pw"/>'
                          % (x, self.y + 11))
        self.parts.append('<circle cx="%.1f" cy="%.1f" r="5.5" class="pf"/>'
                          % (x, self.y + 11))
        self.y += 34
        self.prev = None

    def action(self, label):
        x = self.prev[0] if self.prev else self.center
        self._link(x)
        width = _action(self.parts, x, self.y, label)
        self.width = max(self.width, x + width / 2 + 20)
        self.prev = (x, self.y + 30)
        self.y += 48

    def branch_open(self, condition, yes):
        self._link(self.center)
        half = _diamond(self.parts, self.center, self.y, condition)
        self.parts.append(text(self.center - 8, self.y + 60, yes or "是",
                               "pt-k", "end", FS_S))
        self.parts.append(line(self.center + half, self.y + 22, self.right,
                               self.y + 22, "ps"))
        self.branch = {"y": self.y, "half": half}
        self.prev = (self.center, self.y + 44)
        self.y += 62
        self.width = max(self.width, self.right + 130)

    def branch_else(self, label):
        self.parts.append(text(self.right + 8, self.branch["y"] + 16,
                               label or "否", "pt-k", "start", FS_S))
        self.merge.append(self.prev)
        self.prev = (self.right, self.branch["y"] + 22)

    def branch_close(self):
        self.merge.append(self.prev)
        merge_y = self.y + 6
        for node in [item for item in self.merge if item]:
            self.parts.append(line(node[0], node[1], node[0], merge_y, "ps",
                                   None))
            if abs(node[0] - self.center) > 1:
                self.parts.append(line(node[0], merge_y, self.center, merge_y,
                                       "ps", None))
        self.parts.append('<circle cx="%.1f" cy="%.1f" r="3.5" class="pf"/>'
                          % (self.center, merge_y))
        self.prev, self.branch, self.merge = (self.center, merge_y), None, []
        self.y = merge_y + 16

    def loop_open(self, condition):
        self._link(self.center)
        half = _diamond(self.parts, self.center, self.y, condition)
        self.branch = {"loop_y": self.y + 22, "half": half}
        self.prev = (self.center, self.y + 44)
        self.y += 62

    def loop_close(self):
        if not (self.prev and self.branch and "loop_y" in self.branch):
            return
        half = self.branch["half"]
        back = self.center - half - 26
        x, y = self.prev
        for segment in ((x, y, x, y + 12), (x, y + 12, back, y + 12),
                        (back, y + 12, back, self.branch["loop_y"])):
            self.parts.append(line(*segment, cls="ps", marker=None))
        self.parts.append(line(back, self.branch["loop_y"],
                               self.center - half, self.branch["loop_y"],
                               "ps"))
        self.y = y + 26
        self.prev = (self.center, self.y)
        self.width = max(self.width, self.center + half + 40)
        self.branch = None


def render_activity(lines):
    body, title = clean(lines)
    steps = _steps(body)
    if not steps:
        return ""
    canvas = _Activity(title)
    handlers = {
        "start": lambda _p: canvas.start(),
        "stop": lambda _p: canvas.stop(),
        "act": canvas.action,
        "if": lambda payload: canvas.branch_open(payload[0], payload[1]),
        "else": canvas.branch_else,
        "endif": lambda _p: canvas.branch_close(),
        "while": canvas.loop_open,
        "endwhile": lambda _p: canvas.loop_close(),
    }
    for kind, payload in steps:
        handlers[kind](payload)
    return svg(int(canvas.width), int(canvas.y + 20), canvas.parts, title)


def _graph_model(body):
    labels, edges, seen, alias = {}, [], [], {}

    def node(raw):
        """别名必须归一到同一节点,否则 as 声明会凭空多出一个框。"""
        name = unquote(raw).strip("[]").strip()
        name = alias.get(name, name)
        if name not in labels:
            labels[name] = name
            seen.append(name)
        return name

    for raw in body:
        if GRAPH_DECL_RE.match(raw):
            decl = re.match(r'^\w+\s+("[^"]+"|\S+)(\s+as\s+(\S+))?', raw)
            if decl:
                name = node(decl.group(1))
                if decl.group(3):
                    alias[decl.group(3)] = name
                continue
        edge = GRAPH_EDGE.match(raw)
        if edge:
            arrow = edge.group("arrow")
            style = ("inherit" if "|>" in arrow else "assoc")
            edges.append((node(edge.group("a")), node(edge.group("b")),
                          (edge.group("text") or "").strip(), style,
                          "." in arrow))
    return labels, edges, seen


def _levels(seen, edges):
    level = {name: 0 for name in seen}
    for _pass in range(len(seen)):
        changed = False
        for left, right, _t, _s, _d in edges:
            if level.get(right, 0) < level.get(left, 0) + 1:
                level[right] = level[left] + 1
                changed = True
        if not changed:
            break
    rows = {}
    for name in seen:
        rows.setdefault(min(level[name], 8), []).append(name)
    parents = {}
    for left, right, _t, _s, _d in edges:
        parents.setdefault(right, []).append(left)
    for depth in sorted(rows):          # 重心排序:少一堆交叉线
        if depth == 0:
            continue
        above = rows.get(depth - 1, [])
        index = {name: slot for slot, name in enumerate(above)}
        rows[depth].sort(key=lambda name: (_barycenter(name, parents, index,
                                                       len(above)), name))
    return rows


def _barycenter(name, parents, index, fallback):
    kin = parents.get(name) or ()
    if not kin:
        return 99.0
    return sum(index.get(parent, fallback) for parent in kin) / len(kin)


def _place(rows, labels, top):
    widths = {name: max(110.0, text_width(labels[name]) + 30)
              for names in rows.values() for name in names}
    row_width = {depth: sum(widths[name] for name in names)
                 + GAP_X * (len(names) - 1)
                 for depth, names in rows.items()}
    canvas = max(max(row_width.values()) + 48, 380.0)
    positions, parts = {}, []
    for depth in sorted(rows):
        x = (canvas - row_width[depth]) / 2
        y = top + depth * (NODE_H + GAP_Y)
        for name in rows[depth]:
            width = widths[name]
            positions[name] = (x + width / 2, y)
            parts.append(rect(x, y, width, NODE_H, "pb", 4))
            parts.append(text(x + width / 2, y + 23, labels[name], "pt",
                              "middle"))
            x += width + GAP_X
    return positions, parts, canvas


def _edge_parts(edges, positions):
    parts = []
    for left, right, label, style, dotted in edges:
        if left not in positions or right not in positions:
            continue
        x1, y1 = positions[left]
        x2, y2 = positions[right]
        if y2 > y1:
            start, end = (x1, y1 + NODE_H), (x2, y2)
        elif y2 < y1:
            start, end = (x1, y1), (x2, y2 + NODE_H)
        else:
            start, end = (x1 + 4, y1 + NODE_H / 2), (x2 - 4, y2 + NODE_H / 2)
        parts.append(line(start[0], start[1], end[0], end[1], "ps",
                          "ai" if style == "inherit" else "ah", dotted))
        if label:
            parts.append(text((start[0] + end[0]) / 2 + 6,
                              (start[1] + end[1]) / 2, label, "pt-m",
                              "start", FS_S))
    return parts


def render_graph(lines):
    body, title = clean(lines)
    labels, edges, seen = _graph_model(body)
    if not seen:
        return ""
    rows = _levels(seen, edges)
    top = 34 if title else 16
    positions, node_parts, canvas = _place(rows, labels, top)
    height = top + (max(rows) + 1) * (NODE_H + GAP_Y) - GAP_Y + 24
    return svg(int(canvas), int(height),
               _edge_parts(edges, positions) + node_parts, title)
