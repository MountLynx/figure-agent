"""工作区存储：项目/图目录管理、渲染管线、patch 持久化、快照。

目录布局（§4.1）：workspace/<project>/<figure>/{plot.py, base.svg,
patch.json, meta.json, history/}。base.svg/final.svg 由服务生成，
不进 git；patch.json 进 git。
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import executor
from .svgkit import base_hash, normalize, parse_svg, serialize
from .svgkit import identity, patchops
from .svgkit import geom

NAME_RE = re.compile(r"^[\w][\w .-]*$")

# Windows 保留设备名（不分大小写），用作目录名会导致建目录失败
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _require_name(name: str, what: str) -> str:
    n = name or ""
    if not NAME_RE.match(n):
        raise ValueError(f"非法的{what}名：{name!r}")
    # Windows 会静默剥离目录名结尾的点/空格，导致目录名与请求名不一致
    if n != n.rstrip(" ."):
        raise ValueError(f"非法的{what}名（结尾的点/空格）：{name!r}")
    if n.upper() in _WIN_RESERVED:
        raise ValueError(f"非法的{what}名（Windows 保留设备名）：{name!r}")
    return n


@dataclass
class RenderOutcome:
    ok: bool
    stderr: str = ""
    error_line: Optional[int] = None
    warnings: List[str] | None = None
    stats: Dict | None = None


class Store:
    def __init__(self, workspace: Path, render_timeout: float = 30.0):
        self.workspace = Path(workspace)
        self.render_timeout = render_timeout
        self.workspace.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ 路径

    def project_dir(self, project: str) -> Path:
        return self.workspace / _require_name(project, "项目")

    def figure_dir(self, project: str, figure: str) -> Path:
        return self.project_dir(project) / _require_name(figure, "图")

    # ------------------------------------------------------------ 枚举

    def projects(self) -> List[Dict]:
        out = []
        for pdir in sorted(self.workspace.iterdir()):
            if not pdir.is_dir() or pdir.name.startswith((".", "_")):
                continue
            figs = self.figures(pdir.name)
            if figs or (pdir / "plot.py").exists():
                out.append({"name": pdir.name, "figures": figs})
        return out

    def figures(self, project: str) -> List[Dict]:
        pdir = self.project_dir(project)
        if not pdir.is_dir():
            return []
        out = []
        for fdir in sorted(pdir.iterdir()):
            if not fdir.is_dir() or fdir.name.startswith((".", "_")):
                continue
            meta = self.read_meta(project, fdir.name) or {}
            patch = self.read_patch(project, fdir.name) or {"ops": []}
            out.append(
                {
                    "name": fdir.name,
                    "hasBase": (fdir / "base.svg").exists(),
                    "lastRenderAt": meta.get("lastRenderAt"),
                    "opCount": len(patch.get("ops", [])),
                }
            )
        return out

    # ------------------------------------------------------------ 元数据/文件

    def read_meta(self, project: str, figure: str) -> Optional[Dict]:
        path = self.figure_dir(project, figure) / "meta.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_meta(self, fdir: Path, meta: Dict) -> None:
        (fdir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def read_code(self, project: str, figure: str) -> str:
        return (self.figure_dir(project, figure) / "plot.py").read_text(encoding="utf-8")

    def read_patch(self, project: str, figure: str) -> Optional[Dict]:
        path = self.figure_dir(project, figure) / "patch.json"
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

    def read_svg(self, project: str, figure: str, which: str = "base") -> Optional[str]:
        path = self.figure_dir(project, figure) / f"{which}.svg"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    # ------------------------------------------------------------ 建图

    def templates(self) -> List[Dict]:
        out = []
        if not TEMPLATES_DIR.is_dir():
            return out
        for tdir in sorted(TEMPLATES_DIR.iterdir()):
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

    def init_figure(self, project: str, figure: str, origin: str) -> None:
        """建图目录（无模板代码）：AI 造图/改造的入口。已存在则 ValueError。"""
        _require_name(project, "项目")
        _require_name(figure, "图")
        fdir = self.figure_dir(project, figure)
        if fdir.exists():
            raise ValueError(f"图已存在：{project}/{figure}")
        try:
            fdir.mkdir(parents=True)
        except FileExistsError:  # TOCTOU：exists 检查与建目录之间的竞争
            raise ValueError(f"图已存在：{project}/{figure}")
        (fdir / "history").mkdir()
        self._write_meta(
            fdir,
            {
                "name": figure,
                "project": project,
                "origin": origin,
                "createdAt": now_iso(),
                "lastRenderAt": None,
            },
        )
        self._write_patch(fdir, {"baseHash": "", "ops": []})

    def create_figure(self, project: str, figure: str, template: str) -> Dict:
        _require_name(project, "项目")
        _require_name(figure, "图")
        tdir = TEMPLATES_DIR / _require_name(template, "模板")
        if not (tdir / "plot.py").exists():
            raise ValueError(f"模板不存在：{template}")
        fdir = self.figure_dir(project, figure)
        if fdir.exists():
            raise ValueError(f"图已存在：{project}/{figure}")
        fdir.mkdir(parents=True)
        (fdir / "history").mkdir()
        shutil.copy(tdir / "plot.py", fdir / "plot.py")
        self._write_meta(
            fdir,
            {
                "name": figure,
                "project": project,
                "template": template,
                "origin": "template",
                "createdAt": now_iso(),
                "lastRenderAt": None,
            },
        )
        self._write_patch(fdir, {"baseHash": "", "ops": []})
        outcome = self.render(project, figure)
        return {"ok": outcome.ok, "stderr": outcome.stderr}

    # ------------------------------------------------------------ 渲染管线

    def render(self, project: str, figure: str) -> RenderOutcome:
        fdir = self.figure_dir(project, figure)
        plot_py = fdir / "plot.py"
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

        old_text = self.read_svg(project, figure, "base")
        old_root = None
        if old_text:
            try:
                old_root = parse_svg(old_text)
                normalize(old_root)
            except Exception:
                old_root = None

        patch = self.read_patch(project, figure) or {"baseHash": "", "ops": []}

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

        # 目标重定位/治愈（§6.1 match）
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
        base_path = fdir / "base.svg"
        base_path.write_text(new_text, encoding="utf-8")
        final_text, per_op = patchops.apply_patch(new_root, patch)
        (fdir / "final.svg").write_text(final_text, encoding="utf-8")

        patch["baseHash"] = base_hash(new_text)
        self._write_patch(fdir, patch)

        meta = self.read_meta(project, figure) or {}
        meta["lastRenderAt"] = now_iso()
        self._write_meta(fdir, meta)
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

    def write_code(self, project: str, figure: str, code: str) -> RenderOutcome:
        fdir = self.figure_dir(project, figure)
        (fdir / "plot.py").write_text(code, encoding="utf-8")
        return self.render(project, figure)

    # ------------------------------------------------------------ patch

    def save_patch(self, project: str, figure: str, patch: Dict) -> Dict:
        """写 patch.json；为 transform op 补 pre（从当前 base 估算）。"""
        fdir = self.figure_dir(project, figure)
        base_text = self.read_svg(project, figure, "base")
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
            (fdir / "final.svg").write_text(final_text, encoding="utf-8")
        return {"ok": True}

    def verify_patch(self, project: str, figure: str) -> Dict:
        base_text = self.read_svg(project, figure, "base")
        patch = self.read_patch(project, figure) or {"baseHash": "", "ops": []}
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
        self._write_patch(self.figure_dir(project, figure), new_patch)
        final_text, _ = patchops.apply_patch(root, new_patch)
        (self.figure_dir(project, figure) / "final.svg").write_text(final_text, encoding="utf-8")
        remaining = len(new_patch.get("ops", []))
        return {
            "results": [
                {"opId": op_id, **info}
                for op_id, info in results.items()
            ],
            "remainingOps": remaining,
            "cleared": remaining == 0,
        }

    # ------------------------------------------------------------ 快照

    def snapshot(self, project: str, figure: str, note: str = "") -> Dict:
        fdir = self.figure_dir(project, figure)
        ts = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        dest = fdir / "history" / ts
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("base.svg", "patch.json", "plot.py"):
            src = fdir / name
            if src.exists():
                shutil.copy(src, dest / name)
        (dest / "note.txt").write_text(note or "", encoding="utf-8")
        return {"id": ts, "note": note}

    def snapshots(self, project: str, figure: str) -> List[Dict]:
        hist = self.figure_dir(project, figure) / "history"
        if not hist.is_dir():
            return []
        out = []
        for d in sorted(hist.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            note_file = d / "note.txt"
            out.append(
                {
                    "id": d.name,
                    "note": note_file.read_text(encoding="utf-8") if note_file.exists() else "",
                }
            )
        return out
