# figure-agent 转 Index 仓库模式 — 设计文档

日期：2026-10-22
状态：已经用户确认设计方向（React 复刻管理壳 + 一次性迁移脚本）

## 1. 目标与非目标

### 目标
1. figure-agent 的工作区（`FA_WORKSPACE`）成为一个**合法的 Index 仓库**：可被
   Index 应用（itemmanage / index-framework）直接打开浏览与管理。
2. 本地存储改为**扁平哈希目录**：每张图是仓库根下一个 12 位十六进制文件夹，
   与 Index 条目文件夹规则一致；不再有 `<项目>/<图>/` 双层结构。
3. **所有管理语义进 SQL 与前端**：图名、分组（=原"项目"）、标签、类型/字段、
   来源、AI 审计、快照元数据全部存 `.index/index.db`；废除 `meta.json` 与
   `runs.jsonl`。文件系统只承载内容（plot.py、data.csv、svg、patch、history 载荷、
   uploads）。
4. web 前端重构为 **Index 风格双视图**：管理视图（三栏，React 复刻 Index 壳）
   + 编辑器视图（保留现有 React 画布/微调/AI 面板，零逻辑改动）。

### 非目标
- 不做仓库看板/多仓库管理（单仓库 = `FA_WORKSPACE`）。
- 不实现 index-plugins 插件市场与 Vue 插件加载（前端路线已定为 React 复刻）。
- 不实现 Index 的子仓库、notes、工作区管理 UI（但磁盘上保留
  `workspaces/`、`state.json` 结构以维持打开兼容）。
- 不改变 AI 四工作流（create/adapt/edit/writeback）的 tasklist 与 prompt 契约
  （`ai/prompts.py`、`ai/workflows.py` 流程不动，仅寻址方式从
  `(project, figure)` 改为 `item_id`）。
- 不改动 `svgkit/`、`executor.py`、渲染契约。

## 2. 磁盘契约（仓库格式）

```
<workspace>/                     ← FA_WORKSPACE 即仓库根 = Index 仓库根
├── .index/
│   ├── index.db                 # SQLite，唯一 SQL 存储
│   ├── state.json               # {"theme": "light", ...}（Index state 语义）
│   └── workspaces/
│       └── 默认工作区.json      # WorkspaceConfig，见下
├── <12hex>/                     # 图 = 条目文件夹（扁平，随机 id，永不改名）
│   ├── plot.py                  # 真相源
│   ├── data.csv  data_profile.json
│   ├── base.svg  final.svg
│   ├── patch.json               # {baseHash, ops:[...]}（内容覆盖层，非管理语义）
│   ├── uploads/                 # 用户上传原始数据
│   └── history/<时间戳>/        # 快照载荷（base.svg+patch.json+plot.py+note.txt）
└── ...
```

### 12 位 id 生成（复刻 Index `items.rs generate_id`）

```python
def generate_id() -> str:
    raw = secrets.token_bytes(16)
    return hashlib.sha256(raw).hexdigest()[:12]
```

冲突时重生成（`INSERT` 前查 `items.id`）。

### state.json

初始化写 `{"theme": "light"}`；web 的亮/暗主题读写此文件
（`GET/PUT /api/repo/state`），与 Index 共享。未知 key 保留（merge 写）。

### workspaces/默认工作区.json（WorkspaceConfig，字段名 camelCase）

```json
{
  "name": "默认工作区",
  "icon": "folder",
  "itemTypes": ["图"],
  "groupIds": [],
  "filter": null,
  "centerTabs": [{"type": "list", "label": "图"}],
  "defaultTab": "图",
  "rightPanelAddons": [],
  "sidebarAddons": []
}
```

`itemTypes: ["图"]` 使 Index 应用打开时中栏只列图类条目。

## 3. index.db 契约

### 3.1 Index 原版迁移（嵌入 + 账本）

将 `index-framework/crates/index-engine/migrations/` 的 8 个 SQL 文件**字节级
原样**拷入 `server/src/figure_agent/repo/migrations/`：

| 文件 | SHA-384（账本 checksum 必须等于此值） |
|---|---|
| 20260710000001_init.sql | `cdadcda604aa31477ea8eeb9caf1447f7050ec3fa1ba9266311d2cc97d1b887e6ab326f814ff297e9ab2f0185317436b` |
| 20260710000002_update_preset_icons.sql | `12464a1e5a64e436af44061aecb3c8592f48cca937545871091a98f04893c1b3dc73e0028193a108d74b7acd560960c7` |
| 20260711000003_add_field_icon.sql | `391d3e81a481d0754f912f8d164107f0c41e6431eeb3a03f94705b20756dbb30b591baa2f40fcf6241d3a2f78b8f2c0e` |
| 20260711000004_add_field_label.sql | `0f5628838e2d2e44d6a8bb4506ad52b0a4a3ec65704850a615c0181b6f388af494df4663a9512b566ab13e40b5d12c61` |
| 20260712000005_add_namespace.sql | `0310db3bf3c2e1f64543e8db529bd0e4cf035ea137bde572f1ca7a77e2f11575a49411708144ec31bad9edc2d2dfacea` |
| 20260714000006_add_date_field_to_task.sql | `ea5a17bf05f60460c5907808f66fd3c187f0dadbb047cd151d45bad74f4892b7ffca3bab54ea6996c2619df2061cae1e` |
| 20260720000007_add_field_options.sql | `a8c25324da092b10d52c4e47a64b22b76936b993ff5016db8e8fd5420adc1e0d3b98e98d4a22ab05fa87e1a550639f54` |
| 20260721000008_add_bound_item.sql | `cffa460571c7ef1c99d5b9820056fabd0845a976a877b4dcb3a8725a7f6d7e1deb00905be0e483907523fc112e8926b8` |

规则（已对真实仓库 `E:\Index\test` 实测验证）：
- `_sqlx_migrations(version BIGINT PK, description, installed_on, success,
  checksum BLOB, execution_time)`：checksum = **SQL 文件原始字节的 SHA-384**；
  `version` = 文件名前缀数字；`success=1`。
- 仓库根加 `.gitattributes`：`server/src/figure_agent/repo/migrations/*.sql
  text eol=lf`，防 Windows autocrlf 破坏字节一致性。
- Index 应用 `open_repo_at` 的识别标准仅一条：`<root>/.index` 目录存在。它打开
  时会按 `_sqlx_migrations` 跳过已应用迁移——因此账本必须完整且校验和精确。

### 3.2 fa 扩展（只加表，永不改 Index 的 7 张表）

fa 扩展走独立账本 `fa_schema_migrations(version, applied_at)`，**绝不写
`_sqlx_migrations`**（避免与 Index 未来迁移撞版本号/校验和）：

```sql
CREATE TABLE fa_schema_migrations (
    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);

-- v1：管理语义扩展表
CREATE TABLE fa_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,              -- create|adapt|edit|writeback
    ok INTEGER NOT NULL,
    at TEXT NOT NULL,                -- RFC3339
    rounds INTEGER,
    detail TEXT NOT NULL DEFAULT '{}'-- JSON：stderr/error_line/notes 等（原 runs.jsonl 行字段）
);
CREATE TABLE fa_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,        -- RFC3339
    note TEXT NOT NULL DEFAULT '',
    dir TEXT NOT NULL                -- history/<ts> 相对路径；载荷文件留在条目文件夹
);
```

连接统一 `PRAGMA foreign_keys=ON`、`busy_timeout=5000`；日志模式与 Index 一致
（默认），不启用 WAL。

### 3.3 种子数据（仅在初始化空库时写入）

- `item_types`：保留 init 迁移自带的 `通用/任务`，追加 `('图', icon
  'chart-bar', namespace 'default')`。
- `fields`（type_id = 图）：`模板(text)`、`来源(text)`、`最后渲染(text)`，
  position 0/1/2。取值存 `items.properties` JSON：
  `{"模板": "bar-groups", "来源": "ai", "最后渲染": "<RFC3339>"}`。
- `meta.json` 字段映射：`name→items.name`、`project→分组绑定`、
  `createdAt→items.created_at`、`template→模板`、`origin→来源`、
  `lastRenderAt→最后渲染`。
- `state.json`、`workspaces/默认工作区.json`（见 §2）。

### 3.4 最终表结构（8 迁移后的 7 张 Index 表，运行时只按名取列）

`item_types(id, name, icon, namespace)`、`fields(id, type_id, name, field_type,
position, icon, label, options)`、`items(id TEXT PK, name, type_id, properties,
namespace, created_at, updated_at)`、`groups(id, parent_id, name, position,
namespace, bound_item_id)`、`tags(id, name, namespace)`、`item_groups(item_id,
group_id)`、`item_tags(item_id, tag_id)`。`field_type` 合法值：text / checkbox /
date / number / dropdown / item。

## 4. 语义边界（与 Index 逐条对齐）

| 操作 | 语义 |
|---|---|
| 图/分组重命名 | 只 UPDATE SQL；文件夹名永不变 |
| 删除图 | 事务内 `DELETE FROM items`（CASCADE 清 fa_runs/fa_snapshots/item_groups/item_tags）→ 事务后 best-effort `rmtree(<root>/<id>)`，失败仅留孤儿文件夹 |
| 删除分组 | CASCADE 清 item_groups；条目保留（变未分组） |
| 分组/标签/类型/字段 | 纯 SQL |
| 图内容（plot.py/data.csv/svg/patch/history/uploads） | 纯文件系统，不进 DB |
| 图文件夹创建 | 建图时**立即**创建并写入 plot.py（图与 Index 通用条目不同，内容是必需品；不违反 Index 的惰性约定） |

**双向互通**：SQL 是唯一真相。Index 应用内的重命名/移分组/打标签/删除对
figure-agent 立即可见；figure-agent 列表按 `item_type='图'` 过滤，其他条目
不显示但保留。被 Index 删除的图（文件夹已 rmtree）在 figure-agent 打开时报
404。图名不要求唯一（Index 同名合法），id 消歧。

## 5. server 重构

### 5.1 新增 `figure_agent/repo/` 包

```
repo/
├── migrations/            # 8 个 Index 原版 .sql（字节级副本）+ 000001_fa_ext.sql
├── db.py                  # sqlite3 连接（PRAGMA foreign_keys/busy_timeout）、行转 dict
├── migrations.py          # 幂等迁移器：_sqlx_migrations（只管 8 个原版）
│                          #                + fa_schema_migrations（fa 扩展）
├── repo.py                # open_or_init(root)、state.json 读写、RepoInfo
├── items.py               # create/update/delete/list/get + generate_id + 文件夹管理
├── groups.py  tags.py  types.py   # 镜像 Index engine 的 SQL 子集
└── runs.py                # fa_runs / fa_snapshots 读写
```

初始化策略（`open_or_init`，启动与 `migrate` CLI 共用）：
- `index.db` 不存在 → 建 `.index/`、跑 8 个原版迁移 + fa 扩展、写种子。
- 已存在 → 只确保 fa 扩展已应用 + 校验 `items` 表存在；**不重放**原版迁移。
- 打开时容忍未知列/表（Index 未来版本升级后 figure-agent 按名取列仍可用）。

### 5.2 `Store` 门面（`store.py`）

保留类名与渲染/patch/snapshot 管线，寻址从 `(project, figure)` 改为
`(item_id)`。接口对照：

| 旧 | 新 |
|---|---|
| `projects()` / `figures(project)` | `repo.list_items(type="图")`（分组/标签在 SQL join） |
| `figure_dir(project, figure)` | `figure_dir(item_id)` = `<root>/<id>` |
| `init_figure(project, figure, origin)` | `create_figure(name, origin, template=None, group_id=None)`：INSERT item + 建文件夹 + 写 plot.py |
| `read_meta/write_code/render/save_patch/verify_patch/snapshot/snapshots` | 同名方法改 `item_id`；meta 读写改 `items.properties`；snapshot 元数据写 `fa_snapshots` |
| 无 | `delete_figure(item_id)`、`rename_figure(item_id, name)`（新增） |

`ai/` 耦合点同步改：`workflows.build_registry/run_workflow(kind, store,
item_id, spec)`；`nodes.py` 七个工厂签名 `fdir = store.figure_dir(item_id)`；
`make_finalize` 与 `_audit_failure` 改写 `fa_runs`（经 `repo/runs.py`）；
`main.py` 的 AI 建图回滚 `rmtree(fdir)` 改调 `store.delete_figure`。

### 5.3 API 路由（`main.py` 重写路由表；旧 project/figure 寻址全部废除）

管理（镜像 Index 命令语义，HTTP 化子集）：

| 方法 路径 | 说明 |
|---|---|
| GET `/api/repo/info` | `{path, itemCount, dbVersion}` |
| GET/PUT `/api/repo/state` | state.json 读写（主题等） |
| GET `/api/items` | `?q=&groupId=&tagId=`，按类型"图"过滤，含分组/标签聚合 |
| POST `/api/items` | `{name, groupId?, template?, origin?}` 建图（origin 缺省 `template`） |
| PATCH `/api/items/{id}` | `{name?, properties?}` |
| DELETE `/api/items/{id}` | 删除图（SQL 先行 + rmtree） |
| POST/DELETE `/api/items/{id}/groups`、`/tags` | `{groupId}` / `{tagId}` 绑定与解绑 |
| GET/POST/PATCH/DELETE `/api/groups` | 多级分组 CRUD（`{name, parentId?, position?}`） |
| GET/POST/DELETE `/api/tags` | 扁平标签 |
| GET `/api/types` | 类型 + 字段列表 |
| POST `/api/types`、PATCH/DELETE `/api/types/{id}` | 类型管理（图/通用/任务同规则，预设保护与 Index 一致） |
| POST/PATCH/DELETE `/api/types/{id}/fields[/{fid}]` | 字段 CRUD |

图操作（内容管线，全部 id 寻址）：

> 实现注记（计划阶段裁剪，2026-10-22）：表中 `PATCH /api/types/{id}`（类型改名/图标）
> 与 `POST /api/figures/{id}/upload`（独立上传端点，上传已并入 `/api/figures/ai`、
> `/adapt` 的 multipart）未实现；另增补 `GET /api/figures/{id}/files`（文件树）。

| 方法 路径 | 说明 |
|---|---|
| GET `/api/figures/{id}` | 详情：item+code+baseSvg+finalSvg+patch+snapshots+renderError（懒渲染） |
| PUT `/api/figures/{id}/code`、POST `/run` | 写码/重渲染（更新"最后渲染"） |
| PUT `/api/figures/{id}/patch`、POST `/verify-patch` | patch 保存/收敛校验 |
| POST `/api/figures/{id}/snapshot` | `{note}` 快照 |
| GET `/api/figures/{id}/runs` | fa_runs 倒序 |
| POST `/api/figures/{id}/instruct`、`/writeback`、`/enrich-selection` | AI 编辑/回写/选区富化 |
| POST `/api/figures/ai` | multipart 数据 + `{name?, groupId?}` AI 建图（create 工作流） |
| POST `/api/figures/adapt` | multipart 数据+脚本 + `{name?, groupId?}` 改造建图 |
| POST `/api/figures/{id}/upload` | 上传至 uploads/ |
| GET `/api/templates` | 模板列表（不变） |

WS `/ws`、静态托管 `/` 不变。config：`FA_WORKSPACE` 即仓库根，语义升级为
"Index 仓库"。

## 6. web 重构（React 复刻 Index 管理壳）

### 6.1 双视图（无路由库，`App.tsx` 持 `view: {mode:'manage'} |
{mode:'editor', itemId} `）

**管理视图**（新 `components/manage/`，三栏，令牌复刻 Index `theme.css`）：
- 顶栏：仓库名 + 新建图（模板/AI）+ 亮暗切换。
- 左栏：搜索框（q → `/api/items?q=`）+ 分组树（多级、右键/按钮增删改、拖拽
  移动）+ 标签列表（扁平）。
- 中栏：图列表（名称、模板/来源属性徽标、分组、标签、更新时间；行点击选中，
  双击/打开按钮进编辑器视图；右键菜单：重命名/删除；可拖拽入分组（Index
  交互对齐）。
- 右栏：详情（行内重命名、按"图"字段渲染属性表单、分组 chips、标签 chips、
  文件树只读列出条目文件夹）；ActivityBar 切换"详情/类型"两个 tab，类型
  tab 提供类型+字段管理。

**编辑器视图**：现有 `Viewer`、`SelectionLayer`、`EditorPanel`、`AIPanel`
原样保留（含 dragselect、undo/redo、WS 事件），去掉旧 `Sidebar`（其模板建
图表单迁入管理视图），顶部加"← 返回管理"与图名。四栏 grid 改为
`1fr 300px 320px` 三栏。

### 6.2 样式与主题

`styles.css` 重构为 Index 令牌体系（`--bg/--surface/--text/--accent/…` +
亮暗双主题，暗色用 `html.dark` class）；主题持久化走 `/api/repo/state`
（`.index/state.json`，与 Index 共享），本地不再另存主题。

### 6.3 数据层

`types.ts`：`ProjectInfo/FigureInfo` 废除，新增
`ItemInfo{id,name,groupIds,tags,properties,createdAt,updatedAt}`（Index 语义：
一图可属多分组）、
`GroupInfo/TagInfo/TypeInfo/FieldInfo/RunInfo/SnapshotInfo`。
`api.ts`：按 §5.3 重写；WS 事件名不变。

### 6.4 测试影响

Viewer/selection/zoom/hover/regression 测试零改动；`AIPanel.test.tsx` 与
其余引用旧 API 的用例改 id 寻址；新增 manage 组件测试（分组树、列表、详情
表单、删除/重命名交互）。

## 7. 迁移 CLI

`python -m figure_agent migrate [--archive]`：

1. 前置检查：`<workspace>/.index` 不存在，且存在旧式 `<项目>/<图>/` 结构；
   否则报"无可迁移数据/已是仓库"退出。
2. `open_or_init` 建仓库。
3. 逐项目 → 建同名分组（顶级）；逐图 → `generate_id`、`shutil.move` 目录到
   根 `<id>/`、INSERT item（name/created_at 取自 meta.json，properties 写
   模板/来源/最后渲染）、绑定分组；`runs.jsonl` 逐行导入 `fa_runs`；
   `history/*/note.txt` 等已有快照登记进 `fa_snapshots`。
4. 删除已迁移的 `meta.json` / `runs.jsonl`；删除空项目目录（或 `--archive`
   时将整个旧结构移入 `<workspace>/_migrated_backup/`）。
5. 幂等：任何一步前检查目标已存在则跳过；重跑无副作用。迁移完成后正常启动。

## 8. 测试计划

- `test_repo_migrations.py`：嵌入 SQL 的 SHA-384 与 §3.1 常量逐一相等；
  init 幂等（跑两遍无变化、账本恰好 8 行 success）；fa 扩展幂等；表结构断言
  （7 张 Index 表 + fa 表 + 种子类型/字段）。
- `test_repo_semantics.py`：改名只动 DB；删除顺序（SQL 事务→rmtree，rmtree
  失败不回滚）；分组删除条目保留；同名图允许；索引过滤 type=图。
- `test_migrate_cli.py`：旧 fixture（`<项目>/<图>/`+meta.json+runs.jsonl）→
  迁移后 DB 记录/目录布局/幂等重跑/`--archive`。
- `test_store_executor.py` / `test_api.py` / `test_ai_workflows.py` /
  `test_ai_nodes.py`：全面改 id 寻址与新路由；AI 失败审计断言查 `fa_runs`。
- web：见 §6.4。
- 手工验收：用 Index 应用（itemmanage dev 构建）打开迁移后的 workspace，
  确认图列表/分组/标签/详情/文件树可见可编辑。

## 9. 风险与守则

1. **永不变更 Index 的 7 张表**：不 ALTER、不依赖 `SELECT *`；未来 Index 迁移
   新增列/表时 figure-agent 按名取列保持宽容。
2. **字节一致性**：迁移 SQL 副本 + `.gitattributes` eol=lf + 测试常量守护；
   一旦漂移，Index 打开时 sqlx 校验会失败。
3. **账本纪律**：fa 扩展只进 `fa_schema_migrations`；任何情况下不向
   `_sqlx_migrations` 插入非 Index 原版行。
4. **并发**：单进程 uvicorn + busy_timeout；不引入 WAL（与 Index 磁盘形态
   一致）。
5. **文档同步**：README、AGENTS.md 中涉及 workspace 布局/管理语义的描述随
   本重构更新；`docs/specs` 保留本文档作为契约来源。
