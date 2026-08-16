"""Tests for MemoryEnhancer."""

from __future__ import annotations

import pytest
from modules.llm.memory_enhancer import MemoryEnhancer


@pytest.fixture
def enhancer() -> MemoryEnhancer:
    return MemoryEnhancer()


def test_extract_names(enhancer: MemoryEnhancer):
    names = enhancer.extract_names("My name is Alexander and I'm a developer")
    assert "Alexander" in names


def test_extract_preferences(enhancer: MemoryEnhancer):
    prefs = enhancer.extract_preferences("I prefer dark mode and I like Python")
    assert len(prefs) >= 1


def test_extract_facts(enhancer: MemoryEnhancer):
    facts = enhancer.extract_facts("Python is a programming language")
    assert len(facts) >= 1


def test_extract_all(enhancer: MemoryEnhancer):
    result = enhancer.extract_all("My name is Bob. I prefer chocolate.")
    assert "facts" in result
    assert "preferences" in result
    assert "names" in result
    assert "Bob" in result["names"]
