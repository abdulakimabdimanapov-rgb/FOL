"""Tests for BehavioralLearner."""

from __future__ import annotations

import pytest
from pathlib import Path
from modules.llm.behavioral_learner import BehavioralLearner


@pytest.fixture
def learner(tmp_path: Path) -> BehavioralLearner:
    return BehavioralLearner(data_path=tmp_path / "patterns.json")


@pytest.mark.asyncio
async def test_observe_command(learner: BehavioralLearner):
    await learner.observe_command("hello")
    assert learner.total_patterns >= 1
    assert "hello" in learner.session_commands


@pytest.mark.asyncio
async def test_command_frequency(learner: BehavioralLearner):
    for _ in range(5):
        await learner.observe_command("open safari")
    freq = await learner.get_frequent_commands()
    assert len(freq) == 1
    assert freq[0][0] == "open safari"
    assert freq[0][1] == 5


@pytest.mark.asyncio
async def test_topic_interests(learner: BehavioralLearner):
    await learner.observe_command("what is python programming")
    await learner.observe_command("python is great")
    topics = await learner.get_interesting_topics()
    assert any("python" in t[0] for t in topics)


@pytest.mark.asyncio
async def test_get_context(learner: BehavioralLearner):
    for _ in range(3):
        await learner.observe_command("help me")
    ctx = await learner.get_context()
    assert "help" in ctx.lower()


@pytest.mark.asyncio
async def test_persistence(tmp_path: Path):
    l1 = BehavioralLearner(data_path=tmp_path / "p.json")
    await l1.initialize()
    await l1.observe_command("test command")
    await l1.shutdown()

    l2 = BehavioralLearner(data_path=tmp_path / "p.json")
    await l2.initialize()
    assert l2.total_patterns >= 1
