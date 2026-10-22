"""测试共享 fixture：用本环境 matplotlib 渲染固定场景。

- scene_a：分组柱状图（fa: gid）
- scene_b：数据微变 + 处理组改红（模拟"回写后的代码"）
- scene_a2：与 scene_a 相同代码再渲染一次（测确定性）
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402


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
    from figure_agent.svgkit import normalize, parse_svg

    root = parse_svg(svg_a)
    normalize(root)
    return root


@pytest.fixture()
def roots_b(svg_b):
    from figure_agent.svgkit import normalize, parse_svg

    root = parse_svg(svg_b)
    normalize(root)
    return root
