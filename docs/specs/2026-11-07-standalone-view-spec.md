# 规格：figure-agent 独立内部视图（无项目管理）

日期：2026-11-07
状态：实施中
关联：`itemmanage`（宿主适配）、`itemmanage/sidecar`（后端来源）、`itemmanage/figurePlugins`（UI 来源）

## 1. 定位

figure-agent 复活为**独立的本机 web 应用**：只认一个目录，在目录里画图，不做项目管理。
Index 侧只负责“打开某个条目对应的目录”，用 iframe 把它嵌进中间页签。

```
Index（宿主）                       figure-agent（独立应用）
├─ 右键「创建/打开图表」 ──────────► 起服务：python -m figureagent --dir <条目文件夹>
├─ 中间页签 iframe → http://127.0.0.1:<port>/?dir=…
└─ 右栏页签 iframe → …?panel=ai
```

职责边界：

| 归 Index | 归 figure-agent |
|---|---|
| 条目/类型/分组/标签/附件/工作区 | 目录内的绘图产物（plot.py / base.svg / patch.json / history/） |
| 哪些条目能开图（类型是 Data） | 怎么画、怎么改、怎么审 |
| 页签生命周期、标题、图标 | 画布、选区、AI 工作流、快照 |

## 2. 数据契约

- 唯一输入：`--dir <绝对路径>`（或页面 `?dir=`），必须是存在目录。
- 只读写该目录下的保留文件：`plot.py`（真相源）、`data.csv`、`data_profile.json`、
  `base.svg`、`final.svg`、`patch.json`、`uploads/`、`history/`。
- **不碰任何 SQLite**：没有条目、没有 types/items 表、没有 `ri_schema`。
  （`是否有图` 由 Index 侧看 `plot.py` 是否存在自行判断。）
- 目录路径校验：拒绝 `..`、必须是绝对路径、必须是目录。

## 3. 后端（`figure-agent/server`）

- 来源：`itemmanage/sidecar/src/researchindex`（figures 本体原样保留）+ `figservice` 入口。
- 改造：
  - `repodb` / `ri_schema` / `state`（仓库单例）全部删除 → 换成 `Workdir`（一个目录）。
  - `deps.repo_root` → `deps.workdir`（读 `--dir` 或 `?dir=`）。
  - 删掉图扩展表与 `是否有图` 回写（Index 侧不再依赖）。
- 路由：`/api/*` + `/ws`（figures 全套）+ `/` 静态托管 `web/dist`。
- CORS：只为 dev（vite 5173/1420）保留；生产同源不需要。
- 入口：
  ```
  python -m figureagent --dir <路径> [--port 0] [--host 127.0.0.1]
  ```
  就绪后 stdout 打印 `FIG_SERVICE_PORT=<port>` 与 `FIG_SERVICE_READY`（Index 侧握手契约不变）。
- 测试：把 sidecar 的 81 个用例迁过来，改成“临时目录”夹具（不再建库）。

## 4. 前端（`figure-agent/web`）

- 来源：`itemmanage/figurePlugins/{fig-workbench,fig-ai,shared}` —— **以它为准**（布局、
  侧栏自动收缩、点击元素后的元素列表都是新版领先的部分）。
- 独立化：
  - 去掉 `ctx`：条目信息改为应用内状态（`?dir=` 决定工作目录；目录名作标题）。
  - `shared/base.ts` 的 `__FIG_BASE__` 整套删除：页面由服务自己托管，全部相对路径。
  - 删除 `figure-agent/web/src/components/manage/**`（项目管理：列表/分组/类型/新建对话框）。
  - 单视图编排：画布 + 右侧属性/微调 + AI（先合在中间，`?panel=ai` 预留为后续拆分）。
- 构建：`vite build` → `web/dist`，由服务静态托管；`vite dev` 时 `?dir=` 走代理。

## 5. Index 适配（`itemmanage`）

- 插件退化为 iframe 壳（手写 bundle，<2KB）：
  - `fig-workbench`：itemAction「打开绘图工作台」→ 调 `fig_open(item_id)` 拿 URL → 渲染 iframe。
  - `fig-ai`：右栏 iframe `?panel=ai&dir=…`（二期；先合并进中间）。
- 宿主命令 `fig_open(item_id)`：校验类型 → 解析条目文件夹 → 起服务（`--dir`）→ 返回
  `{ url, dir }`；页签标题用条目名。
- 删除：`itemmanage/figurePlugins/`、`figService.ts` 的基址注入、sidecar 的 repodb。

## 6. 验收

1. 独立跑：`python -m figureagent --dir <某个含 plot.py 的目录>` → 浏览器打开能看图画图改图。
2. 无项目管理：应用里没有任何“仓库/分组/类型/新建条目”入口。
3. Index 内：右键 Data 条目 → 中间页签出现画布 → 改图落盘到条目文件夹 → 重开仍在。
4. 测试：服务侧 pytest 全绿；web 侧 vitest 全绿；Index 侧 tsc/cargo test 全绿。
5. 打包：`web/dist` 进 itemmanage 的 sidecar 产物，随包解释器能起。

## 7. 迁移顺序

1. 后端：拷 figures + 建 `workdir`，删 DB 依赖，静态托管，测试改夹具。
2. 前端：拷新版组件，去 ctx，删 manage，出 dist。
3. 宿主：iframe 插件 + `fig_open`，接 itemAction。
4. 收尾：删旧插件源码与注入逻辑，打包冒烟。
