"""FastAPI 应用：REST API + WS + 静态托管 web/dist（§7.1）。"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, enrich
from .ai.workflows import run_workflow
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
    # enrich-selection 端点以路径参数为准；前端旧形状 {project, figure,
    # selection} 仍可带这两个字段，故为可选
    project: str = ""
    figure: str = ""
    # 单选为对象（旧契约）；多选为对象数组
    selection: dict | list[dict] = Field(default_factory=dict)


class InstructPost(BaseModel):
    instruction: str
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


@app.get("/api/ai/status")
def ai_status():
    from .ai import llm as ai_llm

    return ai_llm.ai_status()


@app.post("/api/projects/{project}/figures")
async def create_figure(project: str, body: FigureCreate):
    try:
        outcome = store.create_figure(project, body.name, body.template)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await _notify({"type": "figure_updated", "project": project, "figure": body.name})
    return outcome


MAX_UPLOAD_BYTES = 10 * 1024 * 1024


async def _save_upload(fdir: Path, upload: UploadFile, default_name: str = "data.csv") -> str:
    name = Path(upload.filename or "").name
    if not name or name in {".", ".."}:
        name = default_name
    data = await upload.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="上传文件超过 10MB 限制")
    updir = fdir / "uploads"
    updir.mkdir(exist_ok=True)
    (updir / name).write_bytes(data)
    return name


@app.post("/api/projects/{project}/figures/ai")
async def create_figure_ai(project: str, name: str = Form(...),
                           requirements: str = Form(...),
                           data: UploadFile = File(...)):
    try:
        store.init_figure(project, name, origin="ai")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    fdir = store.figure_dir(project, name)
    try:
        upload_name = await _save_upload(fdir, data)
    except HTTPException:
        shutil.rmtree(fdir, ignore_errors=True)  # 回滚刚建的空图目录
        raise
    result = await run_workflow(
        "create", store, project, name,
        {"requirements": requirements, "upload_name": upload_name},
    )
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "project": project, "figure": name})
    return result


@app.post("/api/projects/{project}/figures/adapt")
async def adapt_figure(project: str, name: str = Form(...),
                       requirements: str = Form(""),
                       data: UploadFile = File(...),
                       script: UploadFile = File(...)):
    try:
        store.init_figure(project, name, origin="adapt")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    fdir = store.figure_dir(project, name)
    try:
        upload_name = await _save_upload(fdir, data)
        script_name = await _save_upload(fdir, script, default_name="plot.py")
        script_text = (fdir / "uploads" / script_name).read_text(encoding="utf-8",
                                                                  errors="replace")
    except HTTPException:
        shutil.rmtree(fdir, ignore_errors=True)  # 回滚刚建的空图目录
        raise
    result = await run_workflow(
        "adapt", store, project, name,
        {"requirements": requirements, "upload_name": upload_name,
         "script_text": script_text},
    )
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "project": project, "figure": name})
    return result


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


@app.post("/api/figure/{project}/{figure}/instruct")
async def instruct(project: str, figure: str, body: InstructPost):
    _figure_or_404(project, figure)
    code = _safe_code(project, figure)
    if code is None:
        raise HTTPException(status_code=400, detail="图尚无 plot.py（首次 AI 运行未成功），无法执行指令")
    items = body.selection if isinstance(body.selection, list) else [body.selection]
    enriched = [
        enrich.enrich_selection(store, project, figure, item) for item in items
    ]
    result = await run_workflow(
        "edit", store, project, figure,
        {
            "instruction": body.instruction,
            "selection_json": json.dumps(enriched, ensure_ascii=False),
            "code": code,
        },
    )
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "project": project, "figure": figure})
    return result


@app.post("/api/figure/{project}/{figure}/writeback")
async def writeback(project: str, figure: str):
    _figure_or_404(project, figure)
    result = await run_workflow("writeback", store, project, figure, {})
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "project": project, "figure": figure})
    return result


@app.post("/api/figure/{project}/{figure}/enrich-selection")
async def enrich_selection_ep(project: str, figure: str, body: SelectionPost):
    _figure_or_404(project, figure)
    items = body.selection if isinstance(body.selection, list) else [body.selection]
    enriched = [enrich.enrich_selection(store, project, figure, item) for item in items]
    return enriched if isinstance(body.selection, list) else enriched[0]


@app.get("/api/figure/{project}/{figure}/runs")
def list_runs(project: str, figure: str):
    _figure_or_404(project, figure)
    path = store.figure_dir(project, figure) / "runs.jsonl"
    if not path.exists():
        return []
    out = []
    # read_bytes+replace 解码：并发写 runs.jsonl 时 read_text 可能撕裂多字节
    # UTF-8 序列导致 UnicodeDecodeError → 500
    for line in path.read_bytes().decode("utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(out))


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
