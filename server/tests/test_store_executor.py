"""executor 与 Store 渲染管线测试（真实 subprocess + matplotlib）。"""

import json

import pytest

from figure_agent.store import Store
from figure_agent.svgkit import base_hash


CODE_OK = """
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(4, 3))
b = ax.bar([0, 1], [1, 2])
for i, x in enumerate(b):
    x.set_gid(f"fa:bar-{i}")
ax.set_title("t")
"""

CODE_SYNTAX_ERROR = "import matplotlib.pyplot as plt\nfig = 1 +\n"

CODE_NO_FIG = "import matplotlib.pyplot as plt\nx = 1\n"

CODE_BAD_FONTS = (
    "import matplotlib.pyplot as plt\n"
    "plt.rcParams['svg.fonttype'] = 'path'\n"
    "fig, ax = plt.subplots(figsize=(4,3))\n"
    "ax.plot([0,1],[0,1])\n"
)


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "ws")
    s.create_figure("p", "f1", "bar-groups")
    return s


def test_write_code_and_render(store):
    res = store.write_code("p", "f1", CODE_OK)
    assert res.ok, res.stderr
    assert res.stats["faGroups"] == ["fa:bar-0", "fa:bar-1"]
    base = store.read_svg("p", "f1", "base")
    assert "fa:bar-0" in base


def test_syntax_error_reports_line(store):
    res = store.write_code("p", "f1", CODE_SYNTAX_ERROR)
    assert not res.ok
    assert res.error_line == 2
    assert "Traceback" in res.stderr
    # 上一版 base.svg 保留
    assert store.read_svg("p", "f1", "base") is not None


def test_no_fig_error(store):
    res = store.write_code("p", "f1", CODE_NO_FIG)
    assert not res.ok
    assert "fig" in res.stderr


def test_fonttype_override_warning(store):
    res = store.write_code("p", "f1", CODE_BAD_FONTS)
    assert res.ok
    assert any("svg.fonttype" in w for w in (res.warnings or []))
    # 产物文字仍是 <text>
    assert "<text" in store.read_svg("p", "f1", "base")


def test_render_deterministic_hash(store):
    res1 = store.render("p", "f1")
    h1 = store.read_patch("p", "f1")["baseHash"]
    res2 = store.render("p", "f1")
    h2 = store.read_patch("p", "f1")["baseHash"]
    assert res1.ok and res2.ok
    assert h1 == h2


def test_patch_survives_rerender(store):
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_style", "target": {"id": "fa:treatment-bar-1"},
         "attr": "fill", "value": "#dd3322", "intent": "改红", "origin": "manual", "status": "active"},
    ]}
    store.save_patch("p", "f1", patch)
    store.render("p", "f1")  # 代码重跑
    final = store.read_svg("p", "f1", "final")
    assert "#dd3322" in final  # S2：微调不丢
    ops = store.read_patch("p", "f1")["ops"]
    assert ops[0]["status"] == "active"


def test_writeback_flow(store):
    """S3 全流程：微调 → 代码表达 → verify → patch 清空。"""
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_style", "target": {"id": "fa:treatment-bar-2"},
         "attr": "fill", "value": "#dd3322", "intent": "改红", "origin": "manual", "status": "active"},
    ]}
    store.save_patch("p", "f1", patch)
    # 未回写时 verify：active
    v1 = store.verify_patch("p", "f1")
    assert v1["results"][0]["status"] == "active"
    assert v1["cleared"] is False
    # 回写
    code = store.read_code("p", "f1").replace('"#d08770"', '"#dd3322"')
    store.write_code("p", "f1", code)
    v2 = store.verify_patch("p", "f1")
    assert v2["cleared"] is True
    assert store.read_patch("p", "f1")["ops"] == []


def test_snapshot(store):
    store.snapshot("p", "f1", "初始版")
    snaps = store.snapshots("p", "f1")
    assert len(snaps) == 1
    assert snaps[0]["note"] == "初始版"


def test_create_figure_rejects_bad_names(store):
    with pytest.raises(ValueError):
        store.create_figure("p", "../evil", "bar-groups")
    with pytest.raises(ValueError):
        store.create_figure("../evil", "f", "bar-groups")


def test_create_figure_rejects_windows_invalid_names(store):
    # 结尾的点/空格会被 Windows 静默剥离；保留设备名无法建目录
    for bad in ("demo.", "demo ", "con", "aux", "NUL", "com1"):
        with pytest.raises(ValueError):
            store.create_figure("p", bad, "bar-groups")
