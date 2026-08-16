"""Tests for ModelRouter."""

from __future__ import annotations

import pytest
from modules.llm.model_router import ModelRouter, TaskComplexity, ComplexityDetector, ModelProfile


def test_simple_detection():
    detector = ComplexityDetector()
    assert detector.detect("hello") == TaskComplexity.SIMPLE
    assert detector.detect("time") == TaskComplexity.SIMPLE
    assert detector.detect("привет") == TaskComplexity.SIMPLE


def test_complex_detection():
    detector = ComplexityDetector()
    assert detector.detect("implement a sorting algorithm in python") == TaskComplexity.COMPLEX
    assert detector.detect("debug this error in my code") == TaskComplexity.COMPLEX


def test_moderate_detection():
    detector = ComplexityDetector()
    assert detector.detect("what is machine learning and how does it work") == TaskComplexity.MODERATE


def test_router_no_models():
    router = ModelRouter()
    assert router.available_models == []


def test_router_register():
    router = ModelRouter()
    from unittest.mock import MagicMock
    backend = MagicMock()
    profile = ModelProfile(name="test", complexity=TaskComplexity.SIMPLE, speed=1.0, quality=0.5)
    router.register_model("test", backend, profile)
    assert "test" in router.available_models
    assert router.model_profiles["test"].name == "test"
