# figure-agent v2：原生 AI 工作流（SpecModule 嵌入）设计文档

- 日期：2026-10-22
- 状态：已评审（方案 A 已确认）
- 前置：`docs/specs/2026-10-16-figure-agent-design.md`（v1，MCP 形态）

## 1. 背景与目标

v1 的 AI 大脑是外部 coding agent（ZCode），通过 MCP 工具（`fa_*` 系列）读写 FastAPI 服务。本设计去掉 MCP，把 AI 能力原生化到服务端：嵌入 [SpecModule](../../../SpecModule)（Petri 网工作流框架）作为 AI 工作流引擎，LLM 调用成为服务内的 harness 节点。

四条 AI 工作流全部原生化：

| 工作流 | 输入 | 输出 |
|---|---|---|
| **create** 造图 | 数据文件 + 绘图要求（自然语言） | 合规 plot.py + base.svg |
| **adapt** 改造 | 数据文件 + 现成绘图脚本 | 改造为框架合规的 plot.py + base.svg |
| **edit** 改图 | 浏览器选区 JSON + 修改指令 | 定点修改后的 plot.py + base.svg |
| **writeback** 回写 | patch.json（手动微调覆盖层） | patch 翻译进代码，收敛清空 |

### 成功标准（v2）

- T1 脱离 ZCode：四条工作流在浏览器内端到端可用，不依赖任何外部 agent/MCP。
- T2 合规产出：create/adapt 产出的 plot.py 满足渲染契约（`fig` 变量、`svg.fonttype` 不碰、安全字体）与 gid 约定（关键 artist 有 `fa:` gid），数据从 `data.csv` 读取。
- T3 自愈：渲染失败的代码能带着 stderr 自动修复（≤3 轮）后渲染成功。
- T4 回写收敛：writeback 循环至 patch `cleared: true`（或达轮数上限明确报告剩余 op）。

## 2. 已锁定决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 改造范围 | 全部原生化（含选区改图、patch 回写） | 去掉 MCP 后原工作流断裂，留一半没意义 |
| 数据输入 | 只做文件上传，格式不限；工作流首节点做数据标准化 | 用户明确要求；标准化是 harness 节点（任意表格→规范 CSV+画像） |
| 交互形态 | 任务式+迭代指令，无多轮对话 | 符合 SpecModule 无状态 run 哲学；上下文每次从 workspace 重建 |
| 工作流组织 | **方案 A：固定 tasklist 直写通道** | 绘图管线流程固定可预测，SpecModule 文档明确此场景用直写通道；LLM 只在 harness 节点干活 |
| SpecModule 依赖 | 本地路径可编辑安装（`pip install -e <SpecModule 仓库>`） | 两仓库同步开发，改 SpecModule 立即生效 |
| LLM 配置 | 复用 SpecModule 机制：figure-agent 根放 `config.json` + `.env`（+可选 `rules.txt`） | `LLMConfig.from_env()` 回退链原生支持；mock 客户端用 SpecModule 自带 `llm/mock.py` |
| 运行模型 | 同一时刻最多一个 AI run，全局串行；`persist=False` 零落盘 | 单人自用；审计靠自记 `runs.jsonl`，不依赖 SpecModule 落盘 |
| 选区传递 | 随指令请求体直带（删除 session 全局存储） | 不再有外部读者；请求自带更简单可靠 |

## 3. 总体架构

```
浏览器前端 ──HTTP+WS── FastAPI 服务 ──嵌入── SpecModule（module_harness + llm）
  AI 面板               │                  ├─ harness 节点 = LLM（三层 prompt + 输出校验）
  viewer/选区/编辑       │                  ├─ script 节点 = Store/executor 薄包装（纯函数）
  （不动）              │                  └─ 循环边 = 失败带 stderr 修复（≤3 轮）
                        │ subprocess
                  python plot.py → base.svg（渲染管线不变）
```

### 3.1 新增 `server/src/figure_agent/ai/` 包

| 模块 | 职责 |
|---|---|
| `llm.py` | `LLMConfig.from_env()` + `create_llm_client` 单例；`FIGURE_AGENT_MOCK=1` 时用 mock 客户端；`ai_status()` 返回 provider/model/是否 mock |
| `prompts.py` | prompt 资产唯一来源：渲染契约、gid 约定、安全字体表、四条工作流的 `prompt_core`；AGENTS.md 改为指向此文件 |
| `nodes.py` | script 节点函数：`parse_upload` / `write_data` / `render_validate` / `render_verify` / `read_patch` 等，dict 进 dict 出，内部调 Store（SpecModule 嵌入纪律：基础库纯函数，LLM 调用不上移） |
| `workflows.py` | 四条固定 tasklist 模板；`run_workflow(kind, figure_dir, inputs)` 入口：构造 `HarnessRegistry`（注册 harness + script）→ 构造 `Module(tasklist=…, persist=False)` → `await run()`；EventBus 事件桥接 WS hub |

### 3.2 删除清单

- `server/src/figure_agent/mcp_server.py`、仓库根 `.mcp.json`
- pyproject 依赖 `mcp>=1.2,<2`
- `server/src/figure_agent/session.py`（全局选区存储）及 `POST/GET /api/session/selection`
- AGENTS.md 中"微调回写工作流（ZCode 内）"一节，重写为面向服务端工作流的说明

### 3.3 harness 三层 prompt 约定

- `prompt_core`：任务定义 + 输出 JSON 格式约束（如 `{"code": "...", "notes": "..."}`），代码必须完整可执行
- `prompt_modes`：按需注入的契约文本——渲染契约、gid 约定、安全字体表、数据读取约定（从 `data.csv` 读）
- `prompt_extra`：本次运行的具体输入——数据画像 / 用户要求 / 原脚本 / 选区 JSON / 上一轮 stderr

harness 输出统一 `OutputFormat(type="json_object")`，由 SpecModule outputfmt 校验 + 自动提取。无法满足的要求写进 `notes`，禁止编造数据。

## 4. 数据模型变化

figure 目录新增（v1 布局其余不变）：

```
workspace/<project>/<figure>/
  data.csv            # 规范化数据；plot.py 用相对路径读它，不硬编码数据
  data_profile.json   # 数据画像
  uploads/            # 原始上传文件留存（.gitignore）
  runs.jsonl          # AI run 历史（追加写；.gitignore）
  meta.json           # 增加 "origin": "template" | "ai" | "adapt"
```

`data_profile.json` schema：

```json
{
  "shape": [12, 4],
  "columns": [
    {"name": "dose", "dtype": "number", "unit": "mg", "desc": "给药剂量",
     "stats": {"min": 0, "max": 10, "unique": 5}}
  ],
  "notes": "分组对照实验数据，每行一个样本"
}
```

standardize harness 输出 `{"csv": "...", "profile": {...}, "notes": "..."}`，`write_data` script 节点负责落盘 `data.csv` + `data_profile.json`。

## 5. 四条工作流（固定 tasklist）

共享骨架，差异在代码节点与循环出口。

### 5.1 create（数据+要求 → 图）

```
parse_upload → standardize(H) → write_data → gen_code(H) → render_validate
                                  ↑──(渲染失败, ≤3轮)── fix_code(H) ──┘
```

- `parse_upload`（script）：xlsx/xls 等二进制用 pandas 抽成 CSV 文本；文本格式原样透传
- `standardize`（harness）：任意表格文本 → 规范 CSV + 数据画像（列名/类型/单位/统计/语义）
- `gen_code`（harness）：数据画像 + 用户要求 + 契约 → plot.py
- `fix_code`（harness）：上轮代码 + stderr/出错行 + 画像 → 修复版 plot.py
- `render_validate`（script）：写 plot.py、渲染、收集 ok/stderr/errorLine/warnings/gid 统计；轮数计数在此

### 5.2 adapt（数据+脚本 → 改造）

与 create 同构，`gen_code` 换 `adapt_code`（harness）：读原脚本意图（图表类型/映射/风格）→ 改造为合规 plot.py：`fig` 变量、补 `fa:` gid、安全字体、数据源改读 `data.csv`。原脚本与数据冲突时以数据为准，差异写 `notes`。

### 5.3 edit（选区+指令 → 改图）

```
edit_code(H) → render_validate ─┐
   ↑──────(渲染失败, ≤3轮)──────┘
```

无数据节点。`edit_code` 输入：当前 plot.py + 选区 JSON（多选为数组，逐项语义目标）+ 用户指令 + 契约。选区 JSON 由前端从现有 selection 状态构造，随请求体直带。

### 5.4 writeback（patch 回写收敛）

```
read_patch →(ops 空→直接结束) translate_patch(H) → render_verify ─┐
   ↑──────────────(未 cleared, ≤3轮)──────────────────────────────┘
```

- `read_patch`（script）：读 patch.json + 当前代码；ops 为空直接置 `cleared`
- `translate_patch`（harness）：patch ops（intent + 语义目标）翻译进代码（改色→color 参数、隐藏→set_visible(False)、置顶→set_zorder 等），并给对应 artist 补 gid
- `render_verify`（script）：渲染 + 调 `store.verify_patch()`；resolved 自动删除；未 cleared 时把剩余 op 与逐 op 判定结果喂回下一轮

### 5.5 通用约束

- 轮数上限在 script 节点内用 tickflow body 状态计数，超限输出 failed 终态（不抛异常），前端明示"已到修复上限"
- 事件：EventBus 订阅（`HarnessCompleted`/`HarnessFailed`/script 事件等）桥接为 WS 消息 `{type: "ai_run", runId, node, status, detail}`
- 每次 run 结束追加一行 JSON 到 `runs.jsonl`：`{runId, kind, at, ok, rounds, notes, error?}`

## 6. 接口设计

REST 新增（模板建图等 v1 端点全部保留）：

| 方法/路径 | 作用 |
|---|---|
| `GET /api/ai/status` | `{configured, provider, model, mock}`——前端徽标 |
| `POST /api/projects/{p}/figures/ai` | AI 造图。multipart：`name` + `data`（文件）+ `requirements`（文本） |
| `POST /api/figure/{p}/{f}/adapt` | 脚本改造。multipart：`data`（文件）+ `script`（.py 文件） |
| `POST /api/figure/{p}/{f}/instruct` | 选区改图。JSON body：`{instruction, selection}`（selection 为 v1 定位 JSON 或其数组） |
| `POST /api/figure/{p}/{f}/writeback` | patch 回写收敛，返回最终 `{cleared, remainingOps, results}` |
| `GET /api/figure/{p}/{f}/runs` | run 历史（runs.jsonl 倒序） |

WS：`/ws` 在 v1 事件基础上增加 `ai_run` 事件（见 §5.5）。

## 7. 前端设计

- 新增 **AI 面板**（EditorPanel 同级新组件）：
  - 造图表单：图名 + 数据文件选择 + 要求多行文本 → `figures/ai`
  - 改造表单：数据文件 + 脚本文件 → `adapt`
  - 指令输入：多行文本框；当前有选区时自动在请求里附加选区 JSON，并显示"已附加 N 个选区元素"提示 → `instruct`
  - 回写按钮（patch 非空时可用）→ `writeback`
  - run 时间线：订阅 WS `ai_run` 事件，节点名 + 状态（运行中/成功/失败）+ notes 实时展示
  - AI 状态徽标：未配置 LLM 时提示去配 `config.json`/`.env`，面板内提交按钮禁用
- viewer / selection / editor 组件与交互不动；"复制选区 JSON"兜底按钮保留（调试用途）

## 8. 错误处理

| 场景 | 处理 |
|---|---|
| LLM 输出不合法 / `HarnessCallError` | 工作流 failed，failure 链（failure/prompt/raw/usage）写入 runs.jsonl，WS 事件透传摘要；不静默重试 |
| 渲染失败 | fix 循环 ≤3 轮；仍失败保留上一版 base.svg（v1 行为），WS 报 stderr + 出错行 |
| 数据解析失败 | pandas 读不了 → 当纯文本交 standardize；standardize 校验失败 → failed 透传 |
| run 进行中再提交 | 服务端全局串行队列；前端提交后禁用各提交按钮直至 run 结束 |
| WS 断连 | 前端降级为结果轮询（`GET runs` + `GET figure`），v1 可接受手动刷新 |
| gid 缺失 | render 统计 warnings 照旧返回；gen/adapt 的 prompt 已强制 gid，`notes` 提示补齐 |

## 9. 测试策略

- **pytest（主战场）**：
  - mock LLM 客户端（SpecModule `llm/mock.py` 或自写 stub，按 kind 返回固定合规代码）跑通四条工作流：节点触发顺序、落盘产物（data.csv/data_profile.json/plot.py）、runs.jsonl 追加
  - 修复循环：mock 首轮返回坏代码（引用不存在的列）→ 断言 fix 节点被调且第二轮成功
  - writeback：构造带 active op 的 patch → mock 翻译代码 → 断言 `cleared: true`；超限路径断言 failed 终态
  - `parse_upload`/`render_validate`/`render_verify` 纯函数单测（csv/xlsx/坏文件）
  - v1 既有 pytest 全部保留并通过
- **vitest**：AI 面板事件时间线、提交禁用态、选区附加提示
- **真实 LLM smoke**：手动跑 create + adapt 各一例（create：仓库内新增测试夹具 `server/tests/fixtures/iris.csv`；adapt：以现有 `workspace/demo/iris-scatter/plot.py` 为改造输入），人工核对 T2 合规性

## 10. 实施顺序（里程碑）

1. **M-A 基建**：SpecModule 本地安装接线、`ai/llm.py` + config.json/.env、`ai/prompts.py`（契约文本从 AGENTS.md 迁移）、WS 桥接
2. **M-B create 工作流**：nodes + workflows + REST + mock 测试跑通（mock 与真实 LLM 各验一次）
3. **M-C adapt 工作流**：复用骨架，新增 adapt_code prompt 与端点
4. **M-D edit + writeback**：instruct/writeback 端点、writeback 循环收敛
5. **M-E 前端 AI 面板**：表单 + 时间线 + 状态徽标
6. **M-F 清理**：删 mcp_server/.mcp.json/session.py、依赖与文档重写、AGENTS.md 更新

依赖关系：B 依赖 A；C/D 依赖 B（骨架复用）；E 可与 C/D 并行；F 最后。

## 11. 明确不做（v2）

多轮对话/聊天历史、LLM 现场翻译 tasklist（方案 B/C 兜底通道）、R 后端、非表格数据（图像/音频）、数据清洗的交互式确认 UI（standardize 一步到位，notes 说明取舍）、并发 run、SpecModule 落盘审计（persist=False）。

## 12. 风险与对策

| 风险 | 对策 |
|---|---|
| SpecModule 库面 API 与本地仓库演进修辞性断裂 | 本地可编辑安装（不做版本 pin，两仓库同人同步维护）；只依赖文档承诺的库面导出（`module_harness` 顶层 + `llm`），不触达 CLI 等内部子模块 |
| LLM 生成代码不守 gid 约定 | prompt 强制 + render_validate 统计 faGroups，缺失进 warnings；adapt 对原脚本逐 artist 补 gid |
| 大 JSON 里转义长代码易碎 | outputfmt json_object 校验失败 → 该轮按失败处理走 fix 循环；`notes` 独立字段承载非代码说明 |
| xlsx 等二进制解析环境差异 | pandas + openpyxl 进服务端依赖；解析失败降级为文本进 standardize |
| 单 run 串行阻塞其他操作 | 非AI 端点（查看/手动 patch/渲染）不受影响；仅 AI 提交排队 |
| mock 与真实 LLM 行为偏差 | mock 只保证工作流编排正确；T2 合规性靠真实 LLM smoke 人工验收 |
