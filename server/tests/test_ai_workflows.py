"""四条工作流端到端（StubLLM 假客户端，免 key）。"""

from __future__ import annotations

import asyncio
import json

from llm.client import LLMError, LLMResponse

from figureagent.figures.ai.workflows import run_workflow

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


def test_create_with_fix_loop(fig_store):
    store, workdir = fig_store
    stub = StubLLM({
        "数据标准化": [STD_REPLY],
        "绘图代码生成器": [json.dumps({"code": BAD_CODE, "notes": ""}),
                          json.dumps({"code": GOOD_CODE, "notes": ""})],
        "绘图代码修复器": [json.dumps({"code": GOOD_CODE, "notes": "修复列名"})],
    })
    result = asyncio.run(run_workflow(
        "create", store,
        {"requirements": "画剂量响应曲线", "upload_name": "d.csv"},
        llm_client=stub,
    ))
    fdir = store.figure_dir()
    assert result["ok"] is True and result["rounds"] == 2, result
    assert (fdir / "data.csv").exists() and (fdir / "data_profile.json").exists()
    assert "fa:response-curve" in store.read_svg("base")
    runs = store.list_runs()
    assert runs[0]["kind"] == "create" and runs[0]["ok"] is True
    # fix_code 收到了 stderr 与完整当前代码（{render} 含 code 字段）
    fix_prompts = [p for p in stub.prompts if "绘图代码修复器" in p]
    assert fix_prompts and "nope" in fix_prompts[0] and 'ax.plot' in fix_prompts[0]


def test_writeback_converges(fig_store):
    store, workdir = fig_store
    store.write_code(GOOD_CODE)
    store.save_patch({
        "baseHash": "",
        "ops": [{"id": "op-1", "kind": "set_style", "target": {"id": "fa:title"},
                 "attr": "font-size", "value": "20", "intent": "标题字号放大", "origin": "manual",
                 "status": "active"}],
    })
    wb_code = GOOD_CODE.replace('t.set_gid("fa:title")',
                                't.set_gid("fa:title")\nt.set_fontsize(20)')
    stub = StubLLM({"微调回写器": [json.dumps({"code": wb_code, "notes": "标题字号 20"})]})
    result = asyncio.run(run_workflow(
        "writeback", store, {}, llm_client=stub,
    ))
    assert result["ok"] is True and result["cleared"] is True, result
    assert result["remaining"] == 0
    assert store.read_patch()["ops"] == []


def test_writeback_no_ops_short_circuit(fig_store):
    store, workdir = fig_store
    store.write_code(GOOD_CODE)
    stub = StubLLM({})
    result = asyncio.run(run_workflow(
        "writeback", store, {}, llm_client=stub,
    ))
    assert result["ok"] is True and result["cleared"] is True
    assert stub.prompts == []  # 未花任何 LLM 调用


def test_adapt_end_to_end(fig_store):
    store, workdir = fig_store
    orig = (
        "import matplotlib.pyplot as plt\n"
        "fig, ax = plt.subplots(figsize=(4, 3))\n"
        'ax.plot([0, 5, 10], [1, 2, 3], color="red")\n'
        'ax.set_title("old")\n'
    )
    (workdir.uploads_dir() / "orig_plot.py").write_text(orig, encoding="utf-8")
    stub = StubLLM({
        "数据标准化": [STD_REPLY],
        "绘图脚本改造器": [json.dumps({"code": GOOD_CODE, "notes": "改造完成"})],
    })
    result = asyncio.run(run_workflow(
        "adapt", store,
        {"requirements": "", "upload_name": "d.csv", "script_text": orig},
        llm_client=stub,
    ))
    assert result["ok"] is True, result
    assert "fa:response-curve" in store.read_svg("base")
    runs = store.list_runs()
    assert runs[0]["kind"] == "adapt" and runs[0]["ok"] is True


def test_edit_end_to_end(fig_store):
    store, workdir = fig_store
    store.write_code(GOOD_CODE)
    stub = StubLLM({"绘图代码修改器": [json.dumps({"code": GOOD_CODE, "notes": "ok"})]})
    result = asyncio.run(run_workflow(
        "edit", store,
        {"instruction": "改色", "selection_json": "[]", "code": GOOD_CODE},
        llm_client=stub,
    ))
    assert result["ok"] is True and result["rounds"] == 1, result


def test_writeback_max_rounds(fig_store):
    """永不收敛的 op：MAX_ROUNDS 轮后终止，ok=False，LLM 恰好调 3 次。"""
    store, workdir = fig_store
    store.write_code(GOOD_CODE)
    store.save_patch({
        "baseHash": "",
        "ops": [{"id": "op-1", "kind": "set_style", "target": {"id": "fa:nonexistent"},
                 "attr": "fill", "value": "#ff0000", "intent": "改色", "origin": "manual",
                 "status": "active"}],
    })
    stub = StubLLM({"微调回写器": [json.dumps({"code": GOOD_CODE, "notes": "原样"})] * 3})
    result = asyncio.run(run_workflow(
        "writeback", store, {}, llm_client=stub,
    ))
    assert result["ok"] is False and result["cleared"] is False, result
    assert result["rounds"] == 3
    assert len(stub.prompts) == 3
    assert len(store.read_patch()["ops"]) == 1  # op 保留给 patch 覆盖层
    # 每轮都留了审计（3 轮 + Finalize 一次），且都落在 JSONL 里
    assert len(store.list_runs()) >= 1


def test_create_bad_json_failure_audited(fig_store):
    """LLM 持续回无效 JSON：引擎级 Failure 饿死下游、Finalize 不 fire——
    stderr 必须收割出具体失败节点与原因（非泛化文案），并补写运行审计。
    路由给两条坏回复：standardize 是裸 HarnessConfig（无 validate_retries，
    默认 0），第一条坏回复即失败——第二条路由项不会被消费；恰好钉住
    「失败收割」不依赖重试预算的语义。"""
    store, workdir = fig_store
    stub = StubLLM({"数据标准化": ["这不是JSON", "还不是JSON"], "绘图代码生成器": []})
    result = asyncio.run(run_workflow(
        "create", store,
        {"requirements": "画剂量响应曲线", "upload_name": "d.csv"},
        llm_client=stub,
    ))
    assert result["ok"] is False, result
    assert "未到达终点节点" not in result["stderr"]
    assert "失败" in result["stderr"], result  # 形如「节点 Standardize 失败：输出格式校验失败：…」
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0]["kind"] == "create" and runs[0]["ok"] is False
    assert "失败" in runs[0]["stderr"]


def test_create_llm_infra_failure_harvested(fig_store):
    """LLM 调用失败（key 失效 401/网络错/超时）→ harness 返回
    Failure(type="infrastructure") → 引擎记节点 status="aborted"（非
    "failed"）且 run 立即中止。收割必须覆盖 aborted，报出具体节点与
    真实错误——不得落到「工作流未到达终点节点」兜底文案。"""
    store, workdir = fig_store

    class BoomLLM(StubLLM):
        async def complete(self, prompt=None, **kw):
            if "数据标准化" in (prompt or ""):
                raise LLMError(
                    "OpenAI API 调用失败: Error code: 401 - Authentication Fails, "
                    "Your api key: ****d7c3 is invalid")
            return await super().complete(prompt=prompt, **kw)

    stub = BoomLLM({})
    result = asyncio.run(run_workflow(
        "create", store,
        {"requirements": "画剂量响应曲线", "upload_name": "d.csv"},
        llm_client=stub,
    ))
    assert result["ok"] is False, result
    assert "未到达终点节点" not in result["stderr"]
    assert "Standardize" in result["stderr"] and "401" in result["stderr"], result
    runs = store.list_runs()
    assert len(runs) == 1 and runs[0]["kind"] == "create" and runs[0]["ok"] is False
    assert "401" in runs[0]["stderr"]
