# AGENTS.md — figure-agent 绘图代码约定

本仓库是**独立的本地 web 应用**：服务端在**一个工作目录**里画图（matplotlib → SVG），
浏览器端做选区微调与 AI 工作流；不管理项目、不碰任何数据库。它通常被 Index 宿主以
iframe 形式嵌进中间页签（Index 管条目/类型/分组，fig 只管目录里的图）。

- 服务入口：`python -m figureagent --dir <绝对路径>`（托管 `web/dist` + `/api/*` + `/ws`）
- 设计：`docs/specs/2026-11-07-standalone-view-spec.md`
- 代码位置：`server/src/figureagent/`（Python）、`web/src/`（React）

## 面向人的约定（手写 plot.py 时）

### 渲染契约
1. 模块级构建图形，存入变量 `fig`；不要 `plt.show()`。
2. 不要调用 `matplotlib.use()`（服务端已预设 Agg）；不要碰
   `svg.fonttype` / `svg.hashsalt`（服务端强制）。
3. 数据放图目录 `data.csv`，代码用 `pd.read_csv("data.csv")` 读取。

### gid 约定（最重要）
对每个"用户可能想单独选中/修改"的 artist 调 `set_gid("fa:名字")`（示例与
细则见 `server/src/figureagent/figures/ai/prompts.py` 的 GID_CONVENTION）。
命名建议 `fa:<语义>-<序号>`，如 `fa:treatment-bar-2`、`fa:y-label`、`fa:title`。
没有 fa: gid 的元素只能靠脆弱的自动 id（patch_3、text_1，重渲染后会漂移）匹配。

### 安全字体
只用 DejaVu Sans / Arial / Helvetica / Times New Roman / SimHei /
Microsoft YaHei / Noto Sans CJK SC，避免运行时与浏览器渲染漂移过大。

## 面向开发的约定

### 存储契约（单目录）

- 唯一输入是 `--dir` 指定的**一个目录**；服务启动即绑定，**请求里的 `?dir=` 在绑定后
  被忽略**（防止任意页面把服务指向别的目录）。换目录 = 换进程。
- 目录内容固定：`plot.py`（真相源）`data.csv` `data_profile.json` `base.svg`
  `final.svg` `patch.json` `uploads/` `history/`（`history/runs.jsonl` 记运行审计，
  `history/<ts>/` 是快照）。
- **不碰任何 SQLite**：没有条目、没有 types/items、没有图扩展表。`是否有图` 由
  `Workdir.has_figure()`（`plot.py` 是否存在）判定，Index 侧自行看文件。
- 路径一律经 `safe_path(root, rel)`；保留名（`RESERVED_NAMES`/`RESERVED_DIRS`）只用于
  建图门禁，不做 files 域守护（没有 files 域）。

### API 契约

- `GET /api/context` → `{dir, name, has_figure}`；`GET /api/files` → 工作目录只读树
  （`POST /api/files/list` 是同一接口的旧别名，body 里的 `itemId` 忽略）。
- 图端点保持 `/api/figures/{figure_id}/...` 形状，但 **`{figure_id}` 段被忽略**
  （单工作目录模型）；同时提供不带该段的同义路由。前端统一用字面量 `work`。
- WS `/ws` 事件带 `dir` 字段（与 `/api/context` 同值）；没有 item id 语义。
- 就绪握手：stdout 打印 `FIG_SERVICE_PORT=<port>` 与 `FIG_SERVICE_READY`（宿主依赖它）。

### AI 工作流与配置

- prompt 与契约文本唯一来源是 `server/src/figureagent/figures/ai/prompts.py`；
  改契约先改那里，本文件与它保持一致。
- 四条工作流（create 造图 / adapt 改造脚本 / edit 选区改图 / writeback 回写）
  是固定 tasklist，见 `figures/ai/workflows.py`；改流程须同步其测试。
- LLM 配置：`$FIGUREAGENT_HOME`（默认 `~/.figureagent`）下的 `config.json` + `.env`；
  `FIGUREAGENT_MOCK=1` 免 key 冒烟（兼容旧名 `FIGURE_AGENT_MOCK` / `RI_FIGURE_MOCK`）。
- 手动微调（patch）回写：浏览器里微调后点 AI 面板的"回写 patch"，服务端循环翻译进
  代码直至收敛清空。

### 测试

```bash
cd server && PYTHONPATH=src <venv-python> -m pytest tests -q   # 122 用例
cd web   && pnpm test && pnpm build                            # vitest + dist
```
