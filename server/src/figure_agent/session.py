"""浏览器选区会话：保存最新选区并富化（fingerprint/语义路径/nearby）。"""

from __future__ import annotations

import threading
from typing import Dict, Optional

from .svgkit import geom, identity, normalize, parse_svg, semantics
from .svgkit.style import get_style_prop, parse_px_number
from .store import Store

_lock = threading.Lock()
_latest: Optional[Dict] = None
_by_figure: Dict[tuple, Dict] = {}


def save_selection(store: Store, project: str, figure: str, selection: dict | list[dict]) -> dict | list[dict]:
    """富化并保存选区（多选时 selection 为数组，逐条富化）。富化失败时原样保存（带 warning）。"""
    items = selection if isinstance(selection, list) else [selection]
    enriched_items = [_enrich_one(store, project, figure, item) for item in items]
    result: dict | list[dict] = enriched_items if isinstance(selection, list) else enriched_items[0]
    with _lock:
        global _latest
        _latest = result
        _by_figure[(project, figure)] = result
    return result


def _enrich_one(store: Store, project: str, figure: str, selection: dict) -> dict:
    enriched = dict(selection or {})
    enriched.setdefault("project", project)
    enriched.setdefault("figure", figure)
    warnings: list[str] = []
    base_text = store.read_svg(project, figure, "final") or store.read_svg(project, figure, "base")
    if base_text:
        try:
            root = parse_svg(base_text)
            normalize(root)
            el = identity.locate(root, selection or {})
            if el is not None:
                enriched["elementId"] = el.get("id")
                enriched["semanticPath"] = semantics.semantic_path(el)
                enriched["fingerprint"] = identity.fingerprint(el)
                enriched["nearby"] = _nearby(store, project, figure, el)
            else:
                warnings.append("无法在当前 SVG 中定位选区元素（id 与语义路径均未命中）")
        except Exception as exc:  # 防御：选区富化失败不影响保存
            warnings.append(f"选区富化失败：{exc}")
    enriched["warnings"] = warnings
    return enriched


def _nearby(store: Store, project: str, figure: str, el) -> list[str]:
    """语义邻居标签：按 bbox 中心距离排序取最近 5 个。"""
    root = el.getroottree().getroot()
    bbox = geom.estimate_bbox(el)
    if bbox is None:
        return []
    names: list[tuple[float, str]] = []
    for sem in semantics.collect_semantic(root):
        if sem is el:
            continue
        b = geom.estimate_bbox(sem)
        if b is None:
            continue
        d = ((b.cx - bbox.cx) ** 2 + (b.cy - bbox.cy) ** 2) ** 0.5
        label = sem.get("id") or ""
        texts = semantics.subtree_texts(sem)
        if texts:
            label += f" {' / '.join(texts[:2])}"
        names.append((d, label))
    names.sort(key=lambda x: x[0])
    return [n[1] for n in names[:5]]


def get_selection(project: Optional[str] = None, figure: Optional[str] = None) -> Optional[dict]:
    with _lock:
        if project and figure:
            return _by_figure.get((project, figure))
        return _latest
