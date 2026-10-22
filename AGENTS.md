# AGENTS.md — figure-agent 绘图代码约定

本仓库包含 figure-agent：本地 Web 应用。AI 能力由服务端内嵌的 SpecModule
工作流提供（server/src/figure_agent/ai/），不依赖外部 coding agent / MCP。

## 面向人的约定（手写 plot.py 时）

### 渲染契约
1. 模块级构建图形，存入变量 `fig`；不要 `plt.show()`。
2. 不要调用 `matplotlib.use()`（服务端已预设 Agg）；不要碰
   `svg.fonttype` / `svg.hashsalt`（服务端强制）。
3. 数据放图目录 `data.csv`，代码用 `pd.read_csv("data.csv")` 读取。

### gid 约定（最重要）
对每个"用户可能想单独选中/修改"的 artist 调 `set_gid("fa:名字")`（示例与
细则见 `server/src/figure_agent/ai/prompts.py` 的 GID_CONVENTION）。
命名建议 `fa:<语义>-<序号>`，如 `fa:treatment-bar-2`、`fa:y-label`、`fa:title`。
没有 fa: gid 的元素只能靠脆弱的自动 id（patch_3、text_1，重渲染后会漂移）匹配。

### 安全字体
只用 DejaVu Sans / Arial / Helvetica / Times New Roman / SimHei /
Microsoft YaHei / Noto Sans CJK SC，避免运行时与浏览器渲染漂移过大。

## 面向开发的约定

- AI 工作流的 prompt 与契约文本唯一来源是 `server/src/figure_agent/ai/prompts.py`；
  改契约先改那里，本文件与它保持一致。
- 四条工作流（create 造图 / adapt 改造脚本 / edit 选区改图 / writeback 回写）
  是固定 tasklist，见 `server/src/figure_agent/ai/workflows.py`；改流程须同步其测试。
- LLM 配置：仓库根 `config.json` + `.env`（参考 `config.example.json`）；
  `FIGURE_AGENT_MOCK=1` 免 key 冒烟。
- 手动微调（patch）回写：在浏览器里做微调后，点 AI 面板的"回写 patch"，
  服务端循环翻译进代码直至收敛清空。
