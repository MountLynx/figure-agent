# figure-agent 转 Index 仓库模式 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** figure-agent 工作区成为可被 Index 应用直接打开的仓库（`.index/index.db` + 扁平 12hex 条目文件夹），管理语义全部进 SQL 与前端，UI 重构为 Index 风格双视图（React 复刻管理壳 + 现有编辑器）。

**Architecture:** 新增 `figure_agent/repo/` 包（sqlite3 访问层，完整复刻 Index 的 8 个 sqlx 迁移与账本，fa 扩展走独立账本）；`Store` 改为 id 寻址门面；`main.py` 路由全面改 id 寻址；web 新增管理视图（分组树/标签/列表/详情/类型），编辑器视图保留现有画布组件。spec 见 `docs/specs/2026-10-22-index-repo-refactor-design.md`。

**Tech Stack:** Python 3.13 + FastAPI + sqlite3（stdlib）；React 18 + TS + Vitest；Index 仓库格式（index-framework/crates/index-engine 的 SQLite schema）。

**关键契约（必须牢记）：**
- `_sqlx_migrations` 账本 checksum = SQL 文件**原始字节**的 SHA-384（已实测验证）；fa 扩展绝不写该账本。
- 永不 ALTER Index 的 7 张表；只加 `fa_*` 表。
- 条目 id = 随机 16 字节 SHA256 前 12 hex；改名只动 SQL；删除 = DELETE（CASCADE）后 best-effort rmtree。
- 测试命令：server 在 `server/` 下 `python -m pytest tests/<file> -v`；web 在 `web/` 下 `npx vitest run <file>`。

---

## Phase A — repo 基础设施

### Task 1: 嵌入 Index 迁移 SQL + .gitattributes + checksum 守护测试

**Files:**
- Create: `server/src/figure_agent/repo/migrations/`（8 个 Index 原版 .sql，字节级副本）
- Create: `server/src/figure_agent/repo/migrations/000001_fa_ext.sql`
- Create: `server/src/figure_agent/repo/__init__.py`（空文件，docstring 即可）
- Create: `.gitattributes`
- Test: `server/tests/test_repo_migrations.py`

- [ ] **Step 1: 拷贝迁移文件（必须字节级一致）**

```bash
cd "C:\Users\xingy\Desktop\开发\figure-agent"
mkdir -p server/src/figure_agent/repo/migrations
cp /c/Users/xingy/Desktop/开发/index-framework/crates/index-engine/migrations/*.sql server/src/figure_agent/repo/migrations/
printf '"""Index 仓库访问层：SQLite（index.db）+ 扁平哈希条目。"""\n' > server/src/figure_agent/repo/__init__.py
```

- [ ] **Step 2: 写 fa 扩展迁移**

创建 `server/src/figure_agent/repo/migrations/000001_fa_ext.sql`：

```sql
-- figure-agent 扩展表（独立账本 fa_schema_migrations 管理，绝不进 _sqlx_migrations）
CREATE TABLE fa_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    ok INTEGER NOT NULL,
    at TEXT NOT NULL,
    rounds INTEGER,
    detail TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE fa_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    dir TEXT NOT NULL
);
```

- [ ] **Step 3: 写 .gitattributes（防 autocrlf 破坏字节一致性）**

创建仓库根 `.gitattributes`：

```
server/src/figure_agent/repo/migrations/*.sql text eol=lf
```

- [ ] **Step 4: 写失败的 checksum 守护测试**

创建 `server/tests/test_repo_migrations.py`：

```python
"""迁移器与账本契约测试。checksum 常量来自 spec §3.1（对 index-framework
真实迁移文件实测的 SHA-384）——文件一旦漂移，Index 应用打开时 sqlx 校验即失败。"""

import hashlib
from pathlib import Path

import pytest

from figure_agent.repo import migrations as mig
from figure_agent.repo.repo import Repo

MIGRATIONS_DIR = Path(mig.__file__).parent / "migrations"

EXPECTED_SHA384 = {
    "20260710000001_init.sql": "cdadcda604aa31477ea8eeb9caf1447f7050ec3fa1ba9266311d2cc97d1b887e6ab326f814ff297e9ab2f0185317436b",
    "20260710000002_update_preset_icons.sql": "12464a1e5a64e436af44061aecb3c8592f48cca937545871091a98f04893c1b3dc73e0028193a108d74b7acd560960c7",
    "20260711000003_add_field_icon.sql": "391d3e81a481d0754f912f8d164107f0c41e6431eeb3a03f94705b20756dbb30b591baa2f40fcf6241d3a2f78b8f2c0e",
    "20260711000004_add_field_label.sql": "0f5628838e2d2e44d6a8bb4506ad52b0a4a3ec65704850a615c0181b6f388af494df4663a9512b566ab13e40b5d12c61",
    "20260712000005_add_namespace.sql": "0310db3bf3c2e1f64543e8db529bd0e4cf035ea137bde572f1ca7a77e2f11575a49411708144ec31bad9edc2d2dfacea",
    "20260714000006_add_date_field_to_task.sql": "ea5a17bf05f60460c5907808f66fd3c187f0dadbb047cd151d45bad74f4892b7ffca3bab54ea6996c2619df2061cae1e",
    "20260720000007_add_field_options.sql": "a8c25324da092b10d52c4e47a64b22b76936b993ff5016db8e8fd5420adc1e0d3b98e98d4a22ab05fa87e1a550639f54",
    "20260721000008_add_bound_item.sql": "cffa460571c7ef1c99d5b9820056fabd0845a976a877b4dcb3a8725a7f6d7e1deb00905be0e483907523fc112e8926b8",
}


def test_migration_files_byte_identical():
    for fname, hexdigest in EXPECTED_SHA384.items():
        assert hashlib.sha384((MIGRATIONS_DIR / fname).read_bytes()).hexdigest() == hexdigest, fname


def test_init_creates_ledger_tables_and_seeds(tmp_path):
    repo = Repo(tmp_path / "ws")
    repo.open_or_init()
    with repo.conn() as c:
        ledger = c.execute("SELECT version, success, checksum FROM _sqlx_migrations ORDER BY version").fetchall()
        assert [r["version"] for r in ledger] == sorted(mig.INDEX_MIGRATIONS[i][0] for i in range(8))
        assert all(r["success"] == 1 for r in ledger)
        for row, (version, _desc, fname) in zip(ledger, mig.INDEX_MIGRATIONS):
            assert row["checksum"] == hashlib.sha384((MIGRATIONS_DIR / fname).read_bytes()).digest()
        tables = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"items", "item_types", "fields", "groups", "tags",
                "item_groups", "item_tags", "fa_runs", "fa_snapshots"} <= tables
        t = c.execute("SELECT id FROM item_types WHERE name='图'").fetchone()
        assert t is not None
        fields = [r["name"] for r in c.execute(
            "SELECT name FROM fields WHERE type_id=? ORDER BY position", (t["id"],))]
        assert fields == ["模板", "来源", "最后渲染"]
        assert (repo.index_dir / "state.json").exists()
        assert (repo.index_dir / "workspaces" / "默认工作区.json").exists()


def test_init_idempotent(tmp_path):
    repo = Repo(tmp_path / "ws")
    repo.open_or_init()
    repo.open_or_init()
    with repo.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM _sqlx_migrations").fetchone()[0] == 8
        assert c.execute("SELECT COUNT(*) FROM fa_schema_migrations").fetchone()[0] == 1


def test_existing_items_without_ledger_rejected(tmp_path):
    import sqlite3

    ws = tmp_path / "ws"
    ws.mkdir()
    conn = sqlite3.connect(ws / ".index.db.tmp")
    conn.execute("CREATE TABLE items (id TEXT PRIMARY KEY)")
    conn.close()
    (ws / ".index").mkdir()
    (ws / ".index" / "index.db").write_bytes((ws / ".index.db.tmp").read_bytes())
    (ws / ".index.db.tmp").unlink()
    with pytest.raises(RuntimeError, match="账本"):
        Repo(ws).open_or_init()


def test_tolerates_unknown_columns(tmp_path):
    repo = Repo(tmp_path / "ws")
    repo.open_or_init()
    with repo.conn() as c:
        c.execute("ALTER TABLE items ADD COLUMN future_col TEXT")
    Repo(tmp_path / "ws").open_or_init()  # 不抛错
```

- [ ] **Step 5: 运行测试确认失败（缺 migrations.py / repo.py）**

Run: `cd server && python -m pytest tests/test_repo_migrations.py -v`
Expected: FAIL（`ModuleNotFoundError: figure_agent.repo.migrations`）

### Task 2: repo/db.py + repo/migrations.py（迁移器）

**Files:**
- Create: `server/src/figure_agent/repo/db.py`
- Create: `server/src/figure_agent/repo/migrations.py`

- [ ] **Step 1: 写 db.py**

```python
"""SQLite 连接与辅助（Index 仓库 index.db）。

isolation_level=None（autocommit）：所有操作单语句原子，无需显式事务；
删除条目级联清理由 FK ON DELETE CASCADE 完成。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def open_conn(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone()
    return row is not None
```

- [ ] **Step 2: 写 migrations.py**

```python
"""幂等迁移器。

_sqlx_migrations 账本只由 Index 原版 8 个迁移写入（checksum = SQL 文件
原始字节的 SHA-384，与 index-framework 的 sqlx::migrate! 校验规则一致，
Index 应用打开仓库时据此跳过重放）；figure-agent 扩展表走独立账本
fa_schema_migrations，绝不写 _sqlx_migrations（避免与 Index 未来迁移
撞版本号/校验和）。
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .db import table_exists

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# Index 原版迁移（version = 文件名前缀；description = sqlx 由文件名派生）
INDEX_MIGRATIONS: list[tuple[int, str, str]] = [
    (20260710000001, "init", "20260710000001_init.sql"),
    (20260710000002, "update preset icons", "20260710000002_update_preset_icons.sql"),
    (20260711000003, "add field icon", "20260711000003_add_field_icon.sql"),
    (20260711000004, "add field label", "20260711000004_add_field_label.sql"),
    (20260712000005, "add namespace", "20260712000005_add_namespace.sql"),
    (20260714000006, "add date field to task", "20260714000006_add_date_field_to_task.sql"),
    (20260720000007, "add field options", "20260720000007_add_field_options.sql"),
    (20260721000008, "add bound item", "20260721000008_add_bound_item.sql"),
]

# figure-agent 扩展迁移（独立账本）
FA_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "fa ext tables", "000001_fa_ext.sql"),
]

_SQLX_LEDGER_DDL = """
CREATE TABLE _sqlx_migrations (
    version BIGINT PRIMARY KEY,
    description TEXT NOT NULL,
    installed_on TEXT NOT NULL,
    success BOOLEAN NOT NULL,
    checksum BLOB NOT NULL,
    execution_time BIGINT NOT NULL
);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_file(conn: sqlite3.Connection, fname: str) -> None:
    conn.executescript((MIGRATIONS_DIR / fname).read_text(encoding="utf-8"))


def ensure_sqlx_schema(conn: sqlite3.Connection) -> None:
    """空库 → 依序执行 Index 原版迁移并写账本；已有账本 → no-op；
    有业务表但无账本 → 拒绝（不是本工具创建的库）。"""
    if table_exists(conn, "_sqlx_migrations"):
        return
    if table_exists(conn, "items"):
        raise RuntimeError(
            "index.db 已有业务表但缺少 _sqlx_migrations 账本：不是本工具创建的仓库，拒绝初始化"
        )
    conn.executescript(_SQLX_LEDGER_DDL)
    for version, description, fname in INDEX_MIGRATIONS:
        _run_file(conn, fname)
        checksum = hashlib.sha384((MIGRATIONS_DIR / fname).read_bytes()).digest()
        conn.execute(
            "INSERT INTO _sqlx_migrations"
            " (version, description, installed_on, success, checksum, execution_time)"
            " VALUES (?, ?, ?, 1, ?, 0)",
            (version, description, _utc_now(), checksum),
        )


def ensure_fa_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fa_schema_migrations"
        " (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM fa_schema_migrations")}
    for version, _description, fname in FA_MIGRATIONS:
        if version in applied:
            continue
        _run_file(conn, fname)
        conn.execute(
            "INSERT INTO fa_schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, _utc_now()),
        )
```

- [ ] **Step 3: 运行 Task 1 测试（db.py/migrations.py 就位，repo.py 未写仍失败）**

Run: `cd server && python -m pytest tests/test_repo_migrations.py -v`
Expected: FAIL（`ModuleNotFoundError: figure_agent.repo.repo`）

- [ ] **Step 4: Commit**

```bash
git add server/src/figure_agent/repo .gitattributes server/tests/test_repo_migrations.py
git commit -m "feat(repo): 嵌入 Index 原版迁移与 fa 扩展，迁移器 + checksum 守护测试"
```

### Task 3: repo/repo.py（Repo + open_or_init + state + 种子）

**Files:**
- Create: `server/src/figure_agent/repo/repo.py`

- [ ] **Step 1: 写 repo.py**

```python
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
```

- [ ] **Step 2: 运行迁移测试**

Run: `cd server && python -m pytest tests/test_repo_migrations.py -v`
Expected: 5 passed

- [ ] **Step 3: Commit**

```bash
git add server/src/figure_agent/repo/repo.py
git commit -m "feat(repo): Repo open_or_init + state.json + 「图」类型种子"
```

### Task 4: repo/items.py（条目 CRUD + 绑定 + id 生成）

**Files:**
- Create: `server/src/figure_agent/repo/items.py`

- [ ] **Step 1: 写 items.py**

```python
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
    # fullmatch 而非 match：Python 的 `$` 容忍尾换行（"aaaaaaaaaaaa\n" 会溜过）
    if not ID_RE.fullmatch(item_id or ""):
        raise ValueError(f"非法条目 id：{item_id!r}")
    return item_id


def _dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["properties"] = json.loads(d.get("properties") or "{}")
    return d


def get_item(repo: Repo, item_id: str) -> Optional[dict]:
    require_id(item_id)
    with repo.conn() as c:
        row = c.execute(
            "SELECT i.*, t.name AS type_name FROM items i"
            " JOIN item_types t ON t.id = i.type_id WHERE i.id = ?",
            (item_id,),
        ).fetchone()
    return _dict(row) if row else None


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
            item["typeName"] = row["type_name"]
            item["groupIds"] = [r[0] for r in c.execute(
                "SELECT group_id FROM item_groups WHERE item_id = ? ORDER BY group_id",
                (row["id"],))]
            item["tags"] = [r[0] for r in c.execute(
                "SELECT tg.name FROM item_tags it JOIN tags tg ON tg.id = it.tag_id"
                " WHERE it.item_id = ? ORDER BY tg.name", (row["id"],))]
            out.append(item)
    return out


def create_item(repo: Repo, name: str, type_name: str = FIGURE_TYPE,
                properties: Optional[dict] = None) -> dict:
    with repo.conn() as c:
        trow = c.execute("SELECT id FROM item_types WHERE name = ?", (type_name,)).fetchone()
        if trow is None:
            raise ValueError(f"类型不存在：{type_name}")
        while True:
            item_id = generate_id()
            if c.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone() is None:
                break
        now = now_utc()
        c.execute(
            "INSERT INTO items (id, name, type_id, properties, namespace, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'default', ?, ?)",
            (item_id, name, trow["id"], json.dumps(properties or {}, ensure_ascii=False), now, now),
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
        c.execute("INSERT OR IGNORE INTO item_groups (item_id, group_id) VALUES (?, ?)",
                  (item_id, group_id))


def unbind_group(repo: Repo, item_id: str, group_id: int) -> None:
    with repo.conn() as c:
        c.execute("DELETE FROM item_groups WHERE item_id = ? AND group_id = ?",
                  (item_id, group_id))


def bind_tag(repo: Repo, item_id: str, tag_id: int) -> None:
    with repo.conn() as c:
        c.execute("INSERT OR IGNORE INTO item_tags (item_id, tag_id) VALUES (?, ?)",
                  (item_id, tag_id))


def unbind_tag(repo: Repo, item_id: str, tag_id: int) -> None:
    with repo.conn() as c:
        c.execute("DELETE FROM item_tags WHERE item_id = ? AND tag_id = ?",
                  (item_id, tag_id))
```

- [ ] **Step 2: 写语义测试**

创建 `server/tests/test_repo_semantics.py`：

```python
"""repo 语义测试：与 Index 对齐的边界（改名只动 SQL、删除级联、过滤）。"""

import pytest

from figure_agent.repo import groups as repo_groups
from figure_agent.repo import items as repo_items
from figure_agent.repo import runs as repo_runs
from figure_agent.repo.repo import FIGURE_TYPE_NAME, Repo


@pytest.fixture()
def repo(tmp_path):
    r = Repo(tmp_path / "ws")
    r.open_or_init()
    return r


def test_generate_id_shape():
    for _ in range(100):
        assert repo_items.ID_RE.match(repo_items.generate_id())
    assert len({repo_items.generate_id() for _ in range(200)}) == 200


def test_rename_only_touches_db(repo):
    item = repo_items.create_item(repo, "甲")
    repo_items.update_item(repo, item["id"], name="乙")
    assert repo_items.get_item(repo, item["id"])["name"] == "乙"
    assert item["id"] in [i["id"] for i in repo_items.list_items(repo)]  # id 永不变


def test_delete_cascades(repo):
    item = repo_items.create_item(repo, "甲")
    g = repo_groups.create_group(repo, "G")
    repo_items.bind_group(repo, item["id"], g["id"])
    repo_runs.add_run(repo, item["id"], "create", True, 1, detail={"stderr": ""})
    repo_items.delete_item(repo, item["id"])
    assert repo_items.get_item(repo, item["id"]) is None
    assert repo_runs.list_runs(repo, item["id"]) == []
    with repo.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM item_groups").fetchone()[0] == 0
    with pytest.raises(ValueError):
        repo_items.delete_item(repo, item["id"])


def test_same_name_allowed(repo):
    a = repo_items.create_item(repo, "同名")
    b = repo_items.create_item(repo, "同名")
    assert a["id"] != b["id"]
    assert len(repo_items.list_items(repo, FIGURE_TYPE_NAME)) == 2


def test_list_filters(repo):
    fig = repo_items.create_item(repo, "图A", FIGURE_TYPE_NAME)
    repo_items.create_item(repo, "便签", "通用")
    g = repo_groups.create_group(repo, "G")
    t = repo_tags_create(repo)
    repo_items.bind_group(repo, fig["id"], g["id"])
    repo_items.bind_tag(repo, fig["id"], t["id"])
    assert [i["id"] for i in repo_items.list_items(repo, FIGURE_TYPE_NAME)] == [fig["id"]]
    assert [i["id"] for i in repo_items.list_items(repo, q="图A")] == [fig["id"]]
    assert [i["id"] for i in repo_items.list_items(repo, group_id=g["id"])] == [fig["id"]]
    assert [i["id"] for i in repo_items.list_items(repo, tag_id=t["id"])] == [fig["id"]]
    got = repo_items.list_items(repo, FIGURE_TYPE_NAME)[0]
    assert got["groupIds"] == [g["id"]] and got["tags"] == ["T"]


def repo_tags_create(repo):
    from figure_agent.repo import tags as repo_tags

    return repo_tags.create_tag(repo, "T")


def test_require_id_rejects_traversal():
    for bad in ("../../etc", "ABCDEF123456", "a b", ""):
        with pytest.raises(ValueError):
            repo_items.require_id(bad)
```

- [ ] **Step 3: 运行测试**

Run: `cd server && python -m pytest tests/test_repo_semantics.py -v`
Expected: FAIL（缺 groups/tags 模块）——先只跑 `tests/test_repo_semantics.py::test_generate_id_shape` 与 `::test_require_id_rejects_traversal` 应 PASS，其余待 Task 5。

- [ ] **Step 4: Commit**

```bash
git add server/src/figure_agent/repo/items.py server/tests/test_repo_semantics.py
git commit -m "feat(repo): items CRUD/绑定/过滤，id 生成与语义测试"
```

### Task 5: repo/groups.py + tags.py + types.py + runs.py

**Files:**
- Create: `server/src/figure_agent/repo/groups.py`
- Create: `server/src/figure_agent/repo/tags.py`
- Create: `server/src/figure_agent/repo/types.py`
- Create: `server/src/figure_agent/repo/runs.py`

- [ ] **Step 1: 写 groups.py**

```python
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
```

- [ ] **Step 2: 写 tags.py**

```python
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
```

- [ ] **Step 3: 写 types.py**

```python
"""item_types + fields：动态类型系统（Index 子集）。预设型 1/2 删除保护。"""

from __future__ import annotations

import json
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
        cur = c.execute(
            "INSERT INTO item_types (name, icon, namespace) VALUES (?, ?, 'default')",
            (name, icon),
        )
        return {"id": cur.lastrowid, "name": name, "icon": icon, "fields": []}


def delete_type(repo: Repo, type_id: int) -> None:
    if type_id in _PROTECTED_TYPE_IDS:
        raise ValueError(f"预设类型不可删除：{type_id}")
    with repo.conn() as c:
        cur = c.execute("DELETE FROM item_types WHERE id = ?", (type_id,))
        if cur.rowcount == 0:
            raise ValueError(f"类型不存在：{type_id}")


def add_field(repo: Repo, type_id: int, name: str, field_type: str = "text",
              label: str = "", position: Optional[int] = None) -> dict:
    if field_type not in FIELD_TYPES:
        raise ValueError(f"非法字段类型：{field_type}")
    with repo.conn() as c:
        if position is None:
            row = c.execute(
                "SELECT COALESCE(MAX(position) + 1, 0) FROM fields WHERE type_id = ?",
                (type_id,),
            ).fetchone()
            position = row[0]
        cur = c.execute(
            "INSERT INTO fields (type_id, name, field_type, position, label, options)"
            " VALUES (?, ?, ?, ?, ?, '[]')",
            (type_id, name, field_type, position, label),
        )
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
    if not sets:
        return
    params.append(field_id)
    with repo.conn() as c:
        cur = c.execute(f"UPDATE fields SET {', '.join(sets)} WHERE id = ?", params)
        if cur.rowcount == 0:
            raise ValueError(f"字段不存在：{field_id}")


def remove_field(repo: Repo, field_id: int) -> None:
    with repo.conn() as c:
        cur = c.execute("DELETE FROM fields WHERE id = ?", (field_id,))
        if cur.rowcount == 0:
            raise ValueError(f"字段不存在：{field_id}")
```

- [ ] **Step 4: 写 runs.py**

```python
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
```

- [ ] **Step 5: 运行 repo 测试**

Run: `cd server && python -m pytest tests/test_repo_semantics.py tests/test_repo_migrations.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add server/src/figure_agent/repo
git commit -m "feat(repo): groups/tags/types/runs 访问层"
```

## Phase B — Store 门面与 AI 工作流

### Task 6: store.py 改造（id 寻址 + 增删改名 + properties + fa_snapshots + 文件树）

**Files:**
- Modify: `server/src/figure_agent/store.py`（整文件重写）
- Modify: `server/tests/test_store_executor.py`

- [ ] **Step 1: 重写 store.py**

```python
"""工作区存储（Index 仓库门面）：条目/分组/标签/审计经 repo 包走 index.db；
渲染管线、patch 持久化、快照载荷走条目文件夹（扁平 <12hex>，永不改名）。

目录契约（spec §2）：workspace/.index/index.db + workspace/<12hex>/{plot.py,
base.svg, patch.json, history/}。管理语义全部在 SQL；文件系统只承载内容。
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import executor
from .repo import items as repo_items
from .repo import runs as repo_runs
from .repo.items import ID_RE, require_id
from .repo.repo import FIGURE_TYPE_NAME, Repo
from .svgkit import base_hash, normalize, parse_svg, serialize
from .svgkit import identity, patchops
from .svgkit import geom

NAME_RE = re.compile(r"^[\w][\w .-]*$")

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _require_name(name: str, what: str) -> str:
    """名字进 SQL（不再是目录名），仅做基本卫生校验。"""
    n = name or ""
    if not NAME_RE.match(n):
        raise ValueError(f"非法的{what}名：{name!r}")
    return n


@dataclass
class RenderOutcome:
    ok: bool
    stderr: str = ""
    error_line: Optional[int] = None
    warnings: List[str] | None = None
    stats: Dict | None = None


class Store:
    def __init__(self, workspace: Path, render_timeout: float = 30.0):
        self.workspace = Path(workspace)
        self.render_timeout = render_timeout
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.repo = Repo(self.workspace)
        self.repo.open_or_init()

    # ------------------------------------------------------------ 路径/条目

    def figure_dir(self, item_id: str) -> Path:
        require_id(item_id)
        return self.workspace / item_id

    def read_item(self, item_id: str) -> Dict:
        item = repo_items.get_item(self.repo, item_id)
        if item is None:
            raise ValueError(f"图不存在：{item_id}")
        return item

    # ------------------------------------------------------------ 枚举

    def list_figures(self, q: Optional[str] = None, group_id: Optional[int] = None,
                     tag_id: Optional[int] = None) -> List[Dict]:
        out = []
        for item in repo_items.list_items(self.repo, FIGURE_TYPE_NAME, q=q,
                                          group_id=group_id, tag_id=tag_id):
            fdir = self.workspace / item["id"]
            patch = self._read_patch_file(fdir) or {"ops": []}
            out.append({
                **item,
                "hasBase": (fdir / "base.svg").exists(),
                "lastRenderAt": item["properties"].get("最后渲染"),
                "opCount": len(patch.get("ops", [])),
            })
        return out

    # ------------------------------------------------------------ 元数据/文件

    def read_code(self, item_id: str) -> str:
        return (self.figure_dir(item_id) / "plot.py").read_text(encoding="utf-8")

    def read_patch(self, item_id: str) -> Optional[Dict]:
        return self._read_patch_file(self.figure_dir(item_id))

    def _read_patch_file(self, fdir: Path) -> Optional[Dict]:
        path = fdir / "patch.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"baseHash": "", "ops": [], "_error": "patch.json 解析失败"}

    def _write_patch(self, fdir: Path, patch: Dict) -> None:
        (fdir / "patch.json").write_text(
            json.dumps(patch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def read_svg(self, item_id: str, which: str = "base") -> Optional[str]:
        path = self.figure_dir(item_id) / f"{which}.svg"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def read_files(self, item_id: str, subdir: str = "") -> List[Dict]:
        """条目文件夹递归清单（前端文件树）。路径穿越防御。"""
        require_id(item_id)
        base = self.figure_dir(item_id).resolve()
        root = (base / subdir).resolve()
        root.relative_to(base)
        out: List[Dict] = []
        if not root.is_dir():
            return out
        for p in sorted(root.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            rel = p.relative_to(base).as_posix()
            out.append({"path": rel, "isDir": p.is_dir()})
            if p.is_dir():
                out.extend(self.read_files(item_id, rel))
        return out

    # ------------------------------------------------------------ 建图

    def templates(self) -> List[Dict]:
        out = []
        if not TEMPLATES_DIR.is_dir():
            return out
        for tdir in sorted(TEMPLATES_DIR.iterdir()):
            info = tdir / "template.json"
            if tdir.is_dir() and (tdir / "plot.py").exists():
                payload = {}
                if info.exists():
                    payload = json.loads(info.read_text(encoding="utf-8"))
                out.append(
                    {
                        "id": tdir.name,
                        "title": payload.get("title", tdir.name),
                        "description": payload.get("description", ""),
                    }
                )
        return out

    def create_figure(self, name: str, template: Optional[str] = None,
                      origin: str = "template",
                      group_id: Optional[int] = None) -> Dict:
        """建图：INSERT items + 立即建内容文件夹（plot.py 是真相源）。
        同名图允许（Index 语义，id 消歧）。失败整体回滚。"""
        _require_name(name, "图")
        props: Dict = {"来源": origin}
        if template:
            props["模板"] = template
        item = repo_items.create_item(self.repo, name, FIGURE_TYPE_NAME, props)
        fdir = self.workspace / item["id"]
        try:
            fdir.mkdir(parents=True)
            (fdir / "history").mkdir()
            if template:
                tdir = TEMPLATES_DIR / _require_name(template, "模板")
                if not (tdir / "plot.py").exists():
                    raise ValueError(f"模板不存在：{template}")
                shutil.copy(tdir / "plot.py", fdir / "plot.py")
            self._write_patch(fdir, {"baseHash": "", "ops": []})
        except Exception:
            shutil.rmtree(fdir, ignore_errors=True)
            try:
                repo_items.delete_item(self.repo, item["id"])
            except ValueError:
                pass
            raise
        if group_id is not None:
            repo_items.bind_group(self.repo, item["id"], group_id)
        outcome = self.render(item["id"]) if template else None
        return {"id": item["id"], "name": name,
                "ok": outcome.ok if outcome else False,
                "stderr": outcome.stderr if outcome else ""}

    def rename_figure(self, item_id: str, name: str) -> Dict:
        """与 Index 对齐：只动 SQL，文件夹名（id）永不变。"""
        _require_name(name, "图")
        self.read_item(item_id)
        return repo_items.update_item(self.repo, item_id, name=name)

    def delete_figure(self, item_id: str) -> None:
        """SQL 先行（CASCADE 清绑定与 fa 表），再 best-effort 删文件夹。"""
        repo_items.delete_item(self.repo, item_id)
        shutil.rmtree(self.figure_dir(item_id), ignore_errors=True)

    # ------------------------------------------------------------ 渲染管线

    def render(self, item_id: str) -> RenderOutcome:
        fdir = self.figure_dir(item_id)
        plot_py = fdir / "plot.py"
        if not plot_py.exists():
            return RenderOutcome(ok=False, stderr="plot.py 不存在")
        tmp = fdir / ".render-tmp.svg"
        result = executor.render_with_timeout_guard(
            plot_py, tmp, timeout=self.render_timeout, cwd=fdir
        )
        if not result.ok:
            tmp.unlink(missing_ok=True)
            return RenderOutcome(ok=False, stderr=result.stderr, error_line=result.error_line)
        warnings: List[str] = [
            line.split(":", 1)[1].strip()
            for line in result.stderr.splitlines()
            if line.startswith("WARNING:")
        ]
        try:
            new_root = parse_svg(tmp.read_text(encoding="utf-8"))
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            return RenderOutcome(ok=False, stderr=f"渲染产物不是合法 SVG，已保留上一版：{exc}")
        normalize(new_root)
        new_text = serialize(new_root)

        old_text = self.read_svg(item_id, "base")
        old_root = None
        if old_text:
            try:
                old_root = parse_svg(old_text)
                normalize(old_root)
            except Exception:
                old_root = None

        patch = self.read_patch(item_id) or {"baseHash": "", "ops": []}

        # set_visible(隐藏) 特例：目标已从新 base 消失 = 代码已 set_visible(False)，
        # 视为已表达。必须先于 identity.match 剪除——否则 match 会把 op
        # "治愈"到兄弟元素上（比如 control-bar-1），永远无法收敛。
        patch["ops"] = [
            op
            for op in patch.get("ops", [])
            if not (
                op.get("kind") == "set_visible"
                and not op.get("value")
                and identity.locate(new_root, op.get("target") or {}) is None
            )
        ]

        # 目标重定位/治愈（§6.1 match）
        match_result = identity.match(old_root, new_root, patch.get("ops", []))
        for op in patch.get("ops", []):
            mr = match_result.get(op.get("id", ""))
            if mr is not None:
                op["target"] = mr.target
                op["status"] = "active" if mr.status == "matched" else "lost"
                if mr.degraded:
                    op["status"] = "active"
                    op["degraded"] = True

        # base.svg / final.svg
        base_path = fdir / "base.svg"
        base_path.write_text(new_text, encoding="utf-8")
        final_text, per_op = patchops.apply_patch(new_root, patch)
        (fdir / "final.svg").write_text(final_text, encoding="utf-8")

        patch["baseHash"] = base_hash(new_text)
        self._write_patch(fdir, patch)

        repo_items.merge_properties(self.repo, item_id, {"最后渲染": now_iso()})
        tmp.unlink(missing_ok=True)

        stats = self.figure_stats(new_root)
        lost = [op_id for op_id, s in per_op.items() if s == "lost"]
        if lost:
            warnings.append(f"{len(lost)} 个 patch op 目标丢失（lost），UI 中已高亮")
        if any(op.get("status") == "active" and not op.get("target", {}).get("id", "").startswith("fa:") for op in patch.get("ops", [])):
            warnings.append("部分 op 目标缺少 fa: gid（靠指纹匹配），回写前建议在代码中补 gid")
        return RenderOutcome(ok=True, warnings=warnings, stats=stats)

    def figure_stats(self, root) -> Dict:
        from .svgkit.semantics import collect_semantic

        sem = collect_semantic(root)
        all_el = [el for el in root.iter() if isinstance(el.tag, str)]
        fa_ids = [el.get("id") for el in sem if (el.get("id") or "").startswith("fa:")]
        mat_ids = [
            el.get("id")
            for el in sem
            if not (el.get("id") or "").startswith("fa:")
        ][:50]
        return {
            "elementCount": len(all_el),
            "semanticGroupCount": len(sem),
            "faGroups": fa_ids,
            "matplotlibGroups": mat_ids,
        }

    # ------------------------------------------------------------ 代码写入

    def write_code(self, item_id: str, code: str) -> RenderOutcome:
        fdir = self.figure_dir(item_id)
        (fdir / "plot.py").write_text(code, encoding="utf-8")
        return self.render(item_id)

    # ------------------------------------------------------------ patch

    def save_patch(self, item_id: str, patch: Dict) -> Dict:
        """写 patch.json；为 transform op 补 pre（从当前 base 估算）。"""
        fdir = self.figure_dir(item_id)
        base_text = self.read_svg(item_id, "base")
        if base_text:
            root = parse_svg(base_text)
            normalize(root)
            for op in patch.get("ops", []):
                if op.get("kind") == "transform" and not op.get("pre"):
                    el = identity.locate(root, op.get("target") or {})
                    if el is not None:
                        bbox = geom.estimate_bbox(el)
                        if bbox is not None:
                            op["pre"] = {"center": [round(bbox.cx, 3), round(bbox.cy, 3)],
                                         "size": [round(bbox.w, 3), round(bbox.h, 3)]}
            # 重新计算状态（目标可能已不在）
            for op in patch.get("ops", []):
                if op.get("status") not in ("active", "lost"):
                    op["status"] = "active"
                el = identity.locate(root, op.get("target") or {})
                if el is not None:
                    op["status"] = "active"
                elif op.get("kind") == "set_visible" and not op.get("value"):
                    # 隐藏 op 目标消失留给回写校验判收敛，不误标 lost
                    op["status"] = "active"
                else:
                    op["status"] = "lost"
        patch.setdefault("baseHash", base_hash(base_text) if base_text else "")
        self._write_patch(fdir, patch)
        if base_text:
            root = parse_svg(base_text)
            normalize(root)
            final_text, per_op = patchops.apply_patch(root, patch)
            (fdir / "final.svg").write_text(final_text, encoding="utf-8")
        return {"ok": True}

    def verify_patch(self, item_id: str) -> Dict:
        base_text = self.read_svg(item_id, "base")
        patch = self.read_patch(item_id) or {"baseHash": "", "ops": []}
        if not base_text:
            return {"results": [], "remainingOps": 0, "cleared": True, "error": "base.svg 不存在"}
        root = parse_svg(base_text)
        normalize(root)
        results = patchops.verify_patch(root, patch)
        new_patch = patchops.prune_resolved(patch, results)
        for op in new_patch.get("ops", []):
            st = results.get(op.get("id", ""), {})
            if st.get("status") == "lost":
                op["status"] = "lost"
            elif op.get("status") == "lost" and st.get("status") == "active":
                # verify 重新找到了目标（目标回来了）
                op["status"] = "active"
        self._write_patch(self.figure_dir(item_id), new_patch)
        final_text, _ = patchops.apply_patch(root, new_patch)
        (self.figure_dir(item_id) / "final.svg").write_text(final_text, encoding="utf-8")
        remaining = len(new_patch.get("ops", []))
        return {
            "results": [
                {"opId": op_id, **info}
                for op_id, info in results.items()
            ],
            "remainingOps": remaining,
            "cleared": remaining == 0,
        }

    # ------------------------------------------------------------ 快照

    def snapshot(self, item_id: str, note: str = "") -> Dict:
        fdir = self.figure_dir(item_id)
        ts = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        dest = fdir / "history" / ts
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("base.svg", "patch.json", "plot.py"):
            src = fdir / name
            if src.exists():
                shutil.copy(src, dest / name)
        (dest / "note.txt").write_text(note or "", encoding="utf-8")
        repo_runs.add_snapshot(self.repo, item_id, now_iso(), note, f"history/{ts}")
        return {"id": ts, "note": note}

    def snapshots(self, item_id: str) -> List[Dict]:
        return [
            {"id": Path(row["dir"]).name, "note": row["note"]}
            for row in repo_runs.list_snapshots(self.repo, item_id)
        ]
```

（注意：`ID_RE` 导入未用到可删；`require_id` 必须保留。文件头 docstring 中的 `ID_RE` 仅在需要处使用。）

- [ ] **Step 2: 更新 test_store_executor.py（全文替换）**

```python
"""executor 与 Store 渲染管线测试（真实 subprocess + matplotlib）。"""

import json

import pytest

from figure_agent.store import Store
from figure_agent.svgkit import base_hash


CODE_OK = """
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(4, 3))
b = ax.bar([0, 1], [1, 2])
for i, x in enumerate(b):
    x.set_gid(f"fa:bar-{i}")
ax.set_title("t")
"""

CODE_SYNTAX_ERROR = "import matplotlib.pyplot as plt\nfig = 1 +\n"

CODE_NO_FIG = "import matplotlib.pyplot as plt\nx = 1\n"

CODE_BAD_FONTS = (
    "import matplotlib.pyplot as plt\n"
    "plt.rcParams['svg.fonttype'] = 'path'\n"
    "fig, ax = plt.subplots(figsize=(4,3))\n"
    "ax.plot([0,1],[0,1])\n"
)


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "ws")
    fid = s.create_figure("f1", template="bar-groups")["id"]
    return s, fid


def test_write_code_and_render(store):
    s, fid = store
    res = s.write_code(fid, CODE_OK)
    assert res.ok, res.stderr
    assert res.stats["faGroups"] == ["fa:bar-0", "fa:bar-1"]
    base = s.read_svg(fid, "base")
    assert "fa:bar-0" in base
    # 渲染时间进 SQL（properties），不再有 meta.json
    assert s.read_item(fid)["properties"]["最后渲染"]
    assert not (s.figure_dir(fid) / "meta.json").exists()


def test_syntax_error_reports_line(store):
    s, fid = store
    res = s.write_code(fid, CODE_SYNTAX_ERROR)
    assert not res.ok
    assert res.error_line == 2
    assert "Traceback" in res.stderr
    assert s.read_svg(fid, "base") is not None


def test_no_fig_error(store):
    s, fid = store
    res = s.write_code(fid, CODE_NO_FIG)
    assert not res.ok
    assert "fig" in res.stderr


def test_fonttype_override_warning(store):
    s, fid = store
    res = s.write_code(fid, CODE_BAD_FONTS)
    assert res.ok
    assert any("svg.fonttype" in w for w in (res.warnings or []))
    assert "<text" in s.read_svg(fid, "base")


def test_render_deterministic_hash(store):
    s, fid = store
    s.render(fid)
    h1 = s.read_patch(fid)["baseHash"]
    s.render(fid)
    h2 = s.read_patch(fid)["baseHash"]
    assert h1 == h2


def test_patch_survives_rerender(store):
    s, fid = store
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_style", "target": {"id": "fa:treatment-bar-1"},
         "attr": "fill", "value": "#dd3322", "intent": "改红", "origin": "manual", "status": "active"},
    ]}
    s.save_patch(fid, patch)
    s.render(fid)
    final = s.read_svg(fid, "final")
    assert "#dd3322" in final
    ops = s.read_patch(fid)["ops"]
    assert ops[0]["status"] == "active"


def test_writeback_flow(store):
    """S3 全流程：微调 → 代码表达 → verify → patch 清空。"""
    s, fid = store
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_style", "target": {"id": "fa:treatment-bar-2"},
         "attr": "fill", "value": "#dd3322", "intent": "改红", "origin": "manual", "status": "active"},
    ]}
    s.save_patch(fid, patch)
    v1 = s.verify_patch(fid)
    assert v1["results"][0]["status"] == "active"
    assert v1["cleared"] is False
    code = s.read_code(fid).replace('"#d08770"', '"#dd3322"')
    s.write_code(fid, code)
    v2 = s.verify_patch(fid)
    assert v2["cleared"] is True
    assert s.read_patch(fid)["ops"] == []


def test_snapshot(store):
    s, fid = store
    s.snapshot(fid, "初始版")
    snaps = s.snapshots(fid)
    assert len(snaps) == 1
    assert snaps[0]["note"] == "初始版"


def test_create_without_template(tmp_path):
    s = Store(tmp_path / "ws")
    fid = s.create_figure("f", origin="ai")["id"]
    fdir = s.figure_dir(fid)
    assert fdir.is_dir() and (fdir / "history").is_dir()
    assert not (fdir / "plot.py").exists()
    assert s.read_item(fid)["properties"]["来源"] == "ai"
    assert s.read_patch(fid) == {"baseHash": "", "ops": []}
    assert not (fdir / "meta.json").exists()
    # 同名允许（Index 语义）
    fid2 = s.create_figure("f", origin="ai")["id"]
    assert fid2 != fid


def test_create_rejects_bad_names(store):
    s, _ = store
    with pytest.raises(ValueError):
        s.create_figure("../evil", template="bar-groups")
    with pytest.raises(ValueError):
        s.create_figure("a/b", template="bar-groups")


def test_rename_figure_only_touches_db(store):
    s, fid = store
    s.rename_figure(fid, "新名字")
    assert s.read_item(fid)["name"] == "新名字"
    assert s.figure_dir(fid).name == fid  # 文件夹（id）不变


def test_delete_figure_removes_folder_and_rows(store):
    s, fid = store
    fdir = s.figure_dir(fid)
    s.delete_figure(fid)
    assert not fdir.exists()
    with pytest.raises(ValueError):
        s.read_item(fid)
    with pytest.raises(ValueError):
        s.delete_figure(fid)


def test_create_bad_template_rolls_back(tmp_path):
    s = Store(tmp_path / "ws")
    with pytest.raises(ValueError):
        s.create_figure("x", template="nope")
    assert s.list_figures() == []
    assert not (tmp_path / "ws").exists() or not any(
        p.name.isalnum() and len(p.name) == 12 for p in (tmp_path / "ws").iterdir()
    )


def test_read_files_lists_entry_folder(store):
    s, fid = store
    files = s.read_files(fid)
    paths = {f["path"] for f in files}
    assert "plot.py" in paths and "history" in paths
    with pytest.raises(ValueError):
        s.read_files("../evil")
```

- [ ] **Step 3: 运行测试**

Run: `cd server && python -m pytest tests/test_store_executor.py tests/test_repo_semantics.py tests/test_repo_migrations.py -v`
Expected: all passed（`test_store_executor.py` 之外此时 ai/api 相关旧测试会失败——下一任务处理，不要在此步跑全量）

- [ ] **Step 4: Commit**

```bash
git add server/src/figure_agent/store.py server/tests/test_store_executor.py
git commit -m "feat(store)!: Store 改 id 寻址，增删改名/properties/fa_snapshots/文件树"
```

### Task 7: enrich.py + ai/nodes.py + ai/workflows.py 签名改造

**Files:**
- Modify: `server/src/figure_agent/enrich.py`
- Modify: `server/src/figure_agent/ai/nodes.py`
- Modify: `server/src/figure_agent/ai/workflows.py`
- Modify: `server/tests/test_ai_nodes.py`
- Modify: `server/tests/test_ai_workflows.py`

- [ ] **Step 1: enrich.py 签名改 item_id**

`enrich_selection(store, project, figure, selection)` → `enrich_selection(store, item_id, selection)`；`setdefault("project"/"figure")` 两行换成 `enriched.setdefault("item", item_id)`；`store.read_svg(project, figure, ...)` → `store.read_svg(item_id, ...)`；`_nearby(store, project, figure, el)` → `_nearby(el)`（store 本就未用），调用点 `enriched["nearby"] = _nearby(el)`。改后完整文件：

```python
"""选区富化（纯函数）：在当前 SVG 中定位选区元素并补全
elementId/semanticPath/fingerprint/nearby。供 enrich-selection 端点与
instruct 工作流共用；无任何全局状态。"""

from __future__ import annotations

from .svgkit import geom, identity, normalize, parse_svg, semantics
from .store import Store


def enrich_selection(store: Store, item_id: str, selection: dict) -> dict:
    """富化单条选区。富化失败不影响调用方保存（带 warning）。"""
    enriched = dict(selection or {})
    enriched.setdefault("item", item_id)
    warnings: list[str] = []
    base_text = store.read_svg(item_id, "final") or store.read_svg(item_id, "base")
    if base_text:
        try:
            root = parse_svg(base_text)
            normalize(root)
            el = identity.locate(root, selection or {})
            if el is not None:
                enriched["elementId"] = el.get("id")
                enriched["semanticPath"] = semantics.semantic_path(el)
                enriched["fingerprint"] = identity.fingerprint(el)
                enriched["nearby"] = _nearby(el)
            else:
                warnings.append("无法在当前 SVG 中定位选区元素（id 与语义路径均未命中）")
        except Exception as exc:  # 防御：选区富化失败不影响保存
            warnings.append(f"选区富化失败：{exc}")
    enriched["warnings"] = warnings
    return enriched


def _nearby(el) -> list[str]:
    """语义邻居标签：按 bbox 中心距离排序取最近 5 个。"""
    root = el.getroottree().getroot()
    bbox = geom.estimate_bbox(el)
    if bbox is None:
        return []
    names: list[tuple[float, str]] = []
    for sem in semantics.collect_semantic(root):
        if sem is el:
            continue
        b = geom.estimate_bbox(sem)
        if b is None:
            continue
        d = ((b.cx - bbox.cx) ** 2 + (b.cy - bbox.cy) ** 2) ** 0.5
        label = sem.get("id") or ""
        texts = semantics.subtree_texts(sem)
        if texts:
            label += f" {' / '.join(texts[:2])}"
        names.append((d, label))
    names.sort(key=lambda x: x[0])
    return [n[1] for n in names[:5]]
```

- [ ] **Step 2: nodes.py 四个工厂改签名**

`from ..store import Store, now_iso` 后追加 `from ..repo import runs as repo_runs`。四个工厂替换为：

```python
def make_render_validate(store: Store, item_id: str):
    """取代码（fix 优先于 gen）→ 写盘渲染 → {ok, rounds, stderr, code, ...}。

    返回值必须带 "code"（本轮实际渲染的代码）：FixCode 的 prompt 经 {render}
    拿到整个 dict，没有 code 就无法修复（v2 计划评审补上的字段）。
    """

    async def render_validate(view) -> dict:
        try:
            fix = view.field("fix")
        except (KeyError, TypeError):
            fix = None
        code = fix.get("code") if isinstance(fix, dict) else None
        source = "fix"
        if not (isinstance(code, str) and code.strip()):
            try:
                gen = view.field("gen")
            except (KeyError, TypeError):
                gen = None
            code = gen.get("code") if isinstance(gen, dict) else None
            source = "gen"

        rounds = view.state.get("rounds", 0) + 1
        view.state["rounds"] = rounds
        if not (isinstance(code, str) and code.strip()):
            return {"ok": False, "rounds": rounds, "stderr": "上游未产出代码",
                    "error_line": None, "source": source, "code": ""}
        outcome = await asyncio.to_thread(store.write_code, item_id, code)
        return {
            "ok": outcome.ok,
            "rounds": rounds,
            "stderr": (outcome.stderr or "")[-4000:],
            "error_line": outcome.error_line,
            "fa_count": len((outcome.stats or {}).get("faGroups", [])),
            "source": source,
            "code": code,
        }

    return render_validate


def make_read_patch(store: Store, item_id: str):
    def read_patch(view) -> dict:
        patch = store.read_patch(item_id) or {"ops": []}
        return {"ops": patch.get("ops", [])}

    return read_patch


def make_render_verify(store: Store, item_id: str):
    """回写代码 → 渲染 → verify_patch 收敛判定。"""

    async def render_verify(view) -> dict:
        tr = view.field("translated")
        code = tr.get("code") if isinstance(tr, dict) else None
        rounds = view.state.get("rounds", 0) + 1
        view.state["rounds"] = rounds
        if not (isinstance(code, str) and code.strip()):
            return {"ok": False, "cleared": False, "rounds": rounds, "remaining": -1,
                    "results": [], "stderr": "回写节点未产出代码"}
        outcome = await asyncio.to_thread(store.write_code, item_id, code)
        if not outcome.ok:
            return {"ok": False, "cleared": False, "rounds": rounds, "remaining": -1,
                    "results": [], "stderr": (outcome.stderr or "")[-4000:],
                    "error_line": outcome.error_line}
        verdict = await asyncio.to_thread(store.verify_patch, item_id)
        return {"ok": True, "cleared": bool(verdict.get("cleared")),
                "rounds": rounds, "remaining": verdict.get("remainingOps", 0),
                "results": verdict.get("results", []), "stderr": ""}

    return render_verify


def make_finalize(store: Store, item_id: str, kind: str):
    """终点节点：规范化返回值 + 审计进 fa_runs。writeback 的 ok = cleared。

    读 bind 字段 "result"（TaskDefinition inputs={"result": 上游节点}）——
    真实引擎的 NodeView 没有 .output 属性（那是 GuardView 的），body 里读
    view.output 会 AttributeError 静默失败（评审仿真发现）。
    """

    def finalize(view) -> dict:
        o = view.field("result")
        o = o if isinstance(o, dict) else {}
        result = {
            "kind": kind,
            "ok": bool(o.get("cleared")) if kind == "writeback" else bool(o.get("ok")),
            "rounds": o.get("rounds", 0),
            "stderr": o.get("stderr", ""),
            "error_line": o.get("error_line"),
            "notes": o.get("notes", ""),
        }
        if kind == "writeback":
            result["cleared"] = bool(o.get("cleared"))
            result["remaining"] = o.get("remaining", -1)
        detail = {"stderr": result["stderr"], "error_line": result.get("error_line"),
                  "notes": result.get("notes", "")}
        if kind == "writeback":
            detail["cleared"] = result["cleared"]
            detail["remaining"] = result["remaining"]
        repo_runs.add_run(store.repo, item_id, kind, result["ok"],
                          result["rounds"], at=now_iso(), detail=detail)
        return result

    return finalize
```

（`make_parse_upload`、`make_write_data`、`make_merge_wb` 不变；`from pathlib import Path` 若不再使用可删。）

- [ ] **Step 3: workflows.py 改寻址与审计**

`from ..store import Store, now_iso` 后追加 `from ..repo import runs as repo_runs`。以下函数整体替换：

```python
def build_registry(kind: str, store: Store, item_id: str,
                   spec: dict, llm_client, bus: EventBus) -> HarnessRegistry:
    fdir = store.figure_dir(item_id)
    reg = HarnessRegistry(llm_client=llm_client, event_bus=bus)
    # standardize 产出 CSV，与渲染契约/gid/字体无关——用裸 config 不拼 CONTRACT；
    # 但它同样吃任意 LLM 输出，修复链照配（终审遗留：唯一没有 validate_retries 的 harness）
    reg.harness("standardize", HarnessConfig(
        prompt_core=prompts.STANDARDIZE_CORE,
        output_format=OutputFormat(type="json_object"),
        validate_retries=1,
    ))
    for name, core in (
        ("gen_code", prompts.GEN_CODE_CORE),
        ("adapt_code", prompts.ADAPT_CODE_CORE),
        ("fix_code", prompts.FIX_CODE_CORE),
        ("edit_code", prompts.EDIT_CODE_CORE),
        ("translate_patch", prompts.TRANSLATE_PATCH_CORE),
    ):
        reg.harness(name, _hc(core))

    # upload_name 仅 create/adapt 用；writeback/edit 的 spec 无此键，
    # parse_upload 节点在这两条 flow 里不会被 fire，空串安全
    reg.script("parse_upload")(nodes.make_parse_upload(fdir, spec.get("upload_name", "")))
    reg.script("write_data")(nodes.make_write_data(fdir))
    reg.script("render_validate")(nodes.make_render_validate(store, item_id))
    reg.script("read_patch")(nodes.make_read_patch(store, item_id))
    reg.script("merge_wb")(nodes.make_merge_wb(fdir))
    reg.script("render_verify")(nodes.make_render_verify(store, item_id))
    reg.script("finalize")(nodes.make_finalize(store, item_id, kind))

    for gname, gfn in (
        ("needs_fix", nodes.needs_fix),
        ("settled", nodes.settled),
        ("wb_continue", nodes.wb_continue),
        ("wb_done", nodes.wb_done),
    ):
        reg.guard(gname, gfn)
    return reg


def _bridge(item_id: str, run_id: str, bus: EventBus) -> None:
    """EventBus → WS hub：ai_run 事件（节点级进度）。"""
    from ..events import hub

    def push(payload: dict) -> None:
        hub.broadcast_threadsafe({
            "type": "ai_run", "item": item_id,
            "runId": run_id, **payload,
        })

    def on_event(evt) -> None:
        if isinstance(evt, ScriptStarted):
            push({"phase": "node_start", "node": evt.node})
        elif isinstance(evt, ScriptCompleted):
            push({"phase": "node_end", "node": evt.node})
        elif isinstance(evt, ScriptFailed):
            push({"phase": "node_failed", "node": evt.node, "detail": evt.error})
        elif isinstance(evt, LlmCallStarted):
            push({"phase": "llm_start", "node": evt.node})
        elif isinstance(evt, LlmCallCompleted):
            push({"phase": "llm_end", "node": evt.node})
        elif isinstance(evt, HarnessFailed):
            push({"phase": "node_failed", "node": evt.node, "detail": evt.reason})

    for evt_type in (ScriptStarted, ScriptCompleted, ScriptFailed,
                     LlmCallStarted, LlmCallCompleted, HarnessFailed):
        bus.subscribe(evt_type, on_event)


def _audit_failure(store: Store, item_id: str, kind: str, stderr: str) -> None:
    """Finalize 未 fire 的失败补写 fa_runs（形状与 nodes.finalize 一致）。"""
    try:
        repo_runs.add_run(store.repo, item_id, kind, False, 0, at=now_iso(),
                          detail={"stderr": stderr, "error_line": None, "notes": ""})
    except Exception:
        pass


async def run_workflow(kind: str, store: Store, item_id: str,
                       spec: dict, llm_client=None) -> dict:
    """执行一条工作流，返回 Finalize 节点的规范化结果。"""
    if kind not in TASKLISTS:
        raise ValueError(f"未知工作流：{kind}")
    async with _get_run_lock():
        run_id = f"{kind}_{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}"
        from ..events import hub

        hub.broadcast_threadsafe({"type": "ai_run", "item": item_id,
                                  "runId": run_id, "phase": "run_start", "node": kind})
        finalized = False  # Finalize 是否亲自落过审计（防双写）
        try:
            # get_llm/build_registry/Module 构造也在罩内：配置错误等构建期
            # 异常同样走统一失败出口，且必发 run_end（不裸逃逸成 500）
            client = llm_client or get_llm()
            bus = EventBus()
            _bridge(item_id, run_id, bus)
            reg = build_registry(kind, store, item_id, spec, client, bus)
            module = Module(
                spec=spec,
                tasklist=TASKLISTS[kind](spec),
                llm_client=client,
                event_bus=bus,
                registry=reg,
                module_id=run_id,
                persist=False,
                status_file=False,
                keep_records=False,
                stream_log=False,
                control=False,
                review_harness=None,
            )
            firings = await module.run(max_ticks=60)
            result = _final_output(firings)
            finalized = bool(result)
            if not result:
                # Finalize 未 fire（引擎级 Failure 饿死下游）：收割具体原因
                detail = _harvest_failure(firings)
                result = {"kind": kind, "ok": False, "rounds": 0,
                          "stderr": detail or "工作流未到达终点节点"}
        except Exception as exc:  # LLM/构建错误统一失败出口
            result = {"kind": kind, "ok": False, "rounds": 0, "stderr": f"{type(exc).__name__}: {exc}"}
        if not finalized:
            _audit_failure(store, item_id, kind, result.get("stderr") or "")
        hub.broadcast_threadsafe({"type": "ai_run", "item": item_id,
                                  "runId": run_id, "phase": "run_end", "node": kind,
                                  "ok": result.get("ok"), "detail": (result.get("stderr") or "")[:300]})
        return result
```

（`_hc`、四个 `_tl_*`、`TASKLISTS`、`_final_output`、`_harvest_failure` 不变；文件头 docstring 中 "runs.jsonl" 字样改为 "fa_runs"。）

- [ ] **Step 4: 更新 test_ai_nodes.py**

- `_make_store_fig` 替换为：

```python
def _make_store_fig(tmp_path):
    """Store 建图（AI origin：无 plot.py），返回 (store, item_id, fdir)。"""
    ws = tmp_path / "ws"
    store = Store(ws)
    fid = store.create_figure("f", origin="ai")["id"]
    return store, fid, store.figure_dir(fid)
```

- `make_render_validate(store, fdir, "p", "f")` → `make_render_validate(store, fid)`（3 处）；`make_read_patch(store, "p", "f")` → `make_read_patch(store, fid)`；`store.save_patch("p", "f", {...})` → `store.save_patch(fid, {...})`；`make_finalize(fdir, "create")` → `make_finalize(store, fid, "create")`、`make_finalize(fdir, "writeback")` → `make_finalize(store, fid, "writeback")`。
- `test_finalize_writes_runs_jsonl` 整体替换为：

```python
def test_finalize_writes_fa_runs(tmp_path):
    store, fid, fdir = _make_store_fig(tmp_path)
    fn = nodes.make_finalize(store, fid, "create")
    result = fn(FakeView(fields={"result": {"ok": True, "rounds": 2, "stderr": "", "notes": "done"}}))
    assert result["kind"] == "create" and result["ok"] is True
    from figure_agent.repo import runs as repo_runs

    runs = repo_runs.list_runs(store.repo, fid)
    assert len(runs) == 1 and runs[0]["kind"] == "create"
    assert runs[0]["ok"] is True and runs[0]["notes"] == "done"
    assert not (fdir / "runs.jsonl").exists()  # 审计已进 SQL

    fn_wb = nodes.make_finalize(store, fid, "writeback")
    r2 = fn_wb(FakeView(fields={"result": {"cleared": False, "rounds": 3, "remaining": 1, "stderr": "", "ok": True}}))
    assert r2["ok"] is False  # writeback 的 ok = cleared
```

- [ ] **Step 5: 更新 test_ai_workflows.py**

- 顶部追加 `from figure_agent.repo import runs as repo_runs`。
- `make_store` 替换为：

```python
def make_store(tmp_path):
    """返回 (store, item_id)。writeback/edit 测试不走 create 工作流（无
    WriteData 节点），直接备好 data.csv，使 GOOD_CODE 的 pd.read_csv 可渲染。"""
    store = Store(tmp_path / "ws")
    fid = store.create_figure("f", origin="ai")["id"]
    fdir = store.figure_dir(fid)
    up = fdir / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    (up / "d.csv").write_text("dose,response\n0,1.1\n5,2.3\n10,3.9\n", encoding="utf-8")
    (fdir / "data.csv").write_text("dose,response\n0,1.1\n5,2.3\n10,3.9\n", encoding="utf-8")
    return store, fid
```

- 每个测试开头 `store = make_store(tmp_path)` → `store, fid = make_store(tmp_path)`；`run_workflow("create", store, "p", "f", {...})` → `run_workflow("create", store, fid, {...})`（4 条工作流同理）；`store.figure_dir("p", "f")` → `store.figure_dir(fid)`；`store.write_code("p", "f", X)` / `store.save_patch("p", "f", X)` / `store.read_patch("p", "f")` / `store.read_svg("p", "f", "base")` → `fid` 版。
- runs.jsonl 断言替换（2 处 create/adapt + 1 处失败审计）：

```python
    runs = repo_runs.list_runs(store.repo, fid)
    assert runs[0]["kind"] == "create" and runs[0]["ok"] is True
```

```python
    runs = repo_runs.list_runs(store.repo, fid)
    assert runs[0]["kind"] == "adapt" and runs[0]["ok"] is True
```

```python
    runs = repo_runs.list_runs(store.repo, fid)
    assert len(runs) == 1
    assert runs[0]["kind"] == "create" and runs[0]["ok"] is False
    assert "失败" in runs[0]["stderr"]
```

- [ ] **Step 6: 运行测试**

Run: `cd server && python -m pytest tests/test_ai_nodes.py tests/test_ai_workflows.py -v`
Expected: all passed

- [ ] **Step 7: Commit**

```bash
git add server/src/figure_agent/enrich.py server/src/figure_agent/ai server/tests/test_ai_nodes.py server/tests/test_ai_workflows.py
git commit -m "refactor(ai)!: 工作流寻址改 item_id，审计进 fa_runs；enrich 改 id 签名"
```

### Task 8: 迁移 CLI（migrate.py + __main__ 子命令）

**Files:**
- Create: `server/src/figure_agent/migrate.py`
- Modify: `server/src/figure_agent/__main__.py`
- Test: `server/tests/test_migrate_cli.py`

- [ ] **Step 1: 写失败的迁移测试**

创建 `server/tests/test_migrate_cli.py`：

```python
"""迁移 CLI：旧 <项目>/<图>/ → Index 仓库（扁平哈希 + index.db）。"""

import json
from pathlib import Path

from figure_agent.migrate import migrate_workspace
from figure_agent.repo import groups as repo_groups
from figure_agent.repo import items as repo_items
from figure_agent.repo import runs as repo_runs
from figure_agent.repo.repo import Repo


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
    item = repo_items.get_item(repo, entry["id"])
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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && python -m pytest tests/test_migrate_cli.py -v`
Expected: FAIL（`ModuleNotFoundError: figure_agent.migrate`）

- [ ] **Step 3: 写 migrate.py**

```python
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
```

- [ ] **Step 4: __main__.py 加 migrate 子命令（全文替换）**

```python
"""python -m figure_agent：启动本地服务 / 旧数据一次性迁移。"""

from __future__ import annotations

import argparse
import json

import uvicorn

from . import config


def main() -> None:
    parser = argparse.ArgumentParser(prog="figure-agent", description="figure-agent 本地服务")
    parser.add_argument("command", nargs="?", choices=["serve", "migrate"], default="serve",
                        help="serve=启动服务（默认）；migrate=旧 workspace 迁移为 Index 仓库")
    parser.add_argument("--port", type=int, default=config.port())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--workspace", default=None, help="工作区目录（默认 <repo>/workspace 或 $FA_WORKSPACE）")
    parser.add_argument("--archive", action="store_true",
                        help="migrate 时把旧项目目录归档到 _migrated_backup/ 而非删除")
    args = parser.parse_args()

    if args.workspace:
        import os

        os.environ["FA_WORKSPACE"] = str(args.workspace)

    if args.command == "migrate":
        from .migrate import migrate_workspace

        summary = migrate_workspace(config.workspace_dir(), archive=args.archive)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    uvicorn.run(
        "figure_agent.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 运行测试**

Run: `cd server && python -m pytest tests/test_migrate_cli.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add server/src/figure_agent/migrate.py server/src/figure_agent/__main__.py server/tests/test_migrate_cli.py
git commit -m "feat(migrate): 旧 workspace 一次性迁移为 Index 仓库（幂等，--archive 可选）"
```

## Phase C — API 层

### Task 9: main.py 路由重写 + test_api.py 更新

**Files:**
- Modify: `server/src/figure_agent/main.py`（整文件重写）
- Modify: `server/tests/test_api.py`（整文件重写）

- [ ] **Step 1: 重写 test_api.py（先写失败测试）**

```python
"""FastAPI 集成测试：Index 仓库管理 + 图内容管线 + AI 工作流端点。"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import figure_agent.main as main_mod


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FA_WORKSPACE", str(tmp_path / "ws"))
    import importlib

    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def _create(client, name="bars", template="bar-groups", **kw):
    r = client.post("/api/items", json={"name": name, "template": template, **kw})
    assert r.status_code == 200, r.text
    return r.json()  # {id, name, ok, stderr}


def test_repo_info_and_seed(client):
    info = client.get("/api/repo/info").json()
    assert info["itemCount"] == 0 and info["dbVersion"] == 1
    types = {t["name"] for t in client.get("/api/types").json()}
    assert {"通用", "任务", "图"} <= types
    assert client.get("/api/repo/state").json()["theme"] == "light"
    client.put("/api/repo/state", json={"theme": "dark"})
    assert client.get("/api/repo/state").json()["theme"] == "dark"


def test_full_flow(client):
    created = _create(client)
    assert created["ok"] is True
    fid = created["id"]

    items = client.get("/api/items").json()
    assert items[0]["id"] == fid and items[0]["hasBase"] is True

    fig = client.get(f"/api/figures/{fid}").json()
    assert "fa:treatment-bar-0" in fig["baseSvg"]
    assert fig["patch"]["ops"] == []
    assert fig["name"] == "bars"

    # 写代码（渲染错误透传；plot.py 已被写成坏代码，代码=真相源）
    r = client.put(f"/api/figures/{fid}/code", json={"code": "fig = 1 +\n"})
    body = r.json()
    assert body["ok"] is False and body["errorLine"] == 1
    assert "fa:treatment-bar-0" in client.get(f"/api/figures/{fid}").json()["baseSvg"]

    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_style", "target": {"id": "fa:treatment-bar-2"},
         "attr": "fill", "value": "#dd3322", "intent": "改红", "origin": "manual", "status": "active"},
    ]}
    assert client.put(f"/api/figures/{fid}/patch", json=patch).json()["ok"] is True
    assert "#dd3322" in client.get(f"/api/figures/{fid}").json()["finalSvg"]

    v = client.post(f"/api/figures/{fid}/verify-patch").json()
    assert v["cleared"] is False and v["results"][0]["status"] == "active"

    from figure_agent.store import TEMPLATES_DIR

    good_code = (TEMPLATES_DIR / "bar-groups" / "plot.py").read_text(encoding="utf-8")
    assert client.put(f"/api/figures/{fid}/code", json={"code": good_code}).json()["ok"] is True
    assert client.post(f"/api/figures/{fid}/run").json()["ok"] is True

    r = client.post(f"/api/figures/{fid}/snapshot", json={"note": "v1"})
    assert r.status_code == 200
    assert client.get(f"/api/figures/{fid}").json()["snapshots"][0]["note"] == "v1"


def test_rename_delete_groups_tags(client):
    fid = _create(client, name="fig1")["id"]
    g = client.post("/api/groups", json={"name": "项目A"}).json()
    client.post(f"/api/items/{fid}/groups", json={"id": g["id"]})
    items = client.get("/api/items", params={"groupId": g["id"]}).json()
    assert [i["id"] for i in items] == [fid] and items[0]["groupIds"] == [g["id"]]

    # 改名只动 SQL：文件夹名（=id）不变
    client.patch(f"/api/items/{fid}", json={"name": "fig1-renamed"})
    from figure_agent.main import store

    assert Path(store.figure_dir(fid)).name == fid
    assert client.get("/api/items").json()[0]["name"] == "fig1-renamed"

    client.patch(f"/api/items/{fid}", json={"properties": {"来源": "manual"}})
    assert client.get("/api/items").json()[0]["properties"]["来源"] == "manual"

    t = client.post("/api/tags", json={"name": "重要"}).json()
    client.post(f"/api/items/{fid}/tags", json={"id": t["id"]})
    assert client.get("/api/items", params={"tagId": t["id"]}).json()[0]["tags"] == ["重要"]
    client.delete(f"/api/items/{fid}/tags", params={"id": t["id"]})
    assert client.get("/api/items").json()[0]["tags"] == []

    client.delete(f"/api/items/{fid}")
    assert client.get("/api/items").json() == []
    assert not Path(store.figure_dir(fid)).exists()
    assert client.get(f"/api/figures/{fid}").status_code == 404


def test_group_delete_keeps_items(client):
    fid = _create(client, name="fig1")["id"]
    g = client.post("/api/groups", json={"name": "G"}).json()
    client.post(f"/api/items/{fid}/groups", json={"id": g["id"]})
    client.delete(f"/api/groups/{g['id']}")
    items = client.get("/api/items").json()
    assert items[0]["id"] == fid and items[0]["groupIds"] == []


def test_same_name_allowed(client):
    a = _create(client, name="dup")
    b = _create(client, name="dup")
    assert a["id"] != b["id"]
    assert len(client.get("/api/items").json()) == 2


def test_types_and_fields(client):
    fig_type = next(t for t in client.get("/api/types").json() if t["name"] == "图")
    assert [f["name"] for f in fig_type["fields"]] == ["模板", "来源", "最后渲染"]
    f = client.post(f"/api/types/{fig_type['id']}/fields",
                    json={"name": "状态", "fieldType": "dropdown"}).json()
    assert f["fieldType"] == "dropdown"
    client.patch(f"/api/types/{fig_type['id']}/fields/{f['id']}", json={"label": "当前状态"})
    client.delete(f"/api/types/{fig_type['id']}/fields/{f['id']}")
    assert client.delete("/api/types/1").status_code == 400  # 预设型保护


def test_files_endpoint(client):
    fid = _create(client)["id"]
    files = client.get(f"/api/figures/{fid}/files").json()
    paths = {f["path"] for f in files}
    assert {"plot.py", "patch.json", "history"} <= paths


def test_create_bad_template_400_and_rollback(client):
    r = client.post("/api/items", json={"name": "x", "template": "nope"})
    assert r.status_code == 400
    assert client.get("/api/items").json() == []


def _stub_routes(monkeypatch, routes):
    from tests.test_ai_workflows import StubLLM

    stub = StubLLM(routes)
    import figure_agent.ai.workflows as wf

    monkeypatch.setattr(wf, "get_llm", lambda: stub)
    return stub


def test_ai_create_endpoint(client, monkeypatch):
    iris = Path(__file__).parent / "fixtures" / "iris.csv"
    from tests.test_ai_workflows import GOOD_CODE, STD_REPLY

    _stub_routes(monkeypatch, {
        "数据标准化": [STD_REPLY],
        "绘图代码生成器": [json.dumps({"code": GOOD_CODE, "notes": ""})],
    })
    r = client.post(
        "/api/figures/ai",
        data={"name": "ai-fig", "requirements": "散点图，按物种着色"},
        files={"data": ("iris.csv", iris.read_bytes(), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["kind"] == "create"
    fid = body["id"]
    assert "fa:response-curve" in client.get(f"/api/figures/{fid}").json()["baseSvg"]
    assert client.get(f"/api/figures/{fid}").json()["properties"]["来源"] == "ai"
    runs = client.get(f"/api/figures/{fid}/runs").json()
    assert runs[0]["kind"] == "create" and runs[0]["ok"] is True


def test_ai_create_rollback_on_upload_error(client, monkeypatch):
    monkeypatch.setattr(main_mod, "MAX_UPLOAD_BYTES", 10)
    r = client.post(
        "/api/figures/ai",
        data={"name": "big", "requirements": "x"},
        files={"data": ("d.csv", b"a,b\n1,2,3,4,5,6\n", "text/csv")},
    )
    assert r.status_code == 400
    assert client.get("/api/items").json() == []  # 回滚，不留半图


def test_instruct_endpoint(client, monkeypatch):
    fid = _create(client)["id"]
    code = client.get(f"/api/figures/{fid}").json()["code"]
    _stub_routes(monkeypatch, {
        "绘图代码修改器": [json.dumps({"code": code, "notes": "已处理指令"})],
    })
    sel = {"elementId": "fa:treatment-bar-1", "semanticPath": "figure_1/axes_1/fa:treatment-bar-1"}
    r = client.post(f"/api/figures/{fid}/instruct",
                    json={"instruction": "把选中的柱子改红", "selection": sel})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert client.get(f"/api/figures/{fid}").json()["baseSvg"]


def test_writeback_endpoint(client, monkeypatch):
    fid = _create(client)["id"]
    code = client.get(f"/api/figures/{fid}").json()["code"]
    patched = code.replace('b.set_gid(f"fa:treatment-bar-{i}")',
                           'b.set_gid(f"fa:treatment-bar-{i}"); b.set_color("#dd3322")')
    _stub_routes(monkeypatch, {"微调回写器": [json.dumps({"code": patched, "notes": "改色"})]})
    sel = {"elementId": "fa:treatment-bar-1", "semanticPath": "figure_1/axes_1/fa:treatment-bar-1"}
    client.post(f"/api/figures/{fid}/enrich-selection", json={"selection": sel})
    patch = client.get(f"/api/figures/{fid}").json()["patch"]
    patch["ops"] = [{"id": "op-x", "kind": "set_style",
                     "target": {"id": "fa:treatment-bar-1",
                                "semanticPath": "figure_1/axes_1/fa:treatment-bar-1"},
                     "attr": "fill", "value": "#dd3322", "intent": "处理组改红",
                     "origin": "manual", "status": "active"}]
    client.put(f"/api/figures/{fid}/patch", json=patch)
    r = client.post(f"/api/figures/{fid}/writeback")
    body = r.json()
    assert body["cleared"] is True and body["ok"] is True


def test_instruct_without_plot_py_400(client):
    from figure_agent.main import store

    fid = store.create_figure("no-plot", origin="ai")["id"]
    sel = {"elementId": "fa:treatment-bar-1", "semanticPath": "figure_1/axes_1/fa:treatment-bar-1"}
    r = client.post(f"/api/figures/{fid}/instruct",
                    json={"instruction": "改红", "selection": sel})
    assert r.status_code == 400, r.text


def test_enrich_selection_stateless(client):
    fid = _create(client)["id"]
    sel = {"elementId": "fa:treatment-bar-2", "semanticPath": "figure_1/axes_1/fa:treatment-bar-2"}
    body = client.post(f"/api/figures/{fid}/enrich-selection", json={"selection": sel}).json()
    assert body["elementId"] == "fa:treatment-bar-2"
    assert body["fingerprint"]
    assert client.get("/api/session/selection").status_code == 404
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && python -m pytest tests/test_api.py -v`
Expected: FAIL（旧路由 404）

- [ ] **Step 3: 重写 main.py（整文件替换）**

```python
"""FastAPI 应用：Index 仓库管理 API + 图内容管线 + WS + 静态托管 web/dist。

管理语义（条目/分组/标签/类型/主题状态）全部经 figure_agent.repo 走
index.db；图内容（plot.py/svg/patch/快照载荷/uploads）走条目文件夹。
旧 project/figure 寻址已废除，统一 item_id（12 位哈希）。
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, enrich
from .ai.workflows import run_workflow
from .events import hub
from .repo import groups as repo_groups
from .repo import items as repo_items
from .repo import runs as repo_runs
from .repo import tags as repo_tags
from .repo import types as repo_types
from .repo.items import ID_RE
from .store import Store

app = FastAPI(title="figure-agent", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = Store(config.workspace_dir(), render_timeout=config.render_timeout())
repo = store.repo


# ---------------------------------------------------------------- 模型


class CodePut(BaseModel):
    code: str


class ItemCreate(BaseModel):
    name: str
    groupId: int | None = None
    template: str | None = None
    origin: str = "template"


class ItemPatch(BaseModel):
    name: str | None = None
    properties: dict | None = None


class GroupCreate(BaseModel):
    name: str
    parentId: int | None = None
    position: int = 0


class GroupPatch(BaseModel):
    name: str | None = None
    parentId: int | None = None
    position: int | None = None


class TagCreate(BaseModel):
    name: str


class TypeCreate(BaseModel):
    name: str
    icon: str = "file"


class FieldCreate(BaseModel):
    name: str
    fieldType: str = "text"
    label: str = ""


class FieldPatch(BaseModel):
    name: str | None = None
    fieldType: str | None = None
    label: str | None = None
    position: int | None = None


class BindBody(BaseModel):
    id: int


class StatePut(BaseModel):
    theme: str | None = None


class SelectionPost(BaseModel):
    selection: dict | list[dict] = Field(default_factory=dict)


class InstructPost(BaseModel):
    instruction: str
    selection: dict | list[dict] = Field(default_factory=dict)


class SnapshotPost(BaseModel):
    note: str = ""


def _item_or_404(item_id: str) -> dict:
    if not ID_RE.match(item_id or ""):
        raise HTTPException(status_code=404, detail=f"图不存在：{item_id}")
    item = repo_items.get_item(repo, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"图不存在：{item_id}")
    return item


def _fdir_or_404(item_id: str) -> Path:
    _item_or_404(item_id)
    fdir = store.figure_dir(item_id)
    if not fdir.is_dir():
        raise HTTPException(status_code=404,
                            detail=f"图文件夹缺失（可能在 Index 中被删除）：{item_id}")
    return fdir


async def _notify(event: dict) -> None:
    await hub.broadcast(event)


# ---------------------------------------------------------------- 仓库


@app.get("/api/repo/info")
def repo_info():
    return repo.info()


@app.get("/api/repo/state")
def get_state():
    return repo.read_state()


@app.put("/api/repo/state")
def put_state(body: StatePut):
    return repo.write_state({k: v for k, v in body.model_dump().items() if v is not None})


# ---------------------------------------------------------------- 条目/管理语义


@app.get("/api/items")
def list_items(q: str = "", groupId: int | None = None, tagId: int | None = None):
    return store.list_figures(q=q or None, group_id=groupId, tag_id=tagId)


@app.post("/api/items")
async def create_item(body: ItemCreate):
    try:
        result = store.create_figure(body.name, template=body.template,
                                     origin=body.origin, group_id=body.groupId)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await _notify({"type": "figure_updated", "item": result["id"]})
    return result


@app.patch("/api/items/{item_id}")
async def patch_item(item_id: str, body: ItemPatch):
    _item_or_404(item_id)
    try:
        if body.name is not None:
            store.rename_figure(item_id, body.name)
        if body.properties is not None:
            repo_items.update_item(repo, item_id, properties=body.properties)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await _notify({"type": "figure_updated", "item": item_id})
    return repo_items.get_item(repo, item_id)


@app.delete("/api/items/{item_id}")
async def delete_item(item_id: str):
    _item_or_404(item_id)
    store.delete_figure(item_id)
    await _notify({"type": "figure_deleted", "item": item_id})
    return {"ok": True}


@app.post("/api/items/{item_id}/groups")
async def bind_group_ep(item_id: str, body: BindBody):
    _item_or_404(item_id)
    repo_items.bind_group(repo, item_id, body.id)
    await _notify({"type": "figure_updated", "item": item_id})
    return {"ok": True}


@app.delete("/api/items/{item_id}/groups")
async def unbind_group_ep(item_id: str, id: int = Query()):
    _item_or_404(item_id)
    repo_items.unbind_group(repo, item_id, id)
    await _notify({"type": "figure_updated", "item": item_id})
    return {"ok": True}


@app.post("/api/items/{item_id}/tags")
async def bind_tag_ep(item_id: str, body: BindBody):
    _item_or_404(item_id)
    repo_items.bind_tag(repo, item_id, body.id)
    await _notify({"type": "figure_updated", "item": item_id})
    return {"ok": True}


@app.delete("/api/items/{item_id}/tags")
async def unbind_tag_ep(item_id: str, id: int = Query()):
    _item_or_404(item_id)
    repo_items.unbind_tag(repo, item_id, id)
    await _notify({"type": "figure_updated", "item": item_id})
    return {"ok": True}


@app.get("/api/groups")
def list_groups():
    return repo_groups.list_groups(repo)


@app.post("/api/groups")
async def create_group(body: GroupCreate):
    try:
        return repo_groups.create_group(repo, body.name, body.parentId, body.position)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/api/groups/{group_id}")
async def patch_group(group_id: int, body: GroupPatch):
    try:
        return repo_groups.update_group(repo, group_id, body.name, body.parentId, body.position)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/groups/{group_id}")
async def delete_group(group_id: int):
    try:
        repo_groups.delete_group(repo, group_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@app.get("/api/tags")
def list_tags():
    return repo_tags.list_tags(repo)


@app.post("/api/tags")
async def create_tag(body: TagCreate):
    try:
        return repo_tags.create_tag(repo, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/tags/{tag_id}")
async def delete_tag(tag_id: int):
    try:
        repo_tags.delete_tag(repo, tag_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@app.get("/api/types")
def list_types():
    return repo_types.list_types(repo)


@app.post("/api/types")
async def create_type(body: TypeCreate):
    return repo_types.create_type(repo, body.name, body.icon)


@app.delete("/api/types/{type_id}")
async def delete_type(type_id: int):
    try:
        repo_types.delete_type(repo, type_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.post("/api/types/{type_id}/fields")
async def add_field(type_id: int, body: FieldCreate):
    try:
        return repo_types.add_field(repo, type_id, body.name, body.fieldType, body.label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/api/types/{type_id}/fields/{field_id}")
async def patch_field(type_id: int, field_id: int, body: FieldPatch):
    try:
        repo_types.update_field(repo, field_id, body.name, body.fieldType,
                                body.label, body.position)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@app.delete("/api/types/{type_id}/fields/{field_id}")
async def remove_field(type_id: int, field_id: int):
    try:
        repo_types.remove_field(repo, field_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


# ---------------------------------------------------------------- 模板/AI 状态


@app.get("/api/templates")
def list_templates():
    return store.templates()


@app.get("/api/ai/status")
def ai_status():
    from .ai import llm as ai_llm

    return ai_llm.ai_status()


# ---------------------------------------------------------------- 图内容管线

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


async def _save_upload(fdir: Path, upload: UploadFile, default_name: str = "data.csv") -> str:
    name = Path(upload.filename or "").name
    if not name or name in {".", ".."}:
        name = default_name
    data = await upload.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="上传文件超过 10MB 限制")
    updir = fdir / "uploads"
    updir.mkdir(exist_ok=True)
    (updir / name).write_bytes(data)
    return name


@app.post("/api/figures/ai")
async def create_figure_ai(name: str = Form(...), requirements: str = Form(...),
                           groupId: int | None = Form(None),
                           data: UploadFile = File(...)):
    try:
        created = store.create_figure(name, origin="ai", group_id=groupId)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    item_id = created["id"]
    try:
        upload_name = await _save_upload(store.figure_dir(item_id), data)
    except HTTPException:
        store.delete_figure(item_id)  # 回滚刚建的空图
        raise
    result = await run_workflow(
        "create", store, item_id,
        {"requirements": requirements, "upload_name": upload_name},
    )
    result["id"] = item_id
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "item": item_id})
    return result


@app.post("/api/figures/adapt")
async def adapt_figure(name: str = Form(...), requirements: str = Form(""),
                       groupId: int | None = Form(None),
                       data: UploadFile = File(...),
                       script: UploadFile = File(...)):
    try:
        created = store.create_figure(name, origin="adapt", group_id=groupId)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    item_id = created["id"]
    try:
        upload_name = await _save_upload(store.figure_dir(item_id), data)
        script_name = await _save_upload(store.figure_dir(item_id), script,
                                         default_name="plot.py")
        script_text = (store.figure_dir(item_id) / "uploads" / script_name).read_text(
            encoding="utf-8", errors="replace")
    except HTTPException:
        store.delete_figure(item_id)  # 回滚刚建的空图
        raise
    result = await run_workflow(
        "adapt", store, item_id,
        {"requirements": requirements, "upload_name": upload_name,
         "script_text": script_text},
    )
    result["id"] = item_id
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "item": item_id})
    return result


@app.get("/api/figures/{item_id}")
def get_figure(item_id: str):
    _fdir_or_404(item_id)
    item = repo_items.get_item(repo, item_id)
    assert item is not None
    base = {
        "id": item_id,
        "name": item["name"],
        "properties": item["properties"],
        "groupIds": item["groupIds"],
        "tags": item["tags"],
        "patch": store.read_patch(item_id) or {"baseHash": "", "ops": []},
        "snapshots": store.snapshots(item_id),
    }
    if not (store.figure_dir(item_id) / "base.svg").exists():
        # 懒渲染：首次访问时渲染
        outcome = store.render(item_id)
        if not outcome.ok:
            return JSONResponse({
                **base, "code": _safe_code(item_id),
                "baseSvg": None, "finalSvg": None,
                "renderError": outcome.stderr,
            })
    return {
        **base,
        "code": _safe_code(item_id),
        "baseSvg": store.read_svg(item_id, "base"),
        "finalSvg": store.read_svg(item_id, "final"),
    }


def _safe_code(item_id: str) -> str | None:
    try:
        return store.read_code(item_id)
    except (OSError, ValueError):
        return None


@app.put("/api/figures/{item_id}/code")
async def put_code(item_id: str, body: CodePut):
    _fdir_or_404(item_id)
    outcome = await asyncio.to_thread(store.write_code, item_id, body.code)
    await _notify(
        {
            "type": "figure_updated" if outcome.ok else "render_error",
            "item": item_id,
            "stderr": outcome.stderr,
        }
    )
    return {
        "ok": outcome.ok,
        "stderr": outcome.stderr,
        "errorLine": outcome.error_line,
        "warnings": outcome.warnings or [],
        "stats": outcome.stats or {},
    }


@app.post("/api/figures/{item_id}/run")
async def run_figure(item_id: str):
    _fdir_or_404(item_id)
    outcome = await asyncio.to_thread(store.render, item_id)
    await _notify(
        {
            "type": "figure_updated" if outcome.ok else "render_error",
            "item": item_id,
            "stderr": outcome.stderr,
        }
    )
    return {
        "ok": outcome.ok,
        "stderr": outcome.stderr,
        "errorLine": outcome.error_line,
        "warnings": outcome.warnings or [],
        "stats": outcome.stats or {},
    }


@app.put("/api/figures/{item_id}/patch")
async def put_patch(item_id: str, body: dict):
    _fdir_or_404(item_id)
    if not isinstance(body, dict) or "ops" not in body:
        raise HTTPException(status_code=400, detail="patch 需为 {baseHash, ops} 结构")
    result = await asyncio.to_thread(store.save_patch, item_id, body)
    await _notify({"type": "figure_updated", "item": item_id})
    return result


@app.post("/api/figures/{item_id}/verify-patch")
async def verify_patch(item_id: str):
    _fdir_or_404(item_id)
    result = await asyncio.to_thread(store.verify_patch, item_id)
    await _notify({"type": "figure_updated", "item": item_id})
    return result


@app.post("/api/figures/{item_id}/snapshot")
async def snapshot(item_id: str, body: SnapshotPost):
    _fdir_or_404(item_id)
    return store.snapshot(item_id, body.note)


@app.get("/api/figures/{item_id}/runs")
def list_runs(item_id: str):
    _item_or_404(item_id)
    return repo_runs.list_runs(repo, item_id)


@app.get("/api/figures/{item_id}/files")
def list_files(item_id: str):
    _fdir_or_404(item_id)
    return store.read_files(item_id)


@app.post("/api/figures/{item_id}/instruct")
async def instruct(item_id: str, body: InstructPost):
    _fdir_or_404(item_id)
    code = _safe_code(item_id)
    if code is None:
        raise HTTPException(status_code=400, detail="图尚无 plot.py（首次 AI 运行未成功），无法执行指令")
    items = body.selection if isinstance(body.selection, list) else [body.selection]
    enriched = [
        enrich.enrich_selection(store, item_id, item) for item in items
    ]
    result = await run_workflow(
        "edit", store, item_id,
        {
            "instruction": body.instruction,
            "selection_json": json.dumps(enriched, ensure_ascii=False),
            "code": code,
        },
    )
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "item": item_id})
    return result


@app.post("/api/figures/{item_id}/writeback")
async def writeback(item_id: str):
    _fdir_or_404(item_id)
    result = await run_workflow("writeback", store, item_id, {})
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "item": item_id})
    return result


@app.post("/api/figures/{item_id}/enrich-selection")
async def enrich_selection_ep(item_id: str, body: SelectionPost):
    _fdir_or_404(item_id)
    items = body.selection if isinstance(body.selection, list) else [body.selection]
    enriched = [enrich.enrich_selection(store, item_id, item) for item in items]
    return enriched if isinstance(body.selection, list) else enriched[0]


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await hub.connect(ws)
    try:
        while True:
            # 客户端只收不发；ping 用来保活
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        hub.disconnect(ws)
    except Exception:
        hub.disconnect(ws)


# ---------------------------------------------------------------- 静态托管

DIST = config.web_dist_dir()
if (DIST / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="web")
else:

    @app.get("/", include_in_schema=False)
    def no_frontend():
        return HTMLResponse(
            "<h1>figure-agent 服务已启动</h1>"
            "<p>前端尚未构建：运行 <code>cd web && npm install && npm run build</code> 后重启服务。</p>"
            "<p>API 文档：<a href='/docs'>/docs</a></p>"
        )
```

注意：文件顶部需要 `import json`（instruct 用到）。`import sqlite3` 未用到可删。

- [ ] **Step 4: 运行 API 测试**

Run: `cd server && python -m pytest tests/test_api.py -v`
Expected: all passed

- [ ] **Step 5: server 全量回归**

Run: `cd server && python -m pytest -v`
Expected: all passed（含 svgkit 旧测试）

- [ ] **Step 6: Commit**

```bash
git add server/src/figure_agent/main.py server/tests/test_api.py
git commit -m "feat(api)!: 路由全面改 item_id 寻址，新增 items/groups/tags/types/repo 管理 API"
```

## Phase D — web 重构

### Task 10: types.ts + api.ts 重写

**Files:**
- Modify: `web/src/types.ts`（整文件替换）
- Modify: `web/src/api.ts`（整文件替换）

- [ ] **Step 1: types.ts 整文件替换**

```ts
// 共享类型定义（Index 仓库模式：条目 id 寻址）

export interface RepoInfo {
  path: string;
  itemCount: number;
  dbVersion: number;
}

export interface GroupInfo {
  id: number;
  parentId: number | null;
  name: string;
  position: number;
  boundItemId: number | null;
}

export interface TagInfo {
  id: number;
  name: string;
}

export interface FieldInfo {
  id: number;
  name: string;
  fieldType: "text" | "checkbox" | "date" | "number" | "dropdown" | "item";
  position: number;
  label: string;
  options: string[];
}

export interface TypeInfo {
  id: number;
  name: string;
  icon: string;
  fields: FieldInfo[];
}

export interface ItemInfo {
  id: string;
  name: string;
  typeName: string;
  groupIds: number[];
  tags: string[];
  properties: Record<string, string>;
  createdAt: string;
  updatedAt: string;
  hasBase?: boolean;
  lastRenderAt?: string | null;
  opCount?: number;
}

export interface FileInfo {
  path: string;
  isDir: boolean;
}

export interface TemplateInfo {
  id: string;
  title: string;
  description: string;
}

export interface TargetRef {
  id: string | null;
  semanticPath: string;
  fingerprint: string;
}

export type OpKind = "set_style" | "set_text" | "transform" | "set_visible" | "reorder";
export type OpStatus = "active" | "resolved" | "lost";

export interface Op {
  id: string;
  kind: OpKind;
  target: TargetRef;
  attr?: string;
  value?: any; // set_style/set_text: string; transform: {translate?, scale?}; set_visible: boolean; reorder: {to: "front"|"back"}
  intent: string;
  origin: "manual" | "ai";
  status: OpStatus;
  pre?: { center?: [number, number]; size?: [number, number] };
}

export interface PatchDoc {
  baseHash: string;
  ops: Op[];
}

export interface SnapshotInfo {
  id: string;
  note: string;
}

export interface FigureDetail {
  id: string;
  name: string;
  properties: Record<string, string>;
  groupIds: number[];
  tags: string[];
  code: string | null;
  baseSvg: string | null;
  finalSvg: string | null;
  patch: PatchDoc;
  snapshots: SnapshotInfo[];
  renderError?: string | null;
}

export interface RenderResult {
  ok: boolean;
  stderr: string;
  errorLine: number | null;
  warnings: string[];
  stats: {
    elementCount?: number;
    semanticGroupCount?: number;
    faGroups?: string[];
    matplotlibGroups?: string[];
  };
}

export interface SelectionJSON {
  elementId: string | null;
  semanticPath: string;
  userSpaceBBox?: { x: number; y: number; w: number; h: number };
  style?: { fill?: string | null; stroke?: string | null };
  text?: { content: string | null; fontFamily: string | null; fontSize: string | null };
  fingerprint?: string;
  nearby?: string[];
  item?: string;
  warnings?: string[];
}

export interface VerifyResponse {
  results: { opId: string; status: string; detail: string }[];
  remainingOps: number;
  cleared: boolean;
}

export interface AiStatus {
  configured: boolean;
  provider: string;
  model: string;
  mock: boolean;
  detail?: string;
}

export interface AiRunResult {
  id?: string;
  kind: "create" | "adapt" | "edit" | "writeback";
  ok: boolean;
  rounds: number;
  stderr: string;
  error_line?: number | null;
  notes?: string;
  cleared?: boolean;
  remaining?: number;
}

export interface RunEvent {
  runId: string;
  item?: string;
  phase: "run_start" | "run_end" | "node_start" | "node_end" | "node_failed" | "llm_start" | "llm_end";
  node?: string;
  detail?: string;
  ok?: boolean;
  at: number;
}
```

- [ ] **Step 2: api.ts 整文件替换**

```ts
// REST API 客户端（Index 仓库模式）

import type {
  AiRunResult,
  AiStatus,
  FieldInfo,
  FileInfo,
  FigureDetail,
  GroupInfo,
  ItemInfo,
  PatchDoc,
  RenderResult,
  RepoInfo,
  SelectionJSON,
  TagInfo,
  TemplateInfo,
  TypeInfo,
  VerifyResponse,
} from "./types";

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(`${resp.status}: ${detail}`);
  }
  return resp.json() as Promise<T>;
}

function req(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

export const api = {
  // ---- 仓库
  repoInfo: () => fetch("/api/repo/info").then((r) => json<RepoInfo>(r)),
  getRepoState: () =>
    fetch("/api/repo/state").then((r) => json<Record<string, unknown>>(r)),
  putRepoState: (patch: Record<string, unknown>) =>
    fetch("/api/repo/state", req("PUT", patch)).then((r) => json<Record<string, unknown>>(r)),

  // ---- 条目
  listItems: (params: { q?: string; groupId?: number | null; tagId?: number | null } = {}) => {
    const sp = new URLSearchParams();
    if (params.q) sp.set("q", params.q);
    if (params.groupId != null) sp.set("groupId", String(params.groupId));
    if (params.tagId != null) sp.set("tagId", String(params.tagId));
    const qs = sp.toString();
    return fetch(`/api/items${qs ? `?${qs}` : ""}`).then((r) => json<ItemInfo[]>(r));
  },
  createItem: (body: { name: string; groupId?: number | null; template?: string | null; origin?: string }) =>
    fetch("/api/items", req("POST", body)).then((r) =>
      json<{ id: string; name: string; ok: boolean; stderr: string }>(r)
    ),
  patchItem: (id: string, body: { name?: string; properties?: Record<string, string> }) =>
    fetch(`/api/items/${id}`, req("PATCH", body)).then((r) => json<ItemInfo>(r)),
  deleteItem: (id: string) =>
    fetch(`/api/items/${id}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  bindItemGroup: (id: string, groupId: number) =>
    fetch(`/api/items/${id}/groups`, req("POST", { id: groupId })).then((r) => json<{ ok: boolean }>(r)),
  unbindItemGroup: (id: string, groupId: number) =>
    fetch(`/api/items/${id}/groups?id=${groupId}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  bindItemTag: (id: string, tagId: number) =>
    fetch(`/api/items/${id}/tags`, req("POST", { id: tagId })).then((r) => json<{ ok: boolean }>(r)),
  unbindItemTag: (id: string, tagId: number) =>
    fetch(`/api/items/${id}/tags?id=${tagId}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),

  // ---- 分组 / 标签 / 类型
  listGroups: () => fetch("/api/groups").then((r) => json<GroupInfo[]>(r)),
  createGroup: (body: { name: string; parentId?: number | null; position?: number }) =>
    fetch("/api/groups", req("POST", body)).then((r) => json<GroupInfo>(r)),
  updateGroup: (id: number, body: { name?: string; parentId?: number | null; position?: number }) =>
    fetch(`/api/groups/${id}`, req("PATCH", body)).then((r) => json<GroupInfo>(r)),
  deleteGroup: (id: number) =>
    fetch(`/api/groups/${id}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  listTags: () => fetch("/api/tags").then((r) => json<TagInfo[]>(r)),
  createTag: (body: { name: string }) =>
    fetch("/api/tags", req("POST", body)).then((r) => json<TagInfo>(r)),
  deleteTag: (id: number) =>
    fetch(`/api/tags/${id}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  listTypes: () => fetch("/api/types").then((r) => json<TypeInfo[]>(r)),
  createType: (body: { name: string; icon?: string }) =>
    fetch("/api/types", req("POST", body)).then((r) => json<TypeInfo>(r)),
  deleteType: (id: number) =>
    fetch(`/api/types/${id}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),
  addField: (typeId: number, body: { name: string; fieldType?: string; label?: string }) =>
    fetch(`/api/types/${typeId}/fields`, req("POST", body)).then((r) => json<FieldInfo>(r)),
  updateField: (typeId: number, fieldId: number, body: { name?: string; fieldType?: string; label?: string; position?: number }) =>
    fetch(`/api/types/${typeId}/fields/${fieldId}`, req("PATCH", body)).then((r) => json<{ ok: boolean }>(r)),
  removeField: (typeId: number, fieldId: number) =>
    fetch(`/api/types/${typeId}/fields/${fieldId}`, { method: "DELETE" }).then((r) => json<{ ok: boolean }>(r)),

  // ---- 图内容
  listTemplates: () => fetch("/api/templates").then((r) => json<TemplateInfo[]>(r)),
  listFiles: (id: string) => fetch(`/api/figures/${id}/files`).then((r) => json<FileInfo[]>(r)),
  getFigure: (id: string) => fetch(`/api/figures/${id}`).then((r) => json<FigureDetail>(r)),
  putCode: (id: string, code: string) =>
    fetch(`/api/figures/${id}/code`, req("PUT", { code })).then((r) => json<RenderResult>(r)),
  run: (id: string) =>
    fetch(`/api/figures/${id}/run`, { method: "POST" }).then((r) => json<RenderResult>(r)),
  putPatch: (id: string, patch: PatchDoc) =>
    fetch(`/api/figures/${id}/patch`, req("PUT", patch)).then((r) => json<{ ok: boolean }>(r)),
  verifyPatch: (id: string) =>
    fetch(`/api/figures/${id}/verify-patch`, { method: "POST" }).then((r) => json<VerifyResponse>(r)),
  snapshot: (id: string, note: string) =>
    fetch(`/api/figures/${id}/snapshot`, req("POST", { note })).then((r) => json<{ id: string }>(r)),
  listRuns: (id: string) => fetch(`/api/figures/${id}/runs`).then((r) => json<unknown[]>(r)),

  // ---- AI
  aiStatus: () => fetch("/api/ai/status").then((r) => json<AiStatus>(r)),
  createFigureAi: (name: string, requirements: string, groupId: number | null, data: File) => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("requirements", requirements);
    if (groupId != null) fd.append("groupId", String(groupId));
    fd.append("data", data);
    return fetch("/api/figures/ai", { method: "POST", body: fd }).then((r) => json<AiRunResult>(r));
  },
  adaptFigure: (name: string, requirements: string, groupId: number | null, data: File, script: File) => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("requirements", requirements);
    if (groupId != null) fd.append("groupId", String(groupId));
    fd.append("data", data);
    fd.append("script", script);
    return fetch("/api/figures/adapt", { method: "POST", body: fd }).then((r) => json<AiRunResult>(r));
  },
  instruct: (id: string, instruction: string, selection: object | object[]) =>
    fetch(`/api/figures/${id}/instruct`, req("POST", { instruction, selection })).then((r) =>
      json<AiRunResult>(r)
    ),
  writebackPatch: (id: string) =>
    fetch(`/api/figures/${id}/writeback`, { method: "POST" }).then((r) => json<AiRunResult>(r)),
  enrichSelection: (id: string, selection: object | object[]) =>
    fetch(`/api/figures/${id}/enrich-selection`, req("POST", { selection })).then((r) =>
      json<SelectionJSON>(r)
    ),
};
```

- [ ] **Step 3: 类型检查**

Run: `cd web && npx tsc --noEmit`
Expected: 报 `App.tsx`/`AIPanel.tsx`/`Sidebar.tsx` 的旧接口错误——属预期，下一任务修复；`api.ts`/`types.ts` 自身无错。

- [ ] **Step 4: Commit（与 Task 11 一起提交也可；此处单独提交）**

```bash
git add web/src/types.ts web/src/api.ts
git commit -m "feat(web)!: types/api 重写为 Index 仓库 id 寻址契约"
```

### Task 11: manage 管理视图组件 + 样式

**Files:**
- Create: `web/src/components/manage/ManageView.tsx`
- Create: `web/src/components/manage/GroupSidebar.tsx`
- Create: `web/src/components/manage/FigureList.tsx`
- Create: `web/src/components/manage/DetailPanel.tsx`
- Create: `web/src/components/manage/TypePanel.tsx`
- Create: `web/src/components/manage/CreateDialog.tsx`
- Modify: `web/src/styles.css`（末尾追加）
- Test: `web/src/components/manage/ManageView.test.tsx`

- [ ] **Step 1: ManageView.tsx**

```tsx
// 管理视图：Index 风格三栏（左分组+标签 / 中图列表 / 右详情·类型）+ 顶栏。

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import type { FileInfo, GroupInfo, ItemInfo, TagInfo, TypeInfo } from "../../types";
import { CreateDialog } from "./CreateDialog";
import { DetailPanel } from "./DetailPanel";
import { FigureList } from "./FigureList";
import { GroupSidebar } from "./GroupSidebar";
import { TypePanel } from "./TypePanel";

interface Props {
  onOpen: (id: string, name: string) => void;
}

export function ManageView({ onOpen }: Props) {
  const [items, setItems] = useState<ItemInfo[]>([]);
  const [groups, setGroups] = useState<GroupInfo[]>([]);
  const [tags, setTags] = useState<TagInfo[]>([]);
  const [types, setTypes] = useState<TypeInfo[]>([]);
  const [files, setFiles] = useState<FileInfo[]>([]);
  const [q, setQ] = useState("");
  const [groupId, setGroupId] = useState<number | null>(null);
  const [tagId, setTagId] = useState<number | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [rightTab, setRightTab] = useState<"detail" | "types">("detail");
  const [creating, setCreating] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [toast, setToast] = useState<string | null>(null);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(null), 2600);
  }, []);

  const refresh = useCallback(() => {
    api.listItems({ q, groupId, tagId }).then(setItems).catch(() => undefined);
  }, [q, groupId, tagId]);

  const refreshMeta = useCallback(() => {
    api.listGroups().then(setGroups).catch(() => undefined);
    api.listTags().then(setTags).catch(() => undefined);
    api.listTypes().then(setTypes).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);
  useEffect(() => {
    refreshMeta();
    api.getRepoState().then((s) => {
      const t = s.theme === "dark" ? "dark" : "light";
      document.documentElement.classList.toggle("dark", t === "dark");
      setTheme(t);
    }).catch(() => undefined);
  }, [refreshMeta]);

  useEffect(() => {
    if (!selected) {
      setFiles([]);
      return;
    }
    api.listFiles(selected).then(setFiles).catch(() => setFiles([]));
  }, [selected, items]);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    setTheme(next);
    api.putRepoState({ theme: next }).catch(() => undefined);
  };

  const selectedItem = items.find((i) => i.id === selected) ?? null;

  return (
    <div className="manage">
      <div className="topbar">
        <b>figure-agent</b>
        <span className="hint">{items.length} 张图</span>
        <span className="spacer" />
        <button className="primary" onClick={() => setCreating(true)}>＋ 新建图</button>
        <button onClick={toggleTheme}>{theme === "dark" ? "亮色" : "暗色"}</button>
      </div>
      <GroupSidebar
        groups={groups}
        tags={tags}
        q={q}
        onSearch={setQ}
        activeGroupId={groupId}
        activeTagId={tagId}
        onSelectGroup={(gid) => { setGroupId(gid); setTagId(null); }}
        onSelectTag={(tid) => { setTagId(tid); setGroupId(null); }}
        onCreateGroup={(name, parentId) =>
          api.createGroup({ name, parentId }).then(refreshMeta).then(refresh)}
        onRenameGroup={(id, name) => api.updateGroup(id, { name }).then(refreshMeta)}
        onDeleteGroup={(id) => api.deleteGroup(id).then(refreshMeta).then(refresh)}
        onDropItem={(itemId, gid) =>
          api.bindItemGroup(itemId, gid).then(refresh).then(() => showToast("已移入分组"))}
        onCreateTag={(name) => api.createTag({ name }).then(refreshMeta)}
        onDeleteTag={(id) => api.deleteTag(id).then(refreshMeta)}
      />
      <FigureList
        items={items}
        selectedId={selected}
        onSelect={setSelected}
        onOpen={(item) => onOpen(item.id, item.name)}
        onRename={(item, name) => api.patchItem(item.id, { name }).then(refresh)}
        onDelete={(item) => api.deleteItem(item.id).then(refresh).then(refreshMeta)}
      />
      <div className="rightcol">
        <div className="righttabs">
          <button className={rightTab === "detail" ? "active" : ""} onClick={() => setRightTab("detail")}>详情</button>
          <button className={rightTab === "types" ? "active" : ""} onClick={() => setRightTab("types")}>类型</button>
        </div>
        {rightTab === "detail" ? (
          <DetailPanel
            item={selectedItem}
            groups={groups}
            tags={tags}
            types={types}
            files={files}
            onChanged={refresh}
            onOpen={(item) => onOpen(item.id, item.name)}
            showToast={showToast}
          />
        ) : (
          <TypePanel types={types} onChanged={refreshMeta} showToast={showToast} />
        )}
      </div>
      {creating && (
        <CreateDialog
          groups={groups}
          onClose={() => setCreating(false)}
          onCreated={(item, open) => {
            setCreating(false);
            refresh();
            refreshMeta();
            if (open) onOpen(item.id, item.name);
          }}
          showToast={showToast}
        />
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}
```

- [ ] **Step 2: GroupSidebar.tsx**

```tsx
// 左栏：搜索 + 分组树（多级、拖拽入组）+ 扁平标签。删除均为两击确认。

import { useState } from "react";
import type { GroupInfo, TagInfo } from "../../types";

interface Props {
  groups: GroupInfo[];
  tags: TagInfo[];
  q: string;
  onSearch: (q: string) => void;
  activeGroupId: number | null;
  activeTagId: number | null;
  onSelectGroup: (id: number | null) => void;
  onSelectTag: (id: number | null) => void;
  onCreateGroup: (name: string, parentId: number | null) => void;
  onRenameGroup: (id: number, name: string) => void;
  onDeleteGroup: (id: number) => void;
  onDropItem: (itemId: string, groupId: number) => void;
  onCreateTag: (name: string) => void;
  onDeleteTag: (id: number) => void;
}

export function GroupSidebar(props: Props) {
  const [newGroup, setNewGroup] = useState("");
  const [newTag, setNewTag] = useState("");
  const roots = props.groups.filter((g) => g.parentId === null);

  return (
    <div className="gsidebar">
      <input
        type="text"
        className="search"
        placeholder="搜索图…"
        value={props.q}
        onChange={(e) => props.onSearch(e.target.value)}
      />

      <h2>分组</h2>
      <div className="group-node">
        <div
          className={`group-row ${props.activeGroupId === null ? "active" : ""}`}
          onClick={() => props.onSelectGroup(null)}
        >
          全部 / 未分组
        </div>
      </div>
      {roots.map((g) => (
        <GroupNode key={g.id} group={g} {...props} depth={0} />
      ))}
      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
        <input
          type="text"
          placeholder="新建分组"
          value={newGroup}
          onChange={(e) => setNewGroup(e.target.value)}
        />
        <button
          className="small"
          disabled={!newGroup.trim()}
          onClick={() => {
            props.onCreateGroup(newGroup.trim(), null);
            setNewGroup("");
          }}
        >
          ＋
        </button>
      </div>

      <h2>标签</h2>
      {props.tags.map((t) => (
        <TagRow
          key={t.id}
          tag={t}
          active={props.activeTagId === t.id}
          onSelect={() => props.onSelectTag(props.activeTagId === t.id ? null : t.id)}
          onDelete={() => props.onDeleteTag(t.id)}
        />
      ))}
      <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
        <input
          type="text"
          placeholder="新建标签"
          value={newTag}
          onChange={(e) => setNewTag(e.target.value)}
        />
        <button
          className="small"
          disabled={!newTag.trim()}
          onClick={() => {
            props.onCreateTag(newTag.trim());
            setNewTag("");
          }}
        >
          ＋
        </button>
      </div>
    </div>
  );
}

function GroupNode(props: Props & { group: GroupInfo; depth: number }) {
  const { group } = props;
  const [renaming, setRenaming] = useState(false);
  const [addingChild, setAddingChild] = useState(false);
  const [name, setName] = useState(group.name);
  const [confirmDel, setConfirmDel] = useState(false);
  const [drop, setDrop] = useState(false);
  const kids = props.groups.filter((g) => g.parentId === group.id);

  return (
    <div className="group-node">
      <div
        className={`group-row ${props.activeGroupId === group.id ? "active" : ""} ${drop ? "drop" : ""}`}
        onClick={() => props.onSelectGroup(group.id)}
        draggable={false}
        onDragOver={(e) => {
          e.preventDefault();
          setDrop(true);
        }}
        onDragLeave={() => setDrop(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrop(false);
          const itemId = e.dataTransfer.getData("text/plain");
          if (itemId) props.onDropItem(itemId, group.id);
        }}
      >
        📁 {renaming ? (
          <input
            autoFocus
            value={name}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => {
              setRenaming(false);
              if (name.trim() && name !== group.name) props.onRenameGroup(group.id, name.trim());
            }}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          />
        ) : (
          <span>{group.name}</span>
        )}
        <span className="spacer" />
        <button className="gbtn" title="重命名" onClick={(e) => { e.stopPropagation(); setRenaming(true); }}>✎</button>
        <button className="gbtn" title="加子分组" onClick={(e) => { e.stopPropagation(); setAddingChild(true); }}>＋</button>
        <button
          className="gbtn"
          title="删除分组"
          onClick={(e) => {
            e.stopPropagation();
            if (confirmDel) props.onDeleteGroup(group.id);
            else {
              setConfirmDel(true);
              window.setTimeout(() => setConfirmDel(false), 2000);
            }
          }}
        >
          {confirmDel ? "确认?" : "🗑"}
        </button>
      </div>
      {addingChild && (
        <div className="group-kids">
          <input
            autoFocus
            placeholder="子分组名"
            onBlur={(e) => {
              if (e.target.value.trim()) props.onCreateGroup(e.target.value.trim(), group.id);
              setAddingChild(false);
            }}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          />
        </div>
      )}
      {kids.length > 0 && (
        <div className="group-kids">
          {kids.map((k) => (
            <GroupNode key={k.id} group={k} {...props} depth={props.depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

function TagRow(props: { tag: TagInfo; active: boolean; onSelect: () => void; onDelete: () => void }) {
  const [confirmDel, setConfirmDel] = useState(false);
  return (
    <div className={`group-row ${props.active ? "active" : ""}`} onClick={props.onSelect}>
      🏷 <span>{props.tag.name}</span>
      <span className="spacer" />
      <button
        className="gbtn"
        onClick={(e) => {
          e.stopPropagation();
          if (confirmDel) props.onDelete();
          else {
            setConfirmDel(true);
            window.setTimeout(() => setConfirmDel(false), 2000);
          }
        }}
      >
        {confirmDel ? "确认?" : "🗑"}
      </button>
    </div>
  );
}
```

- [ ] **Step 3: FigureList.tsx**

```tsx
// 中栏：图列表。行内重命名、两击删除、双击打开；行可拖拽入分组。

import { useState } from "react";
import type { ItemInfo } from "../../types";

interface Props {
  items: ItemInfo[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onOpen: (item: ItemInfo) => void;
  onRename: (item: ItemInfo, name: string) => void;
  onDelete: (item: ItemInfo) => void;
}

export function FigureList(props: Props) {
  return (
    <div className="figlist">
      {props.items.length === 0 && <div className="hint">没有图。点右上「＋ 新建图」。</div>}
      {props.items.map((item) => (
        <FigRow key={item.id} item={item} {...props} />
      ))}
    </div>
  );
}

function FigRow(props: {
  item: ItemInfo;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onOpen: (item: ItemInfo) => void;
  onRename: (item: ItemInfo, name: string) => void;
  onDelete: (item: ItemInfo) => void;
}) {
  const { item } = props;
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(item.name);
  const [confirmDel, setConfirmDel] = useState(false);

  return (
    <div
      className={`figrow ${props.selectedId === item.id ? "active" : ""}`}
      draggable
      onDragStart={(e) => e.dataTransfer.setData("text/plain", item.id)}
      onClick={() => props.onSelect(item.id)}
      onDoubleClick={() => props.onOpen(item)}
    >
      <span title={item.id}>📊</span>
      {renaming ? (
        <input
          autoFocus
          value={name}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            setRenaming(false);
            if (name.trim() && name !== item.name) props.onRename(item, name.trim());
          }}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        />
      ) : (
        <b>{item.name}</b>
      )}
      {item.tags.map((t) => (
        <span key={t} className="chip">{t}</span>
      ))}
      {(item.opCount ?? 0) > 0 && <span className="chip">{item.opCount} 微调</span>}
      <span className="spacer" />
      <span className="meta">{item.hasBase === false ? "未渲染" : ""}</span>
      <button className="small" onClick={(e) => { e.stopPropagation(); props.onOpen(item); }}>打开</button>
      <button className="small" onClick={(e) => { e.stopPropagation(); setRenaming(true); }}>重命名</button>
      <button
        className="small"
        onClick={(e) => {
          e.stopPropagation();
          if (confirmDel) props.onDelete(item);
          else {
            setConfirmDel(true);
            window.setTimeout(() => setConfirmDel(false), 2000);
          }
        }}
      >
        {confirmDel ? "确认删除?" : "删除"}
      </button>
    </div>
  );
}
```

- [ ] **Step 4: DetailPanel.tsx**

```tsx
// 右栏详情：行内重命名、按「图」字段渲染属性表单、分组/标签 chips、文件树。

import { useEffect, useState } from "react";
import { api } from "../../api";
import type { FileInfo, GroupInfo, ItemInfo, TagInfo, TypeInfo } from "../../types";

interface Props {
  item: ItemInfo | null;
  groups: GroupInfo[];
  tags: TagInfo[];
  types: TypeInfo[];
  files: FileInfo[];
  onChanged: () => void;
  onOpen: (item: ItemInfo) => void;
  showToast: (msg: string) => void;
}

export function DetailPanel(props: Props) {
  const { item } = props;
  const figureType = props.types.find((t) => t.name === "图");
  const [props_, setProps] = useState<Record<string, string>>({});

  useEffect(() => {
    setProps(item?.properties ?? {});
  }, [item?.id, item?.properties]);

  if (!item) {
    return (
      <div className="detail">
        <div className="hint">选中一张图查看详情。</div>
      </div>
    );
  }

  const saveProps = () => {
    api.patchItem(item.id, { properties: props_ })
      .then(props.onChanged)
      .then(() => props.showToast("属性已保存"))
      .catch((e) => props.showToast(`保存失败：${(e as Error).message}`));
  };

  const groupNames = item.groupIds
    .map((gid) => props.groups.find((g) => g.id === gid)?.name ?? `#${gid}`);
  const addableGroups = props.groups.filter((g) => !item.groupIds.includes(g.id));
  const addableTags = props.tags.filter((t) => !item.tags.includes(t.name));

  return (
    <div className="detail">
      <h3 style={{ margin: 0 }}>{item.name}</h3>
      <div className="hint" title={item.id}>{item.id} · 更新 {item.updatedAt.slice(0, 19)}</div>
      <button className="primary" onClick={() => props.onOpen(item)}>打开编辑器</button>

      <section>
        <h4>属性</h4>
        {(figureType?.fields ?? []).map((f) => (
          <label key={f.id} style={{ display: "block", marginBottom: 6 }}>
            {f.label || f.name}
            <input
              type="text"
              style={{ width: "100%" }}
              value={props_[f.name] ?? ""}
              onChange={(e) => setProps({ ...props_, [f.name]: e.target.value })}
            />
          </label>
        ))}
        <button className="small" onClick={saveProps}>保存属性</button>
      </section>

      <section>
        <h4>分组</h4>
        <div className="chips">
          {groupNames.map((name, i) => (
            <span key={i} className="chip">
              {name}
              <button
                onClick={() =>
                  api.unbindItemGroup(item.id, item.groupIds[i]).then(props.onChanged)}
              >
                ×
              </button>
            </span>
          ))}
          {addableGroups.map((g) => (
            <button key={g.id} className="small" onClick={() => api.bindItemGroup(item.id, g.id).then(props.onChanged)}>
              ＋{g.name}
            </button>
          ))}
        </div>
      </section>

      <section>
        <h4>标签</h4>
        <div className="chips">
          {item.tags.map((name) => {
            const tag = props.tags.find((t) => t.name === name);
            return (
              <span key={name} className="chip">
                {name}
                <button onClick={() => tag && api.unbindItemTag(item.id, tag.id).then(props.onChanged)}>×</button>
              </span>
            );
          })}
          {addableTags.map((t) => (
            <button key={t.id} className="small" onClick={() => api.bindItemTag(item.id, t.id).then(props.onChanged)}>
              ＋{t.name}
            </button>
          ))}
        </div>
      </section>

      <section>
        <h4>文件</h4>
        <div className="filetree">
          {props.files.map((f) => (
            <div key={f.path} style={{ paddingLeft: (f.path.split("/").length - 1) * 14 }}>
              {f.isDir ? "📁" : "📄"} {f.path.split("/").pop()}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 5: TypePanel.tsx**

```tsx
// 类型管理：字段增删改标签；新建类型（预设型保护由服务端兜底）。

import { useState } from "react";
import { api } from "../../api";
import type { TypeInfo } from "../../types";

interface Props {
  types: TypeInfo[];
  onChanged: () => void;
  showToast: (msg: string) => void;
}

const FIELD_TYPES = ["text", "checkbox", "date", "number", "dropdown", "item"] as const;

export function TypePanel(props: Props) {
  const [newType, setNewType] = useState("");
  const [fieldName, setFieldName] = useState("");
  const [fieldKind, setFieldKind] = useState<string>("text");

  return (
    <div className="detail">
      {props.types.map((t) => (
        <section key={t.id}>
          <h4>{t.icon === "chart-bar" ? "📊" : "📄"} {t.name} {t.id <= 2 && <span className="hint">（预设）</span>}</h4>
          {t.fields.map((f) => (
            <div key={f.id} className="figrow" style={{ padding: "4px 8px" }}>
              <span>{f.name}</span>
              <span className="meta">{f.fieldType}</span>
              <span className="spacer" />
              <button
                className="small"
                onClick={() =>
                  api.removeField(t.id, f.id).then(props.onChanged).catch((e) => props.showToast((e as Error).message))}
              >
                删除
              </button>
            </div>
          ))}
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <input
              placeholder="新字段名"
              value={fieldName}
              onChange={(e) => setFieldName(e.target.value)}
            />
            <select value={fieldKind} onChange={(e) => setFieldKind(e.target.value)}>
              {FIELD_TYPES.map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
            <button
              className="small"
              disabled={!fieldName.trim()}
              onClick={() =>
                api.addField(t.id, { name: fieldName.trim(), fieldType: fieldKind })
                  .then(() => setFieldName(""))
                  .then(props.onChanged)
                  .catch((e) => props.showToast((e as Error).message))}
            >
              ＋ 字段
            </button>
          </div>
          {t.id > 2 && (
            <button
              className="small"
              style={{ marginTop: 6 }}
              onClick={() => api.deleteType(t.id).then(props.onChanged).catch((e) => props.showToast((e as Error).message))}
            >
              删除该类型
            </button>
          )}
        </section>
      ))}
      <section>
        <h4>新建类型</h4>
        <div style={{ display: "flex", gap: 6 }}>
          <input placeholder="类型名" value={newType} onChange={(e) => setNewType(e.target.value)} />
          <button
            className="small"
            disabled={!newType.trim()}
            onClick={() => api.createType({ name: newType.trim() }).then(() => setNewType("")).then(props.onChanged)}
          >
            创建
          </button>
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 6: CreateDialog.tsx**

```tsx
// 新建图对话框：模板 / AI 造图 / AI 改造 三个 tab。

import { useEffect, useState } from "react";
import { api } from "../../api";
import type { GroupInfo, ItemInfo, TemplateInfo } from "../../types";

interface Props {
  groups: GroupInfo[];
  onClose: () => void;
  onCreated: (item: { id: string; name: string }, open: boolean) => void;
  showToast: (msg: string) => void;
}

type Tab = "template" | "ai" | "adapt";

export function CreateDialog(props: Props) {
  const [tab, setTab] = useState<Tab>("template");
  const [name, setName] = useState("");
  const [groupId, setGroupId] = useState<number | null>(null);
  const [templates, setTemplates] = useState<TemplateInfo[]>([]);
  const [template, setTemplate] = useState("bar-groups");
  const [requirements, setRequirements] = useState("");
  const [dataFile, setDataFile] = useState<File | null>(null);
  const [scriptFile, setScriptFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.listTemplates().then((ts) => {
      setTemplates(ts);
      if (ts[0]) setTemplate(ts[0].id);
    }).catch(() => undefined);
  }, []);

  const disabled = busy || !name.trim() || (tab !== "template" && !dataFile);

  const finish = (r: { id?: string; ok: boolean; stderr: string }) => {
    if (r.id) {
      props.onCreated({ id: r.id, name: name.trim() }, r.ok);
      if (!r.ok) props.showToast(`已建图但渲染/AI 失败：${r.stderr.slice(0, 120)}`);
    } else {
      props.showToast(`失败：${r.stderr.slice(0, 160)}`);
    }
  };

  const submit = async () => {
    setBusy(true);
    try {
      if (tab === "template") {
        finish(await api.createItem({ name: name.trim(), template, groupId }));
      } else if (tab === "ai" && dataFile) {
        finish(await api.createFigureAi(name.trim(), requirements, groupId, dataFile));
      } else if (tab === "adapt" && dataFile && scriptFile) {
        finish(await api.adaptFigure(name.trim(), requirements, groupId, dataFile, scriptFile));
      }
    } catch (e) {
      props.showToast(`失败：${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="dialog-backdrop" onClick={props.onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <div className="righttabs">
          {(["template", "ai", "adapt"] as Tab[]).map((t) => (
            <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
              {t === "template" ? "模板" : t === "ai" ? "AI 造图" : "AI 改造"}
            </button>
          ))}
        </div>
        <label>
          图名
          <input style={{ width: "100%" }} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          分组
          <select
            value={groupId ?? ""}
            onChange={(e) => setGroupId(e.target.value === "" ? null : Number(e.target.value))}
          >
            <option value="">未分组</option>
            {props.groups.map((g) => (
              <option key={g.id} value={g.id}>{g.name}</option>
            ))}
          </select>
        </label>
        {tab === "template" && (
          <label>
            模板
            <select value={template} onChange={(e) => setTemplate(e.target.value)}>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>{t.title}</option>
              ))}
            </select>
          </label>
        )}
        {tab !== "template" && (
          <>
            <textarea
              placeholder="绘图要求（自然语言）"
              value={requirements}
              onChange={(e) => setRequirements(e.target.value)}
            />
            <input type="file" accept=".csv,.tsv,.txt,.xlsx,.xls,.json"
                   onChange={(e) => setDataFile(e.target.files?.[0] ?? null)} />
          </>
        )}
        {tab === "adapt" && (
          <input type="file" accept=".py"
                 onChange={(e) => setScriptFile(e.target.files?.[0] ?? null)} />
        )}
        <div style={{ display: "flex", gap: 8 }}>
          <button className="primary" disabled={disabled} onClick={submit}>
            {busy ? "进行中…" : tab === "template" ? "创建" : "开始生成"}
          </button>
          <button onClick={props.onClose}>取消</button>
        </div>
      </div>
    </div>
  );
}
```

注意：`ItemInfo` 导入未用到可删（保持 tsc 无 unused 报错——若 tsconfig 开了 noUnusedLocals 则删除未用导入）。

- [ ] **Step 7: styles.css 末尾追加**

```css
/* ===== Index 管理壳（manage view）===== */
html.dark {
  --bg: #16181d;
  --panel: #20232a;
  --border: #333842;
  --text: #e8ebf0;
  --text-dim: #9aa3ad;
  --accent: #5b9dff;
  --accent-soft: #1d3557;
}
html.dark .fig-item:hover { background: #2a2f38; }
html.dark .toast { background: #2a2f38; color: var(--text); }

.manage {
  display: grid;
  grid-template-columns: 250px 1fr 360px;
  grid-template-rows: 48px 1fr;
  height: 100%;
}
.manage .topbar {
  grid-column: 1 / 4;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  background: var(--panel);
  border-bottom: 1px solid var(--border);
}
.spacer { flex: 1; }

.gsidebar {
  background: var(--panel);
  border-right: 1px solid var(--border);
  overflow-y: auto;
  padding: 10px;
}
.gsidebar .search { width: 100%; margin-bottom: 6px; }
.group-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 6px;
  cursor: pointer;
}
.group-row:hover, .group-row.drop { background: #eef2f7; }
html.dark .group-row:hover, html.dark .group-row.drop { background: #2a2f38; }
.group-row.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.group-kids { margin-left: 14px; border-left: 1px solid var(--border); padding-left: 4px; }
.gbtn { border: 0; background: transparent; cursor: pointer; color: var(--text-dim); font-size: 11px; padding: 0 2px; }
.gbtn:hover { color: var(--text); }

.figlist { overflow-y: auto; padding: 10px; }
.figrow {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 6px;
  cursor: pointer;
  background: var(--panel);
}
.figrow:hover { border-color: var(--accent); }
.figrow.active { outline: 2px solid var(--accent); }
.figrow .meta { color: var(--text-dim); font-size: 12px; }
.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #e5e7eb;
  border-radius: 10px;
  padding: 1px 8px;
  font-size: 12px;
}
html.dark .chip { background: #333842; }
.chip button { border: 0; background: transparent; cursor: pointer; color: inherit; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }

.rightcol {
  border-left: 1px solid var(--border);
  background: var(--panel);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.righttabs { display: flex; border-bottom: 1px solid var(--border); }
.righttabs button {
  flex: 1;
  border: 0;
  background: transparent;
  padding: 8px;
  cursor: pointer;
  color: var(--text-dim);
  border-bottom: 2px solid transparent;
}
.righttabs button.active { color: var(--accent); border-bottom-color: var(--accent); font-weight: 600; }

.detail { padding: 12px; display: flex; flex-direction: column; gap: 12px; }
.filetree { font-family: ui-monospace, Consolas, monospace; font-size: 12px; color: var(--text-dim); }

.dialog-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: grid;
  place-items: center;
  z-index: 50;
}
.dialog {
  background: var(--panel);
  border-radius: 10px;
  padding: 16px;
  width: 460px;
  max-height: 80vh;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 编辑器视图：去左栏，三栏 */
.app.editor { grid-template-columns: 1fr 300px 320px; }
```

- [ ] **Step 8: Commit**

```bash
git add web/src/components/manage web/src/styles.css
git commit -m "feat(web): Index 风格管理视图（分组树/标签/列表/详情/类型/新建对话框）"
```

### Task 12: App.tsx 双视图 + AIPanel 改造 + 删除 Sidebar

**Files:**
- Modify: `web/src/App.tsx`（整文件替换）
- Modify: `web/src/components/AIPanel.tsx`（整文件替换）
- Delete: `web/src/components/Sidebar.tsx`

- [ ] **Step 1: App.tsx 整文件替换**

```tsx
// App：双视图编排。管理视图（Index 三栏）/ 编辑器视图（画布+AI+微调）。
// 编辑器逻辑与旧版一致，仅寻址从 (project, figure) 改为 item id。

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { Viewer, type ElementNode } from "./components/Viewer";
import { EditorPanel } from "./components/EditorPanel";
import { AIPanel } from "./components/AIPanel";
import { ManageView } from "./components/manage/ManageView";
import type { FigureDetail, Op, RunEvent, SelectionJSON, VerifyResponse } from "./types";

interface HistoryEntry {
  ops: Op[];
  label: string;
}

export default function App() {
  const [target, setTarget] = useState<{ id: string; name: string } | null>(null);
  if (!target) return <ManageView onOpen={(id, name) => setTarget({ id, name })} />;
  return <EditorApp target={target} onBack={() => setTarget(null)} />;
}

function EditorApp({ target, onBack }: { target: { id: string; name: string }; onBack: () => void }) {
  const [detail, setDetail] = useState<FigureDetail | null>(null);
  const [ops, setOps] = useState<Op[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [histIdx, setHistIdx] = useState(-1);
  const [selections, setSelections] = useState<SelectionJSON[]>([]);
  const [selectionPaths, setSelectionPaths] = useState<string[]>([]);
  const [preciseMode, setPreciseMode] = useState(false);
  const [showBase, setShowBase] = useState(false);
  const [lastVerify, setLastVerify] = useState<VerifyResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<{ msg: string; error?: boolean } | null>(null);
  const [wsOnline, setWsOnline] = useState(false);
  const [staleServer, setStaleServer] = useState(false);
  const [elements, setElements] = useState<ElementNode[]>([]);
  const [selectReq, setSelectReq] = useState<{ path: string; nonce: number } | null>(null);
  const [aiEvents, setAiEvents] = useState<RunEvent[]>([]);
  const [runActive, setRunActive] = useState(false);
  const stateRef = useRef({ id: target.id, dirty: false });
  // dirty = 本地 ops 与服务器 patch 不一致（保存按钮/WS 自动刷新共用此语义）
  const dirty = JSON.stringify(ops) !== JSON.stringify(detail?.patch.ops ?? []);
  stateRef.current = { id: target.id, dirty };

  const showToast = useCallback((msg: string, error = false) => {
    setToast({ msg, error });
    window.setTimeout(() => setToast(null), 3200);
  }, []);

  // ---- 图详情加载 ----
  const loadFigure = useCallback(
    async (id: string, keepOps = false) => {
      try {
        const d = await api.getFigure(id);
        if (stateRef.current.id !== id) return; // 守卫：响应期间已切图 → 丢弃过期响应
        setDetail(d);
        if (!keepOps) {
          setOps(d.patch.ops ?? []);
          setHistory([{ ops: d.patch.ops ?? [], label: "服务器版本" }]);
          setHistIdx(0);
          setLastVerify(null);
        }
        setStaleServer(false);
      } catch (e) {
        showToast(`加载失败：${(e as Error).message}`, true);
      }
    },
    [showToast]
  );

  useEffect(() => {
    setSelections([]);
    setSelectionPaths([]);
    setElements([]);
    loadFigure(target.id);
  }, [target.id, loadFigure]);

  // ---- WS 自动刷新 + 轮询降级 ----
  const detailRef = useRef<FigureDetail | null>(null);
  detailRef.current = detail;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let poll: number | null = null;
    let closed = false;

    const handleEvent = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === "ai_run") {
          setAiEvents((prev) => [...prev.slice(-199), { at: Date.now(), ...data }]);
          if (data.phase === "run_end") {
            setRunActive(false);
            const id = stateRef.current.id;
            if (id && (!data.item || data.item === id)) {
              loadFigure(id, stateRef.current.dirty);
            }
          }
          return;
        }
        const id = stateRef.current.id;
        if (!id) return;
        if (data.type === "figure_updated" && data.item === id) {
          if (stateRef.current.dirty) setStaleServer(true);
          else loadFigure(id);
        }
        if (data.type === "figure_deleted" && data.item === id) {
          showToast("该图已被删除", true);
          onBack();
        }
      } catch {
        /* ignore */
      }
    };

    const connect = () => {
      if (closed) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.onopen = () => {
        setWsOnline(true);
        setRunActive(false);
        if (poll) {
          window.clearInterval(poll);
          poll = null;
        }
      };
      ws.onmessage = handleEvent;
      ws.onclose = () => {
        setWsOnline(false);
        if (!closed && !poll) {
          // 降级轮询（WS 断连）
          poll = window.setInterval(() => {
            const id = stateRef.current.id;
            if (!id) return;
            api
              .getFigure(id)
              .then((d) => {
                const fresh = JSON.stringify(d.patch) !== JSON.stringify(detailRef.current?.patch);
                if (fresh && !stateRef.current.dirty) loadFigure(id);
              })
              .catch(() => undefined);
          }, 3000);
        }
        if (!closed) window.setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      closed = true;
      if (poll) window.clearInterval(poll);
      ws?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- ops 编辑（undo/redo 栈）----
  const pushHistory = useCallback((next: Op[], label: string) => {
    setHistory((h) => {
      const trimmed = h.slice(0, histIdxRef.current + 1);
      return [...trimmed, { ops: next, label }];
    });
    setHistIdx((i) => i + 1);
    setOps(next);
  }, []);

  const histIdxRef = useRef(0);
  histIdxRef.current = histIdx;

  const addOps = useCallback(
    (newOps: Op[]) => {
      // set_visible / reorder 是状态型 op：同目标同 kind 的新 op 替换旧 op，不堆积
      const replaceable = new Set(["set_visible", "reorder"]);
      const incoming = new Set(newOps.filter((o) => replaceable.has(o.kind)).map((o) => `${o.kind}|${o.target.id}`));
      const kept = ops.filter((o) => !(replaceable.has(o.kind) && incoming.has(`${o.kind}|${o.target.id}`)));
      pushHistory([...kept, ...newOps], "edit");
    },
    [ops, pushHistory]
  );

  const updateOp = useCallback(
    (id: string, patch: Partial<Op>) => {
      const next = ops.map((o) => (o.id === id ? { ...o, ...patch } : o));
      // 意图编辑不进 undo 栈（避免每次按键一条）
      setOps(next);
      setHistory((h) => {
        const h2 = [...h];
        h2[histIdx] = { ops: next, label: "edit" };
        return h2;
      });
    },
    [ops, histIdx]
  );

  const deleteOp = useCallback(
    (id: string) => {
      pushHistory(
        ops.filter((o) => o.id !== id),
        "delete"
      );
    },
    [ops, pushHistory]
  );

  const undo = useCallback(() => {
    if (histIdx > 0) {
      setHistIdx((i) => i - 1);
      setOps(history[histIdx - 1].ops);
    }
  }, [histIdx, history]);

  const redo = useCallback(() => {
    if (histIdx < history.length - 1) {
      setHistIdx((i) => i + 1);
      setOps(history[histIdx + 1].ops);
    }
  }, [histIdx, history]);

  // ---- 保存 / 校验 / 快照 ----
  const save = useCallback(async () => {
    setBusy(true);
    try {
      const baseHash = detail?.patch.baseHash ?? "";
      await api.putPatch(target.id, { baseHash, ops });
      await loadFigure(target.id);
      setHistory([{ ops, label: "已保存" }]);
      setHistIdx(0);
      showToast("patch 已保存");
    } catch (e) {
      showToast(`保存失败：${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  }, [target, detail, ops, loadFigure, showToast]);

  const verify = useCallback(async () => {
    setBusy(true);
    try {
      const v = await api.verifyPatch(target.id);
      setLastVerify(v);
      await loadFigure(target.id);
      showToast(v.cleared ? "patch 已收敛清空" : `剩余 ${v.remainingOps} 个 op`);
    } catch (e) {
      showToast(`校验失败：${(e as Error).message}`, true);
    } finally {
      setBusy(false);
    }
  }, [target, loadFigure, showToast]);

  const snapshot = useCallback(
    async (note: string) => {
      try {
        await api.snapshot(target.id, note);
        await loadFigure(target.id, true);
        showToast("快照已保存");
      } catch (e) {
        showToast(`快照失败：${(e as Error).message}`, true);
      }
    },
    [target, loadFigure, showToast]
  );

  // ---- 选区 ----
  const onSelection = useCallback(
    (jsons: SelectionJSON[]) => {
      if (jsons.length === 0) return;
      setSelectionPaths(jsons.map((j) => j.semanticPath));
      // 单选保持对象形状（兼容服务端旧契约），多选传数组
      const payload = jsons.length === 1 ? jsons[0] : jsons;
      api
        .enrichSelection(target.id, payload)
        .then((enriched) => setSelections(Array.isArray(enriched) ? enriched : [enriched]))
        .catch(() => setSelections(jsons));
    },
    [target]
  );

  const onClearSelection = useCallback(() => {
    setSelections([]);
    setSelectionPaths([]);
  }, []);

  // ---- 导出 ----
  const getExportSvg = useCallback(async (): Promise<{ text: string; w: number; h: number } | null> => {
    if (dirty) {
      await save();
    }
    const d = await api.getFigure(target.id);
    const text = d.finalSvg ?? d.baseSvg;
    if (!text) return null;
    const doc = new DOMParser().parseFromString(text, "image/svg+xml");
    const svg = doc.documentElement;
    const vb = svg.getAttribute("viewBox")?.split(/[\s,]+/).map(Number);
    let w = parseFloat(svg.getAttribute("width") || "");
    let h = parseFloat(svg.getAttribute("height") || "");
    if ((!Number.isFinite(w) || !Number.isFinite(h)) && vb) {
      w = vb[2];
      h = vb[3];
    }
    return { text, w: w || 400, h: h || 300 };
  }, [target, dirty, save]);

  const exportSvg = useCallback(async () => {
    const out = await getExportSvg();
    if (!out) return;
    downloadBlob(new Blob([out.text], { type: "image/svg+xml" }), `${target.name}.svg`);
    showToast("SVG 已导出");
  }, [getExportSvg, target, showToast]);

  const exportPng = useCallback(async () => {
    const out = await getExportSvg();
    if (!out) return;
    const scale = 2;
    const blob = new Blob([out.text], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(out.w * scale);
      canvas.height = Math.round(out.h * scale);
      const ctx = canvas.getContext("2d")!;
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      canvas.toBlob((b) => {
        if (b) downloadBlob(b, `${target.name}.png`);
        showToast("PNG 已导出");
      }, "image/png");
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      showToast("PNG 导出失败", true);
    };
    img.src = url;
  }, [getExportSvg, target, showToast]);

  const renderError = detail?.renderError;
  const current = { id: target.id, name: target.name };

  return (
    <div className="app editor">
      <div className="main">
        <div className="toolbar">
          <button onClick={onBack}>← 管理</button>
          <b>{target.name}</b>
          <span className="hint">{wsOnline ? "WS 已连接" : "WS 断开（轮询中）"}</span>
          <span className="spacer" />
          <label className="toggle">
            <input type="checkbox" checked={preciseMode} onChange={(e) => setPreciseMode(e.target.checked)} />
            精确模式
          </label>
          <label className="toggle">
            <input type="checkbox" checked={showBase} onChange={(e) => setShowBase(e.target.checked)} />
            查看原始 base
          </label>
          <button
            onClick={async () => {
              setBusy(true);
              try {
                const r = await api.run(target.id);
                showToast(r.ok ? "重渲染完成" : `渲染失败：${r.stderr.slice(0, 160)}`, !r.ok);
                await loadFigure(target.id, stateRef.current.dirty);
              } finally {
                setBusy(false);
              }
            }}
            disabled={busy || runActive}
          >
            重渲染
          </button>
        </div>

        {staleServer && (
          <div className="dirty-banner" style={{ margin: "8px 12px 0" }}>
            服务器上的图已更新（AI 或手动渲染）。本地有未保存的微调，未自动刷新；保存或撤销后刷新。
            <button
              className="small"
              style={{ marginLeft: 8 }}
              onClick={() => loadFigure(target.id)}
            >
              放弃本地修改并刷新
            </button>
          </div>
        )}

        {renderError && <div className="render-error">渲染失败：{renderError}</div>}

        <Viewer
          baseSvg={detail?.baseSvg ?? null}
          ops={ops}
          showBase={showBase}
          preciseMode={preciseMode}
          selectionPaths={selectionPaths}
          onSelection={onSelection}
          onClearSelection={onClearSelection}
          version={1}
          onElements={setElements}
          selectRequest={selectReq}
        />
      </div>

      <AIPanel
        current={current}
        selections={selections}
        patchOpCount={detail?.patch.ops.length ?? 0}
        runEvents={aiEvents}
        runActive={runActive}
        wsOnline={wsOnline}
        onRunStart={() => setRunActive(true)}
        onRunEnd={() => setRunActive(false)}
        onFigureChanged={() => {
          // 经 ref 取最新 id：run 中途切图后，旧闭包里的 id 会把旧图
          // detail/ops 覆盖到新图上下文（再点保存就把旧图 ops 存进新图）
          loadFigure(stateRef.current.id, stateRef.current.dirty);
        }}
        showToast={showToast}
      />

      <EditorPanel
        selections={selections}
        ops={ops}
        dirty={dirty}
        canUndo={histIdx > 0}
        canRedo={histIdx < history.length - 1}
        lastVerify={lastVerify}
        snapshots={detail?.snapshots ?? []}
        code={detail?.code ?? null}
        busy={busy || runActive}
        elements={elements}
        onSelectElement={(path) => setSelectReq({ path, nonce: Date.now() })}
        onAddOps={addOps}
        onUpdateOp={updateOp}
        onDeleteOp={deleteOp}
        onUndo={undo}
        onRedo={redo}
        onSave={save}
        onVerify={verify}
        onExportPng={exportPng}
        onExportSvg={exportSvg}
        onSnapshot={snapshot}
        onCopySelection={() => {
          if (selections.length === 0) return;
          const payload = selections.length === 1 ? selections[0] : selections;
          navigator.clipboard
            .writeText(JSON.stringify(payload, null, 2))
            .then(() =>
              showToast(selections.length === 1 ? "选区 JSON 已复制" : `已复制 ${selections.length} 个元素的选区 JSON`)
            );
        }}
      />

      {toast && <div className={`toast ${toast.error ? "error" : ""}`}>{toast.msg}</div>}
    </div>
  );
}

function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
```

（注意：`version={1}` —— Viewer 用 version 触发重渲染，切图时 useEffect 已重挂载 detail；若 `Viewer` 的 version prop 必须随图变化，改为 `version` state 在 `target.id` 变化时 +1，执行者按 Viewer.tsx 现有 props 语义保留一个 `const [version, setVersion] = useState(0)` 并在切图 effect 中 `setVersion((v) => v + 1)`。**采用后者**（与旧代码一致）：保留 version state。）

- [ ] **Step 2: AIPanel.tsx 整文件替换**

```tsx
// AI 面板：选区指令 + 回写 + run 事件时间线（造图/改造在管理视图的新建对话框）。
import { useEffect, useState } from "react";
import { api } from "../api";
import type { AiStatus, AiRunResult, RunEvent, SelectionJSON } from "../types";

interface Props {
  current: { id: string; name: string };
  selections: SelectionJSON[];
  patchOpCount: number;
  runEvents: RunEvent[];
  runActive: boolean;
  wsOnline: boolean;
  onRunStart: () => void;
  onRunEnd: () => void;
  onFigureChanged: () => void;
  showToast: (msg: string, error?: boolean) => void;
}

export function AIPanel(props: Props) {
  const { current, selections, patchOpCount, runEvents, runActive, wsOnline,
          onRunStart, onRunEnd, onFigureChanged, showToast } = props;
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [instruction, setInstruction] = useState("");

  // 取状态可复调：WS 重连（wsOnline 翻转）时重试——首次失败会永久停在"未配置"，
  // 重连后再取一次可自愈。
  const refreshStatus = () => {
    api.aiStatus().then(setStatus).catch(() => setStatus({ configured: false, provider: "", model: "", mock: false }));
  };

  useEffect(() => {
    refreshStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsOnline]);

  const disabled = runActive || !status?.configured;

  const handleInstruct = async () => {
    if (!instruction.trim()) return;
    onRunStart();
    try {
      const payload = selections.length === 1 ? selections[0] : selections;
      const r: AiRunResult = await api.instruct(current.id, instruction, payload);
      showToast(r.ok ? "修改完成" : `修改失败：${(r.stderr || "").slice(0, 160)}`, !r.ok);
    } catch (e) {
      showToast(`修改失败：${(e as Error).message}`, true);
    } finally {
      onFigureChanged();
      // fetch settle 即代表服务端 run 已结束（含 400 等未进 run_workflow 的早失败），
      // 先于 WS run_end 复位无害且幂合；否则 WS 丢事件时面板永久锁死
      onRunEnd();
    }
  };

  const handleWriteback = async () => {
    onRunStart();
    try {
      const r = await api.writebackPatch(current.id);
      showToast(
        r.cleared
          ? "patch 已收敛清空"
          : (r.remaining ?? -1) < 0
            ? "回写未收敛"
            : `回写未收敛：剩余 ${r.remaining} 个 op`,
        !r.cleared
      );
    } catch (e) {
      showToast(`回写失败：${(e as Error).message}`, true);
    } finally {
      onFigureChanged();
      onRunEnd();
    }
  };

  return (
    <div className="ai-panel">
      <div className="ai-status">
        AI：
        {status === null ? "检测中…" : status.configured
          ? `${status.provider} / ${status.model}${status.mock ? "（mock）" : ""}`
          : `未配置${status.detail ? `（${status.detail}）` : ""}：仓库根放 config.json + .env（参考 config.example.json）`}
      </div>

      <section>
        <h4>指令修改 {selections.length > 0 && `（已附加 ${selections.length} 个选区元素）`}</h4>
        <textarea placeholder="例如：把选中的柱子改成主色蓝，字号统一 12" value={instruction}
                  onChange={(e) => setInstruction(e.target.value)} disabled={disabled} />
        <div>
          <button onClick={handleInstruct} disabled={disabled || !instruction.trim()}>执行修改</button>
          <button onClick={handleWriteback} disabled={disabled || patchOpCount === 0}>
            回写 patch（{patchOpCount} op）
          </button>
        </div>
      </section>

      <section>
        <h4>运行时间线</h4>
        {runEvents.length === 0 && <div className="hint">尚无 AI 运行</div>}
        <ul className="run-events">
          {runEvents.map((ev, i) => (
            <li key={i} className={`run-ev run-ev-${ev.phase}`}>
              {new Date(ev.at).toLocaleTimeString()} {ev.phase}
              {ev.node ? ` · ${ev.node}` : ""}
              {ev.detail ? ` · ${ev.detail}` : ""}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
```

- [ ] **Step 3: 删除 Sidebar**

```bash
git rm web/src/components/Sidebar.tsx
```

- [ ] **Step 4: 类型检查**

Run: `cd web && npx tsc --noEmit`
Expected: 无错误（若 Viewer 的 props 有变化按编译提示修正；不改 Viewer.tsx 本身）

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/components/AIPanel.tsx
git commit -m "feat(web)!: 双视图编排，编辑器改 id 寻址，AI 造图入口移至管理视图"
```

### Task 13: web 测试更新

**Files:**
- Modify: `web/src/components/AIPanel.test.tsx`（整文件替换）
- Create: `web/src/components/manage/ManageView.test.tsx`

- [ ] **Step 1: AIPanel.test.tsx 替换**

```tsx
// @vitest-environment happy-dom
import { describe, expect, it, vi, afterEach } from "vitest";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react-dom/test-utils";
import { AIPanel } from "./AIPanel";
import { api } from "../api";

vi.mock("../api", () => ({
  api: {
    aiStatus: () =>
      Promise.resolve({ configured: true, provider: "mock", model: "mock", mock: true }),
    instruct: vi.fn(),
    writebackPatch: vi.fn(),
  },
}));

describe("AIPanel", () => {
  let root: Root | null = null;
  let container: HTMLElement;

  const props = {
    current: { id: "abc123def456", name: "f1" },
    selections: [],
    patchOpCount: 2,
    runEvents: [{ runId: "r1", phase: "run_end" as const, node: "create", ok: true, at: 0 }],
    runActive: false,
    wsOnline: false,
    onRunStart: vi.fn(),
    onRunEnd: vi.fn(),
    onFigureChanged: vi.fn(),
    showToast: vi.fn(),
  };

  function render(over: Partial<Parameters<typeof AIPanel>[0]> = {}) {
    container = document.body.appendChild(document.createElement("div"));
    root = createRoot(container);
    act(() => root!.render(createElement(AIPanel, { ...props, ...over })));
  }

  afterEach(() => {
    root?.unmount();
    root = null;
  });

  it("渲染状态徽标，未输入指令时执行按钮禁用", async () => {
    render();
    await act(() => new Promise((r) => setTimeout(r, 0)));
    expect(container.textContent).toContain("mock");
    const buttons = [...container.querySelectorAll("button")];
    const exec = buttons.find((b) => b.textContent === "执行修改")!;
    expect(exec.disabled).toBe(true);
  });

  it("显示运行时间线事件", async () => {
    render();
    await act(() => new Promise((r) => setTimeout(r, 0)));
    expect(container.textContent).toContain("run_end");
  });

  it("有 patch op 时回写按钮可用并显示数量", async () => {
    render();
    await act(() => new Promise((r) => setTimeout(r, 0)));
    const wb = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("回写 patch")
    )!;
    expect(wb.disabled).toBe(false);
    expect(wb.textContent).toContain("2 op");
  });

  it("请求失败（reject）后 onRunEnd 被调用，按钮不持续禁用", async () => {
    vi.mocked(api.writebackPatch).mockRejectedValueOnce(new Error("boom"));
    const onRunEnd = vi.fn();
    render({ onRunEnd });
    await act(() => new Promise((r) => setTimeout(r, 0)));
    const wb = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("回写 patch")
    )!;
    expect(wb.disabled).toBe(false);
    await act(async () => {
      wb.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await act(() => new Promise((r) => setTimeout(r, 0)));
    // finally 里的 onRunEnd 是 runActive 锁的解锁契约：fetch settle 必须复位
    expect(onRunEnd).toHaveBeenCalledTimes(1);
    expect(wb.disabled).toBe(false);
  });
});
```

- [ ] **Step 2: ManageView.test.tsx 新建**

```tsx
// @vitest-environment happy-dom
import { describe, expect, it, vi, afterEach } from "vitest";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react-dom/test-utils";
import { ManageView } from "./ManageView";
import { api } from "../../api";

vi.mock("../../api", () => ({
  api: {
    listItems: vi.fn(() =>
      Promise.resolve([
        {
          id: "aaaabbbbcccc", name: "图A", typeName: "图", groupIds: [1],
          tags: ["重要"], properties: { 来源: "ai" },
          createdAt: "2026-01-01T00:00:00+00:00", updatedAt: "2026-01-02T00:00:00+00:00",
          hasBase: true, opCount: 2,
        },
      ])
    ),
    listGroups: vi.fn(() =>
      Promise.resolve([{ id: 1, parentId: null, name: "项目A", position: 0, boundItemId: null }])
    ),
    listTags: vi.fn(() => Promise.resolve([{ id: 1, name: "重要" }])),
    listTypes: vi.fn(() =>
      Promise.resolve([
        { id: 3, name: "图", icon: "chart-bar", fields: [
          { id: 1, name: "模板", fieldType: "text", position: 0, label: "", options: [] },
        ] },
      ])
    ),
    getRepoState: vi.fn(() => Promise.resolve({ theme: "light" })),
    putRepoState: vi.fn(() => Promise.resolve({})),
    listFiles: vi.fn(() => Promise.resolve([{ path: "plot.py", isDir: false }])),
    deleteItem: vi.fn(() => Promise.resolve({ ok: true })),
    bindItemGroup: vi.fn(() => Promise.resolve({ ok: true })),
  },
}));

describe("ManageView", () => {
  let root: Root | null = null;
  let container: HTMLElement;

  afterEach(() => {
    root?.unmount();
    root = null;
  });

  function render() {
    container = document.body.appendChild(document.createElement("div"));
    root = createRoot(container);
    return act(async () => {
      root!.render(createElement(ManageView, { onOpen: vi.fn() }));
      await new Promise((r) => setTimeout(r, 0));
    });
  }

  it("渲染图列表与分组树", async () => {
    await render();
    expect(container.textContent).toContain("图A");
    expect(container.textContent).toContain("项目A");
    expect(container.textContent).toContain("重要");
    expect(container.textContent).toContain("2 微调");
  });

  it("删除按钮两击确认后调用 api.deleteItem", async () => {
    await render();
    const del = [...container.querySelectorAll("button")].find((b) => b.textContent === "删除")!;
    await act(async () => {
      del.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(api.deleteItem).not.toHaveBeenCalled(); // 第一次只确认
    const confirmBtn = [...container.querySelectorAll("button")].find((b) => b.textContent === "确认删除?")!;
    await act(async () => {
      confirmBtn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(api.deleteItem).toHaveBeenCalledWith("aaaabbbbcccc");
  });
});
```

- [ ] **Step 3: 运行 web 测试**

Run: `cd web && npx vitest run`
Expected: 全部 passed（Viewer 4 个测试文件零改动通过；AIPanel/ManageView 新用例通过）

- [ ] **Step 4: 构建 + Commit**

```bash
cd web && npm run build
git add web/src/components/AIPanel.test.tsx web/src/components/manage/ManageView.test.tsx
git commit -m "test(web): AIPanel 改 id 契约；新增 ManageView 测试"
```

## Phase E — 收尾

### Task 14: 文档更新与手工验收

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/specs/2026-10-22-index-repo-refactor-design.md`（如实现中有偏差，回写）

- [ ] **Step 1: 文档同步**

Run: `grep -rn "workspace/<project>\|meta.json\|/api/projects\|runs.jsonl\|项目/" README.md AGENTS.md docs/specs/2026-10-16-figure-agent-design.md 2>/dev/null`

对每处命中的现行描述，替换为新契约（措辞可沿用原文风格）：
- 存储布局：`workspace/.index/index.db + workspace/<12hex>/{plot.py, base.svg, patch.json, history/}`；`meta.json`/`runs.jsonl` 已废除，管理语义在 index.db（items/item_groups/item_tags + fa_runs/fa_snapshots）。
- 项目/图管理：图 = Index 条目（类型「图」），项目 = 分组；分组/标签/类型/改名/删除全部走 SQL 与管理界面；工作区可被 Index 应用作为仓库直接打开。
- API：`/api/items`、`/api/figures/{id}/...`（旧 `/api/projects/...`、`/api/figure/{p}/{f}` 已删）。
- 迁移：`python -m figure_agent migrate [--archive]`。

- [ ] **Step 2: 端到端手工验收（真实服务 + 真实迁移）**

```bash
cd "C:\Users\xingy\Desktop\开发\figure-agent"
python -m figure_agent migrate --archive    # 迁移现有 workspace/demo
python -m figure_agent                      # 启动服务（默认 8765）
```

浏览器验证清单：
1. 管理视图加载：左侧「demo」分组树、中间列出迁移来的图（原 demo/test、demo/test2）、右侧详情属性/文件树。
2. 新建图（模板）→ 出现列表 → 打开编辑器 → 画布/框选/微调/回写/AI 面板正常。
3. 重命名一张图 → 列表更新，编辑器标题更新。
4. 新建分组/标签并绑定 → 列表过滤生效。
5. 暗色切换 → 刷新后仍生效（state.json）。
6. `sqlite3 workspace/.index/index.db "SELECT name FROM items"` 与 UI 一致。

- [ ] **Step 3: Index 应用打开验收（spec §8 手工验收）**

```bash
cd "C:\Users\xingy\Desktop\开发\itemmanage" && npm run tauri dev
```

在 Index 中「打开仓库」选择 `figure-agent/workspace`：
1. 仓库能打开（不报迁移错误），左侧显示 demo 分组 + 标签。
2. 中栏列出「图」条目（工作区 itemTypes 白名单生效）。
3. 右侧详情能看到属性（模板/来源/最后渲染）与文件树（plot.py/base.svg/...）。
4. 在 Index 里重命名一张图 → figure-agent 管理视图刷新后名字跟随（SQL 唯一真相）。
5. 在 Index 里删除一张图 → figure-agent 打开该图报 404（图文件夹缺失）。

- [ ] **Step 4: 全量回归后收尾提交**

```bash
cd server && python -m pytest -q
cd ../web && npx vitest run
git add README.md AGENTS.md docs
git commit -m "docs: 存储布局/项目管理/API 契约切换为 Index 仓库模式"
```

---

## 自审记录（写计划时已核对）

1. **spec 覆盖**：spec §2（磁盘契约→Task 1-3）、§3（index.db→Task 1-3）、§4（语义边界→Task 4-6）、§5（server→Task 6-9）、§6（web→Task 10-13）、§7（迁移→Task 8）、§8（测试→各任务 + Task 14）、§9（风险→Task 1 的 .gitattributes、迁移器拒绝无账本库、types 预设保护、按名取列）。
2. **类型一致性**：`repo_runs.add_run(repo, item_id, kind, ok, rounds, at, detail)` 在 nodes/workflows/migrate/tests 四处一致；`Store.create_figure(name, template, origin, group_id) -> {id, name, ok, stderr}` 在 store/main/migrate/tests 一致；`enrich_selection(store, item_id, selection)` 在 main 两处调用一致；web `api.*` 与 `ManageView/AIPanel/App` 的调用签名一致。
3. **已知执行期自由度**：App.tsx 的 `version` state（Task 12 Step 1 注释）与 tsconfig noUnusedLocals 的未用导入清理，按注释处理。
