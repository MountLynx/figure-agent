"""patch 应用（final = base + patch）与收敛判定（verify）。

- apply_patch：把 active op 应用到 base SVG，产出 final；lost op 跳过。
- verify_patch：判定新 base 是否已表达每个 op（代码回写收敛）。
  transform 类 op 依赖创建时记录的 pre（基准 center/size），按 target
  分组判定（同一目标的多个 translate/scale 看合成效果）。
  set_visible(隐藏) 是唯一"目标消失 = 已表达"的 op：set_visible(False)
  的 artist 根本不会渲染进 SVG。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from . import geom, identity, semantics
from .style import (
    declares_attr,
    effective_values,
    font_family_matches,
    get_style_prop,
    local_name,
    normalize_color,
    parse_px_number,
    set_style_prop,
)

STYLE_ATTRS = {"fill", "stroke", "font-family", "font-size", "opacity"}
NUM_EPS = 0.5          # font-size / 坐标容差（user unit）
OPACITY_EPS = 0.02
TRANS_EPS = 0.75       # 平移收敛容差（user unit）
SCALE_EPS = 0.03       # 缩放相对容差

TRANSFORM_KINDS = {"translate", "scale"}
REORDER_TOS = {"front", "back"}


def _quote_font_family(value: str) -> str:
    families = [f.strip() for f in value.split(",")]
    quoted = [f"'{f.strip(chr(39).strip(chr(34)))}'" if (" " in f and not f.startswith(("'", '"'))) else f for f in families]
    return ", ".join(quoted)


def _apply_set_style(el, attr: str, value: str) -> None:
    v = value.strip()
    if attr == "font-family":
        v = _quote_font_family(v)
    declared: List = []
    if declares_attr(el, attr):
        declared.append(el)
    for desc in el.iter():
        if desc is not el and isinstance(desc.tag, str) and declares_attr(desc, attr):
            declared.append(desc)
    if declared:
        for node in declared:
            set_style_prop(node, attr, v)
    else:
        set_style_prop(el, attr, v)


def _apply_set_text(el, value: str) -> bool:
    t = semantics.first_text_el(el)
    if t is None:
        return False
    # 清空子节点后写纯文本
    for child in list(t):
        t.remove(child)
    t.text = value
    return True


def _translate_piece(dx: float, dy: float) -> str:
    return f"translate({_fmt(dx)} {_fmt(dy)})"


def _scale_piece(sx: float, sy: float, cx: float, cy: float) -> str:
    return f"translate({_fmt(cx)} {_fmt(cy)}) scale({_fmt(sx)} {_fmt(sy)}) translate({_fmt(-cx)} {_fmt(-cy)})"


def _fmt(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def apply_patch(base_root, patch: dict) -> Tuple[Optional[str], Dict[str, str]]:
    """返回 (final_svg_text 或 None(base 解析失败时不会到这)，{op_id: applied|lost|invalid})。"""
    per_op: Dict[str, str] = {}
    root = base_root
    for op in (patch or {}).get("ops", []):
        op_id = op.get("id", "?")
        status = op.get("status", "active")
        kind = op.get("kind")
        if status not in ("active", None):
            per_op[op_id] = "skipped"
            continue
        if kind not in ("set_style", "set_text", "transform", "set_visible", "reorder"):
            per_op[op_id] = "invalid"
            continue
        el = identity.locate(root, op.get("target") or {})
        if el is None:
            per_op[op_id] = "lost"
            continue
        if kind == "set_style":
            attr = op.get("attr", "")
            if attr not in STYLE_ATTRS:
                per_op[op_id] = "invalid"
                continue
            _apply_set_style(el, attr, str(op.get("value", "")))
            per_op[op_id] = "applied"
        elif kind == "set_visible":
            if bool(op.get("value")):
                set_style_prop(el, "display", None)
            else:
                set_style_prop(el, "display", "none")
            per_op[op_id] = "applied"
        elif kind == "reorder":
            parent = el.getparent()
            to = (op.get("value") or {}).get("to")
            if parent is None or to not in REORDER_TOS:
                per_op[op_id] = "invalid"
                continue
            parent.remove(el)
            if to == "front":
                parent.append(el)
            else:
                parent.insert(0, el)
            per_op[op_id] = "applied"
        elif kind == "set_text":
            ok = _apply_set_text(el, str(op.get("value", "")))
            per_op[op_id] = "applied" if ok else "invalid"
        elif kind == "transform":
            value = op.get("value") or {}
            pieces: List[str] = []
            if "translate" in value:
                dx, dy = float(value["translate"][0]), float(value["translate"][1])
                pieces.append(_translate_piece(dx, dy))
            if "scale" in value:
                sx, sy = float(value["scale"][0]), float(value["scale"][1])
                pre = op.get("pre") or {}
                center = pre.get("center")
                if center:
                    cx, cy = float(center[0]), float(center[1])
                else:
                    bbox = geom.estimate_bbox(el)
                    cx, cy = (bbox.cx, bbox.cy) if bbox else (0.0, 0.0)
                pieces.append(_scale_piece(sx, sy, cx, cy))
            if not pieces:
                per_op[op_id] = "invalid"
                continue
            existing = el.get("transform")
            el.set("transform", " ".join(pieces + ([existing] if existing else [])))
            per_op[op_id] = "applied"
    from .normalize import serialize
    return serialize(root), per_op


# ---------------------------------------------------------------- verify


def _style_satisfied(new_root, op) -> Tuple[bool, str]:
    el = identity.locate(new_root, op.get("target") or {})
    if el is None:
        return False, "lost"
    attr = op.get("attr", "")
    expected = str(op.get("value", "")).strip()
    values = effective_values(el, attr)
    if not values:
        return False, f"代码未声明 {attr}"
    if attr == "fill" or attr == "stroke":
        exp = normalize_color(expected)
        for v in values:
            if normalize_color(v) != exp:
                return False, f"{attr}={v!r} ≠ {expected!r}"
        return True, ""
    if attr in ("font-size", "opacity"):
        exp = float(re.sub(r"[^\d.eE+-]", "", expected) or 0)
        for v in values:
            cur = parse_px_number(v)
            if cur is None:
                return False, f"{attr}={v!r} 无法解析"
            eps = OPACITY_EPS if attr == "opacity" else NUM_EPS
            if abs(cur - exp) > eps:
                return False, f"{attr}={cur} ≠ {exp}"
        return True, ""
    if attr == "font-family":
        if not font_family_matches(values, expected):
            return False, f"font-family {values} 不含 {expected!r}"
        return True, ""
    return False, f"未知 attr {attr}"


def _text_satisfied(new_root, op) -> Tuple[bool, str]:
    el = identity.locate(new_root, op.get("target") or {})
    if el is None:
        return False, "lost"
    t = semantics.first_text_el(el)
    if t is None:
        return False, "目标不含文本"
    expected = str(op.get("value", "")).strip()
    actual = "".join(t.itertext()).strip()
    if actual == expected:
        return True, ""
    return False, f"文本 {actual!r} ≠ {expected!r}"


def _target_key(target: dict) -> Tuple:
    return (target.get("id") or "", target.get("semanticPath") or "", target.get("fingerprint") or "")


def _transform_satisfied(new_root, ops_in_group: List[dict]) -> Dict[str, Tuple[bool, str]]:
    """同一目标的 transform op 合成判定。"""
    out: Dict[str, Tuple[bool, str]] = {}
    el = None
    pre_center = None
    pre_size = None
    total_dx = total_dy = 0.0
    prod_sx = prod_sy = 1.0
    for op in ops_in_group:
        value = op.get("value") or {}
        pre = op.get("pre") or {}
        if pre_center is None and pre.get("center"):
            pre_center = tuple(float(v) for v in pre["center"])
        if pre_size is None and pre.get("size"):
            pre_size = tuple(float(v) for v in pre["size"])
        if "translate" in value:
            total_dx += float(value["translate"][0])
            total_dy += float(value["translate"][1])
        if "scale" in value:
            sx = float(value["scale"][0])
            sy = float(value["scale"][1]) if len(value["scale"]) > 1 else sx
            prod_sx *= sx
            prod_sy *= sy
    if el is None:
        el = identity.locate(new_root, ops_in_group[0].get("target") or {})
    if el is None:
        return {op.get("id", "?"): (False, "lost") for op in ops_in_group}
    bbox = geom.estimate_bbox(el)
    if bbox is None:
        return {op.get("id", "?"): (False, "无法估算 bbox") for op in ops_in_group}
    ok_all = True
    detail = ""
    if (total_dx or total_dy) or (prod_sx == 1.0 and prod_sy == 1.0 and pre_center):
        if pre_center is None:
            ok_all = False
            detail = "缺 pre 基准（center）"
        else:
            dx = bbox.cx - (pre_center[0] + total_dx)
            dy = bbox.cy - (pre_center[1] + total_dy)
            if abs(dx) > TRANS_EPS or abs(dy) > TRANS_EPS:
                ok_all = False
                detail = f"中心偏移 ({dx:+.2f}, {dy:+.2f}) 超容差"
    if prod_sx != 1.0 or prod_sy != 1.0:
        if pre_size is None:
            ok_all = False
            detail = detail or "缺 pre 基准（size）"
        else:
            exp_w = pre_size[0] * prod_sx
            exp_h = pre_size[1] * prod_sy
            tol_w = max(abs(exp_w) * SCALE_EPS, TRANS_EPS)
            tol_h = max(abs(exp_h) * SCALE_EPS, TRANS_EPS)
            if abs(bbox.w - exp_w) > tol_w or abs(bbox.h - exp_h) > tol_h:
                ok_all = False
                detail = detail or f"尺寸 {bbox.w:.2f}x{bbox.h:.2f} ≠ 期望 {exp_w:.2f}x{exp_h:.2f}"
    for op in ops_in_group:
        out[op.get("id", "?")] = (ok_all, detail)
    return out


def _visible_satisfied(new_root, op) -> Tuple[bool, str]:
    """可见性收敛：隐藏 op 的目标从新 base 消失 = 代码已 set_visible(False)，判 resolved。

    这是唯一"目标不存在 = 成功"的 op。目标还在时看是否声明了 display:none
    （代码若用样式方式隐藏也能收敛）。
    """
    el = identity.locate(new_root, op.get("target") or {})
    want_show = bool(op.get("value"))
    if el is None:
        return (True, "") if not want_show else (False, "lost")
    display = get_style_prop(el, "display")
    if want_show:
        if display in (None, "", "inline"):
            return True, ""
        return False, f"display={display!r} 仍声明隐藏"
    if display == "none":
        return True, ""
    return False, "代码未隐藏目标（未声明 display:none，元素仍在渲染中）"


def _reorder_satisfied(new_root, op) -> Tuple[bool, str]:
    """排序收敛（尽力而为）：matplotlib 按 zorder 排序绘制，SVG 文档顺序大体
    跟随，但同 zorder 稳定排序、collection 内部不可拆——因此按"是否处于
    父容器首/末位"判定，未处于极端位时保持 active 并给出位置详情。"""
    el = identity.locate(new_root, op.get("target") or {})
    if el is None:
        return False, "lost"
    parent = el.getparent()
    if parent is None:
        return False, "目标无父容器"
    siblings = [c for c in parent if isinstance(c.tag, str)]
    if el not in siblings:
        return False, "目标不在兄弟序列中"
    to = (op.get("value") or {}).get("to")
    idx = siblings.index(el) + 1
    if to == "front":
        if siblings[-1] is el:
            return True, ""
        return False, f"未处于最上层（兄弟位 {idx}/{len(siblings)}）"
    if to == "back":
        if siblings[0] is el:
            return True, ""
        return False, f"未处于最下层（兄弟位 {idx}/{len(siblings)}）"
    return False, f"未知 to {(op.get('value') or {}).get('to')!r}"


def verify_patch(new_root, patch: dict) -> Dict[str, dict]:
    """逐 op 判定新 base 是否已表达。返回 {op_id: {status, detail}}。

    status ∈ resolved | active | lost。transform op 按 target 分组判定。
    """
    ops = [op for op in (patch or {}).get("ops", []) if op.get("status", "active") == "active"]
    results: Dict[str, dict] = {}
    transform_groups: Dict[Tuple, List[dict]] = {}
    for op in ops:
        op_id = op.get("id", "?")
        kind = op.get("kind")
        if kind == "set_style":
            ok, detail = _style_satisfied(new_root, op)
            results[op_id] = {"status": "resolved" if ok else "active", "detail": detail}
        elif kind == "set_text":
            ok, detail = _text_satisfied(new_root, op)
            results[op_id] = {"status": "resolved" if ok else "active", "detail": detail}
        elif kind == "set_visible":
            ok, detail = _visible_satisfied(new_root, op)
            results[op_id] = {"status": "resolved" if ok else "active", "detail": detail}
        elif kind == "reorder":
            ok, detail = _reorder_satisfied(new_root, op)
            results[op_id] = {"status": "resolved" if ok else "active", "detail": detail}
        elif kind == "transform":
            transform_groups.setdefault(_target_key(op.get("target") or {}), []).append(op)
        else:
            results[op_id] = {"status": "active", "detail": f"未知 kind {kind}"}
    for group in transform_groups.values():
        for op_id, (ok, detail) in _transform_satisfied(new_root, group).items():
            results[op_id] = {"status": "resolved" if ok else "active", "detail": detail}
    return results


def prune_resolved(patch: dict, results: Dict[str, dict]) -> dict:
    """从 patch 中删除 resolved 的 op（回写完成即清空）。"""
    ops = [op for op in patch.get("ops", []) if results.get(op.get("id", "?"), {}).get("status") != "resolved"]
    return {"baseHash": patch.get("baseHash", ""), "ops": ops}
