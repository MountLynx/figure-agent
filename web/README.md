# figure-agent web — 独立图文编辑器前端

由 Python 服务（`python -m figureagent --dir <绝对路径>`）同源托管的单页应用：
只编辑**一个工作目录**里的图（`plot.py` / `base.svg` / `final.svg` / `patch.json` /
`history/`），没有任何项目管理（条目/分组/类型/新建对话框）。

- 唯一输入：URL 的 `?dir=<绝对路径>`；缺省时只显示「请从 Index 打开」的提示。
- `?panel=ai`：只渲染 AI 面板的精简布局（二期拆到 Index 右栏用）。
- 不 import `@index/*`，不依赖任何宿主 `ctx`，所有请求都是同源相对路径 `/api/...`。

## 开发 / 构建

```bash
pnpm install
pnpm dev        # vite 5173；/api 与 /ws 代理到 http://127.0.0.1:8801
npx tsc --noEmit
pnpm test       # vitest（happy-dom）
pnpm build      # tsc --noEmit && vite build → dist/
```

`base: "./"`：`dist/index.html` 用相对资源路径，服务可在任意路径托管。

## 目录结构

```
src/
  main.tsx                 入口（注入 fig-* 样式 + 渲染 App）
  App.tsx                  单视图编排：?dir= → /api/context → Workbench / AIPanel
  app/context.ts           fetchContext（{dir,name,has_figure}）+ readDirParam
  shared/                  api 客户端（16 端点）、types、semantics、applyClient、
                           buildJson、styles（fig-* CSS）、ws（同源 /ws）
  fig-workbench/           Workbench 编排 + CreateFlow + components/
                           （Viewer / SelectionLayer / EditorPanel）
  fig-ai/                  AIPanel（指令修改 / 回写 patch / 运行时间线）
  styles.css               设计令牌（取自 Index shell theme.css）+ 页面骨架
```

`fig-workbench/`、`fig-ai/`、`shared/` 三块自 `itemmanage/figurePlugins/` 原样搬来，
差异只有：React 命名空间注入（`shared/reactns.ts`）换成普通 `import * as React`；
`shared/base.ts` 的 `__FIG_BASE__` 机制删除，改同源相对路径。

## 与服务的最小契约

- `GET /api/context?dir=<编码后的绝对路径>` → `{dir, name, has_figure}`
  - `dir`：服务端规范化的工作目录（后续请求与 WS 事件都用它对齐）；
  - `name`：标题（`document.title` + 工作台标题）；
  - `has_figure`：`plot.py` 是否存在 → 无图走建图流，有图进编辑器；也是 AI 面板
    「有图才可用」的应用状态来源。
- 图端点沿用 `/api/figures/{figure_id}/...` 形状，`{figure_id}` 段是固定占位 `work`
  （单工作目录模型，服务端忽略其值）：
  `GET /api/figures/status`、`GET /api/figures/templates`、
  `GET /api/figures/{id}`、`PUT /code`、`POST /run`、`PUT /patch`、
  `POST /verify-patch`、`POST /snapshot`、`GET /runs`、`DELETE /api/figures/{id}`、
  `POST /create`、`POST /adapt`、`POST /instruct`、`POST /writeback`、
  `POST /enrich-selection`。
- `GET /api/files` → 工作目录只读树（建图流挑数据/脚本、右栏文件列表）。
- `WS /ws`：`{type:"ai_run"|"figure_updated"|"figure_deleted"|"render_error", dir, ...}`，
  前端按 `dir` 过滤（没有 dir 字段的事件视为本目录）。
- 每个 `/api` 请求都带 `?dir=`：服务用 `--dir` 启动时忽略它；未指定时它用于**首次**
  绑定工作目录（vite dev 代理场景）。

## 测试

`pnpm test`（9 个文件 / 50 用例）：`Viewer.*`（DOM 所有权、缩放、悬停、多选）、
`AIPanel`（有图才可用、回写计数、WS 时间线、运行锁复位）、`semantics`（服务端同构）、
`api`（相对路径、`?dir=`、错误处理、请求体）、`context`（拉取与形状校验）、
`App`（缺 `?dir=` 不白屏）。
