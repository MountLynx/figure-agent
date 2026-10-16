# figure-agent（科研图表绘制 Agent）设计文档

- 日期：2026-10-16
- 状态：待评审
- 形态：本地 Web 应用 + MCP 工具，单人自用

## 1. 背景与目标

用 AI（当前是 ZCode）编写和修改 matplotlib 绘图代码来产出科研图表。痛点：纯文字描述"改哪里"不准确，AI 靠猜；代码重跑会丢掉手动微调。

本项目提供一个本地工具，把"改哪里"变成结构化数据传给 AI，并让手动微调可记录、可回写为代码：

1. **选区回传**：在浏览器里框选/点选 SVG 元素，生成带语义的定位 JSON，AI 据此定点修改绘图代码并重渲染。
2. **轻量编辑**：颜色、字体字号、位置、大小四项手动微调，记录为 patch，代码重跑不丢失。
3. **微调回写**：AI 把 patch 翻译进绘图代码，重渲染后自动校验收敛，patch 清空即完成。

### 成功标准（v1）

- S1 闭环：仅凭选区 JSON（不看截图坐标），AI 能正确执行"把处理组第三根柱子改红"类指令，成功率 ≥ 90%。
- S2 不丢：修改代码重跑后，手动微调仍然生效。
- S3 回写：典型微调（配色系列、字号、单元素位移）能被 AI 回写为代码，patch 收敛清空的比例 ≥ 80%。

## 2. 已锁定决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 产品形态 | 本地 Web 应用：Vite + React + TS 前端 + Python FastAPI 本地服务 | 迭代最快；浏览器 DOM 是 SVG 交互引擎；Python 贴科研生态 |
| 绘图后端 | v1 仅 Python/matplotlib；R 后置为模板工作 | 先把管线打通，抽象好渲染契约 |
| 用户 | 单人自用：无鉴权、无打包分发、中文 UI | YAGNI |
| AI 集成 | **v1 = MCP server 把工具暴露给 ZCode；不做内嵌聊天面板** | 复用现成 agent，省掉 API key 管理和 agent loop 自研；复制 JSON 作兜底 |
| 选区交互 | DragSelect v3（交互层）+ 原生 `getIntersectionList`（精确模式/校验） | DragSelect 官方支持 SVG selectables；AABB 判定不识别 clip-path，需原生 API 补 |
| 真相模型 | 代码 = 真相源；手动编辑 = patch 覆盖层；`final = base + patch` | 代码重跑不丢微调；回写变成可验证的收敛过程 |
| 元素身份 | gid 约定优先（`set_gid("fa:…")`），指纹回退 | 回写成败的关键，第一天就要有 |

## 3. 总体架构

```
┌─────────────┐  MCP (stdio)  ┌───────────────────────┐  HTTP + WS  ┌──────────────────┐
│ ZCode (AI)  │◄─────────────►│ FastAPI 本地服务        │◄───────────►│ 浏览器前端         │
│ 读选区·改代码│               │ 执行器·身份匹配·patch   │             │ 查看器·选区·轻编辑 │
└─────────────┘               └───────────┬───────────┘             └──────────────────┘
                                          │ subprocess
                                   python plot.py → base.svg
                                          │
                        workspace/<project>/<figure>/
                        plot.py · base.svg · patch.json · meta.json · history/
```

组件职责（每个单元一句话）：

- **前端 viewer**：注入 base.svg 到 DOM，viewBox 平移缩放，监听后端"图已更新"事件自动刷新。
- **前端 selection**：DragSelect 管拖框/点击/修饰键；命中后向上归并到语义组；overlay 高亮；把选区 JSON 推给后端会话状态。
- **前端 editor**：四项编辑手势 → 翻译为 patch op → 本地预览（直接改 DOM）→ 保存时 PUT patch。
- **后端 executor**：subprocess 跑 plot.py，注入渲染契约（见 §5），产出 base.svg。
- **后端 svgkit**：SVG 规范化、语义组标注、元素身份匹配、patch 应用与收敛判定（纯函数库，pytest 主战场）。
- **后端 session**：保存浏览器推送的最新选区，供 MCP 工具读取。
- **MCP server**：stdio 进程，REST API 的薄包装，工具集见 §7。

## 4. 数据模型

### 4.1 项目目录（git 友好，一图一目录）

```
workspace/
  <project>/                     # 项目 = 子目录
    <figure>/
      plot.py                    # 真相源，用户/AI 编辑
      base.svg                   # 代码渲染产物（不可手改，重跑覆盖）
      patch.json                 # 手动微调覆盖层（可手改，进 git）
      meta.json                  # 名称、创建时间、最后渲染时间、代码入口
      history/                   # 不可变快照
        2026-10-16T103005/
          base.svg  patch.json  note.txt
```

项目管理 = 文件系统 + 内存索引，v1 不用数据库。

### 4.2 patch.json schema

```json
{
  "baseHash": "3f9a…",
  "ops": [
    {
      "id": "op-7",
      "kind": "set_style",
      "target": {"id": "fa:series-1", "fingerprint": "p:9c2e", "semanticPath": "fig/layer-2/g/series-1"},
      "attr": "fill",
      "value": "#2A6F97",
      "intent": "处理组柱子改为主色蓝",
      "origin": "manual",
      "status": "active"
    }
  ]
}
```

- `target.id` / `target.fingerprint` 至少有一个；匹配顺序：id → fingerprint → 报告 lost。
- `intent` 必填：回写时 AI 读的是意图 + 语义目标，不是裸 diff。
- op 词表 v1（刻意小）：
  - `set_style`：attr ∈ {fill, stroke, font-family, font-size, opacity}
  - `set_text`：value = 新文本（作用于 `<text>`/`<tspan>`）
  - `transform`：`{translate: [dx, dy]}` 或 `{scale: [sx, sy]}`（以 bbox 中心为原点）
- `status` ∈ {active, resolved, lost}：resolved = 已被代码表达；lost = 目标找不到，UI 高亮提示重新选择。

## 5. 渲染契约（matplotlib）

executor 执行用户 plot.py 时注入前置环境：

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["svg.fonttype"] = "none"   # 文字保持 <text>，可编辑——命脉开关
plt.rcParams["svg.hashsalt"] = "figure-agent"  # 输出确定性
```

- **代码契约**：plot.py 在模块级构建图形并存入变量 `fig`；executor exec 后取 `fig.savefig(base.svg)`。
- **gid 约定**：AI 写代码时对关键 artist 调 `set_gid("fa:series-1")`，会成为 SVG 的 `id`。约定前缀 `fa:`。提供一份 AGENTS.md 模板让 ZCode 自动遵守。
- **禁用项检查**：若用户代码覆盖 `svg.fonttype`，executor 警告并强制回 `none`。
- 超时 30s（可配）；stderr 全文透传给前端和 MCP；渲染失败保留上一版 base.svg。

## 6. 身份匹配与回写

### 6.1 身份匹配（svgkit 纯函数）

语义组来源（优先级从高到低）：`fa:` gid 约定 > matplotlib 自动生成的 id（`PathCollection_1`、`legend_1`、`axes_1` 等）> 原始元素。定位 JSON 与 DragSelect 的 selectables 都基于该语义层。

`match(old_svg, new_svg, ops) -> per-op status`：

1. id 精确匹配（`fa:` gid）；
2. 指纹回退：文本元素用 (textContent + 祖先链 + 兄弟序号)；路径/形状用 (归一化 `d` 相对形状 hash + 祖先链 + 序号)；
3. 都失败 → `lost`。

匹配前对两个 SVG 做规范化（属性排序、transform 展开、数值精度统一），避免假 diff。

### 6.2 收敛式回写循环（M2 核心工作流）

1. 用户在 ZCode 里说"把 patch 回写进代码"；
2. ZCode 调 `fa_get_patch` + `fa_get_figure` 读代码 → 产出代码修改（matplotlib 对应 artist 参数 / rcParams；R 的 ggplot 映射留到 M4），同时给新代码补 gid；
3. ZCode 调 `fa_set_code` → 重渲染新 base；
4. ZCode 调 `fa_verify_patch` → 服务端逐 op 判定：新 base 中目标已具有目标属性值（数值 ±ε）→ resolved；
5. resolved 的 op 自动从 patch 删除，lost/active 保留并继续生效；patch 清空 = 回写完成。

失败安全：翻译错了图也不坏（覆盖层仍在），可反复迭代。

## 7. 接口设计

### 7.1 REST API（FastAPI，静态托管 web/dist）

| 方法/路径 | 作用 |
|---|---|
| GET /api/projects · /api/projects/{p} | 列项目/图 |
| POST /api/projects/{p}/figures | 从模板建图 |
| GET /api/figure/{p}/{f} | base.svg、final.svg、patch、meta |
| PUT /api/figure/{p}/{f}/code | 写 plot.py 并触发渲染 |
| POST /api/figure/{p}/{f}/run | 重渲染 |
| PUT /api/figure/{p}/{f}/patch | 保存 patch |
| POST /api/figure/{p}/{f}/verify-patch | 身份匹配 + 收敛判定 |
| POST /api/figure/{p}/{f}/snapshot | 打快照（note） |
| POST /api/session/selection | 浏览器推送当前选区 JSON |
| WS /ws | 图更新、渲染进度事件 |

### 7.2 MCP 工具（薄包装 REST）

| 工具 | 作用 |
|---|---|
| fa_list_projects / fa_list_figures | 浏览项目 |
| fa_get_selection | 读浏览器当前选区 JSON（无选区时明确返回提示） |
| fa_get_figure | 代码 + base.svg + patch 摘要 |
| fa_set_code | 写代码并渲染，返回错误或成功统计（元素数、语义组列表） |
| fa_run | 不改代码仅重渲染（用户在外部改了 plot.py 后用） |
| fa_get_patch / fa_set_patch | 读/写 patch |
| fa_verify_patch | 回写收敛判定，返回每 op 状态 |

## 8. 前端设计

- **技术**：Vite + React 18 + TS；SVG 以 `dangerouslySetInnerHTML` 注入受控容器；构建后由 FastAPI 静态托管（单进程单端口），开发期 vite proxy。
- **viewer**：自研 viewBox 平移缩放（约百行）；zoom/pan 后重设 DragSelect selectables（封装进 SelectionLayer 组件统一负责）。
- **selection**：
  - selectables = 语义级 `<g>` 组（几十~几百个），不全量喂节点；
  - 单元素点击用 `elementFromPoint` + 向上归并；
  - 精确模式开关：切到 `getIntersectionList`（真实几何判定，排除 clip-path 隐藏元素）；
  - 选中态 = 自绘 overlay bbox 高亮框（不污染原图，导出无选中态）；DragSelect 的 draggability 关闭。
- **定位 JSON**（推给后端会话，供 MCP 读取）：

```json
{
  "elementId": "fa:series-1",
  "semanticPath": "fig/layer-2/g/series-1",
  "userSpaceBBox": {"x": 120.4, "y": 88.0, "w": 18.2, "h": 210.5},
  "style": {"fill": "#4472C4", "stroke": "none"},
  "text": {"content": null, "fontFamily": null, "fontSize": null},
  "fingerprint": "p:9c2e",
  "nearby": ["y轴刻度 0.5", "图例项 'Treatment'"]
}
```

- **editor**：四项手势 1:1 生成 patch op；undo/redo = 本地 op 栈；保存 = PUT patch。
- **面板**：图列表侧栏、op 列表（状态徽标 active/resolved/lost）、快照历史、"复制选区 JSON"按钮（MCP 不可用时的兜底通道）、PNG（前端 canvas）/SVG 导出。
- plot.py 在 web 端只读展示，代码编辑都在 ZCode/编辑器侧（自用，砍掉内嵌代码编辑器）。

## 9. 错误处理

- 渲染错误：stderr 全文 + 出错行号透传到前端与 MCP 返回值。
- patch op 非法或目标 lost：标记状态，绝不静默丢弃；lost 在 UI 高亮。
- SVG 解析失败：拒绝采用新渲染，保留上一版并报错。
- WS 断连：前端降级为轮询 GET figure。

## 10. 测试策略

- pytest 单测（svgkit）：规范化、身份匹配、patch 应用、收敛判定——用固定的 matplotlib 输出做 fixture（含改数据重渲染的场景）。
- vitest：语义归并、选区 JSON 构造。
- 端到端示例项目一个（iris 散点 + 分组柱状图），走"改代码 → 微调 → 回写"全流程，作为冒烟与演示。

## 11. 演进路线

- **M0 选区闭环（1–2 周）**：FastAPI + executor + viewer + DragSelect 选区 + 语义归并 + 定位 JSON + MCP（fa_get_selection / fa_set_code / fa_run）。无任何编辑功能。验收 = S1。
- **M1 轻编辑 + patch（2–3 周）**：四项编辑、op 栈 undo/redo、patch 持久化、`final = base + patch`、快照历史、PNG/SVG 导出、WS 自动刷新。验收 = S2。
- **M2 回写**：svgkit 匹配 + verify-patch API + AGENTS.md 约定模板 + 收敛工作流。验收 = S3。
- **M3 项目与风格**：项目视图完善、期刊模板（Nature/IEEE 尺寸字号色板一键套用）、批量 restyle。
- **M4（可选）**：R 支持（渲染契约换 svglite + 层序映射）、Tauri 壳、内嵌聊天面板。

## 12. 明确不做（v1）

鉴权/多用户、打包安装器、云同步、内嵌 LLM 聊天、R、套索选区、自由绘图、动画、协作编辑。

## 13. 风险与对策

| 风险 | 对策 |
|---|---|
| matplotlib 默认文字转路径 | runner 强制 `svg.fonttype='none'`，覆盖时警告 |
| 运行时与浏览器字体不一致 → 布局漂移 | 文档声明安全字体集（DejaVu/Arial/思源黑体），v1 接受轻微差异 |
| 数据微变导致指纹漂移 | 归一化相对形状 hash；失效降级"祖先链+序号+文本"；lost 可视化提示重选 |
| DragSelect 缓存随 zoom/渲染失效 | SelectionLayer 统一负责重设 selectables |
| `getIntersectionList` 浏览器差异 | 自用 Chrome/Edge；保留 getBBox 手动求交降级路径 |
| AI 不守 gid 约定 | AGENTS.md 模板 + fa_set_code 返回值中提示缺失 gid 的语义组 |
