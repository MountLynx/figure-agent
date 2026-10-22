"""svgkit：SVG 规范化、语义组、身份匹配、patch 应用与收敛判定（纯函数库）。"""

from .style import (
    declares_attr,
    effective_values,
    get_style_prop,
    normalize_color,
    parse_style,
    serialize_style,
    set_style_prop,
)
from .normalize import (
    SVG_NS,
    XLINK_NS,
    base_hash,
    normalize,
    parse_svg,
    serialize,
)
from . import semantics, identity, patchops, geom

__all__ = [
    "SVG_NS",
    "XLINK_NS",
    "base_hash",
    "normalize",
    "parse_svg",
    "serialize",
    "semantics",
    "identity",
    "patchops",
    "geom",
    "style",
]
