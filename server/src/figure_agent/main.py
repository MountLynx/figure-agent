"""FastAPI 应用：Index 仓库管理 API + 图内容管线 + WS + 静态托管 web/dist。

管理语义（条目/分组/标签/类型/主题状态）全部经 figure_agent.repo 走
index.db；图内容（plot.py/svg/patch/快照载荷/uploads）走条目文件夹。
旧 project/figure 寻址已废除，统一 item_id（12 位哈希）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import config, enrich
from .ai.workflows import run_workflow
from .events import hub
from .repo import groups as repo_groups
from .repo import items as repo_items
from .repo import runs as repo_runs
from .repo import tags as repo_tags
from .repo import types as repo_types
from .repo.groups import _UNSET
from .repo.items import ID_RE
from .store import Store

app = FastAPI(title="figure-agent", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = Store(config.workspace_dir(), render_timeout=config.render_timeout())
repo = store.repo


# ---------------------------------------------------------------- 模型


class CodePut(BaseModel):
    code: str


class ItemCreate(BaseModel):
    name: str
    groupId: int | None = None
    template: str | None = None
    origin: str = "template"


class ItemPatch(BaseModel):
    name: str | None = None
    properties: dict | None = None


class GroupCreate(BaseModel):
    name: str
    parentId: int | None = None
    position: int = 0


class GroupPatch(BaseModel):
    name: str | None = None
    parentId: int | None = None
    position: int | None = None


class TagCreate(BaseModel):
    name: str


class TypeCreate(BaseModel):
    name: str
    icon: str = "file"


class FieldCreate(BaseModel):
    name: str
    fieldType: str = "text"
    label: str = ""


class FieldPatch(BaseModel):
    name: str | None = None
    fieldType: str | None = None
    label: str | None = None
    position: int | None = None


class BindBody(BaseModel):
    id: int


class StatePut(BaseModel):
    # extra="allow"：shell 设置键（activePresetId、notes_enabled、
    # create_folder_by_default、remember_last_type、locale…）原样透传落盘，
    # 不再被未声明字段静默丢弃；theme 仍是唯一具名键
    model_config = ConfigDict(extra="allow")

    theme: str | None = None


class SelectionPost(BaseModel):
    selection: dict | list[dict] = Field(default_factory=dict)


class InstructPost(BaseModel):
    instruction: str
    selection: dict | list[dict] = Field(default_factory=dict)


class SnapshotPost(BaseModel):
    note: str = ""


def _item_or_404(item_id: str) -> dict:
    # fullmatch 与 repo_items.require_id 同口径：match+$ 容忍尾 \n，会让
    # require_id 在 get_item 内抛 ValueError 变 500，而非预期 404
    if not ID_RE.fullmatch(item_id or ""):
        raise HTTPException(status_code=404, detail=f"图不存在：{item_id}")
    item = repo_items.get_item(repo, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"图不存在：{item_id}")
    return item


def _bind_fields(item: dict) -> dict:
    """补 groupIds/tags：get_item 返回裸行（绑定字段只有 list_items 组装），
    单图详情按同 SQL 补齐，避免为一张图全量列表。"""
    with repo.conn() as c:
        item["groupIds"] = [r[0] for r in c.execute(
            "SELECT group_id FROM item_groups WHERE item_id = ? ORDER BY group_id",
            (item["id"],))]
        item["tags"] = [r[0] for r in c.execute(
            "SELECT tg.name FROM item_tags it JOIN tags tg ON tg.id = it.tag_id"
            " WHERE it.item_id = ? ORDER BY tg.name", (item["id"],))]
    return item


def _fdir_or_404(item_id: str) -> Path:
    _item_or_404(item_id)
    fdir = store.figure_dir(item_id)
    if not fdir.is_dir():
        raise HTTPException(status_code=404,
                            detail=f"图文件夹缺失（可能在 Index 中被删除）：{item_id}")
    return fdir


def _require_group(group_id: int | None) -> None:
    """建图前置校验分组存在：create_figure 的 bind_group 在回滚块之外，
    幽灵 groupId 会留下孤儿图（item+文件夹已建才抛 ValueError）。"""
    if group_id is not None and not any(
        g["id"] == group_id for g in repo_groups.list_groups(repo)
    ):
        raise HTTPException(status_code=400, detail=f"分组不存在：{group_id}")


async def _notify(event: dict) -> None:
    await hub.broadcast(event)


# ---------------------------------------------------------------- 仓库


@app.get("/api/repo/info")
def repo_info():
    return repo.info()


@app.get("/api/repo/state")
def get_state():
    return repo.read_state()


@app.put("/api/repo/state")
def put_state(body: StatePut):
    # theme 沿用旧行为（None 不落盘）；extra 键原样透传，含 null（shell 依赖
    # 显式 null 清除设置，如 setActivePreset(null)）
    dumped = body.model_dump()
    return repo.write_state({k: v for k, v in dumped.items() if k != "theme" or v is not None})


# ---------------------------------------------------------------- 条目/管理语义


@app.get("/api/items")
def list_items(q: str = "", groupId: int | None = None, tagId: int | None = None):
    return store.list_figures(q=q or None, group_id=groupId, tag_id=tagId)


@app.post("/api/items")
async def create_item(body: ItemCreate):
    _require_group(body.groupId)
    try:
        result = store.create_figure(body.name, template=body.template,
                                     origin=body.origin, group_id=body.groupId)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await _notify({"type": "figure_updated", "item": result["id"]})
    return result


@app.patch("/api/items/{item_id}")
async def patch_item(item_id: str, body: ItemPatch):
    _item_or_404(item_id)
    try:
        if body.name is not None:
            store.rename_figure(item_id, body.name)
        if body.properties is not None:
            repo_items.update_item(repo, item_id, properties=body.properties)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await _notify({"type": "figure_updated", "item": item_id})
    return repo_items.get_item(repo, item_id)


@app.delete("/api/items/{item_id}")
async def delete_item(item_id: str):
    _item_or_404(item_id)
    store.delete_figure(item_id)
    await _notify({"type": "figure_deleted", "item": item_id})
    return {"ok": True}


@app.post("/api/items/{item_id}/groups")
async def bind_group_ep(item_id: str, body: BindBody):
    _item_or_404(item_id)
    try:
        repo_items.bind_group(repo, item_id, body.id)
    except ValueError as exc:  # 幽灵分组 id
        raise HTTPException(status_code=400, detail=str(exc))
    await _notify({"type": "figure_updated", "item": item_id})
    return {"ok": True}


@app.delete("/api/items/{item_id}/groups")
async def unbind_group_ep(item_id: str, id: int = Query()):
    _item_or_404(item_id)
    repo_items.unbind_group(repo, item_id, id)
    await _notify({"type": "figure_updated", "item": item_id})
    return {"ok": True}


@app.post("/api/items/{item_id}/tags")
async def bind_tag_ep(item_id: str, body: BindBody):
    _item_or_404(item_id)
    try:
        repo_items.bind_tag(repo, item_id, body.id)
    except ValueError as exc:  # 幽灵标签 id
        raise HTTPException(status_code=400, detail=str(exc))
    await _notify({"type": "figure_updated", "item": item_id})
    return {"ok": True}


@app.delete("/api/items/{item_id}/tags")
async def unbind_tag_ep(item_id: str, id: int = Query()):
    _item_or_404(item_id)
    repo_items.unbind_tag(repo, item_id, id)
    await _notify({"type": "figure_updated", "item": item_id})
    return {"ok": True}


@app.get("/api/groups")
def list_groups():
    return repo_groups.list_groups(repo)


@app.post("/api/groups")
async def create_group(body: GroupCreate):
    try:
        return repo_groups.create_group(repo, body.name, body.parentId, body.position)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/api/groups/{group_id}")
async def patch_group(group_id: int, body: GroupPatch):
    # parent_id 用哨兵区分「未传（不改）」与「显式 null（移到根）」——
    # 直接透传 body.parentId 会把只改名的 PATCH 误解成移到根
    patch = body.model_dump(exclude_unset=True)
    try:
        return repo_groups.update_group(
            repo, group_id,
            name=patch.get("name"),
            parent_id=patch["parentId"] if "parentId" in patch else _UNSET,
            position=patch.get("position"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/api/groups/{group_id}")
async def delete_group(group_id: int):
    try:
        repo_groups.delete_group(repo, group_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@app.get("/api/tags")
def list_tags():
    return repo_tags.list_tags(repo)


@app.post("/api/tags")
async def create_tag(body: TagCreate):
    try:
        return repo_tags.create_tag(repo, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/tags/{tag_id}")
async def delete_tag(tag_id: int):
    try:
        repo_tags.delete_tag(repo, tag_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@app.get("/api/types")
def list_types():
    return repo_types.list_types(repo)


@app.post("/api/types")
async def create_type(body: TypeCreate):
    try:
        return repo_types.create_type(repo, body.name, body.icon)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/types/{type_id}")
async def delete_type(type_id: int):
    try:
        repo_types.delete_type(repo, type_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.post("/api/types/{type_id}/fields")
async def add_field(type_id: int, body: FieldCreate):
    try:
        return repo_types.add_field(repo, type_id, body.name, body.fieldType, body.label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.patch("/api/types/{type_id}/fields/{field_id}")
async def patch_field(type_id: int, field_id: int, body: FieldPatch):
    try:
        repo_types.update_field(repo, field_id, body.name, body.fieldType,
                                body.label, body.position)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


@app.delete("/api/types/{type_id}/fields/{field_id}")
async def remove_field(type_id: int, field_id: int):
    try:
        repo_types.remove_field(repo, field_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True}


# ---------------------------------------------------------------- 模板/AI 状态


@app.get("/api/templates")
def list_templates():
    return store.templates()


@app.get("/api/ai/status")
def ai_status():
    from .ai import llm as ai_llm

    return ai_llm.ai_status()


# ---------------------------------------------------------------- 图内容管线

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


@app.post("/api/figures/ai")
async def create_figure_ai(name: str = Form(...), requirements: str = Form(...),
                           groupId: int | None = Form(None),
                           data: UploadFile = File(...)):
    _require_group(groupId)
    try:
        created = store.create_figure(name, origin="ai", group_id=groupId)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    item_id = created["id"]
    try:
        upload_name = await _save_upload(store.figure_dir(item_id), data)
    except HTTPException:
        store.delete_figure(item_id)  # 回滚刚建的空图
        raise
    result = await run_workflow(
        "create", store, item_id,
        {"requirements": requirements, "upload_name": upload_name},
    )
    result["id"] = item_id
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "item": item_id})
    return result


@app.post("/api/figures/adapt")
async def adapt_figure(name: str = Form(...), requirements: str = Form(""),
                       groupId: int | None = Form(None),
                       data: UploadFile = File(...),
                       script: UploadFile = File(...)):
    _require_group(groupId)
    try:
        created = store.create_figure(name, origin="adapt", group_id=groupId)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    item_id = created["id"]
    try:
        upload_name = await _save_upload(store.figure_dir(item_id), data)
        script_name = await _save_upload(store.figure_dir(item_id), script,
                                         default_name="plot.py")
        script_text = (store.figure_dir(item_id) / "uploads" / script_name).read_text(
            encoding="utf-8", errors="replace")
    except HTTPException:
        store.delete_figure(item_id)  # 回滚刚建的空图
        raise
    result = await run_workflow(
        "adapt", store, item_id,
        {"requirements": requirements, "upload_name": upload_name,
         "script_text": script_text},
    )
    result["id"] = item_id
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "item": item_id})
    return result


@app.get("/api/figures/{item_id}")
def get_figure(item_id: str):
    _fdir_or_404(item_id)
    item = _bind_fields(repo_items.get_item(repo, item_id))
    base = {
        "id": item_id,
        "name": item["name"],
        "properties": item["properties"],
        "groupIds": item["groupIds"],
        "tags": item["tags"],
        "patch": store.read_patch(item_id) or {"baseHash": "", "ops": []},
        "snapshots": store.snapshots(item_id),
    }
    if not (store.figure_dir(item_id) / "base.svg").exists():
        # 懒渲染：首次访问时渲染
        outcome = store.render(item_id)
        if not outcome.ok:
            return JSONResponse({
                **base, "code": _safe_code(item_id),
                "baseSvg": None, "finalSvg": None,
                "renderError": outcome.stderr,
            })
    return {
        **base,
        "code": _safe_code(item_id),
        "baseSvg": store.read_svg(item_id, "base"),
        "finalSvg": store.read_svg(item_id, "final"),
    }


def _safe_code(item_id: str) -> str | None:
    try:
        return store.read_code(item_id)
    except (OSError, ValueError):
        return None


@app.put("/api/figures/{item_id}/code")
async def put_code(item_id: str, body: CodePut):
    _fdir_or_404(item_id)
    outcome = await asyncio.to_thread(store.write_code, item_id, body.code)
    await _notify(
        {
            "type": "figure_updated" if outcome.ok else "render_error",
            "item": item_id,
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


@app.post("/api/figures/{item_id}/run")
async def run_figure(item_id: str):
    _fdir_or_404(item_id)
    outcome = await asyncio.to_thread(store.render, item_id)
    await _notify(
        {
            "type": "figure_updated" if outcome.ok else "render_error",
            "item": item_id,
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


@app.put("/api/figures/{item_id}/patch")
async def put_patch(item_id: str, body: dict):
    _fdir_or_404(item_id)
    if not isinstance(body, dict) or "ops" not in body:
        raise HTTPException(status_code=400, detail="patch 需为 {baseHash, ops} 结构")
    result = await asyncio.to_thread(store.save_patch, item_id, body)
    await _notify({"type": "figure_updated", "item": item_id})
    return result


@app.post("/api/figures/{item_id}/verify-patch")
async def verify_patch(item_id: str):
    _fdir_or_404(item_id)
    result = await asyncio.to_thread(store.verify_patch, item_id)
    await _notify({"type": "figure_updated", "item": item_id})
    return result


@app.post("/api/figures/{item_id}/snapshot")
async def snapshot(item_id: str, body: SnapshotPost):
    _fdir_or_404(item_id)
    return store.snapshot(item_id, body.note)


@app.get("/api/figures/{item_id}/runs")
def list_runs(item_id: str):
    _item_or_404(item_id)
    return repo_runs.list_runs(repo, item_id)


@app.get("/api/figures/{item_id}/files")
def list_files(item_id: str):
    _fdir_or_404(item_id)
    return store.read_files(item_id)


@app.post("/api/figures/{item_id}/instruct")
async def instruct(item_id: str, body: InstructPost):
    _fdir_or_404(item_id)
    code = _safe_code(item_id)
    if code is None:
        raise HTTPException(status_code=400, detail="图尚无 plot.py（首次 AI 运行未成功），无法执行指令")
    items = body.selection if isinstance(body.selection, list) else [body.selection]
    enriched = [
        enrich.enrich_selection(store, item_id, item) for item in items
    ]
    result = await run_workflow(
        "edit", store, item_id,
        {
            "instruction": body.instruction,
            "selection_json": json.dumps(enriched, ensure_ascii=False),
            "code": code,
        },
    )
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "item": item_id})
    return result


@app.post("/api/figures/{item_id}/writeback")
async def writeback(item_id: str):
    _fdir_or_404(item_id)
    result = await run_workflow("writeback", store, item_id, {})
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "item": item_id})
    return result


@app.post("/api/figures/{item_id}/enrich-selection")
async def enrich_selection_ep(item_id: str, body: SelectionPost):
    _fdir_or_404(item_id)
    items = body.selection if isinstance(body.selection, list) else [body.selection]
    enriched = [enrich.enrich_selection(store, item_id, item) for item in items]
    return enriched if isinstance(body.selection, list) else enriched[0]


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
