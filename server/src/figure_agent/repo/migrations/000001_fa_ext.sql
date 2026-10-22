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
