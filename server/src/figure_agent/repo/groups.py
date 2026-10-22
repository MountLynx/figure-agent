"""groups 表：多级分组（= 原「项目」概念的 Index 化）。删除组保留条目。"""

from __future__ import annotations

from typing import Optional

from .repo import Repo

_COLS = "id, parent_id, name, position, bound_item_id"


def _dict(row) -> dict:
    return {"id": row["id"], "parentId": row["parent_id"], "name": row["name"],
            "position": row["position"], "boundItemId": row["bound_item_id"]}


def list_groups(repo: Repo) -> list[dict]:
    with repo.conn() as c:
        rows = c.execute(f"SELECT {_COLS} FROM groups ORDER BY position, id").fetchall()
    return [_dict(r) for r in rows]


def create_group(repo: Repo, name: str, parent_id: Optional[int] = None,
                 position: int = 0) -> dict:
    with repo.conn() as c:
        if parent_id is not None and c.execute(
            "SELECT 1 FROM groups WHERE id = ?", (parent_id,)
        ).fetchone() is None:
            raise ValueError(f"父分组不存在：{parent_id}")
        cur = c.execute(
            "INSERT INTO groups (parent_id, name, position, namespace) VALUES (?, ?, ?, 'default')",
            (parent_id, name, position),
        )
        group_id = cur.lastrowid
        row = c.execute(f"SELECT {_COLS} FROM groups WHERE id = ?", (group_id,)).fetchone()
    return _dict(row)


def update_group(repo: Repo, group_id: int, name: Optional[str] = None,
                 parent_id: Optional[int] = None, position: Optional[int] = None) -> dict:
    sets, params = [], []
    for col, val in (("name", name), ("parent_id", parent_id), ("position", position)):
        if val is not None:
            sets.append(f"{col} = ?")
            params.append(val)
    params.append(group_id)
    with repo.conn() as c:
        cur = c.execute(f"UPDATE groups SET {', '.join(sets)} WHERE id = ?", params)
        if cur.rowcount == 0:
            raise ValueError(f"分组不存在：{group_id}")
        row = c.execute(f"SELECT {_COLS} FROM groups WHERE id = ?", (group_id,)).fetchone()
    return _dict(row)


def delete_group(repo: Repo, group_id: int) -> None:
    """CASCADE 清 item_groups；条目保留（变未分组）。"""
    with repo.conn() as c:
        cur = c.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        if cur.rowcount == 0:
            raise ValueError(f"分组不存在：{group_id}")
