"""FastAPI 应用：REST API + WS + 静态托管 web/dist（§7.1）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, session
from .events import hub
from .store import Store

app = FastAPI(title="figure-agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = Store(config.workspace_dir(), render_timeout=config.render_timeout())


# ---------------------------------------------------------------- 模型


class CodePut(BaseModel):
    code: str


class SelectionPost(BaseModel):
    project: str
    figure: str
    # 单选为对象（旧契约）；多选为对象数组
    selection: dict | list[dict] = Field(default_factory=dict)


class SnapshotPost(BaseModel):
    note: str = ""


class FigureCreate(BaseModel):
    name: str
    template: str = "bar-groups"


def _figure_or_404(project: str, figure: str) -> Path:
    fdir = store.figure_dir(project, figure)
    if not fdir.is_dir():
        raise HTTPException(status_code=404, detail=f"图不存在：{project}/{figure}")
    return fdir


async def _notify(event: dict) -> None:
    await hub.broadcast(event)


# ---------------------------------------------------------------- API


@app.get("/api/projects")
def list_projects():
    return store.projects()


@app.get("/api/projects/{project}")
def list_figures(project: str):
    return store.figures(project)


@app.get("/api/templates")
def list_templates():
    return store.templates()


@app.post("/api/projects/{project}/figures")
async def create_figure(project: str, body: FigureCreate):
    try:
        outcome = store.create_figure(project, body.name, body.template)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await _notify({"type": "figure_updated", "project": project, "figure": body.name})
    return outcome


@app.get("/api/figure/{project}/{figure}")
def get_figure(project: str, figure: str):
    _figure_or_404(project, figure)
    if not (store.figure_dir(project, figure) / "base.svg").exists():
        # 懒渲染：repo 里不提交 base.svg，首次访问时渲染
        outcome = store.render(project, figure)
        if not outcome.ok:
            meta = store.read_meta(project, figure) or {}
            return JSONResponse(
                {
                    "project": project,
                    "figure": figure,
                    "meta": meta,
                    "baseSvg": None,
                    "finalSvg": None,
                    "patch": store.read_patch(project, figure),
                    "snapshots": store.snapshots(project, figure),
                    "renderError": outcome.stderr,
                }
            )
    return {
        "project": project,
        "figure": figure,
        "meta": store.read_meta(project, figure),
        "code": _safe_code(project, figure),
        "baseSvg": store.read_svg(project, figure, "base"),
        "finalSvg": store.read_svg(project, figure, "final"),
        "patch": store.read_patch(project, figure) or {"baseHash": "", "ops": []},
        "snapshots": store.snapshots(project, figure),
    }


def _safe_code(project: str, figure: str) -> str | None:
    try:
        return store.read_code(project, figure)
    except (OSError, ValueError):
        return None


@app.put("/api/figure/{project}/{figure}/code")
async def put_code(project: str, figure: str, body: CodePut):
    _figure_or_404(project, figure)
    outcome = await asyncio.to_thread(store.write_code, project, figure, body.code)
    await _notify(
        {
            "type": "figure_updated" if outcome.ok else "render_error",
            "project": project,
            "figure": figure,
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


@app.post("/api/figure/{project}/{figure}/run")
async def run_figure(project: str, figure: str):
    _figure_or_404(project, figure)
    outcome = await asyncio.to_thread(store.render, project, figure)
    await _notify(
        {
            "type": "figure_updated" if outcome.ok else "render_error",
            "project": project,
            "figure": figure,
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


@app.put("/api/figure/{project}/{figure}/patch")
async def put_patch(project: str, figure: str, body: dict):
    _figure_or_404(project, figure)
    if not isinstance(body, dict) or "ops" not in body:
        raise HTTPException(status_code=400, detail="patch 需为 {baseHash, ops} 结构")
    result = await asyncio.to_thread(store.save_patch, project, figure, body)
    await _notify({"type": "figure_updated", "project": project, "figure": figure})
    return result


@app.post("/api/figure/{project}/{figure}/verify-patch")
async def verify_patch(project: str, figure: str):
    _figure_or_404(project, figure)
    result = await asyncio.to_thread(store.verify_patch, project, figure)
    await _notify({"type": "figure_updated", "project": project, "figure": figure})
    return result


@app.post("/api/figure/{project}/{figure}/snapshot")
async def snapshot(project: str, figure: str, body: SnapshotPost):
    _figure_or_404(project, figure)
    return store.snapshot(project, figure, body.note)


@app.post("/api/session/selection")
async def post_selection(body: SelectionPost):
    _figure_or_404(body.project, body.figure)
    return session.save_selection(store, body.project, body.figure, body.selection)


@app.get("/api/session/selection")
def get_selection(project: str | None = None, figure: str | None = None):
    sel = session.get_selection(project, figure)
    if sel is None:
        return {"selection": None, "hint": "当前没有选区。在浏览器里点选或框选图形元素后，ZCode 可用 fa_get_selection 读取。"}
    return {"selection": sel}


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
