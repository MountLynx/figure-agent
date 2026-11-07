"""figures API 路由测试（保留名门禁 / 建图流 / 有图判定 / 快照审计 / 删图清理）。

夹具是普通临时目录（``workdir`` + ``client``）：不再建 Index 仓库，也没有
``fig_runs`` / ``fig_snapshots`` 两张表。凡是原来断言「是否有图」属性的地方，
现在断言 ``workdir.has_figure()`` 或 ``GET /api/context``。

路径里的 ``{figure_id}`` 只为保持 /api/figures/* 形状而保留，服务端忽略其值；
带 id 与不带 id 两种写法都测。
"""

from __future__ import annotations

import figureagent.api.figures_api as figures_api

#: 任意占位 id（服务端不解释它）
FIGURE_ID = "aaaaaaaaaaaa"

GOOD_PLOT = (
    "import matplotlib\nmatplotlib.use('Agg')\n"
    "import matplotlib.pyplot as plt\n"
    "fig, ax = plt.subplots(figsize=(5, 3.6))\n"
    "ax.plot([0, 1], [0, 1])\n"
    't = ax.set_title("hello")\nt.set_gid("fa:title")\n'
    "fig.tight_layout()\n"
)


def _figure(client) -> dict:
    return client.get(f"/api/figures/{FIGURE_ID}").json()


# ---------------------------------------------------------------- 无图状态


def test_get_figure_no_figure(client, workdir):
    r = client.get(f"/api/figures/{FIGURE_ID}")
    assert r.status_code == 200
    body = r.json()
    assert body["hasFigure"] is False
    assert body["name"] == "MyData"
    assert body["dir"] == str(workdir.root)


def test_path_segment_is_ignored(client):
    a = client.get(f"/api/figures/{FIGURE_ID}").json()
    b = client.get("/api/figures/whatever-else").json()
    assert a["hasFigure"] is False and b["hasFigure"] is False
    assert a["dir"] == b["dir"]


def test_id_less_alias_works(client, workdir):
    assert client.get("/api/figures").json()["hasFigure"] is False
    workdir.plot_path().write_text(GOOD_PLOT, encoding="utf-8")
    body = client.get("/api/figures").json()
    assert body["hasFigure"] is True
    assert body["id"] == "MyData"  # 省略 id 时用目录名兜底


def test_never_touches_a_database(client, workdir):
    """服务不再碰数据库：跑一圈端点后目录里不会冒出 .index/ 或 *.db。"""
    client.get(f"/api/figures/{FIGURE_ID}/runs")
    client.get("/api/figures/status")
    client.get("/api/context")
    client.put(f"/api/figures/{FIGURE_ID}/code", json={"code": GOOD_PLOT})
    client.post(f"/api/figures/{FIGURE_ID}/snapshot", json={"note": "n"})
    assert client.get(f"/api/figures/{FIGURE_ID}/runs").json() == []
    assert not (workdir.root / ".index").exists()
    assert list(workdir.root.rglob("*.db")) == []
    assert list(workdir.root.rglob("*.sqlite")) == []


# ---------------------------------------------------------------- 建图门禁


def test_create_gates(client, workdir):
    # 保留名冲突（data.csv 已被占用）→ 400 列出冲突
    workdir.data_path().write_text("x\n", encoding="utf-8")
    r = client.post(f"/api/figures/{FIGURE_ID}/create", data={"requirements": "画个图"})
    assert r.status_code == 400 and "data.csv" in r.json()["detail"]
    workdir.data_path().unlink()

    # plot.py 已存在 → 409
    workdir.plot_path().write_text("# pre\n", encoding="utf-8")
    r = client.post(f"/api/figures/{FIGURE_ID}/create", data={"requirements": "画个图"})
    assert r.status_code == 409
    workdir.plot_path().unlink()


def test_create_template_fast_path_no_llm(client, workdir, monkeypatch):
    """模板 + 空 requirements = 确定性建图（不经 run_workflow，直接渲染）。"""
    def forbidden(*args, **kwargs):
        raise AssertionError("模板快速路径不得调用 AI 工作流")

    monkeypatch.setattr(figures_api, "run_workflow", forbidden)
    r = client.post(f"/api/figures/{FIGURE_ID}/create",
                    data={"requirements": "", "template": "bar-groups"})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert r.json()["rounds"] == 0
    assert workdir.has_figure() is True

    fig = _figure(client)
    assert "fa:control-bar-0" in fig["baseSvg"]  # bar-groups 模板产物
    assert 'set_gid(f"fa:control-bar' in fig["code"]  # 模板 plot.py 原文


def test_create_existing_file_from_folder(client, workdir, monkeypatch):
    """existing_file：目录内已有文件作数据源（拷进 uploads/），不弹本地上传。"""
    (workdir.root / "实验数据.csv").write_text("dose,response\n0,1\n", encoding="utf-8")

    async def fake_workflow(kind, store, spec, llm_client=None):
        assert spec["upload_name"] == "实验数据.csv"
        assert (workdir.uploads_dir() / "实验数据.csv").exists()  # 已物化进 uploads/
        return {"kind": "create", "ok": True, "rounds": 1, "stderr": ""}

    monkeypatch.setattr(figures_api, "run_workflow", fake_workflow)
    r = client.post(f"/api/figures/{FIGURE_ID}/create",
                    data={"requirements": "画曲线", "existing_file": "实验数据.csv"})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text


def test_create_existing_file_rejects_reserved(client, workdir):
    # data.csv 是保留名但非真相源（plot.py 才是），不触发 409；应被保留名检查拒绝
    workdir.data_path().write_text("x\n", encoding="utf-8")
    r = client.post(f"/api/figures/{FIGURE_ID}/create",
                    data={"requirements": "x", "existing_file": "data.csv"})
    assert r.status_code == 400 and "保留名" in r.json()["detail"]


def test_create_failure_cleans_partial_files(client, workdir, monkeypatch):
    """AI 失败且未产出 plot.py → 本次残留（data.csv/patch.json/uploads/）自动清掉，
    目录回到干净无图态，可立即重试成功。"""
    async def failing_workflow(kind, store, spec, llm_client=None):
        # 模拟工作流已写产物后失败（Standardize 写 data.csv，路由写 patch.json/uploads）
        store.workdir.data_path().write_text("a,b\n1,2\n", encoding="utf-8")
        return {"kind": "create", "ok": False, "rounds": 1, "stderr": "LLM 失败"}

    monkeypatch.setattr(figures_api, "run_workflow", failing_workflow)
    r = client.post(f"/api/figures/{FIGURE_ID}/create", data={"requirements": "画个图"})
    assert r.status_code == 200 and r.json()["ok"] is False
    assert not workdir.data_path().exists()
    assert not workdir.patch_path().exists()
    assert not workdir.uploads_dir().exists()
    assert workdir.has_figure() is False
    assert client.get("/api/context").json()["has_figure"] is False

    # 立即重试：保留名检查不再阻挡
    async def ok_workflow(kind, store, spec, llm_client=None):
        store.write_code(GOOD_PLOT)
        return {"kind": "create", "ok": True, "rounds": 1, "stderr": ""}

    monkeypatch.setattr(figures_api, "run_workflow", ok_workflow)
    r = client.post(f"/api/figures/{FIGURE_ID}/create", data={"requirements": "画个图"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert workdir.has_figure() is True


def test_create_failure_keeps_plot_py_state(client, workdir, monkeypatch):
    """渲染失败但 plot.py 已产出（真相源在）→ 保留为有图态（renderError 可改代码重试）。"""
    async def render_fail_workflow(kind, store, spec, llm_client=None):
        store.write_code("fig = 1 +\n")  # 语法错误：plot.py 写入但渲染失败
        return {"kind": "create", "ok": False, "rounds": 1, "stderr": "SyntaxError"}

    monkeypatch.setattr(figures_api, "run_workflow", render_fail_workflow)
    r = client.post(f"/api/figures/{FIGURE_ID}/create", data={"requirements": "x"})
    assert r.json()["ok"] is False
    assert workdir.has_figure() is True  # 真相源保留
    fig = _figure(client)
    assert fig["hasFigure"] is True and fig.get("renderError")


def test_create_full_flow_mock(client, workdir, monkeypatch):
    async def fake_workflow(kind, store, spec, llm_client=None):
        assert kind == "create" and spec["requirements"] == "画剂量响应"
        assert spec["upload_name"] == "d.csv"
        store.write_code(GOOD_PLOT)
        return {"kind": "create", "ok": True, "rounds": 1, "stderr": ""}

    monkeypatch.setattr(figures_api, "run_workflow", fake_workflow)
    r = client.post(f"/api/figures/{FIGURE_ID}/create",
                    data={"requirements": "画剂量响应", "template": "bar-groups"},
                    files={"upload": ("d.csv", b"dose,response\n0,1\n5,2\n", "text/csv")})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text

    # 有图 = plot.py 存在（不再回写任何属性）
    assert workdir.has_figure() is True
    assert client.get("/api/context").json()["has_figure"] is True

    # GET：懒渲染出 base/final SVG
    fig = _figure(client)
    assert fig["hasFigure"] is True
    assert "fa:title" in fig["baseSvg"] and "<svg" in fig["finalSvg"]
    assert "properties" not in fig  # 条目属性概念已删除


def test_create_failure_keeps_dir_without_figure(client, workdir, monkeypatch):
    async def failing_workflow(kind, store, spec, llm_client=None):
        return {"kind": "create", "ok": False, "rounds": 1,
                "stderr": "节点 Standardize 失败：输出格式校验失败"}

    monkeypatch.setattr(figures_api, "run_workflow", failing_workflow)
    r = client.post(f"/api/figures/{FIGURE_ID}/create", data={"requirements": "x"})
    assert r.status_code == 200 and r.json()["ok"] is False
    assert workdir.has_figure() is False  # 无 plot.py = 无图
    assert not workdir.plot_path().exists()


# ---------------------------------------------------------------- 内容管线


def test_code_run_patch_roundtrip(client, workdir):
    r = client.put(f"/api/figures/{FIGURE_ID}/code", json={"code": GOOD_PLOT})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert "fa:title" in workdir.base_svg_path().read_text(encoding="utf-8")

    r = client.post(f"/api/figures/{FIGURE_ID}/run")
    assert r.status_code == 200 and r.json()["ok"] is True

    patch = {"baseHash": "", "ops": [
        {"id": "op-1", "kind": "set_style", "target": {"id": "fa:title"},
         "attr": "font-size", "value": "20", "intent": "标题字号放大",
         "origin": "manual", "status": "active"}]}
    r = client.put(f"/api/figures/{FIGURE_ID}/patch", json=patch)
    assert r.status_code == 200 and r.json()["ok"] is True
    fig = _figure(client)
    assert fig["patch"]["ops"][0]["id"] == "op-1"
    assert 'font-size: 20' in fig["finalSvg"]

    r = client.post(f"/api/figures/{FIGURE_ID}/verify-patch")
    body = r.json()
    assert r.status_code == 200 and body["remainingOps"] == 1
    assert body["results"][0]["opId"] == "op-1"


def test_code_endpoints_without_id(client, workdir):
    assert client.put("/api/figures/code", json={"code": GOOD_PLOT}).json()["ok"] is True
    assert client.post("/api/figures/run").json()["ok"] is True
    assert client.get("/api/figures").json()["hasFigure"] is True
    assert client.post("/api/figures/verify-patch").json()["remainingOps"] == 0


def test_code_requires_body(client):
    r = client.put(f"/api/figures/{FIGURE_ID}/code", json={"nope": 1})
    assert r.status_code == 400 and "code" in r.json()["detail"]


def test_snapshot_runs_enrich(client, workdir):
    client.put(f"/api/figures/{FIGURE_ID}/code", json={"code": GOOD_PLOT})

    r = client.post(f"/api/figures/{FIGURE_ID}/snapshot", json={"note": "初版"})
    assert r.status_code == 200 and r.json()["note"] == "初版"
    fig = _figure(client)
    assert len(fig["snapshots"]) == 1 and fig["snapshots"][0]["note"] == "初版"
    snap = workdir.history_dir() / fig["snapshots"][0]["dir"].split("/")[-1]
    assert (snap / "note.txt").exists()
    assert (snap / "plot.py").exists()

    assert client.get(f"/api/figures/{FIGURE_ID}/runs").json() == []
    assert client.get("/api/figures/runs").json() == []

    r = client.post(f"/api/figures/{FIGURE_ID}/enrich-selection",
                    json={"selection": {"id": "fa:title"}})
    body = r.json()
    assert body["elementId"] == "fa:title" and body["semanticPath"].endswith("fa:title")


def test_snapshots_skip_unknown_dirs(client, workdir):
    client.put(f"/api/figures/{FIGURE_ID}/code", json={"code": GOOD_PLOT})
    client.post(f"/api/figures/{FIGURE_ID}/snapshot", json={"note": "a"})
    (workdir.history_dir() / "not-a-timestamp").mkdir()
    assert len(_figure(client)["snapshots"]) == 1


def test_instruct_requires_plot_py(client, workdir, monkeypatch):
    r = client.post(f"/api/figures/{FIGURE_ID}/instruct",
                    json={"instruction": "改色", "selection": {"id": "fa:title"}})
    assert r.status_code == 400 and "plot.py" in r.json()["detail"]

    client.put(f"/api/figures/{FIGURE_ID}/code", json={"code": GOOD_PLOT})

    async def fake_workflow(kind, store, spec, llm_client=None):
        assert kind == "edit"
        assert '"fa:title"' in spec["selection_json"]  # 选区已富化
        return {"kind": "edit", "ok": True, "rounds": 1, "stderr": ""}

    monkeypatch.setattr(figures_api, "run_workflow", fake_workflow)
    r = client.post(f"/api/figures/{FIGURE_ID}/instruct",
                    json={"instruction": "改色", "selection": {"id": "fa:title"}})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_delete_figure_cleanup(client, workdir):
    client.put(f"/api/figures/{FIGURE_ID}/code", json={"code": GOOD_PLOT})
    client.post(f"/api/figures/{FIGURE_ID}/snapshot", json={"note": "n"})

    r = client.delete(f"/api/figures/{FIGURE_ID}")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert not workdir.plot_path().exists()
    assert not workdir.base_svg_path().exists()
    assert not workdir.history_dir().exists()

    assert workdir.has_figure() is False
    assert client.get("/api/context").json()["has_figure"] is False
    assert _figure(client)["hasFigure"] is False
    assert client.delete(f"/api/figures/{FIGURE_ID}").status_code == 404


def test_status_and_templates(client, monkeypatch):
    monkeypatch.setenv("FIGUREAGENT_MOCK", "1")
    assert client.get("/api/figures/status").json()["mock"] is True
    templates = client.get("/api/figures/templates").json()
    assert {t["id"] for t in templates} >= {"bar-groups", "iris-scatter"}


def test_ws_ping_pong(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_adapt_gates_and_flow(client, workdir, monkeypatch):
    async def fake_workflow(kind, store, spec, llm_client=None):
        assert kind == "adapt" and "plt" in spec["script_text"]
        store.write_code(GOOD_PLOT)
        return {"kind": "adapt", "ok": True, "rounds": 1, "stderr": ""}

    monkeypatch.setattr(figures_api, "run_workflow", fake_workflow)
    r = client.post(f"/api/figures/{FIGURE_ID}/adapt",
                    data={"requirements": ""},
                    files={"script": ("orig_plot.py",
                                      b"import matplotlib.pyplot as plt\n",
                                      "text/x-python")})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert (workdir.uploads_dir() / "orig_plot.py").exists()
    assert workdir.has_figure() is True


def test_adapt_requires_script(client):
    r = client.post(f"/api/figures/{FIGURE_ID}/adapt", data={"requirements": ""})
    assert r.status_code == 400 and "绘图脚本" in r.json()["detail"]


# ---------------------------------------------------------------- 文件树


def test_files_tree_lists_workdir(client, workdir):
    """GET /api/files 与 POST /api/files/list 返回同一棵只读树。"""
    (workdir.root / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    sub = workdir.root / "sub"
    sub.mkdir()
    (sub / "notes.txt").write_text("hi", encoding="utf-8")

    tree = client.get("/api/files").json()
    assert tree["is_dir"] is True
    names = {c["name"] for c in tree["children"]}
    assert {"data.csv", "sub"} <= names

    data = next(c for c in tree["children"] if c["name"] == "data.csv")
    # 字节数按实际落盘算（Windows 文本写会把 \n 转成 \r\n）
    assert data["is_dir"] is False
    assert data["size"] == (workdir.root / "data.csv").stat().st_size

    sub_node = next(c for c in tree["children"] if c["name"] == "sub")
    assert any(g["name"] == "notes.txt" for g in sub_node["children"])

    # 旧端点别名：body 里的 itemId 被忽略
    alias = client.post("/api/files/list", json={"itemId": "whatever"}).json()
    assert alias == tree
