"""Coldline.

===================

File:              tests/unit/adapters/test_recorded_model_provider.py
Component:         Unit tests — Recorded model provider
Purpose:           Unit tests for loading and replaying one hosted provider recording.
Interacts With:    One isolated source responsibility
Sprint/Task:       Sprint 3 — Project 3 / Task 3.11
Concepts:          Fast feedback, failure paths, replayed evidence
Tools:             Python 3.12, pytest
"""

import json
from pathlib import Path

import pytest

from adapters.model.recorded import (
    PROVIDER_LABEL,
    RecordedModelProvider,
    RecordingError,
    load_recording,
)
from domain.contracts import ModelRequest
from domain.errors import RetryableProviderError, TerminalProviderError

HEADER = {
    "kind": "recording",
    "provider": "Fictional API",
    "model": "fictional-1",
    "recorded_at": "2026-08-14T15:20:00Z",
    "request_count": 3,
}
REPLIES = [
    {"sequence": 1, "shipment_id": "s-1", "status": 200, "latency_ms": 5, "response": "one"},
    {"sequence": 2, "shipment_id": "s-2", "status": 503, "latency_ms": 7, "error": "busy"},
    {"sequence": 3, "shipment_id": "s-3", "status": 400, "latency_ms": 2, "error": "bad"},
]


def _request(shipment_id: str) -> ModelRequest:
    """Build one request for the given shipment."""
    return ModelRequest(
        exception_id=f"exc-{shipment_id}",
        shipment_id=shipment_id,
        temperature_c=9.0,
        allowed_min_c=2.0,
        allowed_max_c=8.0,
    )


def _write(path: Path, lines: list[dict[str, object]]) -> Path:
    """Write one JSON Lines recording."""
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    return path


async def _no_sleep(_seconds: float) -> None:
    """Replace the recorded waits so replay tests run instantly."""


def test_load_recording_reads_the_source_and_every_reply(tmp_path: Path) -> None:
    """The header names the source and each reply keeps its status, latency, and text."""
    source, replies = load_recording(_write(tmp_path / "r.jsonl", [HEADER, *REPLIES]))

    assert (source.provider, source.model) == ("Fictional API", "fictional-1")
    assert source.request_count == 3
    assert [reply.status for reply in replies] == [200, 503, 400]
    assert replies[0].response == "one" and replies[1].error == "busy"


@pytest.mark.parametrize(
    "lines,message",
    [
        ([], "empty"),
        ([{"kind": "other"}], "kind"),
        ([{**HEADER, "request_count": 2}, *REPLIES], "announces 2 replies"),
        ([HEADER, REPLIES[0], {**REPLIES[1], "sequence": 3}, REPLIES[2]], "sequence must run"),
        ([HEADER, {**REPLIES[0], "status": 302}, *REPLIES[1:]], "status must be 200"),
        ([HEADER, {**REPLIES[0], "response": ""}, *REPLIES[1:]], "non-empty response"),
        ([HEADER, {**REPLIES[0], "latency_ms": -1}, *REPLIES[1:]], "not be negative"),
    ],
    ids=["empty", "wrong-kind", "count", "sequence-gap", "odd-status", "blank", "negative"],
)
def test_a_recording_that_cannot_be_replayed_is_refused(
    tmp_path: Path, lines: list[dict[str, object]], message: str
) -> None:
    """A malformed recording fails to load with a reason, rather than replaying nonsense."""
    with pytest.raises(RecordingError, match=message):
        load_recording(_write(tmp_path / "r.jsonl", lines))


@pytest.mark.asyncio
async def test_replay_returns_the_recorded_text_and_raises_the_recorded_errors(
    tmp_path: Path,
) -> None:
    """A 200 replays as a labelled summary, a 5xx as retryable, a 4xx as terminal."""
    provider = RecordedModelProvider.load(
        _write(tmp_path / "r.jsonl", [HEADER, *REPLIES]), sleep=_no_sleep
    )

    summary = await provider.summarize(_request("s-1"))
    assert summary.summary == "one" and summary.provider == PROVIDER_LABEL
    with pytest.raises(RetryableProviderError, match="busy"):
        await provider.summarize(_request("s-2"))
    with pytest.raises(TerminalProviderError, match="bad"):
        await provider.summarize(_request("s-3"))
    assert provider.replies_left == 0


@pytest.mark.asyncio
async def test_replay_refuses_a_request_the_recording_did_not_answer(tmp_path: Path) -> None:
    """A request out of the recorded order is a harness fault, not a provider error."""
    provider = RecordedModelProvider.load(
        _write(tmp_path / "r.jsonl", [HEADER, *REPLIES]), sleep=_no_sleep
    )

    with pytest.raises(RecordingError, match="s-1"):
        await provider.summarize(_request("s-9"))


@pytest.mark.asyncio
async def test_replay_stops_when_the_recording_is_exhausted(tmp_path: Path) -> None:
    """A twenty-first request against a twenty-reply recording is refused loudly."""
    provider = RecordedModelProvider.load(
        _write(tmp_path / "r.jsonl", [{**HEADER, "request_count": 1}, REPLIES[0]]),
        sleep=_no_sleep,
    )
    await provider.summarize(_request("s-1"))

    with pytest.raises(RecordingError, match="every one has been replayed"):
        await provider.summarize(_request("s-1"))


@pytest.mark.asyncio
async def test_replay_waits_the_recorded_latency(tmp_path: Path) -> None:
    """Each reply waits its own recorded latency before answering."""
    waited: list[float] = []

    async def record(seconds: float) -> None:
        waited.append(seconds)

    provider = RecordedModelProvider.load(
        _write(tmp_path / "r.jsonl", [HEADER, *REPLIES]), sleep=record
    )
    await provider.summarize(_request("s-1"))

    assert waited == [0.005]
