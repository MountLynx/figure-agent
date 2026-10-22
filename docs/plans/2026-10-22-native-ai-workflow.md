# figure-agent v2 原生 AI 工作流实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 去掉 MCP，把四条 AI 工作流（create 造图 / adapt 改造脚本 / edit 选区改图 / writeback patch 回写）原生化到 FastAPI 服务端，用 SpecModule（Petri 网工作流框架）作为 harness/script 编排引擎。

**Architecture:** 前端 AI 面板提交任务 → REST 端点构造 spec → `run_workflow()` 为每次 run 构建全新 `HarnessRegistry`（harness=LLM 节点、script=Store 薄包装）+ 固定 tasklist（直写通道，`review_harness=None`）→ `Module(persist=False…)` 全内存运行 → EventBus 事件桥接 WS 实时推送 → Finalize 节点把结果追加到 `runs.jsonl` 并作为端点返回值。循环（渲染失败修复 / 回写未收敛）用 tickflow guard 边 + `view.state` 计轮数，上限 3 轮。

**Tech Stack:** FastAPI + SpecModule（`pip install -e C:\Users\xingy\Desktop\开发\SpecModule`，提供 `module_harness` / `llm` 顶层包）+ tickflow（SpecModule 依赖，自动安装）+ pandas/openpyxl（xlsx 解析）+ React/Vite。

**Spec:** `docs/specs/2026-10-22-native-ai-workflow-design.md`（本计划的两处有意偏差：① adapt 端点放在项目级 `POST /api/projects/{p}/figures/adapt`（与 create 对称、一步建新图），非 spec 表中的 figure 级；② 契约文本直接拼入 `prompt_core`，不用 `prompt_modes`（所有 harness 都需要全量契约，无"按需"可言）。

## SpecModule API 速查（实现者必读）

| API | 位置 | 要点 |
|---|---|---|
| `Module(spec, tasklist=, llm_client=, event_bus=, registry=, persist=False, status_file=False, keep_records=False, stream_log=False, control=False, review_harness=None, module_id=)` | `SpecModule/module_harness/model/module.py:72` | tasklist 与 template_name 二选一；`review_harness=None` 跳过一致性审核（固定管线不要花一次 LLM）；`await module.run(max_ticks=60)` 返回 firings |
| `Tasklist(tasks={名: TaskDefinition(...)}, flow="...")` | `module_harness/model/spec.py` | flow DSL：`[A] --> B` 起点边、`A --|guard|--> B` 守卫边、`X.join: OR` |
| `TaskDefinition(type="harness", harness="名", inputs={字段: producer节点名或"{spec.xxx}"})` | 同上 | 常量 `{spec.xxx}` 只对 **harness** 生效（进 spec_inputs 作 prompt 兜底）；**script 的常量 inputs 会被静默丢弃**——script 需要的常量一律走闭包 |
| `reg.harness("名", HarnessConfig(prompt_core=..., output_format=OutputFormat(type="json_object")))` | `module_harness/core/registry.py:46` | prompt `{key}` 占位符：先取具名 bind（inputs 键名），再取 spec 常量，未命中保留原样；正则 `\{(\w+)\}`，故 prompt 里 JSON 示例的引号键（`{"code": ...}`）不会被误替换 |
| `reg.script("名")(fn)` | `registry.py:75` | fn(view) 支持同步与 async；`view.field("inputs键名")` 取 producer 最新输出（未点火抛 KeyError/TypeError，须 try/except）；`view.state` 是跨 tick 持久的节点级 dict（计轮数用）；`view.output` 是"最近触发的前驱"输出 |
| `reg.guard("名", fn)` | `module_harness/model/submodule.py:131`（用法示例） | fn(view) -> bool；守卫边 `view.output` = 该边源节点输出。**互补守卫必须严格 XOR**，否则死等或双走 |
| EventBus | `module_harness/infra/events.py` | `bus.subscribe(事件类, 回调)`；事件带 `.node`；`ScriptFailed.error`、`HarnessFailed.reason` |
| harness 输出统一 `json_object`；prompt `{key}` 渲染：具名 bind → spec 常量 → 保留原样。dict 类 bind 以 Python repr 渲染（长代码会带 `\n` 转义）——已知取舍，真实 LLM smoke（Task 7）若发现修复质量差再引入序列化前置节点 |
| `LLMConfig.from_env(project_root=...)` / `create_llm_client(cfg)` | `SpecModule/llm/config.py:168`、`llm/client.py` | 传 `project_root=figure_agent.config.REPO_ROOT` 使 figure-agent 根的 config.json/.env 生效；providers 为空抛 `ValueError`；`cfg.model` / `cfg.provider` |
| `MockLLMClient` | `SpecModule/llm/mock.py` | `complete(**kw)->LLMResponse`；json_object 时返回 `{"result": "mock output", ...}`（内容是占位符，仅用于接线冒烟；工作流测试用自带 StubLLM） |
| LLM 客户端协议 | `example/demo_loop.py:31` | `async complete(prompt=..., **kw) -> LLMResponse(content, usage, finish_reason)` |

**figure-agent 现有约定**：测试跑法 `cd server && python -m pytest tests/ -q`（venv：`server/.venv`）；前端测试 `cd web && npm test`；Store 方法均为同步（渲染走 `executor.render_with_timeout_guard` 子进程）。

---

### Task 1: 依赖接线与 `ai/llm.py` + `GET /api/ai/status`

**Files:**
- Modify: `server/pyproject.toml`
- Create: `server/src/figure_agent/ai/__init__.py`
- Create: `server/src/figure_agent/ai/llm.py`
- Create: `config.example.json`（仓库根）
- Modify: `server/src/figure_agent/main.py`（加一个端点）
- Test: `server/tests/test_ai_llm.py`

- [ ] **Step 1: 安装 SpecModule（可编辑）+ 新依赖**

```bash
cd "C:\Users\xingy\Desktop\开发\figure-agent\server"
.venv/Scripts/pip install -e "C:\Users\xingy\Desktop\开发\SpecModule"
.venv/Scripts/pip install "pandas>=2.0" "openpyxl>=3.1"
.venv/Scripts/python -c "import module_harness, llm, tickflow, pandas; print('ok')"
```

Expected: 打印 `ok`

- [ ] **Step 2: pyproject 更新依赖（mcp 先留着，Task 10 删）**

`server/pyproject.toml` dependencies 数组追加两行：

```toml
    "pandas>=2.0",
    "openpyxl>=3.1",
```

- [ ] **Step 3: 写失败测试**

`server/tests/test_ai_llm.py`：

```python
"""ai.llm：mock 开关与状态探测。"""

from __future__ import annotations

import figure_agent.ai.llm as ai_llm


def test_ai_status_mock(monkeypatch):
    monkeypatch.setenv("FIGURE_AGENT_MOCK", "1")
    status = ai_llm.ai_status()
    assert status == {"configured": True, "provider": "mock", "model": "mock", "mock": True}
    client = ai_llm.get_llm()
    assert type(client).__name__ == "MockLLMClient"


def test_ai_status_unconfigured(monkeypatch, tmp_path):
    monkeypatch.delenv("FIGURE_AGENT_MOCK", raising=False)
    monkeypatch.setattr(ai_llm, "REPO_ROOT", tmp_path)  # 无 config.json 的根
    status = ai_llm.ai_status()
    assert status["configured"] is False and status["mock"] is False
```

- [ ] **Step 4: 运行确认失败**

Run: `cd server && .venv/Scripts/python -m pytest tests/test_ai_llm.py -q`
Expected: FAIL（`ModuleNotFoundError: figure_agent.ai`）

- [ ] **Step 5: 实现**

`server/src/figure_agent/ai/__init__.py`：

```python
"""原生 AI 工作流：SpecModule 嵌入（harness=LLM 节点 / script=Store 薄包装）。"""
```

`server/src/figure_agent/ai/llm.py`：

```python
"""LLM 客户端装配：复用 SpecModule 配置链（config.json / .env / rules.txt）。

配置文件放 figure-agent 仓库根（config.REPO_ROOT），格式见仓库根
config.example.json。FIGURE_AGENT_MOCK=1 时用 SpecModule 的 MockLLMClient
（免 key 接线冒烟；产出为占位内容，不用于功能验收）。
"""

from __future__ import annotations

import os

from .. import config as fa_config

#: 测试注入点：tests 用 monkeypatch 指到无 config 的目录
REPO_ROOT = fa_config.REPO_ROOT


def ai_status() -> dict:
    """LLM 配置状态（前端徽标）。"""
    if os.environ.get("FIGURE_AGENT_MOCK") == "1":
        return {"configured": True, "provider": "mock", "model": "mock", "mock": True}
    try:
        from llm import LLMConfig

        cfg = LLMConfig.from_env(project_root=REPO_ROOT)
    except Exception:
        return {"configured": False, "provider": "", "model": "", "mock": False}
    return {
        "configured": True,
        "provider": cfg.provider,
        "model": cfg.model or "(默认)",
        "mock": False,
    }


_client = None


def get_llm():
    """进程级 LLM 客户端单例（mock 模式不缓存，便于测试切换）。"""
    global _client
    if os.environ.get("FIGURE_AGENT_MOCK") == "1":
        from llm.mock import MockLLMClient

        return MockLLMClient()
    if _client is None:
        from llm import LLMConfig, create_llm_client

        cfg = LLMConfig.from_env(project_root=REPO_ROOT)
        _client = create_llm_client(cfg)
    return _client
```

`config.example.json`（仓库根，拷贝自 SpecModule 的 config.example.json，用户按需改）：

```json
{
  "providers": [
    {
      "name": "zhipu",
      "sdktype": "openai",
      "base_url": "https://open.bigmodel.cn/api/paas/v4",
      "api_key_env": "ZHIPU_API_KEY",
      "timeout": 120,
      "max_retries": 3
    }
  ],
  "models": [
    { "name": "glm-4.6", "provider": "zhipu", "think": true, "multimodal": false, "max_tokens": 8192 }
  ]
}
```

`main.py` 端点（加在 `list_templates` 之后）：

```python
@app.get("/api/ai/status")
def ai_status():
    from .ai import llm as ai_llm

    return ai_llm.ai_status()
```

- [ ] **Step 6: 运行测试通过**

Run: `cd server && .venv/Scripts/python -m pytest tests/test_ai_llm.py -q`
Expected: 2 passed

- [ ] **Step 7: Commit**

```bash
git add server/pyproject.toml server/src/figure_agent/ai/ config.example.json server/src/figure_agent/main.py server/tests/test_ai_llm.py
git commit -m "feat(ai): SpecModule 依赖接线 + ai.llm 配置/mock 开关 + /api/ai/status"
```

---

### Task 2: `ai/prompts.py` — 契约与六个 prompt_core

**Files:**
- Create: `server/src/figure_agent/ai/prompts.py`

（纯常量模块，无单测——内容由 Task 4/6/8 的工作流测试间接覆盖。）

- [ ] **Step 1: 写文件**

```python
"""AI 工作流 prompt 资产（唯一来源）。

三层 prompt 约定：本文件的 *_CORE 是 Layer 1（任务定义+输出格式约束），
契约文本（RENDER_CONTRACT 等）注册时直接拼入 prompt_core 尾部；
运行时输入（数据画像/要求/选区/stderr）经 task inputs 的具名 bind 与
{spec.xxx} 常量注入 {placeholder}。
注意：占位符正则是 \\{\\w+\\}——prompt 里 JSON 示例必须用带引号的键
（如 {"code": ...}），否则花括号会被当占位符吞掉。
AGENTS.md 面向人、本文件面向 harness，两者须一致，此处为准。
"""

RENDER_CONTRACT = """\
## 渲染契约（必须遵守）
1. 模块级构建图形并存入变量 fig，例如 `fig, ax = plt.subplots(...)`；服务端执行后取 fig 存为 SVG。
2. 不要调用 plt.show()。
3. 不要设置 plt.rcParams["svg.fonttype"] 与 ["svg.hashsalt"]（服务端强制，覆盖会被改回）。
4. 结尾调用 fig.tight_layout()（如适用）。"""

GID_CONVENTION = """\
## gid 约定（必须遵守）
对每个"用户可能想单独选中/修改"的 artist 调 set_gid("fa:名字")，gid 会成为 SVG 元素 id，
是选区定位与微调回写的基础：
- 一组柱子逐根命名：`for i, b in enumerate(bars): b.set_gid(f"fa:treatment-bar-{i}")`
- 整个散点系列：`sc = ax.scatter(...)` 然后 `sc.set_gid("fa:setosa")`
- 标题/轴标签：`t = ax.set_title("...")` 然后 `t.set_gid("fa:title")`
命名建议 fa:<语义>-<序号>。没有 fa: gid 的元素只能靠脆弱的自动 id 匹配。"""

SAFE_FONTS = """\
## 安全字体（只用以下字体）
DejaVu Sans / Arial / Helvetica / Times New Roman / SimHei / Microsoft YaHei / Noto Sans CJK SC"""

DATA_RULE = """\
## 数据读取约定
数据文件是脚本同目录下的 data.csv（UTF-8）。用 pandas 读取：
`import pandas as pd` + `df = pd.read_csv("data.csv")`。
不要在代码里硬编码数据值；不要读其他路径。"""

CONTRACT = "\n\n".join([RENDER_CONTRACT, GID_CONVENTION, SAFE_FONTS, DATA_RULE])

STANDARDIZE_CORE = """你是数据标准化专家。把「原始表格文本」整理为规范 CSV：
- 列名单行规范（合并重复/多级表头、去空白）；行列完整；数值列不混入单位文字
- 缺失值留空；不编造、不删除数据行
- 同时产出数据画像 profile：columns 每列含 name/dtype(text|number|datetime)/unit(可空)/desc(中文语义)；
  顶层 shape=[行,列]、notes=数据背景一句话
只输出 JSON 对象，键为 "csv"（规范 CSV 全文）、"profile"（画像对象）、"notes"（整理取舍说明，中文）。

原始表格文本：
{data}"""

GEN_CODE_CORE = """你是绘图代码生成器。根据「数据画像」与「绘图要求」写一个完整的 matplotlib plot.py。
只输出 JSON 对象，键为 "code"（plot.py 全文）与 "notes"（实现说明；要求无法满足时在此说明，禁止编造数据）。

数据画像：
{profile}

绘图要求：
{requirements}"""

ADAPT_CODE_CORE = """你是绘图脚本改造器。把「原始脚本」改造为符合契约的 plot.py：
保留原脚本的图表类型、数据映射与视觉风格；数据来源改为读 data.csv（按数据画像对应列名）；
补齐契约要求的 fig 变量、fa: gid、安全字体。原脚本与数据冲突时以数据为准，差异写进 notes。
只输出 JSON 对象，键为 "code"（plot.py 全文）与 "notes"（改造说明：改了什么、为什么）。

数据画像：
{profile}

绘图要求（可能为空）：
{requirements}

原始脚本：
{script_text}"""

FIX_CODE_CORE = """你是绘图代码修复器。「当前代码」渲染失败，按「渲染结果」里的报错修复：
保持既有视觉设计不变，只修导致报错的问题。
只输出 JSON 对象，键为 "code"（修复后 plot.py 全文）与 "notes"（修复说明）。

当前代码与渲染结果：
{render}"""

EDIT_CODE_CORE = """你是绘图代码修改器。根据「用户指令」与「选区 JSON」定点修改「当前代码」：
- 选区 JSON 的 elementId 对应代码里 set_gid("fa:…") 的 artist；多选为数组，逐项处理
- 只做指令要求的修改；改 artist 属性时优先改对应 matplotlib 参数
只输出 JSON 对象，键为 "code"（修改后 plot.py 全文）与 "notes"（修改说明）。

当前代码：
{code}

选区 JSON：
{selection}

用户指令：
{instruction}"""

TRANSLATE_PATCH_CORE = """你是微调回写器。把「翻译材料」里 ops 的每条手动微调翻译进 code，让代码直接表达它：
- 改色/样式 → 对应 color/linestyle/linewidth 参数
- 文本/字号 → set_title/set_xlabel 等字符串或 fontsize 参数
- 位移/缩放 → 改数据或 offset
- 隐藏 → artist.set_visible(False)；置顶/置底 → artist.set_zorder(大值/小值)
op 的 target.id 形如 "fa:xxx"，对应 code 里 set_gid("fa:xxx") 的 artist，据此定位；intent 是语义意图。
无法合理表达的 op 不要硬改，保留给 patch 覆盖层，并在 notes 说明。给新增/被改动的 artist 补 set_gid("fa:…")。
只输出 JSON 对象，键为 "code"（回写后 plot.py 全文）与 "notes"（逐条 op 处理结果）。

翻译材料（ops=patch 操作列表；code=当前代码；verify=上轮校验结果，首轮为 null）：
{material}"""
```

- [ ] **Step 2: 冒烟验证占位符不被 JSON 示例破坏**

```bash
cd server && .venv/Scripts/python -c "
from figure_agent.ai import prompts
import re
for name in ('STANDARDIZE_CORE','GEN_CODE_CORE','ADAPT_CODE_CORE','FIX_CODE_CORE','EDIT_CODE_CORE','TRANSLATE_PATCH_CORE'):
    core = getattr(prompts, name) + '\n\n' + prompts.CONTRACT
    ph = set(re.findall(r'\{(\w+)\}', core))
    print(name, sorted(ph))
"
```

Expected: 每个输出的占位符集合恰好等于该 prompt 预期的 bind 字段（standardize={data}；gen={profile,requirements}；adapt={profile,requirements,script_text}；fix={render}；edit={code,instruction,selection}；translate={material}），没有多余占位符。

- [ ] **Step 3: Commit**

```bash
git add server/src/figure_agent/ai/prompts.py
git commit -m "feat(ai): prompt 资产（渲染契约/gid/字体/数据约定 + 六个 prompt_core）"
```

---

### Task 3: `ai/nodes.py` — script 节点与 guard（纯逻辑 + 单测）

**Files:**
- Create: `server/src/figure_agent/ai/nodes.py`
- Test: `server/tests/test_ai_nodes.py`

- [ ] **Step 1: 写失败测试**

`server/tests/test_ai_nodes.py`：

```python
"""ai.nodes：script 节点纯逻辑单测（假 view）。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from figure_agent.ai import nodes
from figure_agent.store import Store


class FakeView:
    """模拟 tickflow NodeView 的最小面：field/state/output。"""

    def __init__(self, fields=None, output=None, state=None):
        self._fields = fields or {}
        self.output = output
        self.state = state if state is not None else {}

    def field(self, name):
        # 未点火 producer 模拟：抛 KeyError（与 tickflow 语义一致）
        if name not in self._fields:
            raise KeyError(name)
        v = self._fields[name]
        if isinstance(v, Exception):
            raise v
        return v


CSV_TEXT = "dose,response\n0,1.1\n5,2.3\n10,3.9\n"
PROFILE = {"shape": [3, 2], "columns": [{"name": "dose", "dtype": "number", "unit": "", "desc": "剂量"}], "notes": "剂量响应"}


def test_parse_upload_csv(tmp_path):
    fdir = tmp_path
    up = fdir / "uploads"
    up.mkdir()
    (up / "d.csv").write_text(CSV_TEXT, encoding="utf-8")
    fn = nodes.make_parse_upload(fdir, "d.csv")
    out = fn(FakeView())
    assert out == CSV_TEXT


def test_parse_upload_xlsx(tmp_path):
    pandas = pytest.importorskip("pandas")
    fdir = tmp_path
    up = fdir / "uploads"
    up.mkdir()
    import pandas as pd

    pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).to_excel(up / "d.xlsx", index=False)
    fn = nodes.make_parse_upload(fdir, "d.xlsx")
    out = fn(FakeView())
    assert "a,b" in out and "1,x" in out


def test_write_data(tmp_path):
    fdir = tmp_path
    fn = nodes.make_write_data(fdir)
    profile = fn(FakeView(fields={"data": {"csv": CSV_TEXT, "profile": PROFILE, "notes": "已规范"}}))
    assert (fdir / "data.csv").read_text(encoding="utf-8") == CSV_TEXT
    saved = json.loads((fdir / "data_profile.json").read_text(encoding="utf-8"))
    assert saved["shape"] == [3, 2]
    assert "已规范" in saved["notes"]       # 顶层 notes 并入画像 notes
    assert profile == {**PROFILE, "notes": "剂量响应 已规范"}


def test_render_validate_first_pass_renders_and_counts(tmp_path, monkeypatch):
    """首轮（无 fix）用 gen 的代码；写盘渲染计数。"""
    from figure_agent.store import Store

    ws = tmp_path / "ws"
    store = Store(ws)
    store.init_figure("p", "f", origin="ai")
    good = (
        "import matplotlib\nmatplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "fig, ax = plt.subplots(figsize=(4, 3))\n"
        "ax.plot([0, 1], [0, 1])\nfig.tight_layout()\n"
    )
    fn = nodes.make_render_validate(store, store.figure_dir("p", "f"), "p", "f")
    out = asyncio.run(fn(FakeView(fields={"gen": {"code": good}})))
    assert out["ok"] is True and out["rounds"] == 1 and out["source"] == "gen"
    # store.write_code 已把代码写进 plot.py 并渲染
    assert "ax.plot" in (store.figure_dir("p", "f") / "plot.py").read_text(encoding="utf-8")


def test_render_validate_prefers_fix_and_loop_limit(tmp_path):
    ws = tmp_path / "ws"
    store = Store(ws)
    store.init_figure("p", "f", origin="ai")
    bad = "fig = 1 +\n"
    fn = nodes.make_render_validate(store, store.figure_dir("p", "f"), "p", "f")
    view = FakeView(fields={"gen": {"code": bad}, "fix": {"code": bad}})
    out1 = asyncio.run(fn(view))
    assert out1["ok"] is False and out1["source"] == "fix" and out1["rounds"] == 1
    out2 = asyncio.run(fn(view))  # 同一 view.state 跨 tick 累计
    assert out2["rounds"] == 2
    assert nodes.needs_fix(FakeView(output=out2)) is True
    assert nodes.settled(FakeView(output=out2)) is False


def test_render_validate_no_code(tmp_path):
    ws = tmp_path / "ws"
    store = Store(ws)
    store.init_figure("p", "f", origin="ai")
    fn = nodes.make_render_validate(store, store.figure_dir("p", "f"), "p", "f")
    out = asyncio.run(fn(FakeView(fields={})))
    assert out["ok"] is False and "未产出代码" in out["stderr"]


def test_guards_xor():
    ok1 = {"ok": True, "rounds": 1}
    fail1 = {"ok": False, "rounds": 1}
    fail3 = {"ok": False, "rounds": 3}
    assert nodes.needs_fix(FakeView(output=fail1)) and not nodes.settled(FakeView(output=fail1))
    assert not nodes.needs_fix(FakeView(output=ok1)) and nodes.settled(FakeView(output=ok1))
    assert not nodes.needs_fix(FakeView(output=fail3)) and nodes.settled(FakeView(output=fail3))


def test_writeback_nodes(tmp_path):
    ws = tmp_path / "ws"
    store = Store(ws)
    store.init_figure("p", "f", origin="ai")
    fdir = store.figure_dir("p", "f")
    store.save_patch("p", "f", {
        "baseHash": "",
        "ops": [{"id": "op-1", "kind": "set_style", "target": {"id": "fa:title"},
                 "attr": "font-size", "value": "18", "intent": "标题变大", "origin": "manual",
                 "status": "active"}],
    })
    rp = nodes.make_read_patch(store, "p", "f")
    seed = rp(FakeView())
    assert len(seed["ops"]) == 1

    merge = nodes.make_merge_wb(fdir)
    m1 = merge(FakeView(fields={"seed": seed}))          # 首轮：无 verify
    assert m1["cleared"] is False and m1["rounds"] == 0
    assert nodes.wb_continue(FakeView(output=m1)) is True
    assert nodes.wb_done(FakeView(output=m1)) is False

    # 模拟一轮校验后未收敛
    verify1 = {"ok": True, "cleared": False, "rounds": 1, "remaining": 1, "results": [], "stderr": ""}
    m2 = merge(FakeView(fields={"seed": seed, "verify": verify1}))
    assert m2["rounds"] == 1
    assert nodes.wb_continue(FakeView(output=m2)) is True

    # 收敛：cleared
    verify2 = {"ok": True, "cleared": True, "rounds": 2, "remaining": 0, "results": [], "stderr": ""}
    m3 = merge(FakeView(fields={"seed": seed, "verify": verify2}))
    assert nodes.wb_continue(FakeView(output=m3)) is False
    assert nodes.wb_done(FakeView(output=m3)) is True
    # （wb_verify_settled 已删：直达边冗余且造成 Finalize 双 fire 双重审计）

    # 空 patch：直接收敛路径
    m4 = merge(FakeView(fields={"seed": {"ops": []}}))
    assert nodes.wb_continue(FakeView(output=m4)) is False
    assert nodes.wb_done(FakeView(output=m4)) is True


def test_finalize_writes_runs_jsonl(tmp_path):
    ws = tmp_path / "ws"
    store = Store(ws)
    store.init_figure("p", "f", origin="ai")
    fdir = store.figure_dir("p", "f")
    fn = nodes.make_finalize(fdir, "create")
    result = fn(FakeView(output={"ok": True, "rounds": 2, "stderr": "", "notes": "done"}))
    assert result["kind"] == "create" and result["ok"] is True
    lines = (fdir / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["kind"] == "create"

    fn_wb = nodes.make_finalize(fdir, "writeback")
    r2 = fn_wb(FakeView(output={"cleared": False, "rounds": 3, "remaining": 1, "stderr": "", "ok": True}))
    assert r2["ok"] is False  # writeback 的 ok = cleared
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && .venv/Scripts/python -m pytest tests/test_ai_nodes.py -q`
Expected: FAIL（cannot import name `nodes`）

- [ ] **Step 3: 实现 `ai/nodes.py`**

```python
"""AI 工作流 script 节点与 guard。

节点函数由 workflows.build_registry 以闭包绑定 figure 上下文后注册为
script body；常量（上传文件名等）一律走闭包——SpecModule 的 script 节点
不支持常量 inputs。渲染类节点做成 async body，用 asyncio.to_thread 包
store 的同步渲染，避免阻塞事件循环（registry.script 支持 async fn）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ..store import Store, now_iso

MAX_ROUNDS = 3  # 渲染修复 / 回写收敛的共同轮数上限


# ---------------------------------------------------------------- 造图链

def make_parse_upload(fdir: Path, upload_name: str):
    """uploads/<upload_name> → 表格文本。二进制表格走 pandas，其余按文本读。

    upload_name 来自 REST 层的 Path(...).name，但工厂内再做一次逃逸防御。
    只支持 .xlsx（openpyxl 后端）；遗留 .xls 需要 xlrd，不装（明确拒绝）。
    """
    path = (fdir / "uploads" / upload_name).resolve()
    path.relative_to((fdir / "uploads").resolve())  # 逃逸 uploads/ 直接抛错

    async def parse_upload(view) -> str:
        def _read() -> str:
            suffix = path.suffix.lower()
            if suffix == ".xlsx":
                import pandas as pd

                df = pd.read_excel(path)
                return df.to_csv(index=False)
            if suffix in (".xls",):
                raise ValueError("不支持遗留 .xls 格式，请另存为 .xlsx")
            return path.read_text(encoding="utf-8", errors="replace")

        return await asyncio.to_thread(_read)

    return parse_upload


def make_write_data(fdir: Path):
    """落盘 data.csv + data_profile.json；画像（并入整理说明）作为下游 prompt 输入。"""

    def write_data(view) -> dict:
        out = view.field("data")  # Standardize 输出 {csv, profile, notes}
        if not isinstance(out, dict):
            raise TypeError(f"Standardize 上游输出非 dict：{type(out).__name__}")
        profile = dict(out.get("profile") or {})
        merged = (str(profile.get("notes", "")) + " " + str(out.get("notes", ""))).strip()
        profile["notes"] = merged
        (fdir / "data.csv").write_text(out.get("csv", ""), encoding="utf-8")
        (fdir / "data_profile.json").write_text(
            json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return profile

    return write_data


def make_render_validate(store: Store, fdir: Path, project: str, figure: str):
    """取代码（fix 优先于 gen）→ 写盘渲染 → {ok, rounds, stderr, code, ...}。

    返回值必须带 "code"（本轮实际渲染的代码）：FixCode 的 prompt 经 {render}
    拿到整个 dict，没有 code 就无法修复（v2 计划评审补上的字段）。
    """

    async def render_validate(view) -> dict:
        try:
            fix = view.field("fix")
        except (KeyError, TypeError):
            fix = None
        code = fix.get("code") if isinstance(fix, dict) else None
        source = "fix"
        if not (isinstance(code, str) and code.strip()):
            try:
                gen = view.field("gen")
            except (KeyError, TypeError):
                gen = None
            code = gen.get("code") if isinstance(gen, dict) else None
            source = "gen"

        rounds = view.state.get("rounds", 0) + 1
        view.state["rounds"] = rounds
        if not (isinstance(code, str) and code.strip()):
            return {"ok": False, "rounds": rounds, "stderr": "上游未产出代码",
                    "error_line": None, "source": source, "code": ""}
        outcome = await asyncio.to_thread(store.write_code, project, figure, code)
        return {
            "ok": outcome.ok,
            "rounds": rounds,
            "stderr": (outcome.stderr or "")[-4000:],
            "error_line": outcome.error_line,
            "fa_count": len((outcome.stats or {}).get("faGroups", [])),
            "source": source,
            "code": code,
        }

    return render_validate


# ---------------------------------------------------------------- 回写链

def make_read_patch(store: Store, project: str, figure: str):
    def read_patch(view) -> dict:
        patch = store.read_patch(project, figure) or {"ops": []}
        return {"ops": patch.get("ops", [])}

    return read_patch


def make_merge_wb(fdir: Path):
    """合并种子 ops 与最新校验结果；附当前代码；计数轮数（跨 tick 持久）。"""

    def merge_wb(view) -> dict:
        seed = view.field("seed")
        ops = seed.get("ops", []) if isinstance(seed, dict) else []
        try:
            verify = view.field("verify")
        except (KeyError, TypeError):
            verify = None
        if not isinstance(verify, dict):
            verify = None
        rounds = max(view.state.get("rounds", 0), (verify or {}).get("rounds", 0))
        view.state["rounds"] = rounds
        cleared = (not ops) or bool((verify or {}).get("cleared"))
        try:
            code = (fdir / "plot.py").read_text(encoding="utf-8")
        except OSError:
            code = ""
        return {"ops": ops, "verify": verify, "code": code, "rounds": rounds, "cleared": cleared}

    return merge_wb


def make_render_verify(store: Store, project: str, figure: str):
    """回写代码 → 渲染 → verify_patch 收敛判定。"""

    async def render_verify(view) -> dict:
        tr = view.field("translated")
        code = tr.get("code") if isinstance(tr, dict) else None
        rounds = view.state.get("rounds", 0) + 1
        view.state["rounds"] = rounds
        if not (isinstance(code, str) and code.strip()):
            return {"ok": False, "cleared": False, "rounds": rounds, "remaining": -1,
                    "results": [], "stderr": "回写节点未产出代码"}
        outcome = await asyncio.to_thread(store.write_code, project, figure, code)
        if not outcome.ok:
            return {"ok": False, "cleared": False, "rounds": rounds, "remaining": -1,
                    "results": [], "stderr": (outcome.stderr or "")[-4000:],
                    "error_line": outcome.error_line}
        verdict = await asyncio.to_thread(store.verify_patch, project, figure)
        return {"ok": True, "cleared": bool(verdict.get("cleared")),
                "rounds": rounds, "remaining": verdict.get("remainingOps", 0),
                "results": verdict.get("results", []), "stderr": ""}

    return render_verify


# ---------------------------------------------------------------- 终点

def make_finalize(fdir: Path, kind: str):
    """终点节点：规范化返回值 + 追加 runs.jsonl。writeback 的 ok = cleared。

    读 bind 字段 "result"（TaskDefinition inputs={"result": 上游节点}）——
    真实引擎的 NodeView 没有 .output 属性（那是 GuardView 的），body 里读
    view.output 会 AttributeError 静默失败（评审仿真发现）。
    """

    def finalize(view) -> dict:
        o = view.field("result")
        o = o if isinstance(o, dict) else {}
        result = {
            "kind": kind,
            "ok": bool(o.get("cleared")) if kind == "writeback" else bool(o.get("ok")),
            "rounds": o.get("rounds", 0),
            "stderr": o.get("stderr", ""),
            "error_line": o.get("error_line"),
            "notes": o.get("notes", ""),
        }
        if kind == "writeback":
            result["cleared"] = bool(o.get("cleared"))
            result["remaining"] = o.get("remaining", -1)
        entry = {"at": now_iso(), **result}
        with (fdir / "runs.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return result

    return finalize


# ---------------------------------------------------------------- guards

def _out(view) -> dict:
    return view.output if isinstance(view.output, dict) else {}


def needs_fix(view) -> bool:
    o = _out(view)
    return not o.get("ok") and o.get("rounds", 0) < MAX_ROUNDS


def settled(view) -> bool:
    return not needs_fix(view)  # 严格互补（XOR），与 fact_review_loop 同纪律


def wb_continue(view) -> bool:
    o = _out(view)
    return bool(o.get("ops")) and not o.get("cleared", False) and o.get("rounds", 0) < MAX_ROUNDS


def wb_done(view) -> bool:
    return not wb_continue(view)  # 严格互补
```

- [ ] **Step 4: 运行测试通过**

Run: `cd server && .venv/Scripts/python -m pytest tests/test_ai_nodes.py -q`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add server/src/figure_agent/ai/nodes.py server/tests/test_ai_nodes.py
git commit -m "feat(ai): script 节点（parse/write/render_validate/回写链/finalize）与 guard"
```

---

### Task 4: `ai/workflows.py` — 注册表、四条 tasklist、run_workflow（含 store.init_figure）

**Files:**
- Modify: `server/src/figure_agent/store.py`（加 `init_figure`，`create_figure` 的 meta 加 origin）
- Create: `server/src/figure_agent/ai/workflows.py`
- Test: `server/tests/test_ai_workflows.py`

- [ ] **Step 1: store.init_figure — 先写失败测试**

追加到 `server/tests/test_store_executor.py`：

```python
def test_init_figure(tmp_path):
    store = Store(tmp_path / "ws")
    store.init_figure("p", "f", origin="ai")
    fdir = store.figure_dir("p", "f")
    assert (fdir / "meta.json").exists()
    meta = store.read_meta("p", "f")
    assert meta["origin"] == "ai" and meta["lastRenderAt"] is None
    assert store.read_patch("p", "f") == {"baseHash": "", "ops": []}
    with pytest.raises(ValueError):
        store.init_figure("p", "f", origin="ai")
```

Run: `cd server && .venv/Scripts/python -m pytest tests/test_store_executor.py::test_init_figure -q`
Expected: FAIL（no attribute `init_figure`）

- [ ] **Step 2: 实现 init_figure**

`store.py` 在 `create_figure` 前插入：

```python
    def init_figure(self, project: str, figure: str, origin: str) -> None:
        """建图目录（无模板代码）：AI 造图/改造的入口。已存在则 ValueError。"""
        _require_name(project, "项目")
        _require_name(figure, "图")
        fdir = self.figure_dir(project, figure)
        if fdir.exists():
            raise ValueError(f"图已存在：{project}/{figure}")
        fdir.mkdir(parents=True)
        (fdir / "history").mkdir()
        self._write_meta(
            fdir,
            {
                "name": figure,
                "project": project,
                "origin": origin,
                "createdAt": now_iso(),
                "lastRenderAt": None,
            },
        )
        self._write_patch(fdir, {"baseHash": "", "ops": []})
```

并把 `create_figure` 里 `self._write_meta(...)` 的 dict 增加一项 `"origin": "template",`。

- [ ] **Step 3: 写工作流端到端失败测试**

`server/tests/test_ai_workflows.py`：

```python
"""四条工作流端到端（StubLLM 假客户端，免 key）。"""

from __future__ import annotations

import json
from llm.client import LLMResponse

from figure_agent.ai.workflows import run_workflow
from figure_agent.store import Store

GOOD_CODE = (
    "import matplotlib\nmatplotlib.use('Agg')\n"
    "import matplotlib.pyplot as plt\nimport pandas as pd\n"
    'df = pd.read_csv("data.csv")\n'
    "fig, ax = plt.subplots(figsize=(5, 3.6))\n"
    'ax.plot(df["dose"], df["response"], marker="o", color="#2A6F97")\n'
    'ln = ax.lines[0]\nln.set_gid("fa:response-curve")\n'
    't = ax.set_title("dose-response")\nt.set_gid("fa:title")\n'
    "fig.tight_layout()\n"
)
BAD_CODE = (
    "import matplotlib\nmatplotlib.use('Agg')\n"
    "import matplotlib.pyplot as plt\nimport pandas as pd\n"
    'df = pd.read_csv("data.csv")\n'
    "fig, ax = plt.subplots(figsize=(5, 3.6))\n"
    'ax.plot(df["dose"], df["nope"])\n'
    "fig.tight_layout()\n"
)
STD_REPLY = json.dumps(
    {
        "csv": "dose,response\n0,1.1\n5,2.3\n10,3.9\n",
        "profile": {
            "shape": [3, 2],
            "columns": [
                {"name": "dose", "dtype": "number", "unit": "", "desc": "剂量"},
                {"name": "response", "dtype": "number", "unit": "", "desc": "响应值"},
            ],
            "notes": "剂量响应数据",
        },
        "notes": "已规范为两列数值",
    },
    ensure_ascii=False,
)


class StubLLM:
    """按 prompt 关键词路由预设回复；每路按序弹出（支持失败→修复序列）。"""

    def __init__(self, routes: dict[str, list[str]]):
        self.routes = {k: list(v) for k, v in routes.items()}
        self.prompts: list[str] = []

    async def complete(self, prompt=None, **kw) -> LLMResponse:
        p = prompt or ""
        self.prompts.append(p)
        for key, contents in self.routes.items():
            if key in p and contents:
                return LLMResponse(content=contents.pop(0), usage={}, finish_reason="end_turn")
        return LLMResponse(content="{}", usage={}, finish_reason="end_turn")


def make_store(tmp_path) -> Store:
    store = Store(tmp_path / "ws")
    store.init_figure("p", "f", origin="ai")
    fdir = store.figure_dir("p", "f")
    up = fdir / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    (up / "d.csv").write_text("dose,response\n0,1.1\n5,2.3\n10,3.9\n", encoding="utf-8")
    # writeback/edit 测试不走 create 工作流（无 WriteData 节点），直接备好 data.csv，
    # 使 GOOD_CODE 的 pd.read_csv("data.csv") 可渲染
    (fdir / "data.csv").write_text("dose,response\n0,1.1\n5,2.3\n10,3.9\n", encoding="utf-8")
    return store


def test_create_with_fix_loop(tmp_path):
    store = make_store(tmp_path)
    stub = StubLLM({
        "数据标准化": [STD_REPLY],
        "绘图代码生成器": [json.dumps({"code": BAD_CODE, "notes": ""}),
                          json.dumps({"code": GOOD_CODE, "notes": ""})],
        "绘图代码修复器": [json.dumps({"code": GOOD_CODE, "notes": "修复列名"})],
    })
    result = __import__("asyncio").run(run_workflow(
        "create", store, "p", "f",
        {"requirements": "画剂量响应曲线", "upload_name": "d.csv"},
        llm_client=stub,
    ))
    fdir = store.figure_dir("p", "f")
    assert result["ok"] is True and result["rounds"] == 2, result
    assert (fdir / "data.csv").exists() and (fdir / "data_profile.json").exists()
    assert "fa:response-curve" in store.read_svg("p", "f", "base")
    runs = [json.loads(x) for x in (fdir / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()]
    assert runs[-1]["kind"] == "create" and runs[-1]["ok"] is True
    # fix_code 收到了 stderr 与完整当前代码（{render} 含 code 字段）
    fix_prompts = [p for p in stub.prompts if "绘图代码修复器" in p]
    assert fix_prompts and "nope" in fix_prompts[0] and 'ax.plot' in fix_prompts[0]


def test_writeback_converges(tmp_path):
    store = make_store(tmp_path)
    store.write_code("p", "f", GOOD_CODE)
    store.save_patch("p", "f", {
        "baseHash": "",
        "ops": [{"id": "op-1", "kind": "set_style", "target": {"id": "fa:title"},
                 "attr": "font-size", "value": "20", "intent": "标题字号放大", "origin": "manual",
                 "status": "active"}],
    })
    wb_code = GOOD_CODE.replace('t.set_gid("fa:title")',
                                't.set_gid("fa:title")\nt.set_fontsize(20)')
    stub = StubLLM({"微调回写器": [json.dumps({"code": wb_code, "notes": "标题字号 20"})]})
    result = __import__("asyncio").run(run_workflow(
        "writeback", store, "p", "f", {}, llm_client=stub,
    ))
    assert result["ok"] is True and result["cleared"] is True, result
    assert store.read_patch("p", "f")["ops"] == []


def test_writeback_no_ops_short_circuit(tmp_path):
    store = make_store(tmp_path)
    store.write_code("p", "f", GOOD_CODE)
    stub = StubLLM({})
    result = __import__("asyncio").run(run_workflow(
        "writeback", store, "p", "f", {}, llm_client=stub,
    ))
    assert result["ok"] is True and result["cleared"] is True
    assert stub.prompts == []  # 未花任何 LLM 调用
```

Run: `cd server && .venv/Scripts/python -m pytest tests/test_ai_workflows.py -q`
Expected: FAIL（cannot import `workflows`）

- [ ] **Step 4: 实现 `ai/workflows.py`**

```python
"""四条固定 tasklist 工作流（SpecModule 直写通道）+ run_workflow 入口。

每次 run 构建全新 HarnessRegistry（body 按 {module_id}:{key} 命名空间隔离，
view.state 随 run 隔离）。review_harness=None 跳过一致性审核——固定管线，
省一次 LLM 调用。persist=False 全内存零落盘；审计靠 Finalize 节点写 runs.jsonl。
同一时刻只允许一个 AI run（模块级 asyncio.Lock）。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from module_harness import (
    EventBus,
    HarnessConfig,
    HarnessRegistry,
    Module,
    OutputFormat,
    TaskDefinition,
    Tasklist,
)
from module_harness.infra.events import (
    HarnessFailed,
    LlmCallCompleted,
    LlmCallStarted,
    ScriptCompleted,
    ScriptFailed,
    ScriptStarted,
)

from ..store import Store
from . import nodes, prompts
from .llm import get_llm

_run_lock = asyncio.Lock()


def _hc(core: str) -> HarnessConfig:
    """代码类 harness 统一配置：核心 prompt + 契约文本 + JSON 输出。"""
    return HarnessConfig(
        prompt_core=core + "\n\n" + prompts.CONTRACT,
        output_format=OutputFormat(type="json_object"),
    )


def _tl_create(spec: dict) -> Tasklist:
    return Tasklist(
        tasks={
            "ParseUpload": TaskDefinition(type="script", script="parse_upload"),
            "Standardize": TaskDefinition(type="harness", harness="standardize",
                                          inputs={"data": "ParseUpload"}),
            "WriteData": TaskDefinition(type="script", script="write_data",
                                        inputs={"data": "Standardize"}),
            "GenCode": TaskDefinition(type="harness", harness="gen_code",
                                      inputs={"profile": "WriteData",
                                              "requirements": "{spec.requirements}"}),
            "FixCode": TaskDefinition(type="harness", harness="fix_code",
                                      inputs={"render": "RenderValidate"}),
            "RenderValidate": TaskDefinition(type="script", script="render_validate",
                                             inputs={"gen": "GenCode", "fix": "FixCode"}),
            "Finalize": TaskDefinition(type="script", script="finalize",
                                       inputs={"result": "RenderValidate"}),
        },
        flow=(
            "[ParseUpload] --> Standardize --> WriteData --> GenCode --> RenderValidate\n"
            "RenderValidate --|needs_fix|--> FixCode --> RenderValidate\n"
            "RenderValidate --|settled|--> Finalize\n"
            # RenderValidate 双 producer（GenCode+FixCode）默认 AND join 会死锁：
            # 首轮 FixCode 未 fire 永不满足。OR join = 任一 producer fire 即触发。
            "RenderValidate.join: OR"
        ),
    )


def _tl_adapt(spec: dict) -> Tasklist:
    return Tasklist(
        tasks={
            "ParseUpload": TaskDefinition(type="script", script="parse_upload"),
            "Standardize": TaskDefinition(type="harness", harness="standardize",
                                          inputs={"data": "ParseUpload"}),
            "WriteData": TaskDefinition(type="script", script="write_data",
                                        inputs={"data": "Standardize"}),
            "AdaptCode": TaskDefinition(type="harness", harness="adapt_code",
                                        inputs={"profile": "WriteData",
                                                "requirements": "{spec.requirements}",
                                                "script_text": "{spec.script_text}"}),
            "FixCode": TaskDefinition(type="harness", harness="fix_code",
                                      inputs={"render": "RenderValidate"}),
            "RenderValidate": TaskDefinition(type="script", script="render_validate",
                                             inputs={"gen": "AdaptCode", "fix": "FixCode"}),
            "Finalize": TaskDefinition(type="script", script="finalize",
                                       inputs={"result": "RenderValidate"}),
        },
        flow=(
            "[ParseUpload] --> Standardize --> WriteData --> AdaptCode --> RenderValidate\n"
            "RenderValidate --|needs_fix|--> FixCode --> RenderValidate\n"
            "RenderValidate --|settled|--> Finalize\n"
            "RenderValidate.join: OR"
        ),
    )


def _tl_edit(spec: dict) -> Tasklist:
    return Tasklist(
        tasks={
            "EditCode": TaskDefinition(type="harness", harness="edit_code",
                                       inputs={"instruction": "{spec.instruction}",
                                               "selection": "{spec.selection_json}",
                                               "code": "{spec.code}"}),
            "FixCode": TaskDefinition(type="harness", harness="fix_code",
                                      inputs={"render": "RenderValidate"}),
            "RenderValidate": TaskDefinition(type="script", script="render_validate",
                                             inputs={"gen": "EditCode", "fix": "FixCode"}),
            "Finalize": TaskDefinition(type="script", script="finalize",
                                       inputs={"result": "RenderValidate"}),
        },
        flow=(
            "[EditCode] --> RenderValidate\n"
            "RenderValidate --|needs_fix|--> FixCode --> RenderValidate\n"
            "RenderValidate --|settled|--> Finalize\n"
            "RenderValidate.join: OR"
        ),
    )


def _tl_writeback(spec: dict) -> Tasklist:
    return Tasklist(
        tasks={
            "ReadPatch": TaskDefinition(type="script", script="read_patch"),
            "Merge": TaskDefinition(type="script", script="merge_wb",
                                    inputs={"seed": "ReadPatch", "verify": "RenderVerify"}),
            "Translate": TaskDefinition(type="harness", harness="translate_patch",
                                        inputs={"material": "Merge"}),
            "RenderVerify": TaskDefinition(type="script", script="render_verify",
                                           inputs={"translated": "Translate"}),
            # Finalize 只从 Merge 的 wb_done 边进入（wb_verify_settled 直达边在
            # 评审仿真中被证明冗余且会造成 Finalize 双 fire 双重审计，已删）
            "Finalize": TaskDefinition(type="script", script="finalize",
                                       inputs={"result": "Merge"}),
        },
        flow=(
            "[ReadPatch] --> Merge\n"
            "Merge --|wb_continue|--> Translate --> RenderVerify\n"
            "RenderVerify --> Merge\n"
            "Merge --|wb_done|--> Finalize\n"
            "Merge.join: OR"
        ),
    )


TASKLISTS = {
    "create": _tl_create,
    "adapt": _tl_adapt,
    "edit": _tl_edit,
    "writeback": _tl_writeback,
}


def build_registry(kind: str, store: Store, project: str, figure: str,
                   spec: dict, llm_client, bus: EventBus) -> HarnessRegistry:
    fdir = store.figure_dir(project, figure)
    reg = HarnessRegistry(llm_client=llm_client, event_bus=bus)
    # standardize 产出 CSV，与渲染契约/gid/字体无关——用裸 config 不拼 CONTRACT
    reg.harness("standardize", HarnessConfig(
        prompt_core=prompts.STANDARDIZE_CORE,
        output_format=OutputFormat(type="json_object"),
    ))
    for name, core in (
        ("gen_code", prompts.GEN_CODE_CORE),
        ("adapt_code", prompts.ADAPT_CODE_CORE),
        ("fix_code", prompts.FIX_CODE_CORE),
        ("edit_code", prompts.EDIT_CODE_CORE),
        ("translate_patch", prompts.TRANSLATE_PATCH_CORE),
    ):
        reg.harness(name, _hc(core))

    reg.script("parse_upload")(nodes.make_parse_upload(fdir, spec["upload_name"]))
    reg.script("write_data")(nodes.make_write_data(fdir))
    reg.script("render_validate")(nodes.make_render_validate(store, fdir, project, figure))
    reg.script("read_patch")(nodes.make_read_patch(store, project, figure))
    reg.script("merge_wb")(nodes.make_merge_wb(fdir))
    reg.script("render_verify")(nodes.make_render_verify(store, project, figure))
    reg.script("finalize")(nodes.make_finalize(fdir, kind))

    for gname, gfn in (
        ("needs_fix", nodes.needs_fix),
        ("settled", nodes.settled),
        ("wb_continue", nodes.wb_continue),
        ("wb_done", nodes.wb_done),
    ):
        reg.guard(gname, gfn)
    return reg


def _bridge(project: str, figure: str, run_id: str, bus: EventBus) -> None:
    """EventBus → WS hub：ai_run 事件（节点级进度）。"""
    from ..events import hub

    def push(payload: dict) -> None:
        hub.broadcast_threadsafe({
            "type": "ai_run", "project": project, "figure": figure,
            "runId": run_id, **payload,
        })

    def on_event(evt) -> None:
        if isinstance(evt, ScriptStarted):
            push({"phase": "node_start", "node": evt.node})
        elif isinstance(evt, ScriptCompleted):
            push({"phase": "node_end", "node": evt.node})
        elif isinstance(evt, ScriptFailed):
            push({"phase": "node_failed", "node": evt.node, "detail": evt.error})
        elif isinstance(evt, LlmCallStarted):
            push({"phase": "llm_start", "node": evt.node})
        elif isinstance(evt, LlmCallCompleted):
            push({"phase": "llm_end", "node": evt.node})
        elif isinstance(evt, HarnessFailed):
            push({"phase": "node_failed", "node": evt.node, "detail": evt.reason})

    for evt_type in (ScriptStarted, ScriptCompleted, ScriptFailed,
                     LlmCallStarted, LlmCallCompleted, HarnessFailed):
        bus.subscribe(evt_type, on_event)


def _final_output(firings: list) -> dict:
    for f in reversed(firings):
        if getattr(f, "node", None) == "Finalize":
            out = getattr(f, "output", None)
            if isinstance(out, dict):
                return out
    return {}


async def run_workflow(kind: str, store: Store, project: str, figure: str,
                       spec: dict, llm_client=None) -> dict:
    """执行一条工作流，返回 Finalize 节点的规范化结果。"""
    if kind not in TASKLISTS:
        raise ValueError(f"未知工作流：{kind}")
    async with _run_lock:
        run_id = f"{kind}_{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:4]}"
        client = llm_client or get_llm()
        bus = EventBus()
        _bridge(project, figure, run_id, bus)
        reg = build_registry(kind, store, project, figure, spec, client, bus)
        module = Module(
            spec=spec,
            tasklist=TASKLISTS[kind](spec),
            llm_client=client,
            event_bus=bus,
            registry=reg,
            module_id=run_id,
            persist=False,
            status_file=False,
            keep_records=False,
            stream_log=False,
            control=False,
            review_harness=None,
        )
        from ..events import hub

        hub.broadcast_threadsafe({"type": "ai_run", "project": project, "figure": figure,
                                  "runId": run_id, "phase": "run_start", "node": kind})
        try:
            firings = await module.run(max_ticks=60)
            result = _final_output(firings)
            if not result:
                result = {"kind": kind, "ok": False, "rounds": 0, "stderr": "工作流未到达终点节点"}
        except Exception as exc:  # LLM/构建错误统一失败出口
            result = {"kind": kind, "ok": False, "rounds": 0, "stderr": f"{type(exc).__name__}: {exc}"}
        hub.broadcast_threadsafe({"type": "ai_run", "project": project, "figure": figure,
                                  "runId": run_id, "phase": "run_end", "node": kind,
                                  "ok": result.get("ok"), "detail": (result.get("stderr") or "")[:300]})
        return result
```

- [ ] **Step 5: 跑工作流测试**

Run: `cd server && .venv/Scripts/python -m pytest tests/test_ai_workflows.py tests/test_store_executor.py -q`
Expected: 全部 passed。若 `test_writeback_converges` 因 guard/flow 语法报 `ValueError: tasklist 校验失败`，先检查 flow 里守卫名与注册名一致、`join: OR` 行在 flow 字符串末尾。若所有用例的 result 都是"工作流未到达终点节点"，说明 tickflow Firing 对象的节点字段名不是 `.node`——打印 `vars(firings[0])` 核对字段名并同步修改 `_final_output`。

- [ ] **Step 6: Commit**

```bash
git add server/src/figure_agent/ai/workflows.py server/src/figure_agent/store.py server/tests/test_ai_workflows.py server/tests/test_store_executor.py
git commit -m "feat(ai): 四条固定 tasklist 工作流 + run_workflow（WS 桥接/runs.jsonl/串行锁）"
```

---

### Task 5: REST 端点 — create / adapt / instruct / writeback / runs / enrich-selection

**Files:**
- Create: `server/src/figure_agent/enrich.py`（session.py 富化逻辑的纯函数化，全局存储删除）
- Modify: `server/src/figure_agent/main.py`
- Modify: `server/tests/test_api.py`
- Create: `server/tests/fixtures/iris.csv`

- [ ] **Step 1: 建 iris.csv 夹具（真实 LLM smoke 与 adapt 测试共用）**

`server/tests/fixtures/iris.csv`（取 iris 前 30 行、三列即可，UTF-8 无索引）：

```csv
sepal_length,sepal_width,petal_length,species
5.1,3.5,1.4,setosa
4.9,3.0,1.4,setosa
4.7,3.2,1.3,setosa
4.6,3.1,1.5,setosa
5.0,3.6,1.4,setosa
5.4,3.9,1.7,setosa
4.6,3.4,1.4,setosa
5.0,4.5,1.7,setosa
4.4,2.9,1.4,setosa
4.9,3.1,1.5,setosa
5.4,3.7,1.5,setosa
4.8,3.4,1.6,setosa
4.8,3.0,1.4,setosa
4.3,3.0,1.1,setosa
5.8,4.0,1.2,setosa
5.7,4.4,1.5,setosa
5.4,3.9,1.3,setosa
5.1,3.5,1.4,setosa
5.7,3.8,1.7,setosa
5.1,3.8,1.5,setosa
7.0,3.2,4.7,versicolor
6.4,3.2,4.5,versicolor
6.9,3.1,4.9,versicolor
5.5,2.3,4.0,versicolor
6.5,2.8,4.6,versicolor
5.7,2.8,4.5,versicolor
6.3,3.3,4.7,versicolor
4.9,2.4,3.3,versicolor
6.6,2.9,4.6,versicolor
5.2,2.7,3.9,versicolor
```

- [ ] **Step 2: enrich.py — 从 session.py 迁移富化逻辑**

创建 `server/src/figure_agent/enrich.py`：把 `session.py` 的 `_enrich_one` 与 `_nearby` 原样迁入，`_enrich_one` 改名为公开的 `enrich_selection(store, project, figure, selection)`，删除 `_lock/_latest/_by_figure/save_selection/get_selection`（全局存储不再存在）。文件头 docstring：

```python
"""选区富化（纯函数）：在当前 SVG 中定位选区元素并补全
elementId/semanticPath/fingerprint/nearby。供 enrich-selection 端点与
instruct 工作流共用；无任何全局状态。"""
```

- [ ] **Step 3: 写端点失败测试**

`server/tests/test_api.py` 顶部 imports 增加 `import json`；新增：

```python
def _stub_routes(monkeypatch, routes):
    from tests.test_ai_workflows import StubLLM

    stub = StubLLM(routes)
    import figure_agent.ai.workflows as wf

    monkeypatch.setattr(wf, "get_llm", lambda: stub)
    return stub


def test_ai_create_endpoint(client, monkeypatch, tmp_path):
    import pathlib

    iris = pathlib.Path(__file__).parent / "fixtures" / "iris.csv"
    from tests.test_ai_workflows import GOOD_CODE, STD_REPLY

    _stub_routes(monkeypatch, {
        "数据标准化": [STD_REPLY],
        "绘图代码生成器": [json.dumps({"code": GOOD_CODE, "notes": ""})],
    })
    r = client.post(
        "/api/projects/demo/figures/ai",
        data={"name": "ai-fig", "requirements": "散点图，按物种着色"},
        files={"data": ("iris.csv", iris.read_bytes(), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["kind"] == "create"
    assert "fa:response-curve" in client.get("/api/figure/demo/ai-fig").json()["baseSvg"]
    meta = client.get("/api/figure/demo/ai-fig").json()["meta"]
    assert meta["origin"] == "ai"
    runs = client.get("/api/figure/demo/ai-fig/runs").json()
    assert runs[0]["kind"] == "create"


def test_ai_create_duplicate_400(client, monkeypatch):
    r = client.post(
        "/api/projects/demo/figures/ai",
        data={"name": "bars", "requirements": "x"},
        files={"data": ("d.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert r.status_code == 400  # bars 已由模板建过


def test_instruct_endpoint(client, monkeypatch):
    # stub 返回当前代码原样（demo/bars 是模板图、无 data.csv，
    # 不能回读 data.csv 的 GOOD_CODE，否则渲染失败触发 fix 循环到超限）
    code = client.get("/api/figure/demo/bars").json()["code"]
    _stub_routes(monkeypatch, {
        "绘图代码修改器": [json.dumps({"code": code, "notes": "已处理指令"})],
    })
    sel = {"elementId": "fa:treatment-bar-1", "semanticPath": "fig/axes_1/g/fa:treatment-bar-1"}
    r = client.post("/api/figure/demo/bars/instruct",
                    json={"instruction": "把选中的柱子改红", "selection": sel})
    assert r.status_code == 200 and r.json()["ok"] is True
    # instruct 后图已重渲染
    assert client.get("/api/figure/demo/bars").json()["baseSvg"]


def test_writeback_endpoint(client, monkeypatch):
    code = client.get("/api/figure/demo/bars").json()["code"]
    patched = code.replace('b.set_gid(f"fa:treatment-bar-{i}")',
                           'b.set_gid(f"fa:treatment-bar-{i}"); b.set_color("#dd3322")')
    _stub_routes(monkeypatch, {"微调回写器": [json.dumps({"code": patched, "notes": "改色"})]})
    # 先造一个 active op
    sel = {"elementId": "fa:treatment-bar-1", "semanticPath": "fig/axes_1/g/fa:treatment-bar-1"}
    client.post("/api/figure/demo/bars/enrich-selection", json={"selection": sel})
    patch = client.get("/api/figure/demo/bars").json()["patch"]
    patch["ops"] = [{"id": "op-x", "kind": "set_style", "target": {"id": "fa:treatment-bar-1",
                    "semanticPath": "fig/axes_1/g/fa:treatment-bar-1"},
                    "attr": "fill", "value": "#dd3322", "intent": "处理组改红",
                    "origin": "manual", "status": "active"}]
    client.put("/api/figure/demo/bars/patch", json=patch)
    r = client.post("/api/figure/demo/bars/writeback")
    assert r.status_code == 200
    body = r.json()
    assert body["cleared"] is True and body["ok"] is True


def test_enrich_selection_stateless(client):
    sel = {"elementId": "fa:treatment-bar-2", "semanticPath": "fig/axes_1/g/fa:treatment-bar-2"}
    r = client.post("/api/figure/demo/bars/enrich-selection", json={"selection": sel})
    body = r.json()
    assert body["elementId"] == "fa:treatment-bar-2"
    assert body["fingerprint"]
    assert client.get("/api/session/selection").status_code == 404
```

同时**删除** `test_api.py` 中原 `test_selection_session` 与 `test_multiselect_session`（读全局会话的两条），`test_full_flow` 里若有 `/api/session/selection` 断言一并删除。

Run: `cd server && .venv/Scripts/python -m pytest tests/test_api.py -q`
Expected: 新增 5 条 FAIL（404），存量通过

- [ ] **Step 4: main.py 实现端点**

imports 增加：

```python
import json

from fastapi import File, Form, UploadFile

from . import enrich
from .ai.workflows import run_workflow
```

（`from . import config, session` 改为 `from . import config`；`SelectionPost` 保留。）

删除 `post_selection` / `get_selection` 两个端点函数，新增：

```python
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


async def _save_upload(fdir: Path, upload: UploadFile) -> str:
    name = Path(upload.filename or "data.csv").name
    data = await upload.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="上传文件超过 10MB 限制")
    updir = fdir / "uploads"
    updir.mkdir(exist_ok=True)
    (updir / name).write_bytes(data)
    return name
```

```python
@app.post("/api/projects/{project}/figures/ai")
async def create_figure_ai(project: str, name: str = Form(...),
                           requirements: str = Form(...),
                           data: UploadFile = File(...)):
    try:
        store.init_figure(project, name, origin="ai")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    upload_name = await _save_upload(store.figure_dir(project, name), data)
    result = await run_workflow(
        "create", store, project, name,
        {"requirements": requirements, "upload_name": upload_name},
    )
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "project": project, "figure": name})
    return result


@app.post("/api/projects/{project}/figures/adapt")
async def adapt_figure(project: str, name: str = Form(...),
                       requirements: str = Form(""),
                       data: UploadFile = File(...),
                       script: UploadFile = File(...)):
    try:
        store.init_figure(project, name, origin="adapt")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    fdir = store.figure_dir(project, name)
    upload_name = await _save_upload(fdir, data)
    script_bytes = await script.read()
    if len(script_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="脚本超过 10MB 限制")
    (fdir / "uploads" / Path(script.filename or "plot.py").name).write_bytes(script_bytes)
    result = await run_workflow(
        "adapt", store, project, name,
        {"requirements": requirements, "upload_name": upload_name,
         "script_text": script_bytes.decode("utf-8", errors="replace")},
    )
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "project": project, "figure": name})
    return result


@app.post("/api/figure/{project}/{figure}/instruct")
async def instruct(project: str, figure: str, body: InstructPost):
    _figure_or_404(project, figure)
    items = body.selection if isinstance(body.selection, list) else [body.selection]
    enriched = [
        enrich.enrich_selection(store, project, figure, item) for item in items
    ]
    result = await run_workflow(
        "edit", store, project, figure,
        {
            "instruction": body.instruction,
            "selection_json": json.dumps(enriched, ensure_ascii=False),
            "code": store.read_code(project, figure),
        },
    )
    await _notify({"type": "figure_updated" if result.get("ok") else "render_error",
                   "project": project, "figure": figure})
    return result


@app.post("/api/figure/{project}/{figure}/writeback")
async def writeback(project: str, figure: str):
    _figure_or_404(project, figure)
    result = await run_workflow("writeback", store, project, figure, {})
    await _notify({"type": "figure_updated", "project": project, "figure": figure})
    return result


@app.post("/api/figure/{project}/{figure}/enrich-selection")
async def enrich_selection_ep(project: str, figure: str, body: SelectionPost):
    _figure_or_404(project, figure)
    items = body.selection if isinstance(body.selection, list) else [body.selection]
    enriched = [enrich.enrich_selection(store, project, figure, item) for item in items]
    return enriched if isinstance(body.selection, list) else enriched[0]


@app.get("/api/figure/{project}/{figure}/runs")
def list_runs(project: str, figure: str):
    _figure_or_404(project, figure)
    path = store.figure_dir(project, figure) / "runs.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(out))
```

`InstructPost` 模型（放在"模型"区）：

```python
class InstructPost(BaseModel):
    instruction: str
    selection: dict | list[dict] = Field(default_factory=dict)
```

注意：`run_workflow` 内部 `from .ai.workflows import get_llm` 的间接层——端点测试 monkeypatch 的是 `figure_agent.ai.workflows.get_llm`，因此 workflows.run_workflow 里 `client = llm_client or get_llm()` 引用的是**模块全局名** `get_llm`（本文件顶部 `from .llm import get_llm`），monkeypatch.setattr(wf, "get_llm", ...) 生效。保持现状即可。

- [ ] **Step 5: 删除 session.py 并补 .gitignore**

```bash
git rm server/src/figure_agent/session.py
```

仓库根 `.gitignore` 追加（spec §2/§4：上传原件、run 日志、密钥不进 git；`data.csv` 进 git）：

```
.env
workspace/**/uploads/
workspace/**/runs.jsonl
```

若 `.gitignore` 已含 `.env` 则跳过该行。

- [ ] **Step 6: 全量测试**

Run: `cd server && .venv/Scripts/python -m pytest tests/ -q`
Expected: 全部 passed（含 v1 存量）

- [ ] **Step 7: Commit**

```bash
git add -A server
git commit -m "feat(api): 四条 AI 工作流端点 + runs/enrich-selection；删全局选区会话"
```

---

### Task 6: 前端 — api/types 扩展 + AIPanel + App 接线

**Files:**
- Modify: `web/src/types.ts`
- Modify: `web/src/api.ts`
- Create: `web/src/components/AIPanel.tsx`
- Modify: `web/src/App.tsx`
- Modify: `web/src/styles.css`
- Test: `web/src/components/AIPanel.test.tsx`

- [ ] **Step 1: types.ts 追加**

```ts
export interface AiStatus {
  configured: boolean;
  provider: string;
  model: string;
  mock: boolean;
}

export interface AiRunResult {
  kind: "create" | "adapt" | "edit" | "writeback";
  ok: boolean;
  rounds: number;
  stderr: string;
  error_line?: number | null;
  notes?: string;
  cleared?: boolean;
  remaining?: number;
}

export interface RunEvent {
  runId: string;
  phase: "run_start" | "run_end" | "node_start" | "node_end" | "node_failed" | "llm_start" | "llm_end";
  node?: string;
  detail?: string;
  ok?: boolean;
  at: number;
}
```

- [ ] **Step 2: api.ts 追加（并把 pushSelection 换成 enrichSelection）**

`api` 对象内新增：

```ts
  aiStatus: () => fetch("/api/ai/status").then((r) => json<AiStatus>(r)),

  createFigureAi: (project: string, name: string, requirements: string, data: File) => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("requirements", requirements);
    fd.append("data", data);
    return fetch(`/api/projects/${project}/figures/ai`, { method: "POST", body: fd }).then(
      (r) => json<AiRunResult>(r)
    );
  },

  adaptFigure: (project: string, name: string, requirements: string, data: File, script: File) => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("requirements", requirements);
    fd.append("data", data);
    fd.append("script", script);
    return fetch(`/api/projects/${project}/figures/adapt`, { method: "POST", body: fd }).then(
      (r) => json<AiRunResult>(r)
    );
  },

  instruct: (project: string, figure: string, instruction: string, selection: object | object[]) =>
    fetch(`/api/figure/${project}/${figure}/instruct`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction, selection }),
    }).then((r) => json<AiRunResult>(r)),

  writebackPatch: (project: string, figure: string) =>
    fetch(`/api/figure/${project}/${figure}/writeback`, { method: "POST" }).then((r) =>
      json<AiRunResult>(r)
    ),

  enrichSelection: (project: string, figure: string, selection: object | object[]) =>
    fetch(`/api/figure/${project}/${figure}/enrich-selection`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project, figure, selection }),
    }).then((r) => json<SelectionJSON>(r)),
```

删除旧的 `pushSelection`；types import 增加 `AiRunResult, AiStatus`。

- [ ] **Step 3: AIPanel 组件**

`web/src/components/AIPanel.tsx`：

```tsx
// AI 面板：造图/改造表单 + 选区指令 + 回写 + run 事件时间线。
import { useEffect, useState } from "react";
import { api } from "../api";
import type { AiStatus, AiRunResult, ProjectInfo, RunEvent, SelectionJSON } from "../types";

interface Props {
  projects: ProjectInfo[];
  current: { project: string; figure: string } | null;
  selections: SelectionJSON[];
  patchOpCount: number;
  runEvents: RunEvent[];
  runActive: boolean;
  onRunStart: () => void;
  onFigureReady: (project: string, figure: string) => void;
  onFigureChanged: () => void;
  showToast: (msg: string, error?: boolean) => void;
}

export function AIPanel(props: Props) {
  const { projects, current, selections, patchOpCount, runEvents, runActive,
          onRunStart, onFigureReady, onFigureChanged, showToast } = props;
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [project, setProject] = useState("");
  const [name, setName] = useState("");
  const [requirements, setRequirements] = useState("");
  const [dataFile, setDataFile] = useState<File | null>(null);
  const [scriptFile, setScriptFile] = useState<File | null>(null);
  const [instruction, setInstruction] = useState("");
  const [showAdapt, setShowAdapt] = useState(false);

  useEffect(() => {
    api.aiStatus().then(setStatus).catch(() => setStatus({ configured: false, provider: "", model: "", mock: false }));
  }, []);

  useEffect(() => {
    if (!project && projects.length > 0) setProject(projects[0].name);
  }, [projects, project]);

  const disabled = runActive || !status?.configured;

  const handleCreate = async () => {
    if (!project || !name || !dataFile) return;
    onRunStart();
    try {
      const r: AiRunResult = await api.createFigureAi(project, name, requirements, dataFile);
      showToast(r.ok ? `造图完成（${r.rounds} 轮）` : `造图失败：${(r.stderr || "").slice(0, 160)}`, !r.ok);
      onFigureReady(project, name);
    } catch (e) {
      showToast(`造图失败：${(e as Error).message}`, true);
    } finally {
      onFigureChanged();
    }
  };

  const handleAdapt = async () => {
    if (!project || !name || !dataFile || !scriptFile) return;
    onRunStart();
    try {
      const r = await api.adaptFigure(project, name, requirements, dataFile, scriptFile);
      showToast(r.ok ? `改造完成（${r.rounds} 轮）` : `改造失败：${(r.stderr || "").slice(0, 160)}`, !r.ok);
      onFigureReady(project, name);
    } catch (e) {
      showToast(`改造失败：${(e as Error).message}`, true);
    } finally {
      onFigureChanged();
    }
  };

  const handleInstruct = async () => {
    if (!current || !instruction.trim()) return;
    onRunStart();
    try {
      const payload = selections.length === 1 ? selections[0] : selections;
      const r = await api.instruct(current.project, current.figure, instruction, payload);
      showToast(r.ok ? "修改完成" : `修改失败：${(r.stderr || "").slice(0, 160)}`, !r.ok);
    } catch (e) {
      showToast(`修改失败：${(e as Error).message}`, true);
    } finally {
      onFigureChanged();
    }
  };

  const handleWriteback = async () => {
    if (!current) return;
    onRunStart();
    try {
      const r = await api.writebackPatch(current.project, current.figure);
      showToast(
        r.cleared ? "patch 已收敛清空" : `回写未收敛：剩余 ${r.remaining} 个 op`,
        !r.cleared
      );
    } catch (e) {
      showToast(`回写失败：${(e as Error).message}`, true);
    } finally {
      onFigureChanged();
    }
  };

  return (
    <div className="ai-panel">
      <div className="ai-status">
        AI：
        {status === null ? "检测中…" : status.configured
          ? `${status.provider} / ${status.model}${status.mock ? "（mock）" : ""}`
          : "未配置（仓库根放 config.json + .env，参考 config.example.json）"}
      </div>

      <section>
        <h4>AI 造图</h4>
        <select value={project} onChange={(e) => setProject(e.target.value)} disabled={disabled}>
          {projects.map((p) => (
            <option key={p.name} value={p.name}>{p.name}</option>
          ))}
        </select>
        <input placeholder="图名" value={name} onChange={(e) => setName(e.target.value)} disabled={disabled} />
        <textarea placeholder="绘图要求（自然语言）" value={requirements}
                  onChange={(e) => setRequirements(e.target.value)} disabled={disabled} />
        <input type="file" accept=".csv,.tsv,.txt,.xlsx,.xls,.json"
               onChange={(e) => setDataFile(e.target.files?.[0] ?? null)} disabled={disabled} />
        <button onClick={handleCreate} disabled={disabled || !name || !dataFile}>生成图表</button>
        <button className="link" onClick={() => setShowAdapt((v) => !v)}>
          {showAdapt ? "收起脚本改造" : "改为脚本改造（数据 + 现成脚本）"}
        </button>
        {showAdapt && (
          <div className="adapt-form">
            <input type="file" accept=".py" onChange={(e) => setScriptFile(e.target.files?.[0] ?? null)} disabled={disabled} />
            <button onClick={handleAdapt} disabled={disabled || !name || !dataFile || !scriptFile}>改造脚本</button>
          </div>
        )}
      </section>

      {current && (
        <section>
          <h4>指令修改 {selections.length > 0 && `（已附加 ${selections.length} 个选区元素）`}</h4>
          <textarea placeholder="例如：把选中的柱子改成主色蓝，字号统一 12" value={instruction}
                    onChange={(e) => setInstruction(e.target.value)} disabled={disabled} />
          <div>
            <button onClick={handleInstruct} disabled={disabled || !instruction.trim()}>执行修改</button>
            <button onClick={handleWriteback} disabled={disabled || patchOpCount === 0}>
              回写 patch（{patchOpCount} op）
            </button>
          </div>
        </section>
      )}

      <section>
        <h4>运行时间线</h4>
        {runEvents.length === 0 && <div className="hint">尚无 AI 运行</div>}
        <ul className="run-events">
          {runEvents.map((ev, i) => (
            <li key={i} className={`run-ev run-ev-${ev.phase}`}>
              {new Date(ev.at).toLocaleTimeString()} {ev.phase}
              {ev.node ? ` · ${ev.node}` : ""}
              {ev.detail ? ` · ${ev.detail}` : ""}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
```

- [ ] **Step 4: App.tsx 接线**

1. import 增加 `import { AIPanel } from "./components/AIPanel";` 与类型 `RunEvent`。
2. 状态新增：

```tsx
const [aiEvents, setAiEvents] = useState<RunEvent[]>([]);
const [runActive, setRunActive] = useState(false);
```

3. WS `handleEvent` 中，`figure_updated` 分支后追加：

```tsx
        if (data.type === "ai_run") {
          setAiEvents((prev) => [...prev.slice(-199), { ...data, at: Date.now() }]);
          if (data.phase === "run_end") {
            setRunActive(false);
            if (cur && data.project === cur.project && data.figure === cur.figure) {
              loadFigure(cur.project, cur.figure, stateRef.current.dirty);
            }
            refreshProjects();
          }
        }
```

4. `onSelection` 回调里把 `api.pushSelection(...)` 换成：

```tsx
      api
        .enrichSelection(current.project, current.figure, payload)
        .then((enriched) => setSelections(Array.isArray(enriched) ? enriched : [enriched]))
        .catch(() => setSelections(jsons));
```

5. 布局：`<EditorPanel ... />` 之前插入 `<AIPanel ... />`（同级第三栏；若布局为两栏则放 EditorPanel 上方）：

```tsx
      <AIPanel
        projects={projects}
        current={current}
        selections={selections}
        patchOpCount={detail?.patch.ops.length ?? 0}
        runEvents={aiEvents}
        runActive={runActive}
        onRunStart={() => setRunActive(true)}
        onFigureReady={(p, f) => selectFigure(p, f)}
        onFigureChanged={() => {
          refreshProjects();
          if (current) loadFigure(current.project, current.figure, stateRef.current.dirty);
        }}
        showToast={showToast}
      />
```

6. stale banner 文案 `"服务器上的图已更新（ZCode 改了代码）。..."` 改为 `"服务器上的图已更新（AI 或手动渲染）。本地有未保存的微调，未自动刷新；保存或撤销后刷新。"`。

- [ ] **Step 5: styles.css 追加**

```css
/* AI 面板 */
.ai-panel { width: 300px; border-left: 1px solid var(--border, #ddd); padding: 10px; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; }
.ai-panel h4 { margin: 0 0 6px; font-size: 13px; }
.ai-panel section { display: flex; flex-direction: column; gap: 6px; }
.ai-panel input, .ai-panel select, .ai-panel textarea { width: 100%; box-sizing: border-box; font-size: 12px; }
.ai-panel textarea { min-height: 56px; resize: vertical; }
.ai-status { font-size: 12px; color: #666; padding: 6px 8px; background: #f6f8fa; border-radius: 4px; }
.ai-panel .adapt-form { display: flex; flex-direction: column; gap: 6px; padding-left: 8px; border-left: 2px solid #eee; }
.ai-panel button.link { background: none; border: none; color: #2a6f97; cursor: pointer; padding: 0; text-align: left; font-size: 12px; }
.run-events { list-style: none; margin: 0; padding: 0; font-size: 11px; font-family: ui-monospace, monospace; max-height: 220px; overflow-y: auto; }
.run-ev { padding: 1px 0; color: #555; }
.run-ev-run_start, .run-ev-run_end { color: #222; font-weight: 600; }
.run-ev-node_failed { color: #b00; }
.run-ev-llm_start, .run-ev-llm_end { color: #886; }
```

（若现有 styles.css 用 CSS 变量/暗色主题，按现有变量名微调。）

- [ ] **Step 6: 写 AIPanel 测试**

`web/src/components/AIPanel.test.tsx`：

```tsx
// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react-dom/test-utils";
import { AIPanel } from "./AIPanel";

vi.mock("../api", () => ({
  api: {
    aiStatus: () =>
      Promise.resolve({ configured: true, provider: "mock", model: "mock", mock: true }),
    createFigureAi: vi.fn(() => Promise.resolve({ kind: "create", ok: true, rounds: 1, stderr: "" })),
    adaptFigure: vi.fn(),
    instruct: vi.fn(),
    writebackPatch: vi.fn(),
    enrichSelection: vi.fn(),
  },
}));

describe("AIPanel", () => {
  let root: Root;
  let container: HTMLElement;

  const props = {
    projects: [{ name: "demo", figures: [] }],
    current: { project: "demo", figure: "f1" },
    selections: [],
    patchOpCount: 2,
    runEvents: [{ runId: "r1", phase: "run_end" as const, node: "create", ok: true, at: 0 }],
    runActive: false,
    onRunStart: vi.fn(),
    onFigureReady: vi.fn(),
    onFigureChanged: vi.fn(),
    showToast: vi.fn(),
  };

  function render() {
    container = document.body.appendChild(document.createElement("div"));
    root = createRoot(container);
    act(() => root.render(createElement(AIPanel, props)));
  }

  it("渲染状态徽标与造图表单，未选文件时生成按钮禁用", async () => {
    render();
    await act(() => new Promise((r) => setTimeout(r, 0)));
    expect(container.textContent).toContain("mock");
    expect(container.textContent).toContain("AI 造图");
    const buttons = [...container.querySelectorAll("button")];
    const gen = buttons.find((b) => b.textContent === "生成图表")!;
    expect(gen.disabled).toBe(true);
  });

  it("显示运行时间线事件", () => {
    render();
    expect(container.textContent).toContain("run_end");
  });

  it("有 patch op 时回写按钮可用并显示数量", async () => {
    render();
    await act(() => new Promise((r) => setTimeout(r, 0)));
    const wb = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("回写 patch")
    )!;
    expect(wb.disabled).toBe(false);
    expect(wb.textContent).toContain("2 op");
  });
});
```

- [ ] **Step 7: 运行前端测试与构建**

Run: `cd web && npm test && npm run build`
Expected: 测试全过；tsc 无错误

- [ ] **Step 8: Commit**

```bash
git add web/src
git commit -m "feat(web): AI 面板（造图/改造/选区指令/回写 + run 时间线），选区改走 enrich-selection"
```

---

### Task 7: 真实 LLM 手动 smoke（T2 合规性验收）

**Files:** 无新代码；运行验证

- [ ] **Step 1: 配置真实 provider**

仓库根创建 `config.json`（参照 `config.example.json`，填可用 provider）与 `.env`（`<KEY>_API_KEY=...`）。确认 `.gitignore` 已含 `.env`。

- [ ] **Step 2: 启动服务并跑 create**

```bash
cd server && .venv/Scripts/python -m uvicorn figure_agent.main:app --port 8765
```

浏览器打开 `http://127.0.0.1:8765`，AI 面板造图：上传 `server/tests/fixtures/iris.csv`，要求"按物种画花瓣长 vs 萼片长散点图，图例中文"。

- [ ] **Step 3: 验收 T2**

打开生成的图目录 `workspace/<project>/<figure>/plot.py`，核对：
- 模块级 `fig` 变量；无 `plt.show()`；未覆盖 `svg.fonttype`
- 关键 artist 有 `set_gid("fa:…")`（散点系列/标题/轴标签）
- `pd.read_csv("data.csv")`，无硬编码数据
- 只用安全字体
- 浏览器中选区可选中生成的元素（gid 生效）

- [ ] **Step 4: 验收 adapt**

用现有 `workspace/demo/iris-scatter/plot.py` 作为脚本 + `iris.csv` 走"脚本改造"，验收同上，且 notes 说明数据源替换。

- [ ] **Step 5: 验收 edit + writeback**

- 浏览器选中一个元素，指令"把选中的元素改成红色"，确认渲染更新且只改了目标。
- 在 EditorPanel 做一个手动微调（改色），点"回写 patch"，确认 toast 显示"patch 已收敛清空"。

- [ ] **Step 6: 记录 smoke 结果到 runs.jsonl 检查**

```bash
cat workspace/*/*/runs.jsonl | tail -5
```

Expected: 每次操作一条记录，ok 字段正确。

---

### Task 8: 清理 MCP 与 ZCode 痕迹

**Files:**
- Delete: `server/src/figure_agent/mcp_server.py`、`.mcp.json`
- Modify: `server/pyproject.toml`、`AGENTS.md`、`README.md`、`server/tests/test_api.py`（若残留）

- [ ] **Step 1: 删文件与依赖**

```bash
git rm server/src/figure_agent/mcp_server.py .mcp.json
```

`server/pyproject.toml` dependencies 删除 `"mcp>=1.2,<2",`。

```bash
cd server && .venv/Scripts/pip uninstall -y mcp
```

- [ ] **Step 2: grep 确认无残留引用**

```bash
grep -rn "mcp\|MCP\|ZCode\|session" server/src server/tests web/src --include="*.py" --include="*.ts" --include="*.tsx" | grep -v node_modules
```

Expected: 无 `figure_agent.session` / `mcp_server` 引用；`AGENTS.md`/`README.md` 中的提及在下面两步重写。

- [ ] **Step 3: 重写 AGENTS.md**

全文替换为：

```markdown
# AGENTS.md — figure-agent 绘图代码约定

本仓库包含 figure-agent：本地 Web 应用。AI 能力由服务端内嵌的 SpecModule
工作流提供（server/src/figure_agent/ai/），不再依赖外部 coding agent / MCP。

## 面向人的约定（手写 plot.py 时）

### 渲染契约
1. 模块级构建图形，存入变量 `fig`；不要 `plt.show()`。
2. 不要碰 `svg.fonttype` / `svg.hashsalt`（服务端强制）。
3. 数据放图目录 `data.csv`，代码用 `pd.read_csv("data.csv")` 读取。

### gid 约定（最重要）
对每个"用户可能想单独选中/修改"的 artist 调 `set_gid("fa:名字")`（见
`server/src/figure_agent/ai/prompts.py` 的 GID_CONVENTION，含示例）。
命名建议 `fa:<语义>-<序号>`。

## 面向开发的约定

- AI 工作流的 prompt 与契约文本唯一来源是 `server/src/figure_agent/ai/prompts.py`；
  改契约先改那里（本文件与它保持一致）。
- 四条工作流（create/adapt/edit/writeback）是固定 tasklist，见
  `server/src/figure_agent/ai/workflows.py`；改流程须同步更新其测试。
- LLM 配置：仓库根 `config.json` + `.env`（参考 `config.example.json`）；
  `FIGURE_AGENT_MOCK=1` 免 key 冒烟。
```

- [ ] **Step 4: README.md 更新**

把 README 中所有 MCP/ZCode 工作流描述替换为原生 AI 工作流说明（四条工作流一句话各一行 + config.json/.env 配置说明 + `FIGURE_AGENT_MOCK=1`）。保留安装/启动/测试命令。

- [ ] **Step 5: 全量回归**

```bash
cd server && .venv/Scripts/python -m pytest tests/ -q
cd ../web && npm test && npm run build
```

Expected: 全部通过

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: 移除 MCP server 与 ZCode 工作流痕迹，文档切到原生 AI 工作流"
```

---

## 完成定义（对照 spec 成功标准）

- T1：Task 5/6 完成后浏览器内四条工作流可用；Task 8 后仓库无 MCP 痕迹。
- T2：Task 2 prompts + Task 7 smoke 核对。
- T3：Task 4 `test_create_with_fix_loop`（rounds==2）+ Task 7 观察。
- T4：Task 4 `test_writeback_converges` / `test_writeback_no_ops_short_circuit` + Task 7。
