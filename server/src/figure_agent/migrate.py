"""一次性迁移：旧 workspace/<项目>/<图>/ → Index 仓库（扁平哈希 + index.db）。

用法：python -m figure_agent migrate [--archive]
幂等：已有 .index 即跳过；迁移过程中逐项检查，重跑无副作用。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from .repo import groups as repo_groups
from .repo import items as repo_items
from .repo import runs as repo_runs
from .repo.repo import FIGURE_TYPE_NAME, Repo


def migrate_workspace(root: Path, archive: bool = False) -> Dict:
    root = Path(root)
    if (root / ".index").exists():
        return {"migrated": [], "skipped": "已是 Index 仓库"}
    if not root.exists():
        return {"migrated": [], "skipped": "工作区不存在"}
    project_dirs = [d for d in sorted(root.iterdir())
                    if d.is_dir() and not d.name.startswith((".", "_"))]
    if not any(_figure_dirs(p) for p in project_dirs):
        return {"migrated": [], "skipped": "未发现旧式 <项目>/<图>/ 结构"}

    repo = Repo(root)
    repo.open_or_init()
    migrated: List[Dict] = []
    for pdir in project_dirs:
        figs = _figure_dirs(pdir)
        if not figs:
            continue
        group = repo_groups.create_group(repo, pdir.name)
        for fdir in figs:
            meta = _read_json(fdir / "meta.json") or {}
            props: Dict = {
                "来源": str(meta.get("origin") or "manual"),
                "最后渲染": str(meta.get("lastRenderAt") or ""),
            }
            if meta.get("template"):
                props["模板"] = str(meta["template"])
            item = repo_items.create_item(repo, str(meta.get("name") or fdir.name),
                                          FIGURE_TYPE_NAME, props)
            target = root / item["id"]
            shutil.move(str(fdir), str(target))
            repo_items.bind_group(repo, item["id"], group["id"])
            _import_runs(repo, item["id"], target)
            _import_snapshots(repo, item["id"], target)
            (target / "meta.json").unlink(missing_ok=True)
            (target / "runs.jsonl").unlink(missing_ok=True)
            migrated.append({"id": item["id"], "name": item["name"],
                             "group": pdir.name, "from": str(fdir)})
        if archive:
            backup = root / "_migrated_backup"
            backup.mkdir(exist_ok=True)
            shutil.move(str(pdir), str(backup / pdir.name))
        elif not any(pdir.iterdir()):
            pdir.rmdir()
    return {"migrated": migrated}


def _figure_dirs(pdir: Path) -> List[Path]:
    if not pdir.is_dir():
        return []
    return [d for d in sorted(pdir.iterdir())
            if d.is_dir() and not d.name.startswith((".", "_"))
            and ((d / "meta.json").exists() or (d / "plot.py").exists())]


def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _import_runs(repo: Repo, item_id: str, fdir: Path) -> None:
    path = fdir / "runs.jsonl"
    if not path.exists():
        return
    for line in path.read_bytes().decode("utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        detail = {k: entry[k] for k in ("stderr", "error_line", "notes") if k in entry}
        repo_runs.add_run(repo, item_id, str(entry.get("kind") or "?"),
                          bool(entry.get("ok")), int(entry.get("rounds") or 0),
                          at=entry.get("at"), detail=detail)


def _import_snapshots(repo: Repo, item_id: str, fdir: Path) -> None:
    hist = fdir / "history"
    if not hist.is_dir():
        return
    for d in sorted(hist.iterdir()):
        if not d.is_dir():
            continue
        note_file = d / "note.txt"
        note = note_file.read_text(encoding="utf-8") if note_file.exists() else ""
        repo_runs.add_snapshot(repo, item_id, d.name, note, f"history/{d.name}")
