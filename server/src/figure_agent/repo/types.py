"""item_types + fields：动态类型系统（Index 子集）。预设型 1/2 删除保护。"""

from __future__ import annotations

import json
import sqlite3
from typing import Optional

from .repo import Repo

FIELD_TYPES = ("text", "checkbox", "date", "number", "dropdown", "item")
_PROTECTED_TYPE_IDS = (1, 2)  # Index 预设型：通用/任务


def list_types(repo: Repo) -> list[dict]:
    with repo.conn() as c:
        trows = c.execute("SELECT id, name, icon FROM item_types ORDER BY id").fetchall()
        out = []
        for t in trows:
            frows = c.execute(
                "SELECT id, name, field_type, position, label, options FROM fields"
                " WHERE type_id = ? ORDER BY position, id",
                (t["id"],),
            ).fetchall()
            out.append({
                "id": t["id"], "name": t["name"], "icon": t["icon"],
                "fields": [
                    {"id": f["id"], "name": f["name"], "fieldType": f["field_type"],
                     "position": f["position"], "label": f["label"],
                     "options": json.loads(f["options"] or "[]")}
                    for f in frows
                ],
            })
    return out


def create_type(repo: Repo, name: str, icon: str = "file") -> dict:
    with repo.conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO item_types (name, icon, namespace) VALUES (?, ?, 'default')",
                (name, icon),
            )
        except sqlite3.IntegrityError as exc:  # name UNIQUE
            raise ValueError(f"类型已存在：{name}") from exc
        return {"id": cur.lastrowid, "name": name, "icon": icon, "fields": []}


def delete_type(repo: Repo, type_id: int) -> None:
    if type_id in _PROTECTED_TYPE_IDS:
        raise ValueError(f"预设类型不可删除：{type_id}")
    with repo.conn() as c:
        # items.type_id 的 FK 无 ON DELETE 动作：使用中的类型直接删会
        # IntegrityError，先查使用情况给出可读错误。
        if c.execute("SELECT 1 FROM items WHERE type_id = ?", (type_id,)).fetchone() is not None:
            raise ValueError("类型使用中，先迁移或删除其条目")
        cur = c.execute("DELETE FROM item_types WHERE id = ?", (type_id,))
        if cur.rowcount == 0:
            raise ValueError(f"类型不存在：{type_id}")


def add_field(repo: Repo, type_id: int, name: str, field_type: str = "text",
              label: str = "", position: Optional[int] = None) -> dict:
    if field_type not in FIELD_TYPES:
        raise ValueError(f"非法字段类型：{field_type}")
    with repo.conn() as c:
        if c.execute("SELECT 1 FROM item_types WHERE id = ?", (type_id,)).fetchone() is None:
            raise ValueError(f"类型不存在：{type_id}")
        if position is None:
            row = c.execute(
                "SELECT COALESCE(MAX(position) + 1, 0) FROM fields WHERE type_id = ?",
                (type_id,),
            ).fetchone()
            position = row[0]
        try:
            cur = c.execute(
                "INSERT INTO fields (type_id, name, field_type, position, label, options)"
                " VALUES (?, ?, ?, ?, ?, '[]')",
                (type_id, name, field_type, position, label),
            )
        except sqlite3.IntegrityError as exc:  # UNIQUE(type_id, name)
            raise ValueError(f"字段已存在：{name}") from exc
        return {"id": cur.lastrowid, "name": name, "fieldType": field_type,
                "position": position, "label": label, "options": []}


def update_field(repo: Repo, field_id: int, name: Optional[str] = None,
                 field_type: Optional[str] = None, label: Optional[str] = None,
                 position: Optional[int] = None) -> None:
    if field_type is not None and field_type not in FIELD_TYPES:
        raise ValueError(f"非法字段类型：{field_type}")
    sets, params = [], []
    for col, val in (("name", name), ("field_type", field_type),
                     ("label", label), ("position", position)):
        if val is not None:
            sets.append(f"{col} = ?")
            params.append(val)
    with repo.conn() as c:
        # 存在性检查不看有没有字段要改：幽灵 id 无论何种调用都报错，
        # 不再静默 no-op。
        if c.execute("SELECT 1 FROM fields WHERE id = ?", (field_id,)).fetchone() is None:
            raise ValueError(f"字段不存在：{field_id}")
        if not sets:
            return
        params.append(field_id)
        c.execute(f"UPDATE fields SET {', '.join(sets)} WHERE id = ?", params)


def remove_field(repo: Repo, field_id: int) -> None:
    with repo.conn() as c:
        cur = c.execute("DELETE FROM fields WHERE id = ?", (field_id,))
        if cur.rowcount == 0:
            raise ValueError(f"字段不存在：{field_id}")
