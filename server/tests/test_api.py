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
