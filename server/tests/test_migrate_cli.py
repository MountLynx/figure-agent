"""迁移 CLI：旧 <项目>/<图>/ → Index 仓库（扁平哈希 + index.db）。"""

import json
from pathlib import Path

from figure_agent.migrate import migrate_workspace
from figure_agent.repo import groups as repo_groups
from figure_agent.repo import items as repo_items
from figure_agent.repo import runs as repo_runs
from figure_agent.repo.repo import FIGURE_TYPE_NAME, Repo


def _old_workspace(root: Path):
    fig = root / "demo" / "bars"
    fig.mkdir(parents=True)
    (fig / "meta.json").write_text(json.dumps({
        "name": "bars", "project": "demo", "template": "bar-groups",
        "origin": "template", "createdAt": "2026-01-01T00:00:00",
        "lastRenderAt": "2026-01-02T00:00:00",
    }), encoding="utf-8")
    (fig / "plot.py").write_text("import matplotlib\n", encoding="utf-8")
    (fig / "history" / "2026-01-01T000000").mkdir(parents=True)
    (fig / "history" / "2026-01-01T000000" / "note.txt").write_text("v0", encoding="utf-8")
    (fig / "runs.jsonl").write_text(json.dumps(
        {"at": "2026-01-01T00:00:00", "kind": "create", "ok": True,
         "rounds": 1, "stderr": "", "error_line": None, "notes": ""}) + "\n",
        encoding="utf-8")


def test_migrate_moves_and_records(tmp_path):
    root = tmp_path / "ws"
    _old_workspace(root)
    summary = migrate_workspace(root)
    assert len(summary["migrated"]) == 1
    entry = summary["migrated"][0]
    assert entry["group"] == "demo"
    repo = Repo(root)
    # get_item 不带 groupIds（绑定信息走 list_items）
    item = next((i for i in repo_items.list_items(repo, FIGURE_TYPE_NAME)
                 if i["id"] == entry["id"]), None)
    assert item is not None and item["name"] == "bars"
    assert item["properties"]["模板"] == "bar-groups"
    assert item["properties"]["最后渲染"] == "2026-01-02T00:00:00"
    assert item["groupIds"] == [
        g["id"] for g in repo_groups.list_groups(repo) if g["name"] == "demo"]
    # 目录已搬平，语义文件已清除
    figdir = root / entry["id"]
    assert (figdir / "plot.py").exists()
    assert not (figdir / "meta.json").exists()
    assert not (figdir / "runs.jsonl").exists()
    assert not (root / "demo").exists()  # 旧项目目录已删空移除
    runs = repo_runs.list_runs(repo, entry["id"])
    assert runs and runs[0]["kind"] == "create" and runs[0]["ok"] is True
    snaps = repo_runs.list_snapshots(repo, entry["id"])
    assert snaps and snaps[0]["note"] == "v0"


def test_migrate_idempotent(tmp_path):
    root = tmp_path / "ws"
    _old_workspace(root)
    migrate_workspace(root)
    assert migrate_workspace(root) == {"migrated": [], "skipped": "已是 Index 仓库"}


def test_migrate_archive_keeps_backup(tmp_path):
    root = tmp_path / "ws"
    _old_workspace(root)
    migrate_workspace(root, archive=True)
    assert (root / "_migrated_backup" / "demo").exists()


def test_migrate_no_old_structure(tmp_path):
    (tmp_path / "ws").mkdir()
    assert migrate_workspace(tmp_path / "ws")["skipped"] == "未发现旧式 <项目>/<图>/ 结构"


def test_migrate_runs_jsonl_tolerant(tmp_path):
    """坏 JSON 行跳过、缺 at 落默认、detail 只收 stderr/error_line/notes。"""
    root = tmp_path / "ws"
    fig = root / "demo" / "bars"
    fig.mkdir(parents=True)
    (fig / "meta.json").write_text(json.dumps({"name": "bars", "origin": "ai"}), encoding="utf-8")
    (fig / "plot.py").write_text("x = 1\n", encoding="utf-8")
    (fig / "runs.jsonl").write_text(
        json.dumps({"at": "2026-01-01T00:00:00", "kind": "create", "ok": True,
                    "rounds": 2, "stderr": "e", "error_line": 3, "notes": "n"}) + "\n"
        + "这不是JSON\n"
        + json.dumps({"kind": "adapt"}) + "\n",
        encoding="utf-8",
    )
    summary = migrate_workspace(root)
    repo = Repo(root)
    runs = repo_runs.list_runs(repo, summary["migrated"][0]["id"])
    assert len(runs) == 2  # 坏行跳过
    assert runs[0]["kind"] == "adapt" and runs[0]["ok"] is False and runs[0]["rounds"] == 0
    assert runs[1]["kind"] == "create" and runs[1]["stderr"] == "e"
    assert "at" in runs[0] and "at" in runs[1]  # 缺 at 落了默认时间戳


def test_migrate_keeps_nonempty_project_dir(tmp_path):
    """stray 文件留存 → 非 archive 模式不删项目目录。"""
    root = tmp_path / "ws"
    _old_workspace(root)
    (root / "demo" / "leftover.txt").write_text("keep me", encoding="utf-8")
    summary = migrate_workspace(root)
    assert len(summary["migrated"]) == 1
    assert (root / "demo" / "leftover.txt").exists()  # 目录未被 rmdir
