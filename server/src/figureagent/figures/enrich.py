"""选区富化（纯函数）：在当前 SVG 中定位选区元素并补全
elementId/semanticPath/fingerprint/nearby。供 enrich-selection 端点与
instruct 工作流共用；无任何全局状态。"""

from __future__ import annotations

from .svgkit import geom, identity, normalize, parse_svg, semantics
from .store import FigureStore


def enrich_selection(store: FigureStore, selection: dict) -> dict:
    """富化单条选区。富化失败不影响调用方保存（带 warning）。"""
    enriched = dict(selection or {})
    warnings: list[str] = []
    base_text = store.read_svg("final") or store.read_svg("base")
    if base_text:
        try:
            root = parse_svg(base_text)
            normalize(root)
            el = identity.locate(root, selection or {})
            if el is not None:
                enriched["elementId"] = el.get("id")
                enriched["semanticPath"] = semantics.semantic_path(el)
                enriched["fingerprint"] = identity.fingerprint(el)
                enriched["nearby"] = _nearby(el)
            else:
                warnings.append("无法在当前 SVG 中定位选区元素（id 与语义路径均未命中）")
        except Exception as exc:  # 防御：选区富化失败不影响保存
            warnings.append(f"选区富化失败：{exc}")
    enriched["warnings"] = warnings
    return enriched


def _nearby(el) -> list[str]:
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
