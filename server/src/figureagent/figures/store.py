"""图内容存储：一个工作目录、一套保留文件、零数据库。

与 sidecar 版的差异（独立服务化）：没有 ``repo_root``/``item_id`` 寻址，也不再有
``fig_runs`` / ``fig_snapshots`` 两张 SQL 表。图内容与审计全部落文件：

- 内容：``plot.py``（真相源）/ ``data.csv`` / ``data_profile.json`` /
  ``base.svg`` / ``final.svg`` / ``patch.json``；
- 快照：``history/<时间戳>/``（base.svg + patch.json + plot.py + note.txt）；
- AI 运行审计：``history/runs.jsonl``（追加写，读时倒序），形如原 ``fig_runs`` 行。

渲染管线（normalize→patch 重定位→base/final.svg）与 sidecar 版逐字节一致。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .. import config as fig_config
from ..figure_guard import RESERVED_NAMES
from ..workdir import Workdir
from . import executor
from .svgkit import base_hash, normalize, parse_svg, serialize
from .svgkit import identity, patchops
from .svgkit import geom


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class RenderOutcome:
    ok: bool
    stderr: str = ""
    error_line: Optional[int] = None
    warnings: List[str] | None = None
    stats: Dict | None = None


class FigureStore:
    def __init__(self, workdir: Workdir, render_timeout: float = 30.0):
        self.workdir = workdir
        self.render_timeout = render_timeout

    # ------------------------------------------------------------ 路径

    def figure_dir(self) -> Path:
        """图内容所在的目录（就是工作目录本身）。"""
        return self.workdir.root

    def has_figure(self) -> bool:
        """真相源判定：plot.py 存在。"""
        return self.workdir.has_figure()

    # ------------------------------------------------------------ 文件读写

    def read_code(self) -> str:
        return self.workdir.plot_path().read_text(encoding="utf-8")

    def read_patch(self) -> Optional[Dict]:
        return self._read_patch_file(self.figure_dir())

    def _read_patch_file(self, fdir: Path) -> Optional[Dict]:
        path = fdir / "patch.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"baseHash": "", "ops": [], "_error": "patch.json 解析失败"}

    def _write_patch(self, fdir: Path, patch: Dict) -> None:
        (fdir / "patch.json").write_text(
            json.dumps(patch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def read_svg(self, which: str = "base") -> Optional[str]:
        path = self.workdir.svg_paths().get(which, self.figure_dir() / f"{which}.svg")
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    # ------------------------------------------------------------ 模板 / 保留名

    def templates(self) -> List[Dict]:
        tdir_root = fig_config.templates_dir()
        out: List[Dict] = []
        if not tdir_root.is_dir():
            return out
        for tdir in sorted(tdir_root.iterdir()):
            info = tdir / "template.json"
            if tdir.is_dir() and (tdir / "plot.py").exists():
                payload = {}
                if info.exists():
                    payload = json.loads(info.read_text(encoding="utf-8"))
                out.append(
                    {
                        "id": tdir.name,
                        "title": payload.get("title", tdir.name),
                        "description": payload.get("description", ""),
                    }
                )
        return out

    def reserved_conflicts(self) -> List[str]:
        """已被占用的保留名（建图前检查；列出全部冲突）。"""
        fdir = self.figure_dir()
        conflicts: List[str] = []
        for name in RESERVED_NAMES:
            if (fdir / name).exists():
                conflicts.append(name)
        for d in ("uploads", "history"):
            if (fdir / d).is_dir():
                conflicts.append(d + "/")
        return conflicts

    def create_figure_files(self, template: Optional[str] = None) -> None:
        """建图内容脚手架：保留名占用检查 + 拷模板 plot.py + 空 patch.json。"""
        fdir = self.figure_dir()
        conflicts = [n for n in RESERVED_NAMES if (fdir / n).exists()]
        if conflicts:
            raise ValueError(f"保留名已被占用，无法创建图表：{'、'.join(conflicts)}")
        if template:
            tdir = fig_config.templates_dir() / template
            if not (tdir / "plot.py").exists():
                raise ValueError(f"模板不存在：{template}")
            shutil.copy(tdir / "plot.py", fdir / "plot.py")
        self._write_patch(fdir, {"baseHash": "", "ops": []})

    def delete_figure_files(self) -> None:
        """删图内容：清保留名文件与 uploads//history/ 目录（目录本身保留）。"""
        fdir = self.figure_dir()
        for name in RESERVED_NAMES:
            (fdir / name).unlink(missing_ok=True)
        for d in ("uploads", "history"):
            shutil.rmtree(fdir / d, ignore_errors=True)

    # ------------------------------------------------------------ 渲染管线

    def render(self) -> RenderOutcome:
        fdir = self.figure_dir()
        plot_py = self.workdir.plot_path()
        if not plot_py.exists():
            return RenderOutcome(ok=False, stderr="plot.py 不存在")
        tmp = fdir / ".render-tmp.svg"
        result = executor.render_with_timeout_guard(
            plot_py, tmp, timeout=self.render_timeout, cwd=fdir
        )
        if not result.ok:
            tmp.unlink(missing_ok=True)
            return RenderOutcome(ok=False, stderr=result.stderr, error_line=result.error_line)
        warnings: List[str] = [
            line.split(":", 1)[1].strip()
            for line in result.stderr.splitlines()
            if line.startswith("WARNING:")
        ]
        try:
            new_root = parse_svg(tmp.read_text(encoding="utf-8"))
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            return RenderOutcome(ok=False, stderr=f"渲染产物不是合法 SVG，已保留上一版：{exc}")
        normalize(new_root)
        new_text = serialize(new_root)

        old_text = self.read_svg("base")
        old_root = None
        if old_text:
            try:
                old_root = parse_svg(old_text)
                normalize(old_root)
            except Exception:
                old_root = None

        patch = self.read_patch() or {"baseHash": "", "ops": []}

        # set_visible(隐藏) 特例：目标已从新 base 消失 = 代码已 set_visible(False)，
        # 视为已表达。必须先于 identity.match 剪除——否则 match 会把 op
        # "治愈"到兄弟元素上（比如 control-bar-1），永远无法收敛。
        patch["ops"] = [
            op
            for op in patch.get("ops", [])
            if not (
                op.get("kind") == "set_visible"
                and not op.get("value")
                and identity.locate(new_root, op.get("target") or {}) is None
            )
        ]

        # 目标重定位/治愈（identity.match）
        match_result = identity.match(old_root, new_root, patch.get("ops", []))
        for op in patch.get("ops", []):
            mr = match_result.get(op.get("id", ""))
            if mr is not None:
                op["target"] = mr.target
                op["status"] = "active" if mr.status == "matched" else "lost"
                if mr.degraded:
                    op["status"] = "active"
                    op["degraded"] = True

        # base.svg / final.svg
        base_path = self.workdir.base_svg_path()
        base_path.write_text(new_text, encoding="utf-8")
        final_text, per_op = patchops.apply_patch(new_root, patch)
        self.workdir.final_svg_path().write_text(final_text, encoding="utf-8")

        patch["baseHash"] = base_hash(new_text)
        self._write_patch(fdir, patch)
        tmp.unlink(missing_ok=True)

        stats = self.figure_stats(new_root)
        lost = [op_id for op_id, s in per_op.items() if s == "lost"]
        if lost:
            warnings.append(f"{len(lost)} 个 patch op 目标丢失（lost），UI 中已高亮")
        if any(op.get("status") == "active" and not op.get("target", {}).get("id", "").startswith("fa:") for op in patch.get("ops", [])):
            warnings.append("部分 op 目标缺少 fa: gid（靠指纹匹配），回写前建议在代码中补 gid")
        return RenderOutcome(ok=True, warnings=warnings, stats=stats)

    def figure_stats(self, root) -> Dict:
        from .svgkit.semantics import collect_semantic

        sem = collect_semantic(root)
        all_el = [el for el in root.iter() if isinstance(el.tag, str)]
        fa_ids = [el.get("id") for el in sem if (el.get("id") or "").startswith("fa:")]
        mat_ids = [
            el.get("id")
            for el in sem
            if not (el.get("id") or "").startswith("fa:")
        ][:50]
        return {
            "elementCount": len(all_el),
            "semanticGroupCount": len(sem),
            "faGroups": fa_ids,
            "matplotlibGroups": mat_ids,
        }

    # ------------------------------------------------------------ 代码写入

    def write_code(self, code: str) -> RenderOutcome:
        self.workdir.plot_path().write_text(code, encoding="utf-8")
        return self.render()

    # ------------------------------------------------------------ patch

    def save_patch(self, patch: Dict) -> Dict:
        """写 patch.json；为 transform op 补 pre（从当前 base 估算）。"""
        fdir = self.figure_dir()
        base_text = self.read_svg("base")
        if base_text:
            root = parse_svg(base_text)
            normalize(root)
            for op in patch.get("ops", []):
                if op.get("kind") == "transform" and not op.get("pre"):
                    el = identity.locate(root, op.get("target") or {})
                    if el is not None:
                        bbox = geom.estimate_bbox(el)
                        if bbox is not None:
                            op["pre"] = {"center": [round(bbox.cx, 3), round(bbox.cy, 3)],
                                         "size": [round(bbox.w, 3), round(bbox.h, 3)]}
            # 重新计算状态（目标可能已不在）
            for op in patch.get("ops", []):
                if op.get("status") not in ("active", "lost"):
                    op["status"] = "active"
                el = identity.locate(root, op.get("target") or {})
                if el is not None:
                    op["status"] = "active"
                elif op.get("kind") == "set_visible" and not op.get("value"):
                    # 隐藏 op 目标消失留给回写校验判收敛，不误标 lost
                    op["status"] = "active"
                else:
                    op["status"] = "lost"
        patch.setdefault("baseHash", base_hash(base_text) if base_text else "")
        self._write_patch(fdir, patch)
        if base_text:
            root = parse_svg(base_text)
            normalize(root)
            final_text, per_op = patchops.apply_patch(root, patch)
            self.workdir.final_svg_path().write_text(final_text, encoding="utf-8")
        return {"ok": True}

    def verify_patch(self) -> Dict:
        base_text = self.read_svg("base")
        patch = self.read_patch() or {"baseHash": "", "ops": []}
        if not base_text:
            return {"results": [], "remainingOps": 0, "cleared": True, "error": "base.svg 不存在"}
        root = parse_svg(base_text)
        normalize(root)
        results = patchops.verify_patch(root, patch)
        new_patch = patchops.prune_resolved(patch, results)
        for op in new_patch.get("ops", []):
            st = results.get(op.get("id", ""), {})
            if st.get("status") == "lost":
                op["status"] = "lost"
            elif op.get("status") == "lost" and st.get("status") == "active":
                # verify 重新找到了目标（目标回来了）
                op["status"] = "active"
        self._write_patch(self.figure_dir(), new_patch)
        final_text, _ = patchops.apply_patch(root, new_patch)
        self.workdir.final_svg_path().write_text(final_text, encoding="utf-8")
        remaining = len(new_patch.get("ops", []))
        return {
            "results": [
                {"opId": op_id, **info}
                for op_id, info in results.items()
            ],
            "remainingOps": remaining,
            "cleared": remaining == 0,
        }

    # ------------------------------------------------------------ 快照（history/<ts>/）

    SNAPSHOT_TS_FORMAT = "%Y-%m-%dT%H%M%S"

    def snapshot(self, note: str = "") -> Dict:
        fdir = self.figure_dir()
        ts = datetime.now().strftime(self.SNAPSHOT_TS_FORMAT)
        dest = self.workdir.history_dir() / ts
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("base.svg", "patch.json", "plot.py"):
            src = fdir / name
            if src.exists():
                shutil.copy(src, dest / name)
        (dest / "note.txt").write_text(note or "", encoding="utf-8")
        return {"id": ts, "note": note, "dir": f"history/{ts}", "createdAt": now_iso()}

    def snapshots(self) -> List[Dict]:
        """扫描 history/ 下的时间戳目录（新的在前）；非时间戳目录一律跳过。"""
        hdir = self.workdir.history_dir()
        if not hdir.is_dir():
            return []
        out: List[Dict] = []
        for path in sorted(hdir.iterdir(), key=lambda p: p.name, reverse=True):
            if not path.is_dir():
                continue
            try:
                created = datetime.strptime(path.name, self.SNAPSHOT_TS_FORMAT).astimezone()
            except ValueError:
                continue
            note_path = path / "note.txt"
            note = note_path.read_text(encoding="utf-8") if note_path.is_file() else ""
            out.append({
                "createdAt": created.isoformat(timespec="seconds"),
                "note": note,
                "dir": f"history/{path.name}",
            })
        return out

    def delete_snapshots(self) -> None:
        shutil.rmtree(self.workdir.history_dir(), ignore_errors=True)

    # ------------------------------------------------------------ 运行审计（history/runs.jsonl）

    def add_run(self, kind: str, ok: bool, rounds: int = 0,
                at: Optional[str] = None, detail: Optional[dict] = None) -> None:
        path = self.workdir.runs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "kind": kind,
            "ok": bool(ok),
            "at": at or now_iso(),
            "rounds": rounds,
            "detail": detail or {},
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def list_runs(self) -> List[Dict]:
        """新的在前（等价原 ``ORDER BY id DESC``）；坏行跳过不炸。"""
        path = self.workdir.runs_path()
        if not path.is_file():
            return []
        records: List[Dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        out: List[Dict] = []
        for record in reversed(records):
            detail = record.get("detail")
            if not isinstance(detail, dict):
                detail = {}
            # 基础列在后：detail 里的同名键（如历史脏数据带 "kind"）不得覆盖权威列
            out.append({**detail, "at": record.get("at", ""), "kind": record.get("kind", ""),
                        "ok": bool(record.get("ok")), "rounds": record.get("rounds", 0)})
        return out

    def delete_runs(self) -> None:
        self.workdir.runs_path().unlink(missing_ok=True)
