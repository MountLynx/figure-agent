"""几何：路径取点、transform 矩阵、无渲染 bbox 估算。

bbox 估算只服务两处：transform 类 patch 的收敛判定、以及 MCP 手写 patch
缺 pre 时的兜底。浏览器里的选区 bbox 用真实 DOM（getBBox + CTM），不受
这里的近似影响。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from lxml import etree

from .style import get_style_prop, local_name, parse_px_number

NUM_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")

Command = Tuple[str, List[float]]


def numbers(s: str) -> List[float]:
    return [float(m.group(0)) for m in NUM_RE.finditer(s or "")]


def tokenize_path(d: str) -> List[Command]:
    """把 path d 拆成 (命令, 参数列表)。"""
    tokens = re.findall(r"[MmZzLlHhVvCcSsQqTtAa]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", d or "")
    cmds: List[Command] = []
    cur: Optional[str] = None
    args: List[float] = []
    for t in tokens:
        if re.fullmatch(r"[MmZzLlHhVvCcSsQqTtAa]", t):
            if cur is not None:
                cmds.append((cur, args))
            cur, args = t, []
        else:
            args.append(float(t))
    if cur is not None:
        cmds.append((cur, args))
    return cmds


def path_points(d: str) -> List[Tuple[float, float]]:
    """从 d 中提取顶点/控制点坐标流（近似 bbox 足够）。"""
    pts: List[Tuple[float, float]] = []
    x = y = 0.0
    sx = sy = 0.0
    for cmd, a in tokenize_path(d):
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            i = 0
            while i < len(a):
                nx, ny = (a[i], a[i + 1]) if not rel else (x + a[i], y + a[i + 1])
                if i == 0:
                    x, y = nx, ny
                    sx, sy = x, y
                    pts.append((x, y))
                else:
                    # 隐式 L
                    x, y = nx, ny
                    pts.append((x, y))
                i += 2
        elif c in ("L", "T"):
            for i in range(0, len(a) - 1, 2):
                x, y = (a[i], a[i + 1]) if not rel else (x + a[i], y + a[i + 1])
                pts.append((x, y))
        elif c == "H":
            for v in a:
                x = v if not rel else x + v
                pts.append((x, y))
        elif c == "V":
            for v in a:
                y = v if not rel else y + v
                pts.append((x, y))
        elif c in ("C", "S", "Q"):
            step = {"C": 6, "S": 4, "Q": 4}[c]
            for i in range(0, len(a) - 1, step):
                cx0 = x
                cy0 = y
                # 控制点也纳入 bbox
                for j in range(0, step - 2, 2):
                    px, py = a[i + j], a[i + j + 1]
                    pts.append((px, py) if not rel else (cx0 + px, cy0 + py))
                ex, ey = a[i + step - 2], a[i + step - 1]
                x, y = (ex, ey) if not rel else (cx0 + ex, cy0 + ey)
                pts.append((x, y))
        elif c == "A":
            for i in range(0, len(a) - 6, 7):
                x, y = (a[i + 5], a[i + 6]) if not rel else (x + a[i + 5], y + a[i + 6])
                pts.append((x, y))
        elif c == "Z" or c == "z":
            x, y = sx, sy
    return pts


@dataclass
class BBox:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    def union(self, other: "BBox") -> "BBox":
        x1, y1 = min(self.x, other.x), min(self.y, other.y)
        x2 = max(self.x + self.w, other.x + other.w)
        y2 = max(self.y + self.h, other.y + other.h)
        return BBox(x1, y1, x2 - x1, y2 - y1)

    def corners(self) -> Sequence[Tuple[float, float]]:
        return [
            (self.x, self.y),
            (self.x + self.w, self.y),
            (self.x, self.y + self.h),
            (self.x + self.w, self.y + self.h),
        ]


# 2x3 仿射矩阵 (a, b, c, d, e, f)：x' = a x + c y + e ; y' = b x + d y + f
Matrix = Tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mat_mul(m1: Matrix, m2: Matrix) -> Matrix:
    """先应用 m2 再应用 m1。"""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def mat_apply(m: Matrix, x: float, y: float) -> Tuple[float, float]:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def parse_transform(s: Optional[str]) -> Matrix:
    """解析 SVG transform（translate/scale/matrix/rotate），复合从左到右。"""
    m = IDENTITY
    if not s:
        return m
    for name, argstr in re.findall(r"([a-zA-Z]+)\s*\(([^)]*)\)", s):
        a = numbers(argstr)
        n = name.lower()
        if n == "translate":
            tx = a[0] if len(a) > 0 else 0.0
            ty = a[1] if len(a) > 1 else 0.0
            m = mat_mul(m, (1.0, 0.0, 0.0, 1.0, tx, ty))
        elif n == "scale":
            sx = a[0] if len(a) > 0 else 1.0
            sy = a[1] if len(a) > 1 else sx
            m = mat_mul(m, (sx, 0.0, 0.0, sy, 0.0, 0.0))
        elif n == "matrix" and len(a) >= 6:
            m = mat_mul(m, (a[0], a[1], a[2], a[3], a[4], a[5]))
        elif n == "rotate":
            ang = math.radians(a[0] if a else 0.0)
            cos, sin = math.cos(ang), math.sin(ang)
            rot: Matrix = (cos, sin, -sin, cos, 0.0, 0.0)
            if len(a) >= 3:
                cx, cy = a[1], a[2]
                rot = mat_mul(mat_mul((1, 0, 0, 1, cx, cy), rot), (1, 0, 0, 1, -cx, -cy))
            m = mat_mul(m, rot)
    return m


def transform_bbox(bbox: BBox, m: Matrix) -> BBox:
    pts = [mat_apply(m, x, y) for x, y in bbox.corners()]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return BBox(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _text_bbox(el) -> Optional[BBox]:
    text = "".join(el.itertext()).strip()
    fs = parse_px_number(get_style_prop(el, "font-size")) or 10.0
    xs = numbers(el.get("x", ""))
    ys = numbers(el.get("y", ""))
    if not text:
        return None
    x = xs[0] if xs else 0.0
    y = ys[0] if ys else 0.0
    width = 0.58 * fs * max(1, len(text))
    anchor = (get_style_prop(el, "text-anchor") or el.get("text-anchor") or "start").lower()
    if anchor == "middle":
        bx = x - width / 2
    elif anchor == "end":
        bx = x - width
    else:
        bx = x
    return BBox(bx, y - 0.85 * fs, width, 1.15 * fs)


def _shape_bbox(el, defs: dict) -> Optional[BBox]:
    tag = local_name(el)
    if tag == "path":
        pts = path_points(el.get("d", ""))
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return BBox(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    if tag == "rect":
        x = float(el.get("x", 0) or 0)
        y = float(el.get("y", 0) or 0)
        w = float(el.get("width", 0) or 0)
        h = float(el.get("height", 0) or 0)
        return BBox(x, y, w, h)
    if tag == "circle":
        cx = float(el.get("cx", 0) or 0)
        cy = float(el.get("cy", 0) or 0)
        r = float(el.get("r", 0) or 0)
        return BBox(cx - r, cy - r, 2 * r, 2 * r)
    if tag == "ellipse":
        cx = float(el.get("cx", 0) or 0)
        cy = float(el.get("cy", 0) or 0)
        rx = float(el.get("rx", 0) or 0)
        ry = float(el.get("ry", 0) or 0)
        return BBox(cx - rx, cy - ry, 2 * rx, 2 * ry)
    if tag == "line":
        x1 = float(el.get("x1", 0) or 0)
        y1 = float(el.get("y1", 0) or 0)
        x2 = float(el.get("x2", 0) or 0)
        y2 = float(el.get("y2", 0) or 0)
        return BBox(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
    if tag in ("polygon", "polyline"):
        pts = numbers(el.get("points", ""))
        pairs = [(pts[i], pts[i + 1]) for i in range(0, len(pts) - 1, 2)]
        if not pairs:
            return None
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        return BBox(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    if tag == "use":
        href = el.get("href") or el.get("{http://www.w3.org/1999/xlink}href") or ""
        target = defs.get(href.lstrip("#"))
        if target is None:
            return None
        inner = estimate_bbox(target, defs)
        if inner is None:
            return None
        return BBox(
            inner.x + float(el.get("x", 0) or 0),
            inner.y + float(el.get("y", 0) or 0),
            inner.w,
            inner.h,
        )
    if tag in ("text", "tspan"):
        return _text_bbox(el)
    return None


def build_defs(root) -> dict:
    """收集所有可被 href 引用的元素（defs 内的 path/use 目标等）。"""
    defs: dict = {}
    for el in root.iter():
        if el.get("id") and local_name(el) in ("path", "rect", "circle", "ellipse", "g", "use"):
            defs.setdefault(el.get("id"), el)
    return defs


def estimate_bbox(el, defs: Optional[dict] = None) -> Optional[BBox]:
    """元素在父坐标系中的 bbox 估算（含自身 transform）。"""
    if defs is None:
        defs = build_defs(el.getroottree().getroot())
    own: Optional[BBox] = _shape_bbox(el, defs)
    if own is None:
        own = None
    for child in el:
        if not isinstance(child.tag, str):
            continue
        child_bbox = estimate_bbox(child, defs)
        if child_bbox is None:
            continue
        own = child_bbox if own is None else own.union(child_bbox)
    if own is None:
        return None
    tm = parse_transform(el.get("transform"))
    if tm != IDENTITY:
        own = transform_bbox(own, tm)
    return own
