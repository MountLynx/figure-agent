"""items 表操作（index-engine items.rs 的 Python 子集）。

语义与 Index 对齐：改名只动 SQL；删除 = 单条 DELETE（FK CASCADE 清
item_groups/item_tags/fa_*）；id = 随机 16 字节 SHA256 前 12 hex，永不改名。
本层不碰文件系统——条目文件夹由 Store 管理。
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .repo import Repo

FIGURE_TYPE = "图"
ID_RE = re.compile(r"^[0-9a-f]{12}$")


def generate_id() -> str:
    """与 index-engine items.rs generate_id 同构：16 随机字节 → SHA256 → 前 6 字节 hex。"""
    return hashlib.sha256(secrets.token_bytes(16)).hexdigest()[:12]


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def require_id(item_id: str) -> str:
    # fullmatch 而非 match+$：Python 的 $ 容忍尾 \n，fullmatch 不容忍
    if not ID_RE.fullmatch(item_id or ""):
        raise ValueError(f"非法条目 id：{item_id!r}")
    return item_id


def _dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["properties"] = json.loads(d.get("properties") or "{}")
    d["createdAt"] = d.pop("created_at", None)
    d["updatedAt"] = d.pop("updated_at", None)
    return d


def get_item(repo: Repo, item_id: str) -> Optional[dict]:
    require_id(item_id)
    with repo.conn() as c:
        row = c.execute(
            "SELECT i.*, t.name AS type_name FROM items i"
            " JOIN item_types t ON t.id = i.type_id WHERE i.id = ?",
            (item_id,),
        ).fetchone()
    if row is None:
        return None
    item = _dict(row)
    item["typeName"] = item.pop("type_name")
    return item


def list_items(repo: Repo, type_name: Optional[str] = None, q: Optional[str] = None,
               group_id: Optional[int] = None, tag_id: Optional[int] = None) -> list[dict]:
    sql = ("SELECT i.*, t.name AS type_name FROM items i"
           " JOIN item_types t ON t.id = i.type_id WHERE 1=1")
    params: list = []
    if type_name:
        sql += " AND t.name = ?"
        params.append(type_name)
    if q:
        sql += " AND i.name LIKE ? ESCAPE '\\'"
        params.append("%" + q.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_") + "%")
    if group_id is not None:
        sql += " AND i.id IN (SELECT item_id FROM item_groups WHERE group_id = ?)"
        params.append(group_id)
    if tag_id is not None:
        sql += " AND i.id IN (SELECT item_id FROM item_tags WHERE tag_id = ?)"
        params.append(tag_id)
    sql += " ORDER BY i.updated_at DESC, i.id"
    out: list[dict] = []
    with repo.conn() as c:
        for row in c.execute(sql, params).fetchall():
            item = _dict(row)
            item["typeName"] = item.pop("type_name")
            item["groupIds"] = [r[0] for r in c.execute(
                "SELECT group_id FROM item_groups WHERE item_id = ? ORDER BY group_id",
                (row["id"],))]
            item["tags"] = [r[0] for r in c.execute(
                "SELECT tg.name FROM item_tags it JOIN tags tg ON tg.id = it.tag_id"
                " WHERE it.item_id = ? ORDER BY tg.name", (row["id"],))]
            out.append(item)
    return out


def create_item(repo: Repo, name: str, type_name: str = FIGURE_TYPE,
                properties: Optional[dict] = None,
                created_at: Optional[str] = None) -> dict:
    """created_at：迁移场景透传旧 meta 的创建时间；缺省用当前时刻。"""
    with repo.conn() as c:
        trow = c.execute("SELECT id FROM item_types WHERE name = ?", (type_name,)).fetchone()
        if trow is None:
            raise ValueError(f"类型不存在：{type_name}")
        while True:
            item_id = generate_id()
            if c.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is None:
                break
        now = created_at or now_utc()
        c.execute(
            "INSERT INTO items (id, name, type_id, properties, namespace, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'default', ?, ?)",
            (item_id, name, trow["id"], json.dumps(properties or {}, ensure_ascii=False), now, now_utc()),
        )
    item = get_item(repo, item_id)
    assert item is not None
    return item


def update_item(repo: Repo, item_id: str, name: Optional[str] = None,
                properties: Optional[dict] = None) -> dict:
    require_id(item_id)
    sets: list[str] = []
    params: list = []
    if name is not None:
        sets.append("name = ?")
        params.append(name)
    if properties is not None:
        sets.append("properties = ?")
        params.append(json.dumps(properties, ensure_ascii=False))
    sets.append("updated_at = ?")
    params.append(now_utc())
    params.append(item_id)
    with repo.conn() as c:
        cur = c.execute(f"UPDATE items SET {', '.join(sets)} WHERE id = ?", params)
        if cur.rowcount == 0:
            raise ValueError(f"条目不存在：{item_id}")
    item = get_item(repo, item_id)
    assert item is not None
    return item


def merge_properties(repo: Repo, item_id: str, patch: dict) -> dict:
    item = get_item(repo, item_id)
    if item is None:
        raise ValueError(f"条目不存在：{item_id}")
    return update_item(repo, item_id, properties={**item["properties"], **patch})


def delete_item(repo: Repo, item_id: str) -> None:
    """单条 DELETE；CASCADE 清 item_groups/item_tags/fa_runs/fa_snapshots。"""
    require_id(item_id)
    with repo.conn() as c:
        cur = c.execute("DELETE FROM items WHERE id = ?", (item_id,))
        if cur.rowcount == 0:
            raise ValueError(f"条目不存在：{item_id}")


def bind_group(repo: Repo, item_id: str, group_id: int) -> None:
    with repo.conn() as c:
        try:
            c.execute("INSERT OR IGNORE INTO item_groups (item_id, group_id) VALUES (?, ?)",
                      (item_id, group_id))
        except sqlite3.IntegrityError as exc:  # FK：幽灵条目/分组（OR IGNORE 不作用于 FK）
            raise ValueError(f"条目或分组不存在：{item_id} / {group_id}") from exc


def unbind_group(repo: Repo, item_id: str, group_id: int) -> None:
    with repo.conn() as c:
        c.execute("DELETE FROM item_groups WHERE item_id = ? AND group_id = ?",
                  (item_id, group_id))


def bind_tag(repo: Repo, item_id: str, tag_id: int) -> None:
    with repo.conn() as c:
        try:
            c.execute("INSERT OR IGNORE INTO item_tags (item_id, tag_id) VALUES (?, ?)",
                      (item_id, tag_id))
        except sqlite3.IntegrityError as exc:  # FK：幽灵条目/标签
            raise ValueError(f"条目或标签不存在：{item_id} / {tag_id}") from exc


def unbind_tag(repo: Repo, item_id: str, tag_id: int) -> None:
    with repo.conn() as c:
        c.execute("DELETE FROM item_tags WHERE item_id = ? AND tag_id = ?",
                  (item_id, tag_id))
