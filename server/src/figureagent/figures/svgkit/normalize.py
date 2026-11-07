"""SVG 规范化与确定性 hash。

目标：两份"渲染结果相同"的 matplotlib SVG（如 dc:date 不同、属性顺序不同、
含 rotate(-0 ...) 这类无效 transform），规范化后字节一致，从而 baseHash 稳定、
身份匹配不做假 diff。
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from lxml import etree

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

NUM_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def parse_svg(text: str):
    root = etree.fromstring(text.encode("utf-8"))
    return root


def serialize(root) -> str:
    return etree.tostring(root, encoding="unicode")


def local_name(el) -> str:
    return etree.QName(el).localname


def _normalize_transform_value(value: str) -> Optional[str]:
    """去掉无效 transform 组（rotate(0/-0)、translate(0)、scale(1)、identity matrix）。"""
    groups = re.findall(r"([a-zA-Z]+)\s*\(([^)]*)\)", value)
    kept: list[str] = []
    for name, argstr in groups:
        n = name.lower()
        nums = [float(x) for x in NUM_RE.findall(argstr)]
        if n == "rotate" and (not nums or nums[0] == 0):
            continue
        if n == "translate" and all(v == 0 for v in nums):
            continue
        if n == "scale" and all(v == 1 for v in nums):
            continue
        if n == "matrix" and tuple(nums) == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0):
            continue
        kept.append(f"{name}({argstr.strip()})")
    if not kept:
        return None
    return " ".join(kept)


def _collapse_ws_attr(name: str, value: str) -> str:
    """d / points 等几何属性压缩空白，便于稳定比较。"""
    if name in ("d", "points"):
        return re.sub(r"\s+", " ", value.strip())
    return value


def normalize(root) -> None:
    """就地规范化（matplotlib 产物与浏览器无关的杂音全部去除）。"""
    # 1) 去掉注释、PI、metadata（含 dc:date 等非确定性内容）
    to_remove = []
    for el in root.iter():
        if not isinstance(el.tag, str):
            to_remove.append(el)
        elif local_name(el) == "metadata":
            to_remove.append(el)
    for el in to_remove:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)

    # 2) 属性排序、transform 清理、几何属性空白压缩
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        attrs = dict(sorted(el.attrib.items()))
        el.attrib.clear()
        for k, v in attrs.items():
            el.set(k, _collapse_ws_attr(k, v))
        if el.get("transform") is not None:
            nt = _normalize_transform_value(el.get("transform"))
            if nt is None:
                del el.attrib["transform"]
            else:
                el.set("transform", nt)

    # 3) 仅空白的 tail 去掉（缩进噪音）；text 内容保持原样
    for el in root.iter():
        if isinstance(el.tag, str) and el.tail and not el.tail.strip():
            el.tail = None
        if isinstance(el.tag, str) and el.text and not el.text.strip() and not _has_element_children(el):
            # 空文本节点去掉（matplotlib 不产生，防御手写）
            el.text = None


def _has_element_children(el) -> bool:
    return any(isinstance(c.tag, str) for c in el)


def canonical_text(svg_text: str) -> str:
    root = parse_svg(svg_text)
    normalize(root)
    return serialize(root)


def base_hash(svg_text: str) -> str:
    """规范化后的 sha1（前 16 位）。对相同渲染结果稳定。"""
    return hashlib.sha1(canonical_text(svg_text).encode("utf-8")).hexdigest()[:16]
