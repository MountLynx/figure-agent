"""Index 仓库根：open_or_init、state.json、种子数据、info。

仓库根 = FA_WORKSPACE（一个普通文件夹）。.index/ 下：index.db（唯一 SQL
存储）、state.json、workspaces/。图 = 根下扁平 12hex 文件夹（items.py）。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .db import connect, open_conn
from .migrations import ensure_fa_schema, ensure_sqlx_schema

FIGURE_TYPE_NAME = "图"
FIGURE_FIELDS = ("模板", "来源", "最后渲染")

DEFAULT_WORKSPACE = {
    "name": "默认工作区",
    "icon": "folder",
    "itemTypes": [FIGURE_TYPE_NAME],
    "groupIds": [],
    "filter": None,
    "centerTabs": [{"type": "list", "label": FIGURE_TYPE_NAME}],
    "defaultTab": FIGURE_TYPE_NAME,
    "rightPanelAddons": [],
    "sidebarAddons": [],
}


class Repo:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.index_dir = self.root / ".index"
        self.db_path = self.index_dir / "index.db"
        self.state_path = self.index_dir / "state.json"

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        with open_conn(self.db_path) as c:
            yield c

    def open_or_init(self) -> None:
        if not self.db_path.exists():
            self.index_dir.mkdir(parents=True, exist_ok=True)
        # ensure_sqlx_schema 无条件调用（自防御）：已有账本 → no-op；
        # 有 items 表但无账本 → RuntimeError（拒绝非本工具创建的库）；
        # 空库/空文件 → 正常建账本
        with self.conn() as c:
            ensure_sqlx_schema(c)
            ensure_fa_schema(c)
            _seed(c)
        ws_dir = self.index_dir / "workspaces"
        ws_dir.mkdir(exist_ok=True)
        ws_file = ws_dir / "默认工作区.json"
        if not ws_file.exists():
            ws_file.write_text(
                json.dumps(DEFAULT_WORKSPACE, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if not self.state_path.exists():
            self.write_state({"theme": "light"})

    def read_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def write_state(self, patch: dict) -> dict:
        state = self.read_state()
        state.update(patch)
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return state

    def info(self) -> dict:
        with self.conn() as c:
            count = c.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        return {"path": str(self.root), "itemCount": count, "dbVersion": 1}


def _seed(conn: sqlite3.Connection) -> None:
    """空库种子：「图」类型 + 三个字段。可重入（已有则跳过）。"""
    if conn.execute("SELECT 1 FROM item_types WHERE name = ?", (FIGURE_TYPE_NAME,)).fetchone():
        return
    cur = conn.execute(
        "INSERT INTO item_types (name, icon, namespace) VALUES (?, 'chart-bar', 'default')",
        (FIGURE_TYPE_NAME,),
    )
    type_id = cur.lastrowid
    for position, name in enumerate(FIGURE_FIELDS):
        conn.execute(
            "INSERT INTO fields (type_id, name, field_type, position) VALUES (?, ?, 'text', ?)",
            (type_id, name, position),
        )
