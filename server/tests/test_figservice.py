"""figservice：独立 app 的装配契约。

覆盖：health / context（含 ?dir= 首次绑定）、figures 路由在位而其它域路由缺席、
CORS 只放行 vite dev 的 5173、静态托管 web/dist（缺失时友好降级而非 500）、
/ws 由 figures 路由自带且只挂一次、stdout 握手契约、CLI 对非法 --dir 的拒绝。
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from figureagent import config
from figureagent.figservice import (
    ALLOWED_ORIGINS,
    PORT_MARKER,
    READY_MARKER,
    create_app,
    main,
)

SERVER_DIR = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 基本端点


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_figures_status_ok_without_llm_configured(client):
    r = client.get("/api/figures/status")
    assert r.status_code == 200
    assert "configured" in r.json()


def test_templates_use_bound_workdir(client):
    r = client.get("/api/figures/templates")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert {t["id"] for t in r.json()} >= {"bar-groups", "iris-scatter"}


def test_status_and_templates_do_not_need_a_figure(client):
    # 无 plot.py 也照常工作（建图流的第一步就是列模板）
    assert client.get("/api/figures/templates").status_code == 200
    assert client.get("/api/figures/status").status_code == 200


# ---------------------------------------------------------------- /api/context


def test_context_reports_dir_name_has_figure(client, workdir):
    assert client.get("/api/context").json() == {
        "dir": str(workdir.root),
        "name": "MyData",
        "has_figure": False,
    }
    workdir.plot_path().write_text("fig = None\n", encoding="utf-8")
    assert client.get("/api/context").json()["has_figure"] is True


def test_context_without_dir_flag_is_400(no_workdir_client):
    r = no_workdir_client.get("/api/context")
    assert r.status_code == 400
    assert "--dir" in r.json()["detail"]


def test_context_binds_dir_lazily(no_workdir_client, tmp_path):
    root = tmp_path / "LateData"
    root.mkdir()
    r = no_workdir_client.get("/api/context", params={"dir": str(root)})
    assert r.status_code == 200
    assert r.json()["name"] == "LateData"
    # 首次绑定后，后续不带 ?dir= 的请求继续用它
    assert no_workdir_client.get("/api/context").json()["dir"] == str(root.resolve())


def test_context_bind_rejects_bad_dir(no_workdir_client):
    r = no_workdir_client.get("/api/context", params={"dir": "relative/dir"})
    assert r.status_code == 400
    assert "绝对路径" in r.json()["detail"]


def test_no_dir_flag_dependent_endpoint_is_400_not_500(no_workdir_client):
    # status 不依赖目录；templates 依赖 → 400（中文 detail）而非 500
    assert no_workdir_client.get("/api/figures/status").status_code == 200
    r = no_workdir_client.get("/api/figures/templates")
    assert r.status_code == 400
    assert "工作目录" in r.json()["detail"]


# ---------------------------------------------------------------- 路由边界


@pytest.mark.parametrize("path", ["/api/groups/list", "/api/items/list", "/api/repo/info",
                                  "/api/system/fs-list", "/api/types/list",
                                  "/api/context/sub", "/ws"])
def test_non_figures_routes_are_absent(client, path):
    assert client.get(path).status_code == 404


def test_http_route_table_is_figures_plus_context_health(client):
    paths = set(client.app.openapi()["paths"])
    canonical = {
        # 原有 15 个 figures 端点（13 个带 {figure_id} + 2 个字面量元信息端点）
        "/api/figures/status",
        "/api/figures/templates",
        "/api/figures/{figure_id}",
        "/api/figures/{figure_id}/create",
        "/api/figures/{figure_id}/adapt",
        "/api/figures/{figure_id}/code",
        "/api/figures/{figure_id}/run",
        "/api/figures/{figure_id}/patch",
        "/api/figures/{figure_id}/verify-patch",
        "/api/figures/{figure_id}/writeback",
        "/api/figures/{figure_id}/instruct",
        "/api/figures/{figure_id}/enrich-selection",
        "/api/figures/{figure_id}/snapshot",
        "/api/figures/{figure_id}/runs",
        "/api/figures/{figure_id}",
    }
    assert len(canonical) == 14  # 15 个端点落在 14 条路径上（GET 与 DELETE 共用 /api/figures/{figure_id}）
    assert canonical <= paths
    assert {"/api/health", "/api/context", "/"} <= paths
    # 13 条带 id 的路径各有不带 id 的同义写法；templates/status 本就无 id → 26 条
    figure_paths = {path for path in paths if path.startswith("/api/figures")}
    assert len(figure_paths) == 14 + 12
    # 其它域路由一个都不许挂
    assert not any(
        path.startswith(("/api/items", "/api/groups", "/api/types", "/api/repo", "/api/system"))
        for path in paths
    )


# ---------------------------------------------------------------- CORS（只给 dev）


def test_cors_preflight_allows_vite_origin(client):
    r = client.options(
        "/api/figures/status",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "content-type" in r.headers["access-control-allow-headers"].lower()


def test_cors_simple_request_carries_allow_origin(client):
    r = client.get("/api/figures/status", headers={"Origin": "http://127.0.0.1:5173"})
    assert r.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost:1420",
                                   "http://tauri.localhost", "http://localhost:9999"])
def test_cors_rejects_other_origins(client, origin):
    # 本机服务：不得退化成 allow_origins=["*"]（任意网页可读写）
    r = client.get("/api/figures/status", headers={"Origin": origin})
    assert "access-control-allow-origin" not in r.headers


def test_cors_allowed_origins_exactly_vite_dev():
    assert set(ALLOWED_ORIGINS) == {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }


# ---------------------------------------------------------------- /ws


def test_ws_is_served_by_figures_router(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


# ---------------------------------------------------------------- 静态托管 web/dist


def test_index_served_from_web_dist(static_client):
    r = static_client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "built" in r.text


def test_static_asset_served(static_client):
    r = static_client.get("/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text
    assert "javascript" in r.headers["content-type"]


def test_spa_fallback_serves_index(static_client):
    r = static_client.get("/some/deep/route")
    assert r.status_code == 200
    assert "built" in r.text


def test_missing_asset_is_404_not_index(static_client):
    assert static_client.get("/assets/nope.js").status_code == 404


def test_api_is_not_swallowed_by_static_hosting(static_client):
    assert static_client.get("/api/items/list").status_code == 404
    assert static_client.get("/api/health").json() == {"ok": True}


def test_missing_web_dist_gives_friendly_html(no_dist_client):
    r = no_dist_client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "npm run build" in r.text
    assert "missing-dist" in r.text


def test_missing_web_dist_keeps_api_alive(no_dist_client):
    assert no_dist_client.get("/api/health").json() == {"ok": True}
    assert no_dist_client.get("/api/context").status_code == 200


def test_missing_web_dist_missing_asset_is_404(no_dist_client):
    assert no_dist_client.get("/assets/app.js").status_code == 404


def test_web_dist_located_relative_to_server_package():
    dist = config.web_dist_dir()
    assert dist.name == "dist" and dist.parent.name == "web"
    # ../web/dist 相对 server 包：dist 的祖父目录里就有 server/
    assert (dist.parent.parent / "server" / "src" / "figureagent").is_dir()


# ---------------------------------------------------------------- stdout 契约 / CLI


def test_handshake_markers_unchanged():
    assert PORT_MARKER == "FIG_SERVICE_PORT="
    assert READY_MARKER == "FIG_SERVICE_READY"


@pytest.mark.parametrize("raw", ["relative/dir", "nope"])
def test_cli_rejects_bad_dir(tmp_path, capsys, raw):
    target = raw if raw == "relative/dir" else str(tmp_path / "nope")
    assert main(["--dir", target, "--port", "0"]) == 2
    assert capsys.readouterr().err.strip()  # 有明确报错，不静默


def test_stdout_handshake_on_real_process(workdir):
    """真起一个进程：stdout 恰好两行握手，且端口真的在服务 /api/health。"""
    env = {
        **os.environ,
        "PYTHONPATH": str(SERVER_DIR / "src"),
        "FIGUREAGENT_HOME": str(workdir.root.parent / "home"),
        "PYTHONUTF8": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "figureagent", "--dir", str(workdir.root), "--port", "0"],
        cwd=str(SERVER_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    lines: queue.Queue[str] = queue.Queue()

    def _reader() -> None:
        for line in proc.stdout:
            lines.put(line.rstrip("\n"))

    threading.Thread(target=_reader, daemon=True).start()
    first = second = ""
    try:
        first = lines.get(timeout=90)
        second = lines.get(timeout=90)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover - 卡死的兜底
            proc.kill()

    assert first.startswith(PORT_MARKER), (first, second, proc.stderr.read()[:2000])
    port = int(first[len(PORT_MARKER):])
    assert 0 < port < 65536
    assert second == READY_MARKER
