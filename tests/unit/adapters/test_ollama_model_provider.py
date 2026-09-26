"""Coldline.

===================

File:              tests/unit/adapters/test_ollama_model_provider.py
Component:         Unit tests — Ollama adapter scaffold
Purpose:           Unit tests for the scaffold's supplied transport: construction and settings.
Interacts With:    One isolated source responsibility
Sprint/Task:       Sprint 3 — Project 3 / Task 3.11
Concepts:          Fast feedback, failure paths, settings boundary
Tools:             Python 3.12, pytest

These rows cover the part of the scaffold that is supplied and must stay as supplied; they
pass on a fresh checkout and keep passing after the three TODO parts are completed. What the
three parts must do is stated by the conformance tests under tests/contract/.
"""

import pytest

from adapters.model.ollama import (
    DEFAULT_URL,
    MODEL_SETTING,
    PROVIDER_LABEL,
    URL_SETTING,
    OllamaModelProvider,
)


@pytest.mark.asyncio
async def test_adapter_binds_one_endpoint_one_model_and_one_timeout() -> None:
    """The constructor keeps the endpoint without a trailing slash and the model as given."""
    adapter = OllamaModelProvider("http://127.0.0.1:11435/", "tiny-model", timeout_seconds=1.0)
    try:
        assert adapter.base_url == "http://127.0.0.1:11435"
        assert adapter.model == "tiny-model"
        assert PROVIDER_LABEL == "ollama"
    finally:
        await adapter.aclose()


@pytest.mark.parametrize(
    "base_url,model,timeout_seconds,message",
    [
        ("", "tiny-model", 1.0, "base_url"),
        ("http://127.0.0.1:11435", "  ", 1.0, "model"),
        ("http://127.0.0.1:11435", "tiny-model", 0.0, "timeout_seconds"),
    ],
    ids=["blank-endpoint", "blank-model", "zero-timeout"],
)
def test_adapter_refuses_a_blank_endpoint_a_blank_model_or_a_timeout_of_zero(
    base_url: str, model: str, timeout_seconds: float, message: str
) -> None:
    """A misconfigured adapter fails at construction, not on the first request."""
    with pytest.raises(ValueError, match=message):
        OllamaModelProvider(base_url, model, timeout_seconds=timeout_seconds)


@pytest.mark.asyncio
async def test_from_settings_reads_the_two_named_settings_and_defaults_the_endpoint() -> None:
    """The model is required; the endpoint defaults to the one Ollama serves on."""
    adapter = OllamaModelProvider.from_settings({MODEL_SETTING: "tiny-model"})
    try:
        assert adapter.base_url == DEFAULT_URL
        assert adapter.model == "tiny-model"
    finally:
        await adapter.aclose()

    named = OllamaModelProvider.from_settings(
        {URL_SETTING: "http://127.0.0.1:11435/", MODEL_SETTING: "tiny-model"}
    )
    try:
        assert named.base_url == "http://127.0.0.1:11435"
    finally:
        await named.aclose()


def test_from_settings_refuses_a_missing_model() -> None:
    """Without the model setting there is nothing to ask Ollama for."""
    with pytest.raises(ValueError, match=MODEL_SETTING):
        OllamaModelProvider.from_settings({URL_SETTING: "http://127.0.0.1:11435"})
