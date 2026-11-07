"""路径穿越防护：解析 ``<工作目录>/<rel_path>`` 并拒绝越界（对齐 Rust safe_path.rs）。

Windows 注意：``Path.resolve()`` 即规范化（含符号链接与 ..），非存在路径也能解析出
绝对形式；再以工作目录（已 resolve）为前缀判定。curdir/parentdir 分量在 resolve
中已被消除，无需重复折叠。
"""

from __future__ import annotations

from pathlib import Path


def safe_path(root: Path | str, rel_path: str) -> Path:
    """把相对工作目录的路径解析成绝对路径；越界即 ``ValueError``。"""
    base = Path(root).resolve()
    candidate = (base / (rel_path or "")).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError("Path traversal detected")
    return candidate
