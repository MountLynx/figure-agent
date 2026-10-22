"""figure-agent MCP server（stdio）：REST API 的薄包装（§7.2）。

启动：python -m figure_agent.mcp_server
环境：FIGURE_AGENT_URL（默认 http://127.0.0.1:8765）

工具集：fa_list_projects / fa_list_figures / fa_get_selection /
fa_get_figure / fa_set_code / fa_run / fa_get_patch / fa_set_patch /
fa_verify_patch
"""

from __future__ import annotations

import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

BASE = os.environ.get("FIGURE_AGENT_URL", "http://127.0.0.1:8765").rstrip("/")
mcp = FastMCP("figure-agent", instructions="科研图表绘制 Agent。先让用户在浏览器里选元素，再读选区改代码。")


def _call(method: str, path: str, **kwargs):
    with httpx.Client(timeout=60.0) as client:
        resp = client.request(method, BASE + path, **kwargs)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise RuntimeError(f"HTTP {resp.status_code}: {detail}")
    return resp.json()


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)


@mcp.tool()
def fa_list_projects() -> str:
    """列出工作区里所有项目与图。"""
    return _dump(_call("GET", "/api/projects"))


@mcp.tool()
def fa_list_figures(project: str) -> str:
    """列出一个项目下的所有图。"""
    return _dump(_call("GET", f"/api/projects/{project}"))


@mcp.tool()
def fa_get_selection() -> str:
    """读取浏览器里用户当前框选/点选的元素（带语义定位 JSON）。

    单选返回一个 JSON 对象；多选（Shift+点击/框选多个）返回对象数组，
    每项独立描述一个元素，逐项处理，不要只取第一项。
    没有选区时返回提示，此时应让用户先在浏览器里选择图形元素，
    或让用户用"复制选区 JSON"按钮把 JSON 粘贴过来。
    """
    data = _call("GET", "/api/session/selection")
    if data.get("selection") is None:
        return data["hint"]
    return _dump(data["selection"])


@mcp.tool()
def fa_get_figure(project: str, figure: str) -> str:
    """读图：当前代码 plot.py + patch 摘要 + 语义组列表。

    base.svg 全文较大；如需看 SVG 结构用 fa_get_selection 的语义定位即可。
    """
    fig = _call("GET", f"/api/figure/{project}/{figure}")
    patch = fig.get("patch") or {"ops": []}
    out = {
        "code": fig.get("code"),
        "renderError": fig.get("renderError"),
        "patchSummary": [
            {
                "id": op.get("id"),
                "kind": op.get("kind"),
                "attr": op.get("attr"),
                "value": op.get("value"),
                "intent": op.get("intent"),
                "status": op.get("status"),
                "target": op.get("target"),
            }
            for op in patch.get("ops", [])
        ],
        "baseHash": patch.get("baseHash", ""),
    }
    return _dump(out)


@mcp.tool()
def fa_set_code(project: str, figure: str, code: str) -> str:
    """写入 plot.py 并重渲染。失败时返回完整 stderr 与出错行号。

    约定（重要）：
    - 模块级构建图形并存入变量 fig；
    - 关键 artist 调 set_gid("fa:名字")，这是选区回传与回写收敛的基础；
    - 不要改 svg.fonttype（服务会强制回 none）。
    """
    result = _call("PUT", f"/api/figure/{project}/{figure}/code", json={"code": code})
    if not result.get("ok"):
        return _dump({"ok": False, "stderr": result.get("stderr"), "errorLine": result.get("errorLine")})
    stats = result.get("stats") or {}
    out = {
        "ok": True,
        "elementCount": stats.get("elementCount"),
        "semanticGroupCount": stats.get("semanticGroupCount"),
        "faGroups": stats.get("faGroups", []),
        "warnings": result.get("warnings", []),
    }
    if not out["faGroups"]:
        out["hint"] = "没有任何 fa: gid。请给关键 artist 调 set_gid(\"fa:名字\")，否则选区定位与回写收敛都不可靠。"
    return _dump(out)


@mcp.tool()
def fa_run(project: str, figure: str) -> str:
    """不改代码，仅重渲染（用户在外部改了 plot.py 后用）。"""
    result = _call("POST", f"/api/figure/{project}/{figure}/run")
    return _dump(result)


@mcp.tool()
def fa_get_patch(project: str, figure: str) -> str:
    """读 patch.json 全文（手动微调覆盖层）。"""
    return _dump(_call("GET", f"/api/figure/{project}/{figure}").get("patch"))


@mcp.tool()
def fa_set_patch(project: str, figure: str, patch: str) -> str:
    """写 patch.json（JSON 字符串，结构 {baseHash, ops: [...]}）。

    op 结构：{id, kind: set_style|set_text|transform|set_visible|reorder,
    target: {id, semanticPath, fingerprint}, attr?, value?, intent(必填), origin, status}。
    set_visible 的 value 为 false=隐藏 / true=显示；reorder 的 value 为 {to: "front"|"back"}。
    保存时会自动补 transform op 的 pre 基准并刷新目标状态。
    """
    try:
        patch_obj = json.loads(patch)
    except json.JSONDecodeError as exc:
        return _dump({"ok": False, "error": f"patch 不是合法 JSON：{exc}"})
    return _dump(_call("PUT", f"/api/figure/{project}/{figure}/patch", json=patch_obj))


@mcp.tool()
def fa_verify_patch(project: str, figure: str) -> str:
    """回写收敛判定：逐 op 检查新 base 是否已表达该微调。

    resolved 的 op 会自动从 patch 删除；patch 清空（cleared=true）= 回写完成。
    判定 active 的 op 会带 detail 说明差异。
    """
    return _dump(_call("POST", f"/api/figure/{project}/{figure}/verify-patch"))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
