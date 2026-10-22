"""元素身份：指纹与 match（重渲染后的目标重定位/治愈）。

指纹 = (形状或文本 hash) + 祖先链标签 + 同 tag 序号，sha1 截 4 位，前缀 p:。
匹配顺序：id 精确 → 指纹 → 祖先链+序号降级（文本元素要求文本相同）→ lost。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from lxml import etree

from . import geom
from .normalize import XLINK_NS
from .semantics import (
    is_semantic,
    label,
    local_name,
    semantic_path,
    subtree_texts,
    from_semantic_path,
)
from .style import local_name as _ln

TEXT_TAGS = {"text", "tspan"}
SHAPE_TAGS = {"path", "rect", "circle", "ellipse", "line", "polygon", "polyline", "use"}


def element_sibling_index(el) -> int:
    """全部元素兄弟中的 1-based 序号。"""
    i = 0
    for sib in el.itersiblings(preceding=True):
        if isinstance(sib.tag, str):
            i += 1
    return i + 1


def ancestor_labels(el) -> str:
    parts: List[str] = []
    cur = el.getparent()
    while cur is not None and cur.getparent() is not None:
        parts.append(label(cur))
        cur = cur.getparent()
    return "/".join(reversed(parts))


def _shape_key(el) -> Optional[str]:
    """形状的归一化 key：平移不变、等比缩放不变（保留纵横比），量化到 3 位。"""
    tag = local_name(el)
    if tag == "path":
        pts = geom.path_points(el.get("d", ""))
        if len(pts) < 2:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, y0 = xs[0], ys[0]
        w = max(max(xs) - min(xs), 1e-6)
        h = max(max(ys) - min(ys), 1e-6)
        s = max(w, h)
        rel = [((x - x0) / s, (y - y0) / s) for x, y in pts]
        return "path:" + ";".join(f"{round(a,3):.3f},{round(b,3):.3f}" for a, b in rel)
    if tag == "rect":
        return f"rect:{float(el.get('width',0) or 0):.3f}x{float(el.get('height',0) or 0):.3f}"
    if tag == "circle":
        return f"circle:{float(el.get('r',0) or 0):.3f}"
    if tag == "ellipse":
        return f"ellipse:{float(el.get('rx',0) or 0):.3f}x{float(el.get('ry',0) or 0):.3f}"
    if tag == "line":
        dx = float(el.get("x2", 0) or 0) - float(el.get("x1", 0) or 0)
        dy = float(el.get("y2", 0) or 0) - float(el.get("y1", 0) or 0)
        return f"line:{dx:.3f},{dy:.3f}"
    if tag == "use":
        href = el.get("href") or el.get(f"{{{XLINK_NS}}}href") or ""
        return f"use:{href}"
    return None


def fingerprint(el) -> str:
    texts = subtree_texts(el) if local_name(el) in ("g",) else []
    if local_name(el) in TEXT_TAGS or (local_name(el) == "g" and texts and len(list(el)) == 1):
        # 文本元素/文本包装组：文本内容指纹
        content = "|".join(texts) if texts else "".join(el.itertext()).strip()
        kind = "t"
        body = content
    else:
        kind = "p"
        body = _shape_key(el) or f"tag:{local_name(el)}"
    src = f"{kind}:{body}|{ancestor_labels(el)}|{element_sibling_index(el)}"
    return "p:" + hashlib.sha1(src.encode("utf-8")).hexdigest()[:4]


def find_by_id(root, el_id: str):
    """getElementById；id 重复时优先 fa:/语义 id 在外层的那个（跳过 defs 内）。"""
    cands = [el for el in root.iter() if isinstance(el.tag, str) and el.get("id") == el_id]
    if not cands:
        return None
    non_defs = [e for e in cands if not _in_defs(e)]
    pool = non_defs or cands
    for e in pool:
        if is_semantic(e):
            return e
    return pool[0]


def _in_defs(el) -> bool:
    cur = el.getparent()
    while cur is not None:
        if isinstance(cur.tag, str) and local_name(cur) == "defs":
            return True
        cur = cur.getparent()
    return False


def locate(root, target: dict):
    """按 target.id → semanticPath → fingerprint 定位。返回元素或 None。"""
    tid = (target or {}).get("id")
    if tid:
        el = find_by_id(root, tid)
        if el is not None:
            return el
    sp = (target or {}).get("semanticPath")
    if sp:
        el = from_semantic_path(root, sp)
        if el is not None:
            return el
    fp = (target or {}).get("fingerprint")
    if fp:
        el = find_by_fingerprint(root, fp)
        if el is not None:
            return el
    return None


def find_by_fingerprint(root, fp: str):
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        try:
            if fingerprint(el) == fp:
                return el
        except Exception:
            continue
    return None


@dataclass
class MatchResult:
    op_id: str
    status: str                 # matched | lost
    target: dict = field(default_factory=dict)
    degraded: bool = False


def refresh_target(el) -> dict:
    return {
        "id": el.get("id") or None,
        "semanticPath": semantic_path(el),
        "fingerprint": fingerprint(el),
    }


def _counterpart(old_el, new_root, want_id: Optional[str], want_fp: Optional[str]):
    """老元素在新图中的对应者：id → 指纹 → 祖先链+序号（降级）。"""
    if want_id:
        el = find_by_id(new_root, want_id)
        if el is not None:
            return el, False
    if want_fp:
        el = find_by_fingerprint(new_root, want_fp)
        if el is not None:
            return el, False
    # 降级：相同的祖先链标签 + 同 tag 序号
    chain = [label(x) for x in _ancestor_chain(old_el)]
    cur = new_root
    for lab in chain[:-1]:
        nxt = None
        for child in cur:
            if isinstance(child.tag, str) and label(child) == lab:
                nxt = child
                break
        if nxt is None:
            return None, True
        cur = nxt
    for child in cur:
        if isinstance(child.tag, str) and label(child) == chain[-1]:
            ok = _compatible(old_el, child)
            return (child, True) if ok else (None, True)
    return None, True


def _ancestor_chain(el) -> List:
    chain: List = []
    cur = el
    while cur is not None and cur.getparent() is not None:
        chain.append(cur)
        cur = cur.getparent()
    return list(reversed(chain))


def _compatible(old_el, new_el) -> bool:
    """降级匹配时要求类型相容：文本元素要求文本一致，形状要求同 tag。"""
    t_old = local_name(old_el)
    t_new = local_name(new_el)
    if t_old in TEXT_TAGS or t_new in TEXT_TAGS:
        return "".join(old_el.itertext()).strip() == "".join(new_el.itertext()).strip()
    if t_old in SHAPE_TAGS and t_new in SHAPE_TAGS:
        return t_old == t_new
    return t_old == t_new


def match(old_root, new_root, ops) -> Dict[str, MatchResult]:
    """重渲染后逐 op 重定位目标并治愈 target 引用。"""
    results: Dict[str, MatchResult] = {}
    for op in ops:
        op_id = op.get("id", "")
        target = op.get("target") or {}
        old_el = locate(old_root, target) if old_root is not None else None
        if old_el is None:
            # 老图里也定位不到（例如 AI 手写 patch）：直接在新图按 target 找
            new_el = locate(new_root, target)
            if new_el is not None:
                results[op_id] = MatchResult(op_id, "matched", refresh_target(new_el))
            else:
                results[op_id] = MatchResult(op_id, "lost", target)
            continue
        want_id = old_el.get("id")
        try:
            want_fp = fingerprint(old_el)
        except Exception:
            want_fp = None
        new_el, degraded = _counterpart(old_el, new_root, want_id, want_fp)
        if new_el is None:
            # 指纹也失败时再试老 target 里存下来的指纹（可能更"新鲜"）
            fp2 = target.get("fingerprint")
            if fp2 and fp2 != want_fp:
                new_el = find_by_fingerprint(new_root, fp2)
                degraded = False
        if new_el is None:
            results[op_id] = MatchResult(op_id, "lost", target)
        else:
            results[op_id] = MatchResult(op_id, "matched", refresh_target(new_el), degraded)
    return results
