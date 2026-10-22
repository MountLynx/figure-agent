# figure-agent（科研图表绘制 Agent）

本地 Web 应用：服务端内嵌 SpecModule 工作流，由 AI 编写/修改 matplotlib 代码产出科研图表；浏览器 AI 面板提交任务、实时查看事件时间线；框选/点选 SVG 元素把"改哪里"变成结构化数据回传给 AI；颜色/字号/位置/大小四项手动微调记录为 patch，代码重跑不丢失，并可用收敛式回写把 patch 翻译回代码。

设计文档：`docs/specs/2026-10-16-figure-agent-design.md`（v1 基础）、`docs/specs/2026-10-22-native-ai-workflow-design.md`（原生 AI 工作流）

## 架构

```
浏览器前端 ──HTTP+WS── FastAPI 本地服务(8765) ──内嵌 SpecModule── LLM
                            │ subprocess
                     python plot.py → base.svg
workspace/<project>/<figure>/{plot.py, base.svg, patch.json, meta.json, history/}
```

- `server/` — Python 包 `figure_agent`：executor（渲染契约注入）、svgkit（规范化/语义组/身份匹配/patch 收敛，pytest 主战场）、ai/（SpecModule 四工作流：harness=LLM 节点 / script=Store 薄包装）、REST API + WS、静态托管
- `web/` — Vite + React + TS：viewer（viewBox 平移缩放、悬停高亮）、DragSelect 选区（完全包含判定）+ 语义归并、元素面板（显隐/绘制层级）、四项轻编辑、op 列表、AI 面板（四工作流提交 + 事件时间线 + 回写）
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

## AI 工作流

AI 能力由 FastAPI 服务内嵌的 SpecModule 工作流提供（harness=LLM 节点 / script=Store 薄包装），前端 AI 面板提交任务并实时查看事件时间线。四条工作流：

- **create**：数据 + 要求 → 从零造图
- **adapt**：数据 + 已有脚本 → 改造适配
- **edit**：选区 + 指令 → 定点改图
- **writeback**：手动微调 patch → 循环翻译进代码直至收敛清空

绘图代码约定见 `AGENTS.md`（fa: gid、模块级 `fig` 变量、禁碰 svg.fonttype / svg.hashsalt）。

## LLM 配置

仓库根放 `config.json` + `.env`（参考 `config.example.json`）；`FIGURE_AGENT_MOCK=1` 可免 key 冒烟。SpecModule 以本地可编辑方式安装（路径按本机调整）：

```bash
server\.venv\Scripts\pip install -e "C:\Users\xingy\Desktop\开发\SpecModule"
```

注意：provider SDK 按 `sdktype` 选装（`openai` 兼容后端装 `openai`，Anthropic 装 `anthropic`）——本仓库 pyproject 已内置 `openai`；新建环境装完 SpecModule 后如报「客户端未就绪（openai 包未安装）」即是漏了这步。

## 操作说明（前端）

- 鼠标悬停元素 → 虚线框 + 名称提示（预览"点下去会选中谁"，与单击同一套语义归并）；悬停已选中元素不重复提示
- 单击选元素 / 拖框多选（Shift 加选），框选只选中**完全落在框内**的元素；空格或 Alt + 拖动平移；滚轮缩放
- "精确模式"：拖框用 `getIntersectionList` 真实几何判定（排除 clip-path 隐藏元素），同样只收完全在框内的元素
- 右侧面板：元素面板（语义树，眼睛=显隐 `set_visible`、⬆⬇=层级 `set_zorder`）、颜色/描边、字体字号、位置、大小、文本 → 全部生成 patch op（本地预览，保存生效）
- undo/redo → 保存 patch；"回写校验"触发收敛判定
- 导出 PNG/SVG；快照入 `history/`

## 测试

```bash
cd server && .venv/Scripts/python -m pytest tests -q   # svgkit/executor/API/AI 工作流 62 例
cd web && npm test                                     # 语义归并/选区/预览/AI 面板 27 例
```

## v1 明确不做

鉴权/多用户、打包分发、云同步、内嵌聊天、R 后端、套索选区、动画、协作编辑。
