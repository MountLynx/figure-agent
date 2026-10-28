> **⚠️ 已归档（2026-10-28）**：figure-agent 已整体并入
> [ResearchIndex](../research%20manage)（统一科研工作台）——SVG 编辑器与四条 AI 工作流
> 物理搬入 `server/src/researchindex/figures/` 子包，图内嵌 Data 条目文件夹，
> 右键「创建图表」打开工作台；本仓库退役，仅作历史参考。
> 迁移工具：ResearchIndex `server/scripts/migrate_figure_agent.py`
> （本 workspace 的 3 张图已迁至 `E:\Index\Research`）。设计与偏差 D24-D29 见
> ResearchIndex 仓库 `docs/superpowers/`。

# figure-agent（科研图表绘制 Agent）

本地 Web 应用：服务端内嵌 SpecModule 工作流，由 AI 编写/修改 matplotlib 代码产出科研图表；浏览器 AI 面板提交任务、实时查看事件时间线；框选/点选 SVG 元素把"改哪里"变成结构化数据回传给 AI；颜色/字号/位置/大小四项手动微调记录为 patch，代码重跑不丢失，并可用收敛式回写把 patch 翻译回代码。工作区是一个合法的 Index 仓库：管理语义（图/分组/标签/类型/字段、AI 审计、快照）全部在 `.index/index.db`（SQLite），文件系统只承载图内容，可被 Index 应用（itemmanage）直接打开。

设计文档：`docs/specs/2026-10-16-figure-agent-design.md`（v1 基础）、`docs/specs/2026-10-22-native-ai-workflow-design.md`（原生 AI 工作流）、`docs/specs/2026-10-22-index-repo-refactor-design.md`（Index 仓库模式：存储/API 契约来源）

## 架构

```
浏览器前端 ──HTTP+WS── FastAPI 本地服务(8765) ──内嵌 SpecModule── LLM
                            │ subprocess
                     python plot.py → base.svg
workspace/（= Index 仓库根）
├── .index/index.db   # SQLite：条目/分组/标签/类型/字段 + fa_runs/fa_snapshots（管理语义唯一真相）
└── <12hex>/          # 图 = 条目文件夹（扁平，id 永不改名）
    {plot.py, data.csv, base.svg, final.svg, patch.json, uploads/, history/}
```

- `server/` — Python 包 `figure_agent`：repo/（Index 仓库：SQL 迁移、条目/分组/标签/类型读写、AI 审计与快照）、executor（渲染契约注入）、svgkit（规范化/语义组/身份匹配/patch 收敛，pytest 主战场）、ai/（SpecModule 四工作流：harness=LLM 节点 / script=Store 薄包装）、REST API + WS、静态托管
- `web/` — Vite + React + TS：管理视图（Index 风格三栏：分组树/标签/图列表/详情与类型管理，「＋ 新建图」对话框）+ 编辑器视图（viewer（viewBox 平移缩放、悬停高亮）、DragSelect 选区（完全包含判定）+ 语义归并、元素面板（显隐/绘制层级）、四项轻编辑、op 列表、AI 面板（四工作流提交 + 事件时间线 + 回写））
- `server/templates/` — 建图模板（分组柱状图、iris 散点）
- `workspace/demo/` — 示例工作区（bar-groups + iris-scatter；旧版布局，`FA_WORKSPACE=workspace/demo python -m figure_agent migrate` 迁移后使用）

管理语义全在 SQL（`meta.json` / `runs.jsonl` 已废除）：改名只 UPDATE；删除图 = SQL 事务先行 + best-effort 删文件夹；同名图允许（12hex id 消歧）。API 全面 id 寻址：`/api/items`、`/api/groups`、`/api/tags`、`/api/types`、`/api/repo/info|state`、`/api/figures/{id}/...`、`/api/figures/ai|adapt`；旧 `/api/projects/...`、`/api/figure/{p}/{f}` 已删。

## 启动

```bash
# 1) 后端（首次：uv venv + uv pip install -e .）
cd server && uv venv .venv && uv pip install -p .venv/Scripts/python.exe -e ".[dev]"
.venv/Scripts/python -m figure_agent        # http://127.0.0.1:8765

# 2) 前端（构建后由后端静态托管；开发期可 npm run dev 走 proxy）
cd web && npm install && npm run build

# 浏览器打开 http://127.0.0.1:8765
```

环境变量：`FA_WORKSPACE`（默认 `<repo>/workspace`，即 Index 仓库根）、`FA_PORT`（默认 8765）、`FA_RENDER_TIMEOUT`（默认 30s）。

旧版 workspace（`<项目>/<图>/` + meta.json 布局）一次性迁移为 Index 仓库（幂等，可重复执行）：

```bash
.venv/Scripts/python -m figure_agent migrate           # 加 --archive 则归档到 _migrated_backup/ 而非删除旧目录
```

## AI 工作流

AI 能力由 FastAPI 服务内嵌的 SpecModule 工作流提供（harness=LLM 节点 / script=Store 薄包装），前端 AI 面板提交任务并实时查看事件时间线。四条工作流：

- **create**：数据 + 要求 → 从零造图
- **adapt**：数据 + 已有脚本 → 改造适配
- **edit**：选区 + 指令 → 定点改图
- **writeback**：手动微调 patch → 循环翻译进代码直至收敛清空

create / adapt 的入口在管理视图「＋ 新建图」对话框；edit / writeback 在编辑器视图的 AI 面板。

绘图代码约定见 `AGENTS.md`（fa: gid、模块级 `fig` 变量、禁碰 svg.fonttype / svg.hashsalt）。

## LLM 配置

仓库根放 `config.json` + `.env`（参考 `config.example.json`）；`FIGURE_AGENT_MOCK=1` 可免 key 冒烟。SpecModule 以本地可编辑方式安装（路径按本机调整）：

```bash
server\.venv\Scripts\pip install -e "C:\Users\xingy\Desktop\开发\SpecModule"
```

注意：provider SDK 按 `sdktype` 选装（`openai` 兼容后端装 `openai`，Anthropic 装 `anthropic`）——本仓库 pyproject 已内置 `openai`；新建环境装完 SpecModule 后如报「客户端未就绪（openai 包未安装）」即是漏了这步。

## 操作说明（前端）

双视图：管理视图 ⇄ 编辑器视图，顶栏「← 返回管理」切换。

管理视图（Index 风格三栏）：

- 左栏搜索（按名称过滤）+ 多级分组树（增删改/拖拽移动）+ 扁平标签
- 中栏图列表：行点击选中、双击/打开进编辑器、右键重命名/删除、拖拽入分组
- 右栏详情（行内重命名、按"图"字段渲染的属性表单、分组/标签 chips、条目文件树只读）与类型/字段管理
- 顶栏「＋ 新建图」对话框：从模板建图或 AI 造图（create / adapt 工作流）
- 亮/暗主题持久化到 `.index/state.json`，与 Index 应用共享

编辑器视图：

- 鼠标悬停元素 → 虚线框 + 名称提示（预览"点下去会选中谁"，与单击同一套语义归并）；悬停已选中元素不重复提示
- 单击选元素 / 拖框多选（Shift 加选），框选只选中**完全落在框内**的元素；空格或 Alt + 拖动平移；滚轮缩放
- "精确模式"：拖框用 `getIntersectionList` 真实几何判定（排除 clip-path 隐藏元素），同样只收完全在框内的元素
- 右侧面板：元素面板（语义树，眼睛=显隐 `set_visible`、⬆⬇=层级 `set_zorder`）、颜色/描边、字体字号、位置、大小、文本 → 全部生成 patch op（本地预览，保存生效）
- undo/redo → 保存 patch；"回写校验"触发收敛判定
- 导出 PNG/SVG；快照入 `history/`

## 测试

```bash
cd server && .venv/Scripts/python -m pytest tests -q   # svgkit/executor/API/AI 工作流/repo 迁移与语义/迁移 CLI 97 例
cd web && npm test                                     # 语义归并/选区/预览/管理视图/AI 面板 29 例
```

## v1 明确不做

鉴权/多用户、打包分发、云同步、内嵌聊天、R 后端、套索选区、动画、协作编辑。
