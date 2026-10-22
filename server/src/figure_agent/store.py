"""工作区存储（Index 仓库门面）：条目/分组/标签/审计经 repo 包走 index.db；
渲染管线、patch 持久化、快照载荷走条目文件夹（扁平 <12hex>，永不改名）。

目录契约（spec §2）：workspace/.index/index.db + workspace/<12hex>/{plot.py,
base.svg, patch.json, history/}。管理语义全部在 SQL；文件系统只承载内容。
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from . import executor
from .repo import items as repo_items
from .repo import runs as repo_runs
from .repo.items import require_id
from .repo.repo import FIGURE_TYPE_NAME, Repo
from .svgkit import base_hash, normalize, parse_svg, serialize
from .svgkit import identity, patchops
from .svgkit import geom

NAME_RE = re.compile(r"^[\w][\w .-]*$")

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _require_name(name: str, what: str) -> str:
    """名字进 SQL（不再是目录名），仅做基本卫生校验。"""
    n = name or ""
    if not NAME_RE.match(n):
        raise ValueError(f"非法的{what}名：{name!r}")
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
        self.repo = Repo(self.workspace)
        self.repo.open_or_init()

    # ------------------------------------------------------------ 路径/条目

    def figure_dir(self, item_id: str) -> Path:
        require_id(item_id)
        return self.workspace / item_id

    def read_item(self, item_id: str) -> Dict:
        item = repo_items.get_item(self.repo, item_id)
        if item is None:
            raise ValueError(f"图不存在：{item_id}")
        return item

    # ------------------------------------------------------------ 枚举

    def list_figures(self, q: Optional[str] = None, group_id: Optional[int] = None,
                     tag_id: Optional[int] = None) -> List[Dict]:
        out = []
        for item in repo_items.list_items(self.repo, FIGURE_TYPE_NAME, q=q,
                                          group_id=group_id, tag_id=tag_id):
            fdir = self.workspace / item["id"]
            patch = self._read_patch_file(fdir) or {"ops": []}
            out.append({
                **item,
                "hasBase": (fdir / "base.svg").exists(),
                "lastRenderAt": item["properties"].get("最后渲染"),
                "opCount": len(patch.get("ops", [])),
            })
        return out

    # ------------------------------------------------------------ 元数据/文件

    def read_code(self, item_id: str) -> str:
        return (self.figure_dir(item_id) / "plot.py").read_text(encoding="utf-8")

    def read_patch(self, item_id: str) -> Optional[Dict]:
        return self._read_patch_file(self.figure_dir(item_id))

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

    def read_svg(self, item_id: str, which: str = "base") -> Optional[str]:
        path = self.figure_dir(item_id) / f"{which}.svg"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def read_files(self, item_id: str, subdir: str = "") -> List[Dict]:
        """条目文件夹递归清单（前端文件树）。路径穿越防御。"""
        require_id(item_id)
        base = self.figure_dir(item_id).resolve()
        root = (base / subdir).resolve()
        root.relative_to(base)
        out: List[Dict] = []
        if not root.is_dir():
            return out
        for p in sorted(root.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            rel = p.relative_to(base).as_posix()
            out.append({"path": rel, "isDir": p.is_dir()})
            if p.is_dir():
                out.extend(self.read_files(item_id, rel))
        return out

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

    def create_figure(self, name: str, template: Optional[str] = None,
                      origin: str = "template",
                      group_id: Optional[int] = None) -> Dict:
        """建图：INSERT items + 立即建内容文件夹（plot.py 是真相源）。
        同名图允许（Index 语义，id 消歧）。失败整体回滚。"""
        _require_name(name, "图")
        props: Dict = {"来源": origin}
        if template:
            props["模板"] = template
        item = repo_items.create_item(self.repo, name, FIGURE_TYPE_NAME, props)
        fdir = self.workspace / item["id"]
        try:
            fdir.mkdir(parents=True)
            (fdir / "history").mkdir()
            if template:
                tdir = TEMPLATES_DIR / _require_name(template, "模板")
                if not (tdir / "plot.py").exists():
                    raise ValueError(f"模板不存在：{template}")
                shutil.copy(tdir / "plot.py", fdir / "plot.py")
            self._write_patch(fdir, {"baseHash": "", "ops": []})
        except Exception:
            shutil.rmtree(fdir, ignore_errors=True)
            try:
                repo_items.delete_item(self.repo, item["id"])
            except ValueError:
                pass
            raise
        if group_id is not None:
            repo_items.bind_group(self.repo, item["id"], group_id)
        outcome = self.render(item["id"]) if template else None
        return {"id": item["id"], "name": name,
                "ok": outcome.ok if outcome else False,
                "stderr": outcome.stderr if outcome else ""}

    def rename_figure(self, item_id: str, name: str) -> Dict:
        """与 Index 对齐：只动 SQL，文件夹名（id）永不变。"""
        _require_name(name, "图")
        self.read_item(item_id)
        return repo_items.update_item(self.repo, item_id, name=name)

    def delete_figure(self, item_id: str) -> None:
        """SQL 先行（CASCADE 清绑定与 fa 表），再 best-effort 删文件夹。"""
        repo_items.delete_item(self.repo, item_id)
        shutil.rmtree(self.figure_dir(item_id), ignore_errors=True)

    # ------------------------------------------------------------ 渲染管线

    def render(self, item_id: str) -> RenderOutcome:
        fdir = self.figure_dir(item_id)
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

        old_text = self.read_svg(item_id, "base")
        old_root = None
        if old_text:
            try:
                old_root = parse_svg(old_text)
                normalize(old_root)
            except Exception:
                old_root = None

        patch = self.read_patch(item_id) or {"baseHash": "", "ops": []}

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

        repo_items.merge_properties(self.repo, item_id, {"最后渲染": now_iso()})
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

    def write_code(self, item_id: str, code: str) -> RenderOutcome:
        fdir = self.figure_dir(item_id)
        (fdir / "plot.py").write_text(code, encoding="utf-8")
        return self.render(item_id)

    # ------------------------------------------------------------ patch

    def save_patch(self, item_id: str, patch: Dict) -> Dict:
        """写 patch.json；为 transform op 补 pre（从当前 base 估算）。"""
        fdir = self.figure_dir(item_id)
        base_text = self.read_svg(item_id, "base")
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

    def verify_patch(self, item_id: str) -> Dict:
        base_text = self.read_svg(item_id, "base")
        patch = self.read_patch(item_id) or {"baseHash": "", "ops": []}
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
        self._write_patch(self.figure_dir(item_id), new_patch)
        final_text, _ = patchops.apply_patch(root, new_patch)
        (self.figure_dir(item_id) / "final.svg").write_text(final_text, encoding="utf-8")
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

    def snapshot(self, item_id: str, note: str = "") -> Dict:
        fdir = self.figure_dir(item_id)
        ts = datetime.now().strftime("%Y-%m-%dT%H%M%S")
        dest = fdir / "history" / ts
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("base.svg", "patch.json", "plot.py"):
            src = fdir / name
            if src.exists():
                shutil.copy(src, dest / name)
        (dest / "note.txt").write_text(note or "", encoding="utf-8")
        repo_runs.add_snapshot(self.repo, item_id, now_iso(), note, f"history/{ts}")
        return {"id": ts, "note": note}

    def snapshots(self, item_id: str) -> List[Dict]:
        return [
            {"id": Path(row["dir"]).name, "note": row["note"]}
            for row in repo_runs.list_snapshots(self.repo, item_id)
        ]
