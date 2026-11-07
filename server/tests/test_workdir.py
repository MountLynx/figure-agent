"""workdir：唯一输入（--dir）的校验与路径访问器。

服务的全部世界就是这个目录——必须绝对、必须存在、必须是目录、不得含 ``..``；
「是否有图」= ``plot.py`` 存在（Index 侧照此判定，服务不回写任何属性）。
"""

from __future__ import annotations

import pytest

from figureagent.workdir import Workdir


def test_absolute_dir_is_accepted(tmp_path):
    root = tmp_path / "Data A"
    root.mkdir()
    workdir = Workdir(root)
    assert workdir.root == root.resolve()
    assert workdir.name() == "Data A"


def test_unicode_dir_name(tmp_path):
    root = tmp_path / "实验数据"
    root.mkdir()
    assert Workdir(root).name() == "实验数据"


@pytest.mark.parametrize("raw", ["relative/dir", "dir", "./x"])
def test_relative_path_rejected(raw):
    with pytest.raises(ValueError, match="绝对路径"):
        Workdir(raw)


def test_missing_dir_rejected(tmp_path):
    with pytest.raises(ValueError, match="不存在"):
        Workdir(tmp_path / "nope")


def test_file_not_dir_rejected(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="不是目录"):
        Workdir(path)


def test_dotdot_rejected(tmp_path):
    with pytest.raises(ValueError, match=r"\.\."):
        Workdir(str(tmp_path / "a" / ".." / "b"))


def test_empty_rejected():
    with pytest.raises(ValueError, match="为空"):
        Workdir("")


def test_path_accessors(tmp_path):
    root = tmp_path / "Data"
    root.mkdir()
    workdir = Workdir(root)
    resolved = root.resolve()
    assert workdir.plot_path() == resolved / "plot.py"
    assert workdir.data_path() == resolved / "data.csv"
    assert workdir.data_profile_path() == resolved / "data_profile.json"
    assert workdir.patch_path() == resolved / "patch.json"
    assert workdir.svg_paths() == {"base": resolved / "base.svg",
                                   "final": resolved / "final.svg"}
    assert workdir.uploads_dir() == resolved / "uploads"
    assert workdir.history_dir() == resolved / "history"
    assert workdir.runs_path() == resolved / "history" / "runs.jsonl"


def test_has_figure_is_plot_py_only(tmp_path):
    root = tmp_path / "Data"
    root.mkdir()
    workdir = Workdir(root)
    assert workdir.has_figure() is False
    # 其它图产物在也不代表有图：真相源只有 plot.py
    (root / "base.svg").write_text("<svg/>", encoding="utf-8")
    workdir.patch_path().write_text("{}", encoding="utf-8")
    assert workdir.has_figure() is False
    workdir.plot_path().write_text("fig = None\n", encoding="utf-8")
    assert workdir.has_figure() is True
