"""配置：workspace 与端口解析（env 可覆盖）。"""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent.parent.parent  # server/src/figure_agent → 仓库根


def workspace_dir() -> Path:
    env = os.environ.get("FA_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    return REPO_ROOT / "workspace"


def web_dist_dir() -> Path:
    env = os.environ.get("FA_WEB_DIST")
    if env:
        return Path(env).expanduser().resolve()
    return REPO_ROOT / "web" / "dist"


def port() -> int:
    return int(os.environ.get("FA_PORT", "8765"))


def render_timeout() -> float:
    return float(os.environ.get("FA_RENDER_TIMEOUT", "30"))
