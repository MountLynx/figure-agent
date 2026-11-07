"""四条固定 tasklist 工作流（SpecModule 直写通道）+ run_workflow 入口。

每次 run 构建全新 HarnessRegistry（body 按 {module_id}:{key} 命名空间隔离，
view.state 随 run 隔离）。review_harness=None 跳过一致性审核——固定管线，
省一次 LLM 调用。persist=False 全内存零落盘；审计靠 Finalize 节点写
history/runs.jsonl（Finalize 未 fire 的引擎级失败由 _audit_failure 补写，形状一致）。
同一事件循环内只允许一个 AI run（per-loop asyncio.Lock 注册表）。

独立服务化后不再有 item_id：一次 run 只针对召唤它的那个工作目录，
WS 事件用 ``dir`` 标识（与 /api/context 的 dir 同值）。

图结构备注（均经真实引擎仿真验证）：
- RenderValidate 双 producer（GenCode/EditCode + FixCode）必须 OR join，否则死锁
- Finalize 经具名 bind inputs={"result": 上游} 读输入（NodeView 无 .output 属性）
- writeback 的 Finalize 只从 Merge 的 wb_done 边进入（直达边会造成双 fire 双重审计）

spec §12 的部分实现：五个代码 harness 设 validate_retries=1，引擎层修复链
（围栏剥离→JSON 提取→尾部截断→带校验错误反馈重试一次）挡住"LLM 忘了去
markdown 围栏"这类最常见坏输出；把坏 JSON 送进 fix 循环的完整实现需重构输出
通道，留待真实 LLM smoke 后评估。残余引擎级失败由 _harvest_failure 收割
具体 stderr（不泛化）、经 _audit_failure 落运行审计，可见可审计。
"""

from __future__ import annotations

import asyncio
import uuid
import weakref
from datetime import datetime

from module_harness import (
    EventBus,
    HarnessConfig,
    HarnessRegistry,
    Module,
    OutputFormat,
    TaskDefinition,
    Tasklist,
)
from module_harness.infra.events import (
    HarnessFailed,
    LlmCallCompleted,
    LlmCallStarted,
    ScriptCompleted,
    ScriptFailed,
    ScriptStarted,
)

from ..store import FigureStore, now_iso
from . import nodes, prompts
from .llm import get_llm

# 每事件循环一把锁：asyncio.Lock 一旦竞争即绑定首个 loop 且永久失效，
# 测试的 asyncio.run（每次新 loop）与生产 uvicorn 主 loop 互不污染。
_run_locks: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _get_run_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _run_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _run_locks[loop] = lock
    return lock


def _hc(core: str) -> HarnessConfig:
    """代码类 harness 统一配置：核心 prompt + 契约文本 + JSON 输出。

    validate_retries=1：SpecModule 内置修复链（围栏剥离→JSON 提取→尾部
    截断→带校验错误反馈重试一次），把"LLM 忘了去 markdown 围栏"挡在引擎层
    ——spec §12 完整 fix-loop 化的部分实现，其余留待真实 smoke 后评估。
    """
    return HarnessConfig(
        prompt_core=core + "\n\n" + prompts.CONTRACT,
        output_format=OutputFormat(type="json_object"),
        validate_retries=1,
    )


def _tl_create(spec: dict) -> Tasklist:
    return Tasklist(
        tasks={
            "ParseUpload": TaskDefinition(type="script", script="parse_upload"),
            "Standardize": TaskDefinition(type="harness", harness="standardize",
                                          inputs={"data": "ParseUpload"}),
            "WriteData": TaskDefinition(type="script", script="write_data",
                                        inputs={"data": "Standardize"}),
            "GenCode": TaskDefinition(type="harness", harness="gen_code",
                                      inputs={"profile": "WriteData",
                                              "requirements": "{spec.requirements}"}),
            "FixCode": TaskDefinition(type="harness", harness="fix_code",
                                      inputs={"render": "RenderValidate"}),
            "RenderValidate": TaskDefinition(type="script", script="render_validate",
                                             inputs={"gen": "GenCode", "fix": "FixCode"}),
            "Finalize": TaskDefinition(type="script", script="finalize",
                                       inputs={"result": "RenderValidate"}),
        },
        flow=(
            # tickflow DSL 每行一条边（A-->B-->C 链式写法会被 _EDGE_RE 拒绝）
            "[ParseUpload] --> Standardize\n"
            "Standardize --> WriteData\n"
            "WriteData --> GenCode\n"
            "GenCode --> RenderValidate\n"
            "RenderValidate --|needs_fix|--> FixCode\n"
            "FixCode --> RenderValidate\n"
            "RenderValidate --|settled|--> Finalize\n"
            # RenderValidate 双 producer（GenCode+FixCode）默认 AND join 会死锁：
            # 首轮 FixCode 未 fire 永不满足。OR join = 任一 producer fire 即触发。
            "RenderValidate.join: OR"
        ),
    )


def _tl_adapt(spec: dict) -> Tasklist:
    return Tasklist(
        tasks={
            "ParseUpload": TaskDefinition(type="script", script="parse_upload"),
            "Standardize": TaskDefinition(type="harness", harness="standardize",
                                          inputs={"data": "ParseUpload"}),
            "WriteData": TaskDefinition(type="script", script="write_data",
                                        inputs={"data": "Standardize"}),
            "AdaptCode": TaskDefinition(type="harness", harness="adapt_code",
                                        inputs={"profile": "WriteData",
                                                "requirements": "{spec.requirements}",
                                                "script_text": "{spec.script_text}"}),
            "FixCode": TaskDefinition(type="harness", harness="fix_code",
                                      inputs={"render": "RenderValidate"}),
            "RenderValidate": TaskDefinition(type="script", script="render_validate",
                                             inputs={"gen": "AdaptCode", "fix": "FixCode"}),
            "Finalize": TaskDefinition(type="script", script="finalize",
                                       inputs={"result": "RenderValidate"}),
        },
        flow=(
            "[ParseUpload] --> Standardize\n"
            "Standardize --> WriteData\n"
            "WriteData --> AdaptCode\n"
            "AdaptCode --> RenderValidate\n"
            "RenderValidate --|needs_fix|--> FixCode\n"
            "FixCode --> RenderValidate\n"
            "RenderValidate --|settled|--> Finalize\n"
            "RenderValidate.join: OR"
        ),
    )


def _tl_edit(spec: dict) -> Tasklist:
    return Tasklist(
        tasks={
            "EditCode": TaskDefinition(type="harness", harness="edit_code",
                                       inputs={"instruction": "{spec.instruction}",
                                               "selection": "{spec.selection_json}",
                                               "code": "{spec.code}"}),
            "FixCode": TaskDefinition(type="harness", harness="fix_code",
                                      inputs={"render": "RenderValidate"}),
            "RenderValidate": TaskDefinition(type="script", script="render_validate",
                                             inputs={"gen": "EditCode", "fix": "FixCode"}),
            "Finalize": TaskDefinition(type="script", script="finalize",
                                       inputs={"result": "RenderValidate"}),
        },
        flow=(
            "[EditCode] --> RenderValidate\n"
            "RenderValidate --|needs_fix|--> FixCode\n"
            "FixCode --> RenderValidate\n"
            "RenderValidate --|settled|--> Finalize\n"
            "RenderValidate.join: OR"
        ),
    )


def _tl_writeback(spec: dict) -> Tasklist:
    return Tasklist(
        tasks={
            "ReadPatch": TaskDefinition(type="script", script="read_patch"),
            "Merge": TaskDefinition(type="script", script="merge_wb",
                                    inputs={"seed": "ReadPatch", "verify": "RenderVerify"}),
            "Translate": TaskDefinition(type="harness", harness="translate_patch",
                                        inputs={"material": "Merge"}),
            "RenderVerify": TaskDefinition(type="script", script="render_verify",
                                           inputs={"translated": "Translate"}),
            # Finalize 只从 Merge 的 wb_done 边进入（wb_verify_settled 直达边在
            # 评审仿真中被证明冗余且会造成 Finalize 双 fire 双重审计，已删）
            "Finalize": TaskDefinition(type="script", script="finalize",
                                       inputs={"result": "Merge"}),
        },
        flow=(
            "[ReadPatch] --> Merge\n"
            "Merge --|wb_continue|--> Translate\n"
            "Translate --> RenderVerify\n"
            "RenderVerify --> Merge\n"
            "Merge --|wb_done|--> Finalize\n"
            "Merge.join: OR"
        ),
    )


TASKLISTS = {
    "create": _tl_create,
    "adapt": _tl_adapt,
    "edit": _tl_edit,
    "writeback": _tl_writeback,
}


def build_registry(kind: str, store: FigureStore,
                   spec: dict, llm_client, bus: EventBus) -> HarnessRegistry:
    fdir = store.figure_dir()
    reg = HarnessRegistry(llm_client=llm_client, event_bus=bus)
    # standardize 产出 CSV，与渲染契约/gid/字体无关——用裸 config 不拼 CONTRACT；
    # 但它同样吃任意 LLM 输出，修复链照配（终审遗留：唯一没有 validate_retries 的 harness）
    reg.harness("standardize", HarnessConfig(
        prompt_core=prompts.STANDARDIZE_CORE,
        output_format=OutputFormat(type="json_object"),
        validate_retries=1,
    ))
    for name, core in (
        ("gen_code", prompts.GEN_CODE_CORE),
        ("adapt_code", prompts.ADAPT_CODE_CORE),
        ("fix_code", prompts.FIX_CODE_CORE),
        ("edit_code", prompts.EDIT_CODE_CORE),
        ("translate_patch", prompts.TRANSLATE_PATCH_CORE),
    ):
        reg.harness(name, _hc(core))

    # upload_name 仅 create/adapt 用；writeback/edit 的 spec 无此键，
    # parse_upload 节点在这两条 flow 里不会被 fire，空串安全
    reg.script("parse_upload")(nodes.make_parse_upload(fdir, spec.get("upload_name", "")))
    reg.script("write_data")(nodes.make_write_data(fdir))
    reg.script("render_validate")(nodes.make_render_validate(store))
    reg.script("read_patch")(nodes.make_read_patch(store))
    reg.script("merge_wb")(nodes.make_merge_wb(fdir))
    reg.script("render_verify")(nodes.make_render_verify(store))
    reg.script("finalize")(nodes.make_finalize(store, kind))

    for gname, gfn in (
        ("needs_fix", nodes.needs_fix),
        ("settled", nodes.settled),
        ("wb_continue", nodes.wb_continue),
        ("wb_done", nodes.wb_done),
    ):
        reg.guard(gname, gfn)
    return reg


def _bridge(dir_label: str, run_id: str, bus: EventBus) -> None:
    """EventBus → WS hub：ai_run 事件（节点级进度）。"""
    from ..events import hub

    def push(payload: dict) -> None:
        hub.broadcast_threadsafe({
            "type": "ai_run", "dir": dir_label,
            "runId": run_id, **payload,
        })

    def on_event(evt) -> None:
        if isinstance(evt, ScriptStarted):
            push({"phase": "node_start", "node": evt.node})
        elif isinstance(evt, ScriptCompleted):
            push({"phase": "node_end", "node": evt.node})
        elif isinstance(evt, ScriptFailed):
            push({"phase": "node_failed", "node": evt.node, "detail": evt.error})
        elif isinstance(evt, LlmCallStarted):
            push({"phase": "llm_start", "node": evt.node})
        elif isinstance(evt, LlmCallCompleted):
            push({"phase": "llm_end", "node": evt.node})
        elif isinstance(evt, HarnessFailed):
            push({"phase": "node_failed", "node": evt.node, "detail": evt.reason})

    for evt_type in (ScriptStarted, ScriptCompleted, ScriptFailed,
                     LlmCallStarted, LlmCallCompleted, HarnessFailed):
        bus.subscribe(evt_type, on_event)


def _final_output(firings: list) -> dict:
    for f in reversed(firings):
        if getattr(f, "node", None) == "Finalize":
            out = getattr(f, "output", None)
            if isinstance(out, dict):
                return out
    return {}


def _harvest_failure(firings: list) -> str:
    """引擎级失败收割：反向扫 firings，取最后一个失败节点的具体错误。

    NodeState 实测字段（vars 探明）：status='ok'|'failed'|'aborted'、
    error=str，output 可为 Failure(error=..., type=...)。LLM 输出校验失败
    （type="llm"）记 status='failed'；LLM 调用失败等基础设施故障
    （type="infrastructure"，key 失效/网络/超时）记 status='aborted' 且 run
    立即中止——两者都必须收，否则 401 只会浮出「工作流未到达终点节点」。
    LLM 输出校验失败等引擎级 Failure 会让下游全部跳过、run 提前结束——
    Finalize 不 fire，具体原因只能从这里收，否则 HTTP 结果与审计都只剩
    泛化文案。
    """
    for f in reversed(firings):
        if getattr(f, "status", "") not in ("failed", "aborted"):
            continue
        err = getattr(f, "error", None)
        if not err:
            err = getattr(getattr(f, "output", None), "error", None)
        return f"节点 {getattr(f, 'node', '?')} 失败：{err or '未知错误'}"
    return ""


def _audit_failure(store: FigureStore, kind: str, stderr: str) -> None:
    """Finalize 未 fire 的失败补写运行审计（形状与 nodes.finalize 一致）。"""
    try:
        store.add_run(kind, False, 0, at=now_iso(),
                      detail={"stderr": stderr, "error_line": None, "notes": ""})
    except Exception:
        pass


async def run_workflow(kind: str, store: FigureStore,
                       spec: dict, llm_client=None) -> dict:
    """执行一条工作流，返回 Finalize 节点的规范化结果。"""
    if kind not in TASKLISTS:
        raise ValueError(f"未知工作流：{kind}")
    dir_label = str(store.workdir.root)
    async with _get_run_lock():
        run_id = f"{kind}_{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:8]}"
        from ..events import hub

        hub.broadcast_threadsafe({"type": "ai_run", "dir": dir_label,
                                  "runId": run_id, "phase": "run_start", "node": kind})
        finalized = False  # Finalize 是否亲自落过审计（防双写）
        try:
            # get_llm/build_registry/Module 构造也在罩内：配置错误等构建期
            # 异常同样走统一失败出口，且必发 run_end（不裸逃逸成 500）
            client = llm_client or get_llm()
            bus = EventBus()
            _bridge(dir_label, run_id, bus)
            reg = build_registry(kind, store, spec, client, bus)
            module = Module(
                spec=spec,
                tasklist=TASKLISTS[kind](spec),
                llm_client=client,
                event_bus=bus,
                registry=reg,
                module_id=run_id,
                persist=False,
                status_file=False,
                keep_records=False,
                stream_log=False,
                control=False,
                review_harness=None,
            )
            firings = await module.run(max_ticks=60)
            result = _final_output(firings)
            finalized = bool(result)
            if not result:
                # Finalize 未 fire（引擎级 Failure 饿死下游）：收割具体原因
                detail = _harvest_failure(firings)
                result = {"kind": kind, "ok": False, "rounds": 0,
                          "stderr": detail or "工作流未到达终点节点"}
        except Exception as exc:  # LLM/构建错误统一失败出口
            result = {"kind": kind, "ok": False, "rounds": 0, "stderr": f"{type(exc).__name__}: {exc}"}
        if not finalized:
            _audit_failure(store, kind, result.get("stderr") or "")
        hub.broadcast_threadsafe({"type": "ai_run", "dir": dir_label,
                                  "runId": run_id, "phase": "run_end", "node": kind,
                                  "ok": result.get("ok"), "detail": (result.get("stderr") or "")[:300]})
        return result
