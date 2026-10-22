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
