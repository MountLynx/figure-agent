# figure-agent

**在一个目录里画科研图**的本地 web 应用：AI 写/改 matplotlib 代码产出 SVG，浏览器里选区微调、
把「改哪里」变成结构化数据回传给 AI、把微调 patch 收敛式回写进代码。

不管理项目、不碰数据库：给它一个目录，它只读写目录里的
`plot.py`（真相源）/ `data.csv` / `base.svg` / `final.svg` / `patch.json` / `uploads/` / `history/`。

> 2026-11-07 复活：本仓此前并入 ResearchIndex 后退役；现在**去掉项目管理**，回到独立应用，
> 作为 Index 宿主的内部视图被 iframe 嵌入（Index 管条目，fig 只管目录里的图）。
> 设计：`docs/specs/2026-11-07-standalone-view-spec.md`。

## 架构

```
浏览器（web/dist，由服务同源托管）
   │ HTTP + WS
FastAPI（--dir 绑定一个目录）
   ├─ figures/     内容管线：normalize → identity → apply/verify patch → 快照
   ├─ figures/ai/  SpecModule 四工作流：create / adapt / edit / writeback
   └─ executor     子进程跑 plot.py（Agg + svg.fonttype=none + 固定 hashsalt）
```

- `server/` — Python 包 `figureagent`：`workdir`（目录绑定与校验）、`figures`（渲染/SVG/patch/AI）、
  `figservice`（app 装配 + 静态托管 + 握手行）。**没有任何 SQLite 代码**。
- `web/` — Vite + React：画布（viewBox 平移缩放、悬停高亮、DragSelect 选区 + 语义归并）、
  元素面板、四项轻编辑、AI 面板（四工作流 + 事件时间线 + 回写）。

## 运行

```bash
cd server && uv venv && uv pip install -e ".[dev]"          # 首次
cd server && PYTHONPATH=src .venv/Scripts/python.exe -m figureagent --dir "C:/path/to/figure_dir"
# → FIG_SERVICE_PORT=...  FIG_SERVICE_READY  打开 http://127.0.0.1:<port>/
```

开发态：`cd web && pnpm dev`（5173，`/api` 与 `/ws` 代理到 8801），另起服务时加 `--port 8801`。

## 测试

```bash
cd server && PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests -q   # 122 passed
cd web && pnpm test && pnpm build                                        # vitest + dist/
```

## 与 Index 的关系

Index（itemmanage）只做三件事：右键「打开绘图工作台」→ 用条目文件夹启动本服务 →
把页面 iframe 进中间页签。**它不向本服务传 item id，也不读本服务的数据库**——因为这里没有数据库。
