"""FastAPI 集成测试：REST 全流程 + AI 工作流端点。"""

import json

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


def _stub_routes(monkeypatch, routes):
    from tests.test_ai_workflows import StubLLM

    stub = StubLLM(routes)
    import figure_agent.ai.workflows as wf

    monkeypatch.setattr(wf, "get_llm", lambda: stub)
    return stub


def test_ai_create_endpoint(client, monkeypatch):
    import pathlib

    iris = pathlib.Path(__file__).parent / "fixtures" / "iris.csv"
    from tests.test_ai_workflows import GOOD_CODE, STD_REPLY

    _stub_routes(monkeypatch, {
        "数据标准化": [STD_REPLY],
        "绘图代码生成器": [json.dumps({"code": GOOD_CODE, "notes": ""})],
    })
    r = client.post(
        "/api/projects/demo/figures/ai",
        data={"name": "ai-fig", "requirements": "散点图，按物种着色"},
        files={"data": ("iris.csv", iris.read_bytes(), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["kind"] == "create"
    assert "fa:response-curve" in client.get("/api/figure/demo/ai-fig").json()["baseSvg"]
    meta = client.get("/api/figure/demo/ai-fig").json()["meta"]
    assert meta["origin"] == "ai"
    runs = client.get("/api/figure/demo/ai-fig/runs").json()
    assert runs[0]["kind"] == "create"


def test_ai_create_duplicate_400(client):
    client.post("/api/projects/demo/figures", json={"name": "bars", "template": "bar-groups"})
    r = client.post(
        "/api/projects/demo/figures/ai",
        data={"name": "bars", "requirements": "x"},
        files={"data": ("d.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert r.status_code == 400  # bars 已由模板建过


def test_instruct_endpoint(client, monkeypatch):
    client.post("/api/projects/demo/figures", json={"name": "bars", "template": "bar-groups"})
    # stub 返回当前代码原样（demo/bars 是模板图、无 data.csv，
    # 不能回读 data.csv 的 GOOD_CODE，否则渲染失败触发 fix 循环到超限）
    code = client.get("/api/figure/demo/bars").json()["code"]
    _stub_routes(monkeypatch, {
        "绘图代码修改器": [json.dumps({"code": code, "notes": "已处理指令"})],
    })
    # semanticPath 为 svgkit 真实格式（root-first：figure_1/axes_1/<gid>）
    sel = {"elementId": "fa:treatment-bar-1", "semanticPath": "figure_1/axes_1/fa:treatment-bar-1"}
    r = client.post("/api/figure/demo/bars/instruct",
                    json={"instruction": "把选中的柱子改红", "selection": sel})
    assert r.status_code == 200 and r.json()["ok"] is True
    # instruct 后图已重渲染
    assert client.get("/api/figure/demo/bars").json()["baseSvg"]


def test_writeback_endpoint(client, monkeypatch):
    client.post("/api/projects/demo/figures", json={"name": "bars", "template": "bar-groups"})
    code = client.get("/api/figure/demo/bars").json()["code"]
    patched = code.replace('b.set_gid(f"fa:treatment-bar-{i}")',
                           'b.set_gid(f"fa:treatment-bar-{i}"); b.set_color("#dd3322")')
    _stub_routes(monkeypatch, {"微调回写器": [json.dumps({"code": patched, "notes": "改色"})]})
    # 先造一个 active op
    sel = {"elementId": "fa:treatment-bar-1", "semanticPath": "figure_1/axes_1/fa:treatment-bar-1"}
    client.post("/api/figure/demo/bars/enrich-selection", json={"selection": sel})
    patch = client.get("/api/figure/demo/bars").json()["patch"]
    patch["ops"] = [{"id": "op-x", "kind": "set_style", "target": {"id": "fa:treatment-bar-1",
                    "semanticPath": "figure_1/axes_1/fa:treatment-bar-1"},
                    "attr": "fill", "value": "#dd3322", "intent": "处理组改红",
                    "origin": "manual", "status": "active"}]
    client.put("/api/figure/demo/bars/patch", json=patch)
    r = client.post("/api/figure/demo/bars/writeback")
    assert r.status_code == 200
    body = r.json()
    assert body["cleared"] is True and body["ok"] is True


def test_instruct_without_plot_py_400(client):
    # AI create/adapt 失败会留下有 meta 无 plot.py 的图目录：instruct 应 400 而非 500
    from figure_agent.main import store

    store.init_figure("demo", "no-plot", origin="ai")
    sel = {"elementId": "fa:treatment-bar-1", "semanticPath": "figure_1/axes_1/fa:treatment-bar-1"}
    r = client.post("/api/figure/demo/no-plot/instruct",
                    json={"instruction": "改红", "selection": sel})
    assert r.status_code == 400, r.text


def test_enrich_selection_stateless(client):
    client.post("/api/projects/demo/figures", json={"name": "bars", "template": "bar-groups"})
    sel = {"elementId": "fa:treatment-bar-2", "semanticPath": "figure_1/axes_1/fa:treatment-bar-2"}
    r = client.post("/api/figure/demo/bars/enrich-selection", json={"selection": sel})
    body = r.json()
    assert body["elementId"] == "fa:treatment-bar-2"
    assert body["fingerprint"]
    assert client.get("/api/session/selection").status_code == 404
