"""Tests for PromptManager."""

from __future__ import annotations

import pytest
from pathlib import Path
from modules.llm.prompt_manager import PromptManager


@pytest.fixture
def pm(tmp_path: Path) -> PromptManager:
    return PromptManager(prompts_dir=tmp_path / "prompts")


@pytest.mark.asyncio
async def test_default_system_prompt(pm: PromptManager):
    prompt = await pm.get_system_prompt()
    assert "F.O.L." in prompt
    assert "JARVIS" in prompt


@pytest.mark.asyncio
async def test_custom_system_prompt(pm: PromptManager):
    await pm.set_system_prompt("Custom prompt")
    prompt = await pm.get_system_prompt()
    assert prompt == "Custom prompt"


@pytest.mark.asyncio
async def test_system_prompt_with_context(pm: PromptManager):
    prompt = await pm.get_system_prompt(user_context={"name": "Alexander", "language": "ru"})
    assert "Alexander" in prompt
    assert "ru" in prompt


@pytest.mark.asyncio
async def test_templates(pm: PromptManager):
    await pm.set_template("greeting", "Hello {name}!")
    result = await pm.render_template("greeting", variables={"name": "sir"})
    assert result == "Hello sir!"


@pytest.mark.asyncio
async def test_persistence(tmp_path: Path):
    pm1 = PromptManager(prompts_dir=tmp_path / "p")
    await pm1.initialize()
    await pm1.set_system_prompt("Persistent prompt")
    await pm1.shutdown()

    pm2 = PromptManager(prompts_dir=tmp_path / "p")
    await pm2.initialize()
    assert pm2.has_custom_prompt
