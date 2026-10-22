"""ai.llm：mock 开关与状态探测。"""

from __future__ import annotations

import pytest

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
    assert "detail" in status  # 诊断字段：区分未安装 / 格式错 / 未配置


def test_get_llm_unconfigured_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("FIGURE_AGENT_MOCK", raising=False)
    monkeypatch.setattr(ai_llm, "REPO_ROOT", tmp_path)
    with pytest.raises(Exception):
        ai_llm.get_llm()
