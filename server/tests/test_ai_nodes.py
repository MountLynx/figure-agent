"""ai.nodes：script 节点纯逻辑单测（假 view）。"""

from __future__ import annotations

import asyncio
import json

import pytest

from figure_agent.ai import nodes
from figure_agent.store import Store


class FakeView:
    """模拟 tickflow NodeView 的最小面：field/state/output。"""

    def __init__(self, fields=None, output=None, state=None):
        self._fields = fields or {}
        self.output = output
        self.state = state if state is not None else {}

    def field(self, name):
        # 未点火 producer 模拟：抛 KeyError（与 tickflow 语义一致）
        if name not in self._fields:
            raise KeyError(name)
        v = self._fields[name]
        if isinstance(v, Exception):
            raise v
        return v


CSV_TEXT = "dose,response\n0,1.1\n5,2.3\n10,3.9\n"
PROFILE = {"shape": [3, 2], "columns": [{"name": "dose", "dtype": "number", "unit": "", "desc": "剂量"}], "notes": "剂量响应"}


def _make_store_fig(tmp_path):
    """Store 建图（AI origin：无 plot.py），返回 (store, item_id, fdir)。"""
    ws = tmp_path / "ws"
    store = Store(ws)
    fid = store.create_figure("f", origin="ai")["id"]
    return store, fid, store.figure_dir(fid)


def test_parse_upload_csv(tmp_path):
    fdir = tmp_path
    up = fdir / "uploads"
    up.mkdir()
    (up / "d.csv").write_text(CSV_TEXT, encoding="utf-8")
    fn = nodes.make_parse_upload(fdir, "d.csv")
    out = asyncio.run(fn(FakeView()))
    assert out == CSV_TEXT


def test_parse_upload_xlsx(tmp_path):
    pytest.importorskip("pandas")
    fdir = tmp_path
    up = fdir / "uploads"
    up.mkdir()
    import pandas as pd

    pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).to_excel(up / "d.xlsx", index=False)
    fn = nodes.make_parse_upload(fdir, "d.xlsx")
    out = asyncio.run(fn(FakeView()))
    assert "a,b" in out and "1,x" in out


def test_write_data(tmp_path):
    fdir = tmp_path
    fn = nodes.make_write_data(fdir)
    profile = fn(FakeView(fields={"data": {"csv": CSV_TEXT, "profile": PROFILE, "notes": "已规范"}}))
    assert (fdir / "data.csv").read_text(encoding="utf-8") == CSV_TEXT
    saved = json.loads((fdir / "data_profile.json").read_text(encoding="utf-8"))
    assert saved["shape"] == [3, 2]
    assert "已规范" in saved["notes"]       # 顶层 notes 并入画像 notes
    assert profile == {**PROFILE, "notes": "剂量响应 已规范"}


def test_render_validate_first_pass_renders_and_counts(tmp_path):
    """首轮（无 fix）用 gen 的代码；写盘渲染计数；返回值带 code。"""
    store, fid, fdir = _make_store_fig(tmp_path)
    good = (
        "import matplotlib\nmatplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "fig, ax = plt.subplots(figsize=(4, 3))\n"
        "ax.plot([0, 1], [0, 1])\nfig.tight_layout()\n"
    )
    fn = nodes.make_render_validate(store, fid)
    out = asyncio.run(fn(FakeView(fields={"gen": {"code": good}})))
    assert out["ok"] is True and out["rounds"] == 1 and out["source"] == "gen"
    assert out["code"] == good              # fix 循环的修复器要靠它拿当前代码
    assert "ax.plot" in (fdir / "plot.py").read_text(encoding="utf-8")


def test_render_validate_prefers_fix_and_loop_limit(tmp_path):
    store, fid, fdir = _make_store_fig(tmp_path)
    bad = "fig = 1 +\n"
    fn = nodes.make_render_validate(store, fid)
    view = FakeView(fields={"gen": {"code": bad}, "fix": {"code": bad}})
    out1 = asyncio.run(fn(view))
    assert out1["ok"] is False and out1["source"] == "fix" and out1["rounds"] == 1
    out2 = asyncio.run(fn(view))  # 同一 view.state 跨 tick 累计
    assert out2["rounds"] == 2
    assert nodes.needs_fix(FakeView(output=out2)) is True
    assert nodes.settled(FakeView(output=out2)) is False


def test_render_validate_no_code(tmp_path):
    store, fid, fdir = _make_store_fig(tmp_path)
    fn = nodes.make_render_validate(store, fid)
    out = asyncio.run(fn(FakeView(fields={})))
    assert out["ok"] is False and "未产出代码" in out["stderr"] and out["code"] == ""


def test_guards_xor():
    ok1 = {"ok": True, "rounds": 1}
    fail1 = {"ok": False, "rounds": 1}
    fail3 = {"ok": False, "rounds": 3}
    assert nodes.needs_fix(FakeView(output=fail1)) and not nodes.settled(FakeView(output=fail1))
    assert not nodes.needs_fix(FakeView(output=ok1)) and nodes.settled(FakeView(output=ok1))
    assert not nodes.needs_fix(FakeView(output=fail3)) and nodes.settled(FakeView(output=fail3))


def test_writeback_nodes(tmp_path):
    store, fid, fdir = _make_store_fig(tmp_path)
    store.save_patch(fid, {
        "baseHash": "",
        "ops": [{"id": "op-1", "kind": "set_style", "target": {"id": "fa:title"},
                 "attr": "font-size", "value": "18", "intent": "标题变大", "origin": "manual",
                 "status": "active"}],
    })
    rp = nodes.make_read_patch(store, fid)
    seed = rp(FakeView())
    assert len(seed["ops"]) == 1

    merge = nodes.make_merge_wb(fdir)
    m1 = merge(FakeView(fields={"seed": seed}))          # 首轮：无 verify
    assert m1["cleared"] is False and m1["rounds"] == 0
    assert nodes.wb_continue(FakeView(output=m1)) is True
    assert nodes.wb_done(FakeView(output=m1)) is False

    # 模拟一轮校验后未收敛
    verify1 = {"ok": True, "cleared": False, "rounds": 1, "remaining": 1, "results": [], "stderr": ""}
    m2 = merge(FakeView(fields={"seed": seed, "verify": verify1}))
    assert m2["rounds"] == 1
    assert nodes.wb_continue(FakeView(output=m2)) is True

    # 收敛：cleared
    verify2 = {"ok": True, "cleared": True, "rounds": 2, "remaining": 0, "results": [], "stderr": ""}
    m3 = merge(FakeView(fields={"seed": seed, "verify": verify2}))
    assert nodes.wb_continue(FakeView(output=m3)) is False
    assert nodes.wb_done(FakeView(output=m3)) is True

    # 空 patch：直接收敛路径
    m4 = merge(FakeView(fields={"seed": {"ops": []}}))
    assert nodes.wb_continue(FakeView(output=m4)) is False
    assert nodes.wb_done(FakeView(output=m4)) is True


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


def test_render_validate_tolerates_missing_sentinel(tmp_path):
    """真实引擎未点火 producer 返回 tickflow Missing（非 KeyError）——isinstance 防御须兜住。"""
    from tickflow.views import Missing

    store, fid, fdir = _make_store_fig(tmp_path)
    fn = nodes.make_render_validate(store, fid)
    out = asyncio.run(fn(FakeView(fields={"gen": {"code": ""}, "fix": Missing})))
    # fix 为 Missing（非 dict）→ 走 gen；gen.code 为空串 → 视为无代码
    assert out["ok"] is False and out["source"] == "gen" and "未产出代码" in out["stderr"]
