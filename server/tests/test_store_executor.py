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
    fid = s.create_figure("f1", template="bar-groups")["id"]
    return s, fid


def test_write_code_and_render(store):
    s, fid = store
    res = s.write_code(fid, CODE_OK)
    assert res.ok, res.stderr
    assert res.stats["faGroups"] == ["fa:bar-0", "fa:bar-1"]
    base = s.read_svg(fid, "base")
    assert "fa:bar-0" in base
    # 渲染时间进 SQL（properties），不再有 meta.json
    assert s.read_item(fid)["properties"]["最后渲染"]
    assert not (s.figure_dir(fid) / "meta.json").exists()


def test_syntax_error_reports_line(store):
    s, fid = store
    res = s.write_code(fid, CODE_SYNTAX_ERROR)
    assert not res.ok
    assert res.error_line == 2
    assert "Traceback" in res.stderr
    assert s.read_svg(fid, "base") is not None


def test_no_fig_error(store):
    s, fid = store
    res = s.write_code(fid, CODE_NO_FIG)
    assert not res.ok
    assert "fig" in res.stderr


def test_fonttype_override_warning(store):
    s, fid = store
    res = s.write_code(fid, CODE_BAD_FONTS)
    assert res.ok
    assert any("svg.fonttype" in w for w in (res.warnings or []))
    assert "<text" in s.read_svg(fid, "base")


def test_render_deterministic_hash(store):
    s, fid = store
    s.render(fid)
    h1 = s.read_patch(fid)["baseHash"]
    s.render(fid)
    h2 = s.read_patch(fid)["baseHash"]
    assert h1 == h2


def test_patch_survives_rerender(store):
    s, fid = store
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_style", "target": {"id": "fa:treatment-bar-1"},
         "attr": "fill", "value": "#dd3322", "intent": "改红", "origin": "manual", "status": "active"},
    ]}
    s.save_patch(fid, patch)
    s.render(fid)
    final = s.read_svg(fid, "final")
    assert "#dd3322" in final
    ops = s.read_patch(fid)["ops"]
    assert ops[0]["status"] == "active"


def test_writeback_flow(store):
    """S3 全流程：微调 → 代码表达 → verify → patch 清空。"""
    s, fid = store
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_style", "target": {"id": "fa:treatment-bar-2"},
         "attr": "fill", "value": "#dd3322", "intent": "改红", "origin": "manual", "status": "active"},
    ]}
    s.save_patch(fid, patch)
    v1 = s.verify_patch(fid)
    assert v1["results"][0]["status"] == "active"
    assert v1["cleared"] is False
    code = s.read_code(fid).replace('"#d08770"', '"#dd3322"')
    s.write_code(fid, code)
    v2 = s.verify_patch(fid)
    assert v2["cleared"] is True
    assert s.read_patch(fid)["ops"] == []


def test_snapshot(store):
    s, fid = store
    s.snapshot(fid, "初始版")
    snaps = s.snapshots(fid)
    assert len(snaps) == 1
    assert snaps[0]["note"] == "初始版"


def test_create_without_template(tmp_path):
    s = Store(tmp_path / "ws")
    fid = s.create_figure("f", origin="ai")["id"]
    fdir = s.figure_dir(fid)
    assert fdir.is_dir() and (fdir / "history").is_dir()
    assert not (fdir / "plot.py").exists()
    assert s.read_item(fid)["properties"]["来源"] == "ai"
    assert s.read_patch(fid) == {"baseHash": "", "ops": []}
    assert not (fdir / "meta.json").exists()
    # 同名允许（Index 语义）
    fid2 = s.create_figure("f", origin="ai")["id"]
    assert fid2 != fid


def test_create_rejects_bad_names(store):
    s, _ = store
    with pytest.raises(ValueError):
        s.create_figure("../evil", template="bar-groups")
    with pytest.raises(ValueError):
        s.create_figure("a/b", template="bar-groups")


def test_rename_figure_only_touches_db(store):
    s, fid = store
    s.rename_figure(fid, "新名字")
    assert s.read_item(fid)["name"] == "新名字"
    assert s.figure_dir(fid).name == fid  # 文件夹（id）不变


def test_delete_figure_removes_folder_and_rows(store):
    s, fid = store
    fdir = s.figure_dir(fid)
    s.delete_figure(fid)
    assert not fdir.exists()
    with pytest.raises(ValueError):
        s.read_item(fid)
    with pytest.raises(ValueError):
        s.delete_figure(fid)


def test_create_bad_template_rolls_back(tmp_path):
    s = Store(tmp_path / "ws")
    with pytest.raises(ValueError):
        s.create_figure("x", template="nope")
    assert s.list_figures() == []
    assert not (tmp_path / "ws").exists() or not any(
        p.name.isalnum() and len(p.name) == 12 for p in (tmp_path / "ws").iterdir()
    )


def test_read_files_lists_entry_folder(store):
    s, fid = store
    files = s.read_files(fid)
    paths = {f["path"] for f in files}
    assert "plot.py" in paths and "history" in paths
    with pytest.raises(ValueError):
        s.read_files("../evil")
