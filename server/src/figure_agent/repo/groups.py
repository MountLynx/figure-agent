"""groups 表：多级分组（= 原「项目」概念的 Index 化）。删除组保留条目。"""

from __future__ import annotations

from typing import Any, Optional

from .repo import Repo

_COLS = "id, parent_id, name, position, bound_item_id"

# update_group 的 parent_id 哨兵：显式 None = 移到根；缺省（_UNSET）= 不改。
# 不能用 None 当缺省——None 是有语义的合法值。
_UNSET = object()


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
                 parent_id: Any = _UNSET, position: Optional[int] = None) -> dict:
    with repo.conn() as c:
        row = c.execute(f"SELECT {_COLS} FROM groups WHERE id = ?", (group_id,)).fetchone()
        if row is None:
            raise ValueError(f"分组不存在：{group_id}")
        if name is None and parent_id is _UNSET and position is None:
            return _dict(row)  # 全部未变：直接返回现状，不生成空 SET
        sets: list[str] = []
        params: list = []
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if position is not None:
            sets.append("position = ?")
            params.append(position)
        if parent_id is not _UNSET:
            if parent_id is None:
                sets.append("parent_id = NULL")  # 显式移回根
            else:
                prow = c.execute(
                    "SELECT parent_id FROM groups WHERE id = ?", (parent_id,)
                ).fetchone()
                if prow is None:
                    raise ValueError(f"父分组不存在：{parent_id}")
                # 环守卫：从新父级沿 parent 链向上走，遇到自身即成环。
                # （库中既有结构由本守卫 + create_group 只挂叶保证无环；
                # visited 集合防御手改库造成的脏环导致死循环。）
                visited: set[int] = set()
                walker: Any = parent_id
                while walker is not None and walker not in visited:
                    if walker == group_id:
                        raise ValueError("不能把分组移到自己的子级")
                    visited.add(walker)
                    wrow = c.execute(
                        "SELECT parent_id FROM groups WHERE id = ?", (walker,)
                    ).fetchone()
                    walker = wrow["parent_id"] if wrow is not None else None
                sets.append("parent_id = ?")
                params.append(parent_id)
        params.append(group_id)
        c.execute(f"UPDATE groups SET {', '.join(sets)} WHERE id = ?", params)
        row = c.execute(f"SELECT {_COLS} FROM groups WHERE id = ?", (group_id,)).fetchone()
    return _dict(row)


def delete_group(repo: Repo, group_id: int) -> None:
    """CASCADE 清 item_groups；条目保留（变未分组）。"""
    with repo.conn() as c:
        cur = c.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        if cur.rowcount == 0:
            raise ValueError(f"分组不存在：{group_id}")
