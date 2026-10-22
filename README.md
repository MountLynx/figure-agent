# figure-agent（科研图表绘制 Agent）

本地 Web 应用 + MCP 工具：AI（ZCode）编写/修改 matplotlib 代码产出科研图表；浏览器里框选/点选 SVG 元素把"改哪里"变成结构化数据回传给 AI；颜色/字号/位置/大小四项手动微调记录为 patch，代码重跑不丢失，并可用收敛式回写把 patch 翻译回代码。

设计文档：`docs/specs/2026-10-16-figure-agent-design.md`

## 架构

```
ZCode (AI) ──MCP(stdio)── FastAPI 本地服务(8765) ──HTTP+WS── 浏览器前端
                            │ subprocess
                     python plot.py → base.svg
workspace/<project>/<figure>/{plot.py, base.svg, patch.json, meta.json, history/}
```

- `server/` — Python 包 `figure_agent`：executor（渲染契约注入）、svgkit（规范化/语义组/身份匹配/patch 收敛，pytest 主战场）、REST API + WS、静态托管
- `web/` — Vite + React + TS：viewer（viewBox 平移缩放、悬停高亮）、DragSelect 选区（完全包含判定）+ 语义归并、元素面板（显隐/绘制层级）、四项轻编辑、op 列表
- `server/templates/` — 建图模板（分组柱状图、iris 散点）
- `workspace/demo/` — 示例项目（bar-groups + iris-scatter）

## 启动

```bash
# 1) 后端（首次：uv venv + uv pip install -e .）
cd server && uv venv .venv && uv pip install -p .venv/Scripts/python.exe -e ".[dev]"
.venv/Scripts/python -m figure_agent        # http://127.0.0.1:8765

# 2) 前端（构建后由后端静态托管；开发期可 npm run dev 走 proxy）
cd web && npm install && npm run build

# 浏览器打开 http://127.0.0.1:8765
```

环境变量：`FA_WORKSPACE`（默认 `<repo>/workspace`）、`FA_PORT`（默认 8765）、`FA_RENDER_TIMEOUT`（默认 30s）。

## ZCode / MCP 接入

仓库根的 `.mcp.json` 已注册 `figure-agent` MCP server（stdio，薄包装 REST）。工具集：

`fa_list_projects` `fa_list_figures` `fa_get_selection` `fa_get_figure` `fa_set_code` `fa_run` `fa_get_patch` `fa_set_patch` `fa_verify_patch`

典型闭环（S1）：用户在浏览器选元素 → `fa_get_selection` 读定位 JSON → `fa_get_figure` 读代码 → `fa_set_code` 定点修改并重渲染。
回写闭环（S3）：`fa_get_patch` → 改代码表达意图 → `fa_set_code` → `fa_verify_patch` → patch 清空即完成。

绘图代码约定见 `AGENTS.md`（fa: gid、模块级 `fig` 变量、禁碰 svg.fonttype）。

## 操作说明（前端）

- 鼠标悬停元素 → 虚线框 + 名称提示（预览"点下去会选中谁"，与单击同一套语义归并）；悬停已选中元素不重复提示
- 单击选元素 / 拖框多选（Shift 加选），框选只选中**完全落在框内**的元素；空格或 Alt + 拖动平移；滚轮缩放
- "精确模式"：拖框用 `getIntersectionList` 真实几何判定（排除 clip-path 隐藏元素），同样只收完全在框内的元素
- 右侧面板：元素面板（语义树，眼睛=显隐 `set_visible`、⬆⬇=层级 `set_zorder`）、颜色/描边、字体字号、位置、大小、文本 → 全部生成 patch op（本地预览，保存生效）
- undo/redo → 保存 patch；"回写校验"触发收敛判定
- 导出 PNG/SVG；快照入 `history/`

## 测试

```bash
cd server && .venv/Scripts/python -m pytest tests -q   # svgkit/executor/API 30 例
cd web && npm test                                     # 语义归并/选区/预览 9 例
```

## v1 明确不做

鉴权/多用户、打包分发、云同步、内嵌聊天、R 后端、套索选区、动画、协作编辑。
