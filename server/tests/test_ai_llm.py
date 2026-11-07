"""ai.llm：mock 开关、llm.json 解析与状态探测（应用级配置 ~/.figureagent）。"""

from __future__ import annotations

import json

import pytest

import figureagent.figures.ai.llm as ai_llm

LLM_JSON = {
    "providers": [
        {"name": "p1", "sdktype": "openai", "base_url": "https://x.example",
         "api_key_env": "K", "timeout": 10, "max_retries": 1}
    ],
    "models": [{"name": "m1", "provider": "p1", "max_tokens": 99}],
}


def _point_to(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_llm, "CONFIG_PATH", tmp_path / "llm.json")
    monkeypatch.setattr(ai_llm, "ENV_PATH", tmp_path / ".env")


def test_ai_status_mock(home, monkeypatch):
    monkeypatch.setenv("FIGUREAGENT_MOCK", "1")
    status = ai_llm.ai_status()
    assert status == {"configured": True, "provider": "mock", "model": "mock", "mock": True}
    client = ai_llm.get_llm()
    assert type(client).__name__ == "MockLLMClient"


def test_mock_compat_env_names(home, monkeypatch):
    """旧名 FIGURE_AGENT_MOCK / RI_FIGURE_MOCK 仍然开关 mock（迁移期兼容）。"""
    for key in ("FIGURE_AGENT_MOCK", "RI_FIGURE_MOCK"):
        monkeypatch.setenv(key, "1")
        try:
            assert ai_llm.ai_status()["mock"] is True, key
        finally:
            monkeypatch.delenv(key)


def test_ai_status_unconfigured(home, monkeypatch, tmp_path):
    _point_to(monkeypatch, tmp_path)  # 无 llm.json 的目录
    status = ai_llm.ai_status()
    assert status["configured"] is False and status["mock"] is False
    assert "llm.json" in status["detail"]  # 诊断字段：区分未安装 / 格式错 / 未配置


def test_load_config_parses_providers_and_models(home, monkeypatch, tmp_path):
    (tmp_path / "llm.json").write_text(json.dumps(LLM_JSON), encoding="utf-8")
    monkeypatch.setenv("K", "sk-test")
    _point_to(monkeypatch, tmp_path)
    cfg = ai_llm.load_config()
    assert cfg.provider == "openai" and cfg.api_key == "sk-test"
    assert cfg.model == "m1" and cfg.max_tokens == 99
    assert cfg.providers["p1"].api_key == "sk-test"
    assert cfg.base_url == "https://x.example"
    status = ai_llm.ai_status()
    assert status["configured"] is True and status["model"] == "m1" and status["mock"] is False


def test_env_file_loaded_without_overwrite(home, monkeypatch, tmp_path):
    """llm.json 的 api_key_env 引 .env 变量；os.environ 已有键不被 .env 覆盖。"""
    monkeypatch.delenv("K", raising=False)
    (tmp_path / "llm.json").write_text(json.dumps(LLM_JSON), encoding="utf-8")
    (tmp_path / ".env").write_text("K=from-file\n", encoding="utf-8")
    _point_to(monkeypatch, tmp_path)
    assert ai_llm.load_config().api_key == "from-file"
    monkeypatch.setenv("K", "from-env")
    assert ai_llm.load_config().api_key == "from-env"


def test_load_config_missing_providers_raises(home, monkeypatch, tmp_path):
    (tmp_path / "llm.json").write_text(json.dumps({"providers": [], "models": []}),
                                       encoding="utf-8")
    _point_to(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="providers"):
        ai_llm.load_config()


def test_get_llm_unconfigured_raises(home, monkeypatch, tmp_path):
    _point_to(monkeypatch, tmp_path)
    with pytest.raises(Exception):
        ai_llm.get_llm()
