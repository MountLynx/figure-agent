"""FastAPI 集成测试：REST 全流程 + 选区会话。"""

import pytest
from fastapi.testclient import TestClient

import figure_agent.main as main_mod


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FA_WORKSPACE", str(tmp_path / "ws"))
    # 重新加载 app 以应用 workspace
    import importlib

    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def test_full_flow(client):
    # 建图（模板）
    r = client.post("/api/projects/demo/figures", json={"name": "bars", "template": "bar-groups"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # 项目/图列表
    assert client.get("/api/projects").json()[0]["name"] == "demo"
    figs = client.get("/api/projects/demo").json()
    assert figs[0]["name"] == "bars" and figs[0]["hasBase"]

    # 读图
    fig = client.get("/api/figure/demo/bars").json()
    assert "fa:treatment-bar-0" in fig["baseSvg"]
    assert fig["patch"]["ops"] == []

    # 写代码（渲染错误透传；注意 plot.py 已被写成坏代码，符合"代码=真相源"）
    r = client.put("/api/figure/demo/bars/code", json={"code": "fig = 1 +\n"})
    body = r.json()
    assert body["ok"] is False and body["errorLine"] == 1
    # 上一版仍在
    assert "fa:treatment-bar-0" in client.get("/api/figure/demo/bars").json()["baseSvg"]

    # 选区会话
    r = client.post(
        "/api/session/selection",
        json={
            "project": "demo",
            "figure": "bars",
            "selection": {"id": "fa:treatment-bar-2"},
        },
    )
    sel = r.json()
    assert sel["elementId"] == "fa:treatment-bar-2"
    assert sel["fingerprint"].startswith("p:")
    assert sel["semanticPath"].endswith("fa:treatment-bar-2")
    assert sel["nearby"]

    # MCP 读取
    got = client.get("/api/session/selection").json()["selection"]
    assert got["fingerprint"].startswith("p:")

    # patch + 回写收敛
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_style", "target": {"id": "fa:treatment-bar-2"},
         "attr": "fill", "value": "#dd3322", "intent": "改红", "origin": "manual", "status": "active"},
    ]}
    r = client.put("/api/figure/demo/bars/patch", json=patch)
    assert r.json()["ok"] is True
    fig = client.get("/api/figure/demo/bars").json()
    assert "#dd3322" in fig["finalSvg"]

    v = client.post("/api/figure/demo/bars/verify-patch").json()
    assert v["cleared"] is False and v["results"][0]["status"] == "active"

    # 恢复好代码后再重渲染
    from figure_agent.store import TEMPLATES_DIR

    good_code = (TEMPLATES_DIR / "bar-groups" / "plot.py").read_text(encoding="utf-8")
    r = client.put("/api/figure/demo/bars/code", json={"code": good_code})
    assert r.json()["ok"] is True
    r = client.post("/api/figure/demo/bars/run")
    assert r.json()["ok"] is True

    # snapshot
    r = client.post("/api/figure/demo/bars/snapshot", json={"note": "v1"})
    assert r.status_code == 200
    assert client.get("/api/figure/demo/bars").json()["snapshots"][0]["note"] == "v1"


def test_verify_after_code_writeback(client):
    client.post("/api/projects/demo/figures", json={"name": "bars2", "template": "bar-groups"})
    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_style", "target": {"id": "fa:treatment-bar-2"},
         "attr": "fill", "value": "#dd3322", "intent": "改红", "origin": "manual", "status": "active"},
    ]}
    client.put("/api/figure/demo/bars2/patch", json=patch)
    # 模拟 AI 回写：读代码 → 改色 → 写回
    # （代码读取走 MCP 的 fa_get_figure；测试里直接读文件）
    from figure_agent.main import store

    code = store.read_code("demo", "bars2").replace('"#d08770"', '"#dd3322"')
    r = client.put("/api/figure/demo/bars2/code", json={"code": code})
    assert r.json()["ok"] is True
    v = client.post("/api/figure/demo/bars2/verify-patch").json()
    assert v["cleared"] is True, v


def test_multiselect_session(client):
    """多选：POST 数组 → 每个元素各自富化；GET/f MCP 读到完整数组。"""
    client.post("/api/projects/demo/figures", json={"name": "bars3", "template": "bar-groups"})
    r = client.post(
        "/api/session/selection",
        json={
            "project": "demo",
            "figure": "bars3",
            "selection": [{"id": "fa:treatment-bar-1"}, {"id": "fa:treatment-bar-2"}],
        },
    )
    sel = r.json()
    assert isinstance(sel, list) and len(sel) == 2
    assert [s["elementId"] for s in sel] == ["fa:treatment-bar-1", "fa:treatment-bar-2"]
    assert all(s["fingerprint"].startswith("p:") for s in sel)
    # 两条 JSON 各自独立描述自己的元素，不能是第一条的克隆
    assert sel[0]["semanticPath"] != sel[1]["semanticPath"]

    got = client.get("/api/session/selection").json()["selection"]
    assert isinstance(got, list) and got[1]["elementId"] == "fa:treatment-bar-2"
