"""ai.prompts：占位符结构守卫（每个 core+CONTRACT 的占位符集合必须精确）。"""

from __future__ import annotations

import re

from figureagent.figures.ai import prompts

EXPECT = {
    "STANDARDIZE_CORE": {"data"},
    "GEN_CODE_CORE": {"profile", "requirements"},
    "ADAPT_CODE_CORE": {"profile", "requirements", "script_text"},
    "FIX_CODE_CORE": {"render"},
    "EDIT_CODE_CORE": {"code", "instruction", "selection"},
    "TRANSLATE_PATCH_CORE": {"material"},
}


def test_core_placeholders_exact():
    for name, want in EXPECT.items():
        core = getattr(prompts, name) + "\n\n" + prompts.CONTRACT
        got = set(re.findall(r"\{(\w+)\}", core))
        assert got == want | prompts.CONTRACT_PLACEHOLDERS, (name, sorted(got))


def test_role_keywords_present():
    """StubLLM 测试按这些角色词路由 prompt，改动措辞会静默破坏路由。"""
    for keyword in ("数据标准化专家", "绘图代码生成器", "绘图脚本改造器",
                    "绘图代码修复器", "绘图代码修改器", "微调回写器"):
        assert any(keyword in getattr(prompts, name)
                   for name in EXPECT), keyword
