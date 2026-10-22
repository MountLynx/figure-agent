"""fa_runs（AI 审计，替代 runs.jsonl）与 fa_snapshots（快照元数据）。

载荷文件（history/<ts>/）留在条目文件夹；这里只存管理语义。
list_runs 展平 detail，返回与旧 runs.jsonl 行相同的形状（前端契约不变）。
"""

from __future__ import annotations

import json
from typing import Optional

from .items import now_utc
from .repo import Repo


def add_run(repo: Repo, item_id: str, kind: str, ok: bool, rounds: int = 0,
            at: Optional[str] = None, detail: Optional[dict] = None) -> None:
    with repo.conn() as c:
        c.execute(
            "INSERT INTO fa_runs (item_id, kind, ok, at, rounds, detail)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, kind, 1 if ok else 0, at or now_utc(), rounds,
             json.dumps(detail or {}, ensure_ascii=False)),
        )


def list_runs(repo: Repo, item_id: str) -> list[dict]:
    with repo.conn() as c:
        rows = c.execute(
            "SELECT kind, ok, at, rounds, detail FROM fa_runs"
            " WHERE item_id = ? ORDER BY id DESC",
            (item_id,),
        ).fetchall()
    out = []
    for r in rows:
        detail = json.loads(r["detail"] or "{}")
        out.append({"at": r["at"], "kind": r["kind"], "ok": bool(r["ok"]),
                    "rounds": r["rounds"], **detail})
    return out


def add_snapshot(repo: Repo, item_id: str, created_at: str, note: str, dir_: str) -> None:
    with repo.conn() as c:
        c.execute(
            "INSERT INTO fa_snapshots (item_id, created_at, note, dir) VALUES (?, ?, ?, ?)",
            (item_id, created_at, note, dir_),
        )


def list_snapshots(repo: Repo, item_id: str) -> list[dict]:
    with repo.conn() as c:
        rows = c.execute(
            "SELECT created_at, note, dir FROM fa_snapshots"
            " WHERE item_id = ? ORDER BY created_at DESC, id DESC",
            (item_id,),
        ).fetchall()
    return [{"createdAt": r["created_at"], "note": r["note"], "dir": r["dir"]}
            for r in rows]
