"""LLM 客户端装配：配置在 ~/.figureagent/llm.json + .env（应用级，非目录级）。

llm.json 的 schema 与 SpecModule 的 config.json 完全一致（providers/models
数组，provider.api_key_env 引 .env 变量名）——把 figure-agent 旧仓库根
config.json 内容原样拷为 llm.json 即可。不使用 rules.txt。
``FIGUREAGENT_MOCK=1``（兼容 FIGURE_AGENT_MOCK / RI_FIGURE_MOCK）时用
SpecModule 的 MockLLMClient（免 key 接线冒烟）。
"""

from __future__ import annotations

import json
import os

from ... import config as fig_config

#: 测试注入点：tests 用 monkeypatch 指到无配置的临时目录
CONFIG_PATH = fig_config.llm_config_path()
ENV_PATH = fig_config.llm_env_path()


def _load_env(path) -> None:
    """加载 .env 到 os.environ；已存在于 os.environ 的键不被覆盖。"""
    if not path.exists():
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


def load_config():
    """读 llm.json + .env 构造 SpecModule LLMConfig（语义与 from_env 同构）。

    providers 缺失/为空 → ValueError；models[0] 为默认模型。
    """
    _load_env(ENV_PATH)
    from llm import LLMConfig
    from llm.config import ProviderConfig

    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    providers: list[dict] = raw.get("providers", [])
    models: list[dict] = raw.get("models", [])
    if not providers:
        raise ValueError(
            "llm.json 中 providers 为空或缺失。"
            "请参照 SpecModule config.example.json 配置 ~/.figureagent/llm.json。"
        )
    providers_map: dict[str, ProviderConfig] = {}
    for i, entry in enumerate(providers):
        pname = entry.get("name", "") or f"provider_{i}"
        if pname in providers_map:
            raise ValueError(f"llm.json providers 名重复: {pname!r}")
        key_env = entry.get("api_key_env", "")
        providers_map[pname] = ProviderConfig(
            name=pname,
            sdktype=entry.get("sdktype", "openai"),
            api_key=os.environ.get(key_env, "") if key_env else "",
            base_url=entry.get("base_url"),
            timeout=float(entry.get("timeout", 60.0)),
            max_retries=int(entry.get("max_retries", 3)),
        )
    default_pc = providers_map[providers[0].get("name", "") or "provider_0"]

    models_map: dict[str, dict] = {}
    default_model = ""
    default_temperature = 0.7
    default_max_tokens = 4096
    for m in models:
        name = m.get("name", "")
        if name:
            models_map[name] = m
        if not default_model:
            default_model = name
            default_temperature = float(m.get("temperature", 0.7))
            default_max_tokens = int(m.get("max_tokens", 4096))

    return LLMConfig(
        provider=default_pc.sdktype,
        api_key=default_pc.api_key,
        base_url=default_pc.base_url,
        timeout=default_pc.timeout,
        max_retries=default_pc.max_retries,
        model=default_model,
        max_tokens=default_max_tokens,
        temperature=default_temperature,
        models=models_map,
        providers=providers_map,
    )


def ai_status() -> dict:
    """LLM 配置状态（AI 面板徽标）。"""
    if fig_config.mock_enabled():
        return {"configured": True, "provider": "mock", "model": "mock", "mock": True}
    try:
        cfg = load_config()
    except Exception as exc:
        return {
            "configured": False,
            "provider": "",
            "model": "",
            "mock": False,
            "detail": f"{type(exc).__name__}: {exc}",
        }
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
    if fig_config.mock_enabled():
        from llm.mock import MockLLMClient

        return MockLLMClient()
    if _client is None:
        from llm import create_llm_client

        _client = create_llm_client(load_config())
    return _client
