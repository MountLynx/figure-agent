"""figures 域路由：图内容管线 + AI 工作流 + WS 广播。

**独立服务**：只认一个工作目录（``--dir``，或未指定时的 ``?dir=``）。路径里的
``{figure_id}`` 仅为了保持 ``/api/figures/*`` 的原有形状而保留，服务端**忽略其值**
（一个目录只有一张图）；同时提供不带该段的同义路由（``/api/figures/code`` 等），
前端两种写法都可用。

端点（15 个 + ``/ws``）：
    GET    /api/figures/status
    GET    /api/figures/templates
    POST   /api/figures/{figure_id}/create
    POST   /api/figures/{figure_id}/adapt
    GET    /api/figures/{figure_id}
    PUT    /api/figures/{figure_id}/code
    POST   /api/figures/{figure_id}/run
    PUT    /api/figures/{figure_id}/patch
    POST   /api/figures/{figure_id}/verify-patch
    POST   /api/figures/{figure_id}/writeback
    POST   /api/figures/{figure_id}/instruct
    POST   /api/figures/{figure_id}/enrich-selection
    POST   /api/figures/{figure_id}/snapshot
    GET    /api/figures/{figure_id}/runs
    DELETE /api/figures/{figure_id}
    WS     /ws

不再有任何条目概念：没有「读条目详情」「校验条目类型」「回写是否有图」——
「是否有图」由 ``FigureStore.has_figure()``（plot.py 存在）判定，Index 侧自行看文件。
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse

from ..config import render_timeout
from ..figure_guard import RESERVED_DIRS, RESERVED_NAMES
from ..figures import enrich
from ..figures.ai.workflows import run_workflow
from ..figures.events import hub
from ..figures.store import FigureStore
from ..safe_path import safe_path
from ..workdir import Workdir
from .deps import get_workdir

router = APIRouter()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _store(workdir: Workdir = Depends(get_workdir)) -> FigureStore:
    return FigureStore(workdir, render_timeout())


async def _notify(store: FigureStore, event: dict) -> None:
    """向 /ws 广播（``dir`` 标识是哪个工作目录，等同 /api/context 的 dir）。"""
    await hub.broadcast({"dir": str(store.workdir.root), **event})


async def _save_upload(workdir: Workdir, upload: UploadFile,
                       default_name: str = "data.csv") -> str:
    name = Path(upload.filename or "").name
    if not name or name in {".", ".."}:
        name = default_name
    data = await upload.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="上传文件超过 10MB 限制")
    updir = safe_path(workdir.root, "uploads")
    updir.mkdir(parents=True, exist_ok=True)
    safe_path(workdir.root, f"uploads/{name}").write_bytes(data)
    return name


def _materialize_existing(workdir: Workdir, rel: str) -> str:
    """目录内已有文件 → uploads/<basename>（AI 工作流只认 uploads/ 下的文件）。

    rel 为工作目录内相对路径（safe_path 守卫）；保留名文件不可作为数据源。
    """
    src = safe_path(workdir.root, rel)
    if not src.is_file():
        raise HTTPException(status_code=400, detail=f"文件不存在：{rel}")
    first = Path(rel.replace("\\", "/")).parts[0]
    if first in RESERVED_NAMES or first in RESERVED_DIRS:
        raise HTTPException(status_code=400, detail=f"图表保留名不可作为数据源：{rel}")
    if src.stat().st_size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="文件超过 10MB 限制")
    updir = safe_path(workdir.root, "uploads")
    updir.mkdir(parents=True, exist_ok=True)
    dst = updir / Path(rel.replace("\\", "/")).name
    shutil.copy2(src, dst)
    return dst.name


def _safe_code(store: FigureStore) -> str | None:
    try:
        return store.read_code()
    except (OSError, ValueError):
        return None


def _cleanup_failed_attempt(store: FigureStore) -> None:
    """建图/adapt 失败且未产出 plot.py → 清掉本次残留（data.csv/patch.json/uploads/
    等），回到干净无图态可立即重试。plot.py 在（代码已产出、渲染失败）则保留——
    那是有图状态，工作台可手动改代码重渲染。保留名检查已保证失败前目录无保留名
    文件，此处清理不会触及用户附件。"""
    if not store.has_figure():
        store.delete_figure_files()


def _render_response(outcome) -> dict:
    return {
        "ok": outcome.ok,
        "stderr": outcome.stderr,
        "errorLine": outcome.error_line,
        "warnings": outcome.warnings or [],
        "stats": outcome.stats or {},
    }


# ---------------------------------------------------------------- 元信息


@router.get("/api/figures/status")
def figures_status():
    from ..figures.ai import llm as ai_llm

    return ai_llm.ai_status()


@router.get("/api/figures/templates")
def figures_templates(store: FigureStore = Depends(_store)):
    return store.templates()


@router.get("/api/figures/{figure_id}/runs")
@router.get("/api/figures/runs")
def runs_ep(figure_id: str = "", store: FigureStore = Depends(_store),
            workdir: Workdir = Depends(get_workdir)):
    """AI 运行审计（history/runs.jsonl，新的在前）。

    注意：字面量路由必须排在 ``GET /api/figures/{figure_id}`` 之前，否则
    ``/api/figures/runs`` 会被通配段吃掉。
    """
    return store.list_runs()


# ---------------------------------------------------------------- 建图


@router.post("/api/figures/{figure_id}/create")
@router.post("/api/figures/create")
async def create_figure(figure_id: str = "",
                        requirements: str = Form(""),
                        template: str = Form(""),
                        existing_file: str = Form(""),
                        upload: UploadFile | None = File(None),
                        store: FigureStore = Depends(_store),
                        workdir: Workdir = Depends(get_workdir)):
    if store.has_figure():
        raise HTTPException(status_code=409,
                            detail=f"该目录已有图表：{workdir.name()}")
    conflicts = store.reserved_conflicts()
    if conflicts:
        raise HTTPException(status_code=400,
                            detail=f"保留名已被占用，无法创建图表：{'、'.join(conflicts)}")
    upload_name = None
    if existing_file:
        upload_name = _materialize_existing(workdir, existing_file)
    elif upload is not None:
        upload_name = await _save_upload(workdir, upload)

    # 模板快速路径：模板 + 空 requirements = 确定性建图（脚手架 + 渲染，不经 LLM）
    if template and not requirements.strip():
        store.create_figure_files(template=template)
        outcome = await asyncio.to_thread(store.render)
        await _notify(store, {"type": "figure_updated" if outcome.ok else "render_error",
                              "stderr": outcome.stderr})
        return {"kind": "create", "ok": outcome.ok, "rounds": 0, "stderr": outcome.stderr}

    store.create_figure_files()
    result = await run_workflow(
        "create", store,
        {"requirements": requirements, "upload_name": upload_name},
    )
    if not result.get("ok"):
        _cleanup_failed_attempt(store)
    await _notify(store, {"type": "figure_updated" if result.get("ok") else "render_error"})
    return result


@router.post("/api/figures/{figure_id}/adapt")
@router.post("/api/figures/adapt")
async def adapt_figure(figure_id: str = "",
                       existing_script: str = Form(""),
                       existing_data: str = Form(""),
                       script: UploadFile | None = File(None),
                       upload: UploadFile | None = File(None),
                       requirements: str = Form(""),
                       store: FigureStore = Depends(_store),
                       workdir: Workdir = Depends(get_workdir)):
    if store.has_figure():
        raise HTTPException(status_code=409,
                            detail=f"该目录已有图表：{workdir.name()}")
    conflicts = store.reserved_conflicts()
    if conflicts:
        raise HTTPException(status_code=400,
                            detail=f"保留名已被占用，无法创建图表：{'、'.join(conflicts)}")
    upload_name = None
    if existing_data:
        upload_name = _materialize_existing(workdir, existing_data)
    elif upload is not None:
        upload_name = await _save_upload(workdir, upload)
    if existing_script:
        script_src = safe_path(workdir.root, existing_script)
        if not script_src.is_file():
            raise HTTPException(status_code=400, detail=f"文件不存在：{existing_script}")
        script_text = script_src.read_text(encoding="utf-8", errors="replace")
        _materialize_existing(workdir, existing_script)
    else:
        if script is None:
            raise HTTPException(status_code=400, detail="缺少绘图脚本（existing_script 或 script 文件）")
        script_name = await _save_upload(workdir, script, default_name="plot.py")
        script_text = safe_path(workdir.root, f"uploads/{script_name}").read_text(
            encoding="utf-8", errors="replace")
    result = await run_workflow(
        "adapt", store,
        {"requirements": requirements, "upload_name": upload_name,
         "script_text": script_text},
    )
    if not result.get("ok"):
        _cleanup_failed_attempt(store)
    await _notify(store, {"type": "figure_updated" if result.get("ok") else "render_error"})
    return result


# ---------------------------------------------------------------- 图状态/内容管线


@router.get("/api/figures/{figure_id}")
@router.get("/api/figures")
def get_figure(figure_id: str = "",
               store: FigureStore = Depends(_store),
               workdir: Workdir = Depends(get_workdir)):
    base = {
        "hasFigure": store.has_figure(),
        "id": figure_id or workdir.name(),
        "name": workdir.name(),
        "dir": str(workdir.root),
    }
    if not base["hasFigure"]:
        # 目录里没有 plot.py 一律视为无图（工作台据此呈现建图流）
        return base
    base.update({
        "patch": store.read_patch() or {"baseHash": "", "ops": []},
        "snapshots": store.snapshots(),
    })
    if not workdir.base_svg_path().exists():
        # 懒渲染：首次访问时渲染
        outcome = store.render()
        if not outcome.ok:
            return JSONResponse({
                **base, "code": _safe_code(store),
                "baseSvg": None, "finalSvg": None,
                "renderError": outcome.stderr,
            })
    return {
        **base,
        "code": _safe_code(store),
        "baseSvg": store.read_svg("base"),
        "finalSvg": store.read_svg("final"),
    }


@router.put("/api/figures/{figure_id}/code")
@router.put("/api/figures/code")
async def put_code(body: dict, figure_id: str = "",
                   store: FigureStore = Depends(_store),
                   workdir: Workdir = Depends(get_workdir)):
    code = body.get("code") if isinstance(body, dict) else None
    if not isinstance(code, str):
        raise HTTPException(status_code=400, detail="请求体需为 {code: str}")
    outcome = await asyncio.to_thread(store.write_code, code)
    await _notify(store, {"type": "figure_updated" if outcome.ok else "render_error",
                          "stderr": outcome.stderr})
    return _render_response(outcome)


@router.post("/api/figures/{figure_id}/run")
@router.post("/api/figures/run")
async def run_figure(figure_id: str = "", store: FigureStore = Depends(_store),
                     workdir: Workdir = Depends(get_workdir)):
    outcome = await asyncio.to_thread(store.render)
    await _notify(store, {"type": "figure_updated" if outcome.ok else "render_error",
                          "stderr": outcome.stderr})
    return _render_response(outcome)


@router.put("/api/figures/{figure_id}/patch")
@router.put("/api/figures/patch")
async def put_patch(body: dict, figure_id: str = "",
                    store: FigureStore = Depends(_store),
                    workdir: Workdir = Depends(get_workdir)):
    if not isinstance(body, dict) or "ops" not in body:
        raise HTTPException(status_code=400, detail="patch 需为 {baseHash, ops} 结构")
    result = await asyncio.to_thread(store.save_patch, body)
    await _notify(store, {"type": "figure_updated"})
    return result


@router.post("/api/figures/{figure_id}/verify-patch")
@router.post("/api/figures/verify-patch")
async def verify_patch_ep(figure_id: str = "", store: FigureStore = Depends(_store),
                          workdir: Workdir = Depends(get_workdir)):
    result = await asyncio.to_thread(store.verify_patch)
    await _notify(store, {"type": "figure_updated"})
    return result


@router.post("/api/figures/{figure_id}/writeback")
@router.post("/api/figures/writeback")
async def writeback_ep(figure_id: str = "", store: FigureStore = Depends(_store),
                       workdir: Workdir = Depends(get_workdir)):
    result = await run_workflow("writeback", store, {})
    await _notify(store, {"type": "figure_updated" if result.get("ok") else "render_error"})
    return result


@router.post("/api/figures/{figure_id}/instruct")
@router.post("/api/figures/instruct")
async def instruct_ep(body: dict, figure_id: str = "",
                      store: FigureStore = Depends(_store),
                      workdir: Workdir = Depends(get_workdir)):
    instruction = body.get("instruction") if isinstance(body, dict) else None
    selection = body.get("selection") if isinstance(body, dict) else None
    if not isinstance(instruction, str) or not instruction:
        raise HTTPException(status_code=400, detail="请求体需为 {instruction: str, selection}")
    code = _safe_code(store)
    if code is None:
        raise HTTPException(status_code=400, detail="图尚无 plot.py（首次 AI 运行未成功），无法执行指令")
    items = selection if isinstance(selection, list) else [selection]
    enriched = [enrich.enrich_selection(store, item) for item in items]
    result = await run_workflow(
        "edit", store,
        {
            "instruction": instruction,
            "selection_json": json.dumps(enriched, ensure_ascii=False),
            "code": code,
        },
    )
    await _notify(store, {"type": "figure_updated" if result.get("ok") else "render_error"})
    return result


@router.post("/api/figures/{figure_id}/enrich-selection")
@router.post("/api/figures/enrich-selection")
async def enrich_selection_ep(body: dict, figure_id: str = "",
                              store: FigureStore = Depends(_store),
                              workdir: Workdir = Depends(get_workdir)):
    selection = body.get("selection") if isinstance(body, dict) else None
    items = selection if isinstance(selection, list) else [selection]
    enriched = [enrich.enrich_selection(store, item) for item in items]
    return enriched if isinstance(selection, list) else enriched[0]


# ---------------------------------------------------------------- 快照/审计/删图


@router.post("/api/figures/{figure_id}/snapshot")
@router.post("/api/figures/snapshot")
async def snapshot_ep(body: dict, figure_id: str = "",
                      store: FigureStore = Depends(_store),
                      workdir: Workdir = Depends(get_workdir)):
    note = body.get("note", "") if isinstance(body, dict) else ""
    return store.snapshot(note if isinstance(note, str) else "")


@router.delete("/api/figures/{figure_id}")
@router.delete("/api/figures")
async def delete_figure_ep(figure_id: str = "", store: FigureStore = Depends(_store),
                           workdir: Workdir = Depends(get_workdir)):
    if not store.has_figure():
        raise HTTPException(status_code=404, detail="该目录没有图表")
    store.delete_figure_files()
    store.delete_runs()
    store.delete_snapshots()
    await _notify(store, {"type": "figure_deleted"})
    return {"ok": True}


# ---------------------------------------------------------------- 文件树（只读）


_MAX_TREE_DEPTH = 8


def _tree(path: Path, depth: int = 0) -> dict:
    """目录树 → {name, is_dir, children[]}（文件带 size）；跳过符号链接与不可读项。"""
    children: list[dict] = []
    if depth < _MAX_TREE_DEPTH:
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            entries = []
        for entry in entries:
            if entry.is_symlink():
                continue
            try:
                if entry.is_dir():
                    children.append(_tree(entry, depth + 1))
                else:
                    children.append({
                        "name": entry.name,
                        "is_dir": False,
                        "size": entry.stat().st_size,
                    })
            except OSError:
                continue
    return {"name": path.name, "is_dir": True, "children": children}


@router.get("/api/files")
@router.post("/api/files/list")
def list_files(workdir: Workdir = Depends(get_workdir)) -> dict:
    """工作目录的只读文件树。

    建图流用它挑「目录内已有的数据/脚本」，右栏用它列附件；`POST` 形态是旧
    `files/list` 的别名（请求体里的 itemId 忽略——独立版没有条目概念）。
    """
    return _tree(workdir.root)


# ---------------------------------------------------------------- WebSocket


@router.websocket("/ws")
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
