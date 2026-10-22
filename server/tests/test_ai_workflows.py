"""四条工作流端到端（StubLLM 假客户端，免 key）。"""

from __future__ import annotations

import asyncio
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
    result = asyncio.run(run_workflow(
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
    result = asyncio.run(run_workflow(
        "writeback", store, "p", "f", {}, llm_client=stub,
    ))
    assert result["ok"] is True and result["cleared"] is True, result
    assert result["remaining"] == 0
    assert store.read_patch("p", "f")["ops"] == []


def test_writeback_no_ops_short_circuit(tmp_path):
    store = make_store(tmp_path)
    store.write_code("p", "f", GOOD_CODE)
    stub = StubLLM({})
    result = asyncio.run(run_workflow(
        "writeback", store, "p", "f", {}, llm_client=stub,
    ))
    assert result["ok"] is True and result["cleared"] is True
    assert stub.prompts == []  # 未花任何 LLM 调用


def test_adapt_end_to_end(tmp_path):
    store = make_store(tmp_path)
    fdir = store.figure_dir("p", "f")
    orig = (
        "import matplotlib.pyplot as plt\n"
        "fig, ax = plt.subplots(figsize=(4, 3))\n"
        'ax.plot([0, 5, 10], [1, 2, 3], color="red")\n'
        'ax.set_title("old")\n'
    )
    (fdir / "uploads" / "orig_plot.py").write_text(orig, encoding="utf-8")
    stub = StubLLM({
        "数据标准化": [STD_REPLY],
        "绘图脚本改造器": [json.dumps({"code": GOOD_CODE, "notes": "改造完成"})],
    })
    result = asyncio.run(run_workflow(
        "adapt", store, "p", "f",
        {"requirements": "", "upload_name": "d.csv", "script_text": orig},
        llm_client=stub,
    ))
    assert result["ok"] is True, result
    assert "fa:response-curve" in store.read_svg("p", "f", "base")
    runs = [json.loads(x) for x in (fdir / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()]
    assert runs[-1]["kind"] == "adapt" and runs[-1]["ok"] is True


def test_edit_end_to_end(tmp_path):
    store = make_store(tmp_path)
    store.write_code("p", "f", GOOD_CODE)
    stub = StubLLM({"绘图代码修改器": [json.dumps({"code": GOOD_CODE, "notes": "ok"})]})
    result = asyncio.run(run_workflow(
        "edit", store, "p", "f",
        {"instruction": "改色", "selection_json": "[]", "code": GOOD_CODE},
        llm_client=stub,
    ))
    assert result["ok"] is True and result["rounds"] == 1, result


def test_writeback_max_rounds(tmp_path):
    """永不收敛的 op：MAX_ROUNDS 轮后终止，ok=False，LLM 恰好调 3 次。"""
    store = make_store(tmp_path)
    store.write_code("p", "f", GOOD_CODE)
    store.save_patch("p", "f", {
        "baseHash": "",
        "ops": [{"id": "op-1", "kind": "set_style", "target": {"id": "fa:nonexistent"},
                 "attr": "fill", "value": "#ff0000", "intent": "改色", "origin": "manual",
                 "status": "active"}],
    })
    stub = StubLLM({"微调回写器": [json.dumps({"code": GOOD_CODE, "notes": "原样"})] * 3})
    result = asyncio.run(run_workflow(
        "writeback", store, "p", "f", {}, llm_client=stub,
    ))
    assert result["ok"] is False and result["cleared"] is False, result
    assert result["rounds"] == 3
    assert len(stub.prompts) == 3
    assert len(store.read_patch("p", "f")["ops"]) == 1  # op 保留给 patch 覆盖层


def test_create_bad_json_failure_audited(tmp_path):
    """LLM 持续回无效 JSON：引擎级 Failure 饿死下游、Finalize 不 fire——
    stderr 必须收割出具体失败节点与原因（非泛化文案），并补写 runs.jsonl。
    路由给两条坏回复：validate_retries=1 会先重试一次，单条坏回复会被
    StubLLM 的 "{}" 兜底救活，到不了收割路径。"""
    store = make_store(tmp_path)
    stub = StubLLM({"数据标准化": ["这不是JSON", "还不是JSON"], "绘图代码生成器": []})
    result = asyncio.run(run_workflow(
        "create", store, "p", "f",
        {"requirements": "画剂量响应曲线", "upload_name": "d.csv"},
        llm_client=stub,
    ))
    assert result["ok"] is False, result
    assert "未到达终点节点" not in result["stderr"]
    assert "失败" in result["stderr"], result  # 形如「节点 Standardize 失败：输出格式校验失败：…」
    lines = (store.figure_dir("p", "f") / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["kind"] == "create" and entry["ok"] is False
    assert "失败" in entry["stderr"]
