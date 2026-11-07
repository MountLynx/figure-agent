"""测试共享 fixture：matplotlib 场景 + 临时工作目录（不建仓库、不建数据库）。

- scene_a：分组柱状图（fa: gid）
- scene_b：数据微变 + 处理组改红（模拟"回写后的代码"）
- scene_a2：与 scene_a 相同代码再渲染一次（测确定性）

工作目录夹具：``workdir``（空目录）/ ``fig_store``（含 data.csv + uploads/d.csv）；
应用夹具：``client``（已绑定目录）/ ``no_workdir_client``（未绑定）。
"""

from __future__ import annotations

import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from figureagent.figures.store import FigureStore  # noqa: E402
from figureagent.figservice import create_app  # noqa: E402
from figureagent.workdir import Workdir  # noqa: E402


def _render(code: str) -> str:
    plt.rcdefaults()
    plt.rcParams["svg.fonttype"] = "none"
    plt.rcParams["svg.hashsalt"] = "figure-agent"
    g: dict = {}
    exec(compile(code, "<test>", "exec"), g)  # noqa: S102
    buf = io.StringIO()
    g["fig"].savefig(buf, format="svg")
    return buf.getvalue()


PLOT_A = """
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(5.2, 3.6))
control = [2.1, 3.2, 2.8]
treatment = [3.4, 4.1, 3.9]
x = range(3)
w = 0.36
bc = ax.bar([i - w/2 for i in x], control, width=w, label="control", color="#8aa8c4")
bt = ax.bar([i + w/2 for i in x], treatment, width=w, label="treatment", color="#d08770")
for i, b in enumerate(bc):
    b.set_gid(f"fa:control-bar-{i}")
for i, b in enumerate(bt):
    b.set_gid(f"fa:treatment-bar-{i}")
ax.set_xticks(list(x)); ax.set_xticklabels(["A", "B", "C"])
ax.set_ylabel("value")
ax.set_title("groups")
ax.legend()
"""

PLOT_B = PLOT_A.replace("control = [2.1, 3.2, 2.8]", "control = [2.0, 3.0, 2.7]").replace(
    '"#d08770"', '"#dd3322"'
)

PLOT_SCATTER = """
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(5, 4))
sc = ax.scatter([1, 2, 3], [2, 3, 1], s=30, c="#4477aa", label="set")
sc.set_gid("fa:set")
sc2 = ax.scatter([1.5, 2.5], [1.0, 3.5], s=30, c="#ee7733", label="other")
sc2.set_gid("fa:other")
ax.legend()
"""

PLOT_TEXT = """
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(4, 3))
ax.plot([0, 1], [0, 1])
t = ax.set_title("hello title")
ax.text(0.5, 0.3, "annotation", ha="center")
"""


@pytest.fixture(scope="session")
def svg_a() -> str:
    return _render(PLOT_A)


@pytest.fixture(scope="session")
def svg_a2() -> str:
    return _render(PLOT_A)


@pytest.fixture(scope="session")
def svg_b() -> str:
    return _render(PLOT_B)


@pytest.fixture(scope="session")
def svg_scatter() -> str:
    return _render(PLOT_SCATTER)


@pytest.fixture(scope="session")
def svg_text() -> str:
    return _render(PLOT_TEXT)


@pytest.fixture()
def roots_a(svg_a):
    from figureagent.figures.svgkit import normalize, parse_svg

    root = parse_svg(svg_a)
    normalize(root)
    return root


@pytest.fixture()
def roots_b(svg_b):
    from figureagent.figures.svgkit import normalize, parse_svg

    root = parse_svg(svg_b)
    normalize(root)
    return root


CSV_TEXT = "dose,response\n0,1.1\n5,2.3\n10,3.9\n"

GOOD_PLOT = (
    "import matplotlib\nmatplotlib.use('Agg')\n"
    "import matplotlib.pyplot as plt\n"
    "fig, ax = plt.subplots(figsize=(5, 3.6))\n"
    "ax.plot([0, 1], [0, 1])\n"
    't = ax.set_title("hello")\nt.set_gid("fa:title")\n'
    "fig.tight_layout()\n"
)


# ---------------------------------------------------------------- 应用数据目录


@pytest.fixture()
def home(tmp_path, monkeypatch) -> Path:
    """应用数据目录指到临时目录，并清掉 mock 开关（不读用户 ~/.figureagent）。"""
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("FIGUREAGENT_HOME", str(path))
    for key in ("FIGUREAGENT_MOCK", "FIGURE_AGENT_MOCK", "RI_FIGURE_MOCK"):
        monkeypatch.delenv(key, raising=False)
    return path


# ---------------------------------------------------------------- 工作目录 / store


@pytest.fixture()
def workdir(tmp_path, home) -> Workdir:
    """空工作目录（还没有 plot.py）。"""
    root = tmp_path / "MyData"
    root.mkdir()
    return Workdir(root)


@pytest.fixture()
def fig_store(workdir) -> tuple[FigureStore, Workdir]:
    """图目录（uploads/d.csv 与 data.csv 已备好，尚无 plot.py）。返回 (store, workdir)。"""
    uploads = workdir.uploads_dir()
    uploads.mkdir(parents=True)
    (uploads / "d.csv").write_text(CSV_TEXT, encoding="utf-8")
    workdir.data_path().write_text(CSV_TEXT, encoding="utf-8")
    return FigureStore(workdir), workdir


# ---------------------------------------------------------------- TestClient


@pytest.fixture()
def client(workdir):
    """已绑定工作目录的 app（--dir 等价）。"""
    with TestClient(create_app(workdir)) as c:
        yield c


@pytest.fixture()
def no_workdir_client(tmp_path, home):
    """未给 --dir 的 app（模拟漏传；端点应 400 而非 500）。"""
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def dist_dir(tmp_path) -> Path:
    """假的前端构建产物（index.html + assets/app.js）。"""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><body><div id='app'>built</div></body></html>",
        encoding="utf-8",
    )
    (dist / "assets" / "app.js").write_text("console.log(1)\n", encoding="utf-8")
    return dist


@pytest.fixture()
def static_client(workdir, dist_dir):
    """托管一个已构建好的 web/dist。"""
    with TestClient(create_app(workdir, web_dist=dist_dir)) as c:
        yield c


@pytest.fixture()
def no_dist_client(workdir, tmp_path):
    """托管一个不存在的 web/dist（前端还没构建）。"""
    with TestClient(create_app(workdir, web_dist=tmp_path / "missing-dist")) as c:
        yield c
