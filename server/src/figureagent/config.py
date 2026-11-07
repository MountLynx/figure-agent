"""figureagent 配置：渲染超时 / 模板目录 / 应用数据目录（LLM 配置）/ 前端产物目录。

全部走环境变量，没有任何数据库或仓库配置：

- ``FIGUREAGENT_RENDER_TIMEOUT``：渲染超时秒数，默认 30；
- ``templates_dir()``：随包分发的 plot.py 模板（``figures/templates/<id>/``）；
- ``FIGUREAGENT_HOME``：应用数据目录，默认 ``~/.figureagent``（``llm.json`` + ``.env``）；
- ``FIGUREAGENT_WEB_DIST``：前端构建产物目录，默认 ``<repo>/web/dist``（相对 server 包定位）；
- 免 key 冒烟开关：``FIGUREAGENT_MOCK=1``（兼容旧名 ``FIGURE_AGENT_MOCK`` / ``RI_FIGURE_MOCK``）。
"""

from __future__ import annotations

import os
from pathlib import Path

#: 包目录：<repo>/server/src/figureagent
_PKG_DIR = Path(__file__).resolve().parent
#: server 包目录：<repo>/server
_SERVER_DIR = _PKG_DIR.parents[1]
#: 仓库根：<repo>（= figure-agent/）
_REPO_DIR = _SERVER_DIR.parent

#: 前端产物相对 server 包的位置：../web/dist
DEFAULT_WEB_DIST = _REPO_DIR / "web" / "dist"

#: 免 key 冒烟开关的接受名（新名在前；两种旧名保留兼容）。
MOCK_ENV_KEYS = ("FIGUREAGENT_MOCK", "FIGURE_AGENT_MOCK", "RI_FIGURE_MOCK")


def render_timeout() -> float:
    return float(os.environ.get("FIGUREAGENT_RENDER_TIMEOUT", "30"))


def templates_dir() -> Path:
    return _PKG_DIR / "figures" / "templates"


def web_dist_dir() -> Path:
    """前端构建产物目录（``vite build`` → ``web/dist``）。目录可能不存在。"""
    override = os.environ.get("FIGUREAGENT_WEB_DIST")
    return Path(override) if override else DEFAULT_WEB_DIST


def home_dir() -> Path:
    """应用数据目录：llm.json、.env 所在地（图可属任何目录，故是应用级而非目录级）。"""
    return Path(os.environ.get("FIGUREAGENT_HOME") or (Path.home() / ".figureagent"))


def llm_config_path() -> Path:
    return home_dir() / "llm.json"


def llm_env_path() -> Path:
    return home_dir() / ".env"


def mock_enabled() -> bool:
    """是否有任一 mock 开关被打开（``=1``）。"""
    return any(os.environ.get(key) == "1" for key in MOCK_ENV_KEYS)
