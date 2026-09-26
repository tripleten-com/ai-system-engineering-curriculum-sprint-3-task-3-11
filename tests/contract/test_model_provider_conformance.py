"""Coldline.

===================

File:              tests/contract/test_model_provider_conformance.py
Component:         Contract tests — ModelProvider conformance
Purpose:           State what any ModelProvider must do, and run it against every adapter.
Interacts With:    src/adapters/model/deterministic.py, src/adapters/model/ollama.py,
                    src/adapters/model/resilient.py, tests/doubles/ollama_stub.py
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Port conformance, boundary translation, failure classification
Tools:             Python 3.12, pytest, httpx

One suite, two adapters. The port-level rows run against both the emulator and the Ollama
adapter pointed at the supplied stub, which `poe conformance` starts and stops itself. The
transport rows (the request body, and the classification of each failure the stub can
produce) run against the Ollama adapter alone: the emulator has no transport and no
backend to fail, so there is nothing of it to classify. Nothing here calls a real model.
`poe contract` skips this whole module because it is marked `assessed`; `poe conformance`,
`poe provider-contract`, and `poe verify` run it.
"""

import json
import socket
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import pytest

from adapters.model import DeterministicModelProvider, ResilientModelProvider
from adapters.model.ollama import PROVIDER_LABEL, OllamaModelProvider
from domain.contracts import ModelRequest, ModelSummary
from domain.errors import ProviderError, RetryableProviderError, TerminalProviderError
from ports import ModelProvider
from tests.doubles.ollama_stub import STUB_MODEL, OllamaStub

pytestmark = [pytest.mark.assessed]

REQUEST = ModelRequest(
    exception_id="exc-conformance-001",
    shipment_id="shipment-conformance-001",
    temperature_c=9.2,
    allowed_min_c=2.0,
    allowed_max_c=8.0,
)
# Shorter than the stub's stall, so the adapter's own timeout is what ends a stalled call.
ADAPTER_TIMEOUT_SECONDS = 0.5
# Long enough that a refused connection is reported as refused. Windows retries a refused
# localhost connect for about two seconds, so under the short timeout above a refusal there
# surfaces as a connect timeout and this row would test timeout handling instead.
REFUSED_CONNECTION_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Subject:
    """Name one adapter under test and the label its summaries must carry."""

    name: str
    provider: ModelProvider
    label: str


@pytest.fixture(scope="module")
def stub() -> Iterator[OllamaStub]:
    """Start the supplied stub once for the module and stop it afterwards."""
    server = OllamaStub()
    server.start()
    yield server
    server.stop()


@pytest.fixture(autouse=True)
def _clean_stub(stub: OllamaStub) -> None:
    """Forget recorded requests and queued failures before every test."""
    stub.reset()


@pytest.fixture
async def ollama(stub: OllamaStub) -> AsyncIterator[OllamaModelProvider]:
    """Return the Ollama adapter pointed at the stub, and release its client afterwards."""
    adapter = OllamaModelProvider(
        stub.base_url, STUB_MODEL, timeout_seconds=ADAPTER_TIMEOUT_SECONDS
    )
    try:
        yield adapter
    finally:
        await adapter.aclose()


@pytest.fixture(params=["emulator", "ollama"])
async def subject(request: pytest.FixtureRequest, stub: OllamaStub) -> AsyncIterator[Subject]:
    """Return each adapter in turn for the rows every ModelProvider must pass."""
    if request.param == "emulator":
        yield Subject("emulator", DeterministicModelProvider(latency_ms=0), "deterministic-local")
    else:
        adapter = OllamaModelProvider(
            stub.base_url, STUB_MODEL, timeout_seconds=ADAPTER_TIMEOUT_SECONDS
        )
        try:
            yield Subject("ollama", adapter, PROVIDER_LABEL)
        finally:
            await adapter.aclose()


async def _summary_of(subject: Subject) -> ModelSummary:
    """Call one adapter once and turn any exception into a readable failure."""
    try:
        return await subject.provider.summarize(REQUEST)
    except Exception as exc:
        pytest.fail(
            f"a successful call to the {subject.name} adapter raised {type(exc).__name__}: {exc}"
        )


async def _expect(provider: ModelProvider, expected: type[ProviderError], *, kind: str) -> None:
    """Call the adapter once and require exactly the expected error class."""
    try:
        summary = await provider.summarize(REQUEST)
    except expected:
        return
    except (RetryableProviderError, TerminalProviderError) as exc:
        pytest.fail(
            f"{kind}: the adapter raised {type(exc).__name__}, not {expected.__name__}: {exc}"
        )
    except Exception as exc:
        pytest.fail(
            f"{kind}: {type(exc).__name__} escaped the adapter unclassified ({exc}); every "
            "failure must be raised as RetryableProviderError or TerminalProviderError"
        )
    pytest.fail(
        f"{kind}: the call returned a summary ({summary.summary[:60]!r}) instead of raising "
        f"{expected.__name__}"
    )


def _closed_port() -> int:
    """Return a loopback port nothing is listening on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


# --- what every ModelProvider must do -----------------------------------------------------


async def test_adapter_satisfies_the_model_provider_port(subject: Subject) -> None:
    """The adapter is a ModelProvider: one `summarize` taking a ModelRequest."""
    assert isinstance(subject.provider, ModelProvider), (
        f"the {subject.name} adapter does not satisfy the ModelProvider port"
    )


async def test_a_successful_call_returns_a_non_empty_summary_with_the_adapters_own_label(
    subject: Subject,
) -> None:
    """A successful call returns a ModelSummary with text, labelled with the adapter's name."""
    summary = await _summary_of(subject)
    assert isinstance(summary, ModelSummary), "summarize must return a ModelSummary"
    assert summary.summary.strip(), "the summary must not be empty"
    assert summary.provider == subject.label, (
        f"the provider label must be the adapter's own name {subject.label!r}, not "
        f"{summary.provider!r}; a label copied from a reply changes whenever the model does"
    )


async def test_the_summary_names_the_shipment_it_was_asked_about(subject: Subject) -> None:
    """The summary is about the request: it names the shipment the request named."""
    summary = await _summary_of(subject)
    assert REQUEST.shipment_id in summary.summary, (
        f"the summary does not name {REQUEST.shipment_id}; the request the adapter sends "
        "must carry the shipment for the provider to write about it"
    )


# --- what the Ollama transport must send ---------------------------------------------------


async def test_the_request_body_carries_the_model_the_stream_flag_and_every_field_of_the_request(
    ollama: OllamaModelProvider, stub: OllamaStub
) -> None:
    """The body names the model, sets stream to false, and carries every request value."""
    try:
        await ollama.summarize(REQUEST)
    except Exception:
        # The body was sent before the reply could fail; the reply is another row's concern.
        pass
    assert stub.requests, "no request reached the stub"
    body = stub.requests[-1]
    problems: list[str] = []
    if "raw" in body:
        problems.append("the body is not a JSON object")
    if body.get("model") != STUB_MODEL:
        problems.append(f"model must be the adapter's model name {STUB_MODEL!r}")
    if body.get("stream") is not False:
        problems.append("stream must be false, so the reply is one JSON object, not fragments")
    text = json.dumps(body)
    for field_name, value in REQUEST.model_dump().items():
        if str(value) not in text:
            problems.append(f"the body does not carry {field_name} ({value})")
    assert problems == [], "\n".join(problems)


# --- what the Ollama adapter must raise ------------------------------------------------------


async def test_a_refused_connection_is_raised_as_retryable(stub: OllamaStub) -> None:
    """A connection nothing accepts is the provider being down: retryable."""
    adapter = OllamaModelProvider(
        f"http://127.0.0.1:{_closed_port()}",
        STUB_MODEL,
        timeout_seconds=REFUSED_CONNECTION_TIMEOUT_SECONDS,
    )
    try:
        await _expect(adapter, RetryableProviderError, kind="a refused connection")
    finally:
        await adapter.aclose()


async def test_a_dropped_connection_is_raised_as_retryable(
    ollama: OllamaModelProvider, stub: OllamaStub
) -> None:
    """A connection closed without a reply is the provider failing mid-call: retryable."""
    stub.fail_next("drop")
    await _expect(ollama, RetryableProviderError, kind="a dropped connection")


async def test_a_timeout_is_raised_as_retryable(
    ollama: OllamaModelProvider, stub: OllamaStub
) -> None:
    """A reply that does not arrive within the per-request timeout is retryable."""
    stub.fail_next("timeout")
    await _expect(ollama, RetryableProviderError, kind="a timeout")


async def test_a_server_error_is_raised_as_retryable(
    ollama: OllamaModelProvider, stub: OllamaStub
) -> None:
    """A 5xx status is the provider being overloaded or broken for now: retryable."""
    stub.fail_next("server_error")
    await _expect(ollama, RetryableProviderError, kind="a 503 reply")


async def test_a_rejected_request_is_raised_as_terminal(
    ollama: OllamaModelProvider, stub: OllamaStub
) -> None:
    """A 4xx status means the request itself is wrong; no attempt will fix it: terminal."""
    stub.fail_next("client_error")
    await _expect(ollama, TerminalProviderError, kind="a 400 reply")


async def test_a_reply_that_is_not_json_is_raised_as_terminal(
    ollama: OllamaModelProvider, stub: OllamaStub
) -> None:
    """A 200 reply whose body is not JSON is not the generate contract: terminal."""
    stub.fail_next("not_json")
    await _expect(ollama, TerminalProviderError, kind="a reply that is not JSON")


async def test_a_reply_without_a_response_field_is_raised_as_terminal(
    ollama: OllamaModelProvider, stub: OllamaStub
) -> None:
    """A JSON reply with no `response` field is malformed: terminal, never an empty summary."""
    stub.fail_next("missing_response")
    await _expect(ollama, TerminalProviderError, kind="a reply without a response field")


async def test_an_empty_response_is_raised_as_terminal(
    ollama: OllamaModelProvider, stub: OllamaStub
) -> None:
    """A JSON reply whose `response` is empty is malformed: terminal, never an empty summary."""
    stub.fail_next("empty_response")
    await _expect(ollama, TerminalProviderError, kind="a reply with an empty response")


async def test_the_resilient_wrapper_retries_a_retryable_failure_and_stops_on_a_terminal_one(
    ollama: OllamaModelProvider, stub: OllamaStub
) -> None:
    """Through the worker's wrapper, one 503 is retried to success and one 400 ends at once."""
    wrapper = ResilientModelProvider(ollama, timeout_seconds=1.0, max_attempts=2, backoff_seconds=0)
    stub.fail_next("server_error")
    try:
        summary = await wrapper.summarize(REQUEST)
    except Exception as exc:
        pytest.fail(
            "one 503 followed by success must end in a summary through the wrapper; it raised "
            f"{type(exc).__name__}: {exc}"
        )
    assert summary.provider == PROVIDER_LABEL
    assert len(stub.requests) == 2, "the wrapper retries a retryable failure exactly once here"

    stub.reset()
    stub.fail_next("client_error")
    with pytest.raises(TerminalProviderError):
        await wrapper.summarize(REQUEST)
    assert len(stub.requests) == 1, (
        "a terminal failure spends no retry on a request that cannot succeed"
    )
