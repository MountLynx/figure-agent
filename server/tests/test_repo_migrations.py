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
    assert {p.name for p in MIGRATIONS_DIR.glob("*.sql")} == set(EXPECTED_SHA384) | {"000001_fa_ext.sql"}
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
