"""工作目录：独立 figures 服务唯一认的那个目录。

一个 ``Workdir`` 就是一个普通文件夹；服务只读写它下面的保留文件（``plot.py``、
``data.csv``、``data_profile.json``、``base.svg``、``final.svg``、``patch.json``、
``uploads/``、``history/``），不碰任何数据库，也不存在「条目」这一层。

校验规则（任一不满足即 ``ValueError``，API 层统一转 400）：

- 必须是绝对路径（``~`` 先展开，展开后仍须绝对）；
- 拒绝含 ``..`` 分量的路径（在解析前按分量判定，避免 ``a/../b`` 绕过）；
- 必须存在；
- 必须是目录（文件不行）。

``has_figure()`` 是「是否有图」的唯一判定：``plot.py`` 是否存在。Index 宿主侧
也照此判定，服务不再回写任何属性。
"""

from __future__ import annotations

from pathlib import Path

#: 图内容的保留文件名（与 figure_guard.RESERVED_NAMES 同源，此处只列路径访问器用到的）。
PLOT_NAME = "plot.py"
DATA_NAME = "data.csv"
DATA_PROFILE_NAME = "data_profile.json"
PATCH_NAME = "patch.json"
BASE_SVG_NAME = "base.svg"
FINAL_SVG_NAME = "final.svg"

#: 保留目录名。
UPLOADS_DIRNAME = "uploads"
HISTORY_DIRNAME = "history"

#: AI 运行审计日志（原 fig_runs 表的替身；JSONL，落在 history/ 里，不新增保留名）。
RUNS_NAME = "runs.jsonl"


def parse_workdir(raw: str | Path) -> Path:
    """校验并规范化工作目录，返回 resolve 后的绝对路径。"""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("工作目录为空：需要 --dir <绝对路径>")
    path = Path(text).expanduser()
    if ".." in path.parts:
        raise ValueError(f"工作目录不得包含 ..：{text}")
    if not path.is_absolute():
        raise ValueError(f"工作目录必须是绝对路径：{text}")
    if not path.exists():
        raise ValueError(f"工作目录不存在：{text}")
    if not path.is_dir():
        raise ValueError(f"工作目录不是目录：{text}")
    return path.resolve()


class Workdir:
    """单个工作目录（构造即校验）。"""

    def __init__(self, raw: str | Path) -> None:
        self.root: Path = parse_workdir(raw)

    # ---------------------------------------------------------------- 标识

    def name(self) -> str:
        """目录名（前端标题用）。驱动器根目录没有名字时退回完整路径。"""
        return self.root.name or str(self.root)

    # ---------------------------------------------------------------- 判定

    def has_figure(self) -> bool:
        """「是否有图」= plot.py 存在（唯一真相源）。"""
        return self.plot_path().is_file()

    # ---------------------------------------------------------------- 路径访问器

    def plot_path(self) -> Path:
        return self.root / PLOT_NAME

    def data_path(self) -> Path:
        return self.root / DATA_NAME

    def data_profile_path(self) -> Path:
        return self.root / DATA_PROFILE_NAME

    def patch_path(self) -> Path:
        return self.root / PATCH_NAME

    def base_svg_path(self) -> Path:
        return self.root / BASE_SVG_NAME

    def final_svg_path(self) -> Path:
        return self.root / FINAL_SVG_NAME

    def svg_paths(self) -> dict[str, Path]:
        """两版 SVG：base = 代码渲染产物，final = 叠加 patch 后的呈现。"""
        return {"base": self.base_svg_path(), "final": self.final_svg_path()}

    def uploads_dir(self) -> Path:
        return self.root / UPLOADS_DIRNAME

    def history_dir(self) -> Path:
        """快照目录（``history/<时间戳>/``）；审计日志也在它下面。"""
        return self.root / HISTORY_DIRNAME

    def runs_path(self) -> Path:
        return self.history_dir() / RUNS_NAME

    # ---------------------------------------------------------------- 杂项

    def __str__(self) -> str:  # pragma: no cover - 仅日志/报错展示
        return str(self.root)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试展示
        return f"Workdir({str(self.root)!r})"
