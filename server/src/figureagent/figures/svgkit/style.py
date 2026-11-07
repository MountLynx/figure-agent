"""style 属性（CSS 声明）与颜色的解析/写入/比较。

matplotlib SVG 把表现样式写进 `style="fill: #1f77b4; stroke: none"`，
所以所有样式读写都要走 CSS 声明，而不是表现属性。
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

from lxml import etree

SVG_NS = "http://www.w3.org/2000/svg"

_NAMED_COLORS = {
    "black": "#000000",
    "white": "#ffffff",
    "red": "#ff0000",
    "lime": "#00ff00",
    "green": "#008000",
    "blue": "#0000ff",
    "orange": "#ffa500",
    "yellow": "#ffff00",
    "cyan": "#00ffff",
    "magenta": "#ff00ff",
    "purple": "#800080",
    "pink": "#ffc0cb",
    "gray": "#808080",
    "grey": "#808080",
    "silver": "#c0c0c0",
    "gold": "#ffd700",
    "navy": "#000080",
    "teal": "#008080",
    "brown": "#a52a2a",
    "none": "none",
    "transparent": "none",
}


def local_name(el) -> str:
    return etree.QName(el).localname


def parse_style(style: str) -> Dict[str, str]:
    """解析 style 属性为有序 dict（后出现的声明覆盖前面的）。"""
    props: Dict[str, str] = {}
    for part in (style or "").split(";"):
        if not part.strip():
            continue
        if ":" not in part:
            continue
        name, _, value = part.partition(":")
        props[name.strip().lower()] = value.strip()
    return props


def serialize_style(props: Dict[str, str]) -> str:
    return "; ".join(f"{k}: {v}" for k, v in props.items())


def set_style_prop(el, name: str, value: Optional[str]) -> None:
    """在元素的 style 属性上设置/删除一条声明（value=None 删除）。"""
    props = parse_style(el.get("style", ""))
    if value is None:
        props.pop(name, None)
    else:
        props[name] = value
    if props:
        el.set("style", serialize_style(props))
    elif el.get("style") is not None:
        del el.attrib["style"]


def get_style_prop(el, name: str) -> Optional[str]:
    """读元素上的声明：style 属性优先，其次表现属性（fill="..." 等）。"""
    props = parse_style(el.get("style", ""))
    if name in props:
        return props[name]
    val = el.get(name)
    return val


def declares_attr(el, name: str) -> bool:
    """该元素是否显式声明了某表现属性（style 或表现属性均可）。"""
    return get_style_prop(el, name) is not None


def effective_values(el, name: str) -> List[str]:
    """子树内所有对该属性的显式声明值（含自身）。空列表 = 全靠继承。"""
    out: List[str] = []
    if declares_attr(el, name):
        out.append(get_style_prop(el, name) or "")
    for desc in el.iter():
        if desc is el:
            continue
        if declares_attr(desc, name):
            out.append(get_style_prop(desc, name) or "")
    return out


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def normalize_color(value: Optional[str]) -> Optional[str]:
    """归一化为 #rrggbb（小写）或 "none"；解析失败返回 None。

    颜色的 alpha（rgba 第 4 分量）在比较中被忽略——v1 不区分透明度，
    透明度由 opacity / fill-opacity 单独控制。
    """
    if value is None:
        return None
    v = value.strip().lower()
    if not v:
        return None
    if v in _NAMED_COLORS:
        return _NAMED_COLORS[v]
    if v.startswith("#"):
        hexpart = v[1:]
        if re.fullmatch(r"[0-9a-f]{3}", hexpart):
            return "#" + "".join(c * 2 for c in hexpart)
        if re.fullmatch(r"[0-9a-f]{6}", hexpart):
            return "#" + hexpart
        if re.fullmatch(r"[0-9a-f]{8}", hexpart):
            return "#" + hexpart[:6]
        return None
    m = re.fullmatch(r"rgba?\(\s*([^)]*)\s*\)", v)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        if len(parts) < 3:
            return None
        try:
            if all(p.endswith("%") for p in parts[:3]):
                chans = [round(_clamp01(float(p[:-1]) / 100.0) * 255) for p in parts[:3]]
            else:
                chans = [round(_clamp01(float(p))) for p in parts[:3]]
        except ValueError:
            return None
        return "#{:02x}{:02x}{:02x}".format(*chans)
    return None


def normalize_font_family(value: Optional[str]) -> List[str]:
    """拆出字体族 token（去引号、小写），供“期望族 ∈ 声明列表”式比较。"""
    if not value:
        return []
    tokens: List[str] = []
    for raw in value.split(","):
        t = raw.strip().strip("'\"").lower()
        t = re.sub(r"\s+", " ", t)
        if t:
            tokens.append(t)
    return tokens


def font_family_matches(declared: Iterable[str], expected: str) -> bool:
    exp_tokens = normalize_font_family(expected)
    if not exp_tokens:
        return False
    declared_tokens = set()
    for d in declared:
        declared_tokens.update(normalize_font_family(d))
    return all(t in declared_tokens for t in exp_tokens)


def parse_px_number(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    m = re.search(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?", value)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None
