"""tags 表：扁平标签。"""

from __future__ import annotations

import sqlite3

from .repo import Repo


def list_tags(repo: Repo) -> list[dict]:
    with repo.conn() as c:
        rows = c.execute("SELECT id, name FROM tags ORDER BY name").fetchall()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def create_tag(repo: Repo, name: str) -> dict:
    with repo.conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO tags (name, namespace) VALUES (?, 'default')", (name,)
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"标签已存在：{name}") from exc
        return {"id": cur.lastrowid, "name": name}


def delete_tag(repo: Repo, tag_id: int) -> None:
    with repo.conn() as c:
        cur = c.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        if cur.rowcount == 0:
            raise ValueError(f"标签不存在：{tag_id}")
