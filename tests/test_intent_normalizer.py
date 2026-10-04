import asyncio

import pytest

from mosaic_common.config import Settings
from services.intent.llm import LLMClient, LLMError
from services.intent.normalizer import merge, normalise_llm
from services.intent.rule_parser import parse


def test_llm_values_mapped_to_vocabulary():
    raw = {"category": ["Sari", "spaceship"], "occasion": ["marriage"], "material": ["pure cotton"], "colour": ["Navy Blue"],
           "season": "Summer", "budget_max": "2000", "gender": "Women", "category_explicit": True}
    norm, warn = normalise_llm(raw)
    assert norm["category"] == ["saree"] and norm["occasion"] == ["wedding"] and norm["material"] == ["cotton"]
    assert norm["colour"] == ["navy"] and norm["season"] == "summer" and norm["budget_max"] == 2000 and norm["gender"] == "women"
    assert any("spaceship" in w for w in warn)   # out-of-vocabulary values dropped, not trusted


def test_rules_win_for_numbers():
    rules = parse("kurta under 1500")
    norm, warn = normalise_llm({"category": ["kurta"], "budget_max": 15000, "category_explicit": True})
    m = merge(rules, norm, warn)
    assert m.budget_max == 1500 and m.parser == "llm+rules"


def test_disabled_llm_raises_so_caller_falls_back():
    c = LLMClient(Settings(llm_provider="none"))
    with pytest.raises(LLMError):
        asyncio.run(c.decompose("anything"))


def test_unreachable_llm_raises_llmerror():
    c = LLMClient(Settings(llm_provider="openai_compat", llm_base_url="http://127.0.0.1:9/v1", llm_timeout_s=0.5))
    with pytest.raises(LLMError):
        asyncio.run(c.decompose("cotton dress"))
