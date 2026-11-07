"""图表保留名（原 D25 守护的精简版）。

图内容文件就在工作目录里：``plot.py`` 是真相源，「是否有图」= ``plot.py`` 存在
（判定在 :class:`figureagent.workdir.Workdir.has_figure`）。建图前若保留名已被
占用（用户自己的同名附件），一律拒绝——否则会把用户文件当图产物覆盖掉。

独立服务里没有 files 域，故只剩常量与 :func:`is_reserved` 判定。
"""

from __future__ import annotations

from pathlib import Path

RESERVED_NAMES = (
    "plot.py",
    "data.csv",
    "data_profile.json",
    "base.svg",
    "final.svg",
    "patch.json",
)
RESERVED_DIRS = ("uploads", "history")


def is_reserved(rel: str) -> bool:
    """首段命中保留名即保留（uploads/x.png 与 uploads 同受保护）。"""
    first = Path((rel or "").replace("\\", "/")).parts[0] if rel else ""
    return first in RESERVED_NAMES or first in RESERVED_DIRS
