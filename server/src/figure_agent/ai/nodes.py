"""AI 工作流 script 节点与 guard。

节点函数由 workflows.build_registry 以闭包绑定 figure 上下文后注册为
script body；常量（上传文件名等）一律走闭包——SpecModule 的 script 节点
不支持常量 inputs。渲染类节点做成 async body，用 asyncio.to_thread 包
store 的同步渲染，避免阻塞事件循环（registry.script 支持 async fn）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ..store import Store, now_iso

MAX_ROUNDS = 3  # 渲染修复 / 回写收敛的共同轮数上限


# ---------------------------------------------------------------- 造图链

def make_parse_upload(fdir: Path, upload_name: str):
    """uploads/<upload_name> → 表格文本。二进制表格走 pandas，其余按文本读。

    upload_name 来自 REST 层的 Path(...).name，但工厂内再做一次逃逸防御。
    只支持 .xlsx（openpyxl 后端）；遗留 .xls 需要 xlrd，不装（明确拒绝）。
    """
    path = (fdir / "uploads" / upload_name).resolve()
    path.relative_to((fdir / "uploads").resolve())  # 逃逸 uploads/ 直接抛错

    async def parse_upload(view) -> str:
        def _read() -> str:
            suffix = path.suffix.lower()
            if suffix == ".xlsx":
                import pandas as pd

                df = pd.read_excel(path)
                return df.to_csv(index=False)
            if suffix in (".xls",):
                raise ValueError("不支持遗留 .xls 格式，请另存为 .xlsx")
            return path.read_text(encoding="utf-8", errors="replace")

        return await asyncio.to_thread(_read)

    return parse_upload


def make_write_data(fdir: Path):
    """落盘 data.csv + data_profile.json；画像（并入整理说明）作为下游 prompt 输入。"""

    def write_data(view) -> dict:
        out = view.field("data")  # Standardize 输出 {csv, profile, notes}
        if not isinstance(out, dict):
            raise TypeError(f"Standardize 上游输出非 dict：{type(out).__name__}")
        profile = dict(out.get("profile") or {})
        merged = (str(profile.get("notes", "")) + " " + str(out.get("notes", ""))).strip()
        profile["notes"] = merged
        (fdir / "data.csv").write_text(out.get("csv", ""), encoding="utf-8")
        (fdir / "data_profile.json").write_text(
            json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return profile

    return write_data


def make_render_validate(store: Store, fdir: Path, project: str, figure: str):
    """取代码（fix 优先于 gen）→ 写盘渲染 → {ok, rounds, stderr, code, ...}。

    返回值必须带 "code"（本轮实际渲染的代码）：FixCode 的 prompt 经 {render}
    拿到整个 dict，没有 code 就无法修复（v2 计划评审补上的字段）。
    """

    async def render_validate(view) -> dict:
        try:
            fix = view.field("fix")
        except (KeyError, TypeError):
            fix = None
        code = fix.get("code") if isinstance(fix, dict) else None
        source = "fix"
        if not (isinstance(code, str) and code.strip()):
            try:
                gen = view.field("gen")
            except (KeyError, TypeError):
                gen = None
            code = gen.get("code") if isinstance(gen, dict) else None
            source = "gen"

        rounds = view.state.get("rounds", 0) + 1
        view.state["rounds"] = rounds
        if not (isinstance(code, str) and code.strip()):
            return {"ok": False, "rounds": rounds, "stderr": "上游未产出代码",
                    "error_line": None, "source": source, "code": ""}
        outcome = await asyncio.to_thread(store.write_code, project, figure, code)
        return {
            "ok": outcome.ok,
            "rounds": rounds,
            "stderr": (outcome.stderr or "")[-4000:],
            "error_line": outcome.error_line,
            "fa_count": len((outcome.stats or {}).get("faGroups", [])),
            "source": source,
            "code": code,
        }

    return render_validate


# ---------------------------------------------------------------- 回写链

def make_read_patch(store: Store, project: str, figure: str):
    def read_patch(view) -> dict:
        patch = store.read_patch(project, figure) or {"ops": []}
        return {"ops": patch.get("ops", [])}

    return read_patch


def make_merge_wb(fdir: Path):
    """合并种子 ops 与最新校验结果；附当前代码；计数轮数（跨 tick 持久）。"""

    def merge_wb(view) -> dict:
        seed = view.field("seed")
        ops = seed.get("ops", []) if isinstance(seed, dict) else []
        try:
            verify = view.field("verify")
        except (KeyError, TypeError):
            verify = None
        if not isinstance(verify, dict):
            verify = None
        rounds = max(view.state.get("rounds", 0), (verify or {}).get("rounds", 0))
        view.state["rounds"] = rounds
        cleared = (not ops) or bool((verify or {}).get("cleared"))
        remaining = (verify or {}).get("remaining", len(ops))
        try:
            code = (fdir / "plot.py").read_text(encoding="utf-8")
        except OSError:
            code = ""
        return {"ops": ops, "verify": verify, "code": code, "rounds": rounds,
                "cleared": cleared, "remaining": remaining}

    return merge_wb


def make_render_verify(store: Store, project: str, figure: str):
    """回写代码 → 渲染 → verify_patch 收敛判定。"""

    async def render_verify(view) -> dict:
        tr = view.field("translated")
        code = tr.get("code") if isinstance(tr, dict) else None
        rounds = view.state.get("rounds", 0) + 1
        view.state["rounds"] = rounds
        if not (isinstance(code, str) and code.strip()):
            return {"ok": False, "cleared": False, "rounds": rounds, "remaining": -1,
                    "results": [], "stderr": "回写节点未产出代码"}
        outcome = await asyncio.to_thread(store.write_code, project, figure, code)
        if not outcome.ok:
            return {"ok": False, "cleared": False, "rounds": rounds, "remaining": -1,
                    "results": [], "stderr": (outcome.stderr or "")[-4000:],
                    "error_line": outcome.error_line}
        verdict = await asyncio.to_thread(store.verify_patch, project, figure)
        return {"ok": True, "cleared": bool(verdict.get("cleared")),
                "rounds": rounds, "remaining": verdict.get("remainingOps", 0),
                "results": verdict.get("results", []), "stderr": ""}

    return render_verify


# ---------------------------------------------------------------- 终点

def make_finalize(fdir: Path, kind: str):
    """终点节点：规范化返回值 + 追加 runs.jsonl。writeback 的 ok = cleared。

    读 bind 字段 "result"（TaskDefinition inputs={"result": 上游节点}）——
    真实引擎的 NodeView 没有 .output 属性（那是 GuardView 的），body 里读
    view.output 会 AttributeError 静默失败（评审仿真发现）。
    """

    def finalize(view) -> dict:
        o = view.field("result")
        o = o if isinstance(o, dict) else {}
        result = {
            "kind": kind,
            "ok": bool(o.get("cleared")) if kind == "writeback" else bool(o.get("ok")),
            "rounds": o.get("rounds", 0),
            "stderr": o.get("stderr", ""),
            "error_line": o.get("error_line"),
            "notes": o.get("notes", ""),
        }
        if kind == "writeback":
            result["cleared"] = bool(o.get("cleared"))
            result["remaining"] = o.get("remaining", -1)
        entry = {"at": now_iso(), **result}
        with (fdir / "runs.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return result

    return finalize


# ---------------------------------------------------------------- guards

def _out(view) -> dict:
    return view.output if isinstance(view.output, dict) else {}


def needs_fix(view) -> bool:
    o = _out(view)
    return not o.get("ok") and o.get("rounds", 0) < MAX_ROUNDS


def settled(view) -> bool:
    return not needs_fix(view)  # 严格互补（XOR），与 fact_review_loop 同纪律


def wb_continue(view) -> bool:
    o = _out(view)
    return bool(o.get("ops")) and not o.get("cleared", False) and o.get("rounds", 0) < MAX_ROUNDS


def wb_done(view) -> bool:
    return not wb_continue(view)  # 严格互补
