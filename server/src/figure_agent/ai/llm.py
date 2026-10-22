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
