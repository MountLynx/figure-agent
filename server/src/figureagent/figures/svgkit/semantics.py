"""语义层：fa: gid 约定 > matplotlib 自动 id > 原始元素。

语义 id 判定、标签/语义路径（TS 端有同构实现，语义路径算法必须一致）：
- 元素带 id → 标签 = id 原样（含 fa: 前缀）
- 无 id → 标签 = `tag[n]`，n 为同 tag 兄弟中的 1-based 序号
- semanticPath = 从 <svg> 根（不含）到自身的标签序列，用 "/" 连接
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from lxml import etree

from .style import local_name

SEMANTIC_ID_RE = re.compile(r"^(fa:.+|[A-Za-z][\w.]*_\d+)$")


def is_semantic(el) -> bool:
    eid = el.get("id")
    return bool(eid and SEMANTIC_ID_RE.match(eid))


def is_fa(el) -> bool:
    eid = el.get("id") or ""
    return eid.startswith("fa:")


def tag_index(el) -> int:
    """同 tag 兄弟中的 1-based 序号。"""
    tag = el.tag
    i = 0
    for sib in el.itersiblings(preceding=True):
        if sib.tag == tag:
            i += 1
    return i + 1


def label(el) -> str:
    eid = el.get("id")
    if eid:
        return eid
    return f"{local_name(el)}[{tag_index(el)}]"


def semantic_path(el) -> str:
    parts: List[str] = []
    cur = el
    while cur is not None:
        parent = cur.getparent()
        if parent is None:
            break  # 到达 <svg> 根，不纳入路径
        if etree.QName(parent).localname == "svg" and parent.getparent() is None:
            parts.append(label(cur))
            break
        parts.append(label(cur))
        cur = parent
    return "/".join(reversed(parts))


def from_semantic_path(root, path: str):
    """按 semanticPath 走树定位元素（id 漂移时的第二定位手段）。"""
    if not path:
        return None
    cur = root
    for part in path.split("/"):
        nxt = None
        for child in cur:
            if not isinstance(child.tag, str):
                continue
            if label(child) == part:
                nxt = child
                break
        if nxt is None:
            return None
        cur = nxt
    return cur


def collect_semantic(root) -> List:
    return [el for el in root.iter() if isinstance(el.tag, str) and is_semantic(el)]


def collect_selectables(root) -> List:
    """全部语义元素。选中归并在前端做（向上归并到语义组），不在这里裁剪。"""
    return collect_semantic(root)


def nearest_semantic_ancestor(el):
    cur = el.getparent()
    while cur is not None:
        if isinstance(cur.tag, str) and is_semantic(cur):
            return cur
        cur = cur.getparent()
    return None


def direct_semantic_children(root) -> Dict[int, List]:
    """语义节点之间的直接父子：key=语义元素 id(el)，value=其内部的下一层语义元素。"""
    sem = collect_semantic(root)
    sem_set = {id(e) for e in sem}
    out: Dict[int, List] = {id(e): [] for e in sem}
    for e in sem:
        # 找最近语义祖先
        anc = nearest_semantic_ancestor(e)
        if anc is not None:
            out[id(anc)].append(e)
    return out


def leaf_semantics_of(el) -> Set[int]:
    """el 内部的最外层语义后代集合（无中间语义层的直接语义子）。"""
    children = direct_semantic_children(el.getroottree().getroot())
    return {id(c) for c in children.get(id(el), [])}


def subtree_texts(el) -> List[str]:
    """子树内 <text>/<tspan> 的文本内容。"""
    out: List[str] = []
    for desc in el.iter():
        if not isinstance(desc.tag, str):
            continue
        if local_name(desc) in ("text", "tspan"):
            t = "".join(desc.itertext())
            if t.strip():
                out.append(t.strip())
    return out


def first_text_el(el):
    for desc in el.iter():
        if isinstance(desc.tag, str) and local_name(desc) in ("text", "tspan"):
            return desc
    if local_name(el) in ("text", "tspan"):
        return el
    return None
