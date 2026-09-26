"""Coldline.

===================

File:              src/adapters/model/recorded.py
Component:         Adapter — Recorded hosted provider (replay)
Purpose:           Replay one hosted provider's recorded replies and latencies through the port.
Interacts With:    infra/provider-fixtures/hosted-recorded.jsonl, domain.contracts, domain.errors
Sprint/Task:       Sprint 3 — Project 3 / Task 3.11
Concepts:          Recorded fixture, replay, deterministic evidence
Tools:             Python 3.12, asyncio

The fixture adapter. It reads one recording (the first line names the provider and model
the recording came from; every later line is one reply with its latency) and answers the
harness's requests in the recorded order: it waits the recorded latency, then returns the
recorded text as a ``ModelSummary`` or raises the error class the recorded status maps to.
Nothing is sent anywhere. It refuses a request that is not the one the recording answered
at that position, so the harness's pinned request set and the recording cannot drift apart
without the run failing loudly.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard

from domain.contracts import ModelRequest, ModelSummary
from domain.errors import RetryableProviderError, TerminalProviderError

# The label every summary this adapter returns carries: the replayed recording, not the
# provider it was recorded from, is what answered.
PROVIDER_LABEL = "hosted-fixture"
RECORDING_KIND = "recording"


class RecordingError(RuntimeError):
    """Report a recording that cannot be replayed as it stands, or a request it never saw."""


@dataclass(frozen=True)
class RecordingSource:
    """Name what the recording came from, as its first line states."""

    provider: str
    model: str
    recorded_at: str
    request_count: int


@dataclass(frozen=True)
class RecordedReply:
    """Hold one recorded reply: the request it answered, its status, its latency, its text."""

    sequence: int
    shipment_id: str
    status: int
    latency_ms: int
    response: str
    error: str


def load_recording(path: Path) -> tuple[RecordingSource, tuple[RecordedReply, ...]]:
    """Read one JSON Lines recording and validate its shape before anything replays it."""
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as exc:
        raise RecordingError(f"the recording {path.name} cannot be read: {exc}") from exc
    if not lines:
        raise RecordingError(f"the recording {path.name} is empty")
    header = _json_object(lines[0], path, 1)
    if header.get("kind") != RECORDING_KIND:
        raise RecordingError(f"{path.name} line 1 must name kind {RECORDING_KIND!r}")
    request_count = header.get("request_count")
    if isinstance(request_count, bool) or not isinstance(request_count, int) or request_count < 1:
        raise RecordingError(f"{path.name} line 1 must carry a whole request_count")
    source = RecordingSource(
        provider=_text(header, "provider", path, 1),
        model=_text(header, "model", path, 1),
        recorded_at=_text(header, "recorded_at", path, 1),
        request_count=request_count,
    )
    replies: list[RecordedReply] = []
    for number, line in enumerate(lines[1:], start=2):
        entry = _json_object(line, path, number)
        sequence = entry.get("sequence")
        status = entry.get("status")
        latency = entry.get("latency_ms")
        if not (_is_whole(sequence) and _is_whole(status) and _is_whole(latency)):
            raise RecordingError(
                f"{path.name} line {number} must carry whole sequence, status, and latency_ms"
            )
        if sequence != len(replies) + 1:
            raise RecordingError(f"{path.name} line {number}: sequence must run 1, 2, 3, ...")
        if latency < 0:
            raise RecordingError(f"{path.name} line {number}: latency_ms must not be negative")
        if status == 200:
            response = _text(entry, "response", path, number)
            error = ""
        elif 400 <= status <= 599:
            response = ""
            error = _text(entry, "error", path, number)
        else:
            raise RecordingError(
                f"{path.name} line {number}: status must be 200 or a 4xx/5xx code; got {status}"
            )
        replies.append(
            RecordedReply(
                sequence=sequence,
                shipment_id=_text(entry, "shipment_id", path, number),
                status=status,
                latency_ms=latency,
                response=response,
                error=error,
            )
        )
    if len(replies) != request_count:
        raise RecordingError(
            f"{path.name} line 1 announces {request_count} replies; {len(replies)} follow"
        )
    return source, tuple(replies)


def _json_object(line: str, path: Path, number: int) -> dict[str, Any]:
    """Decode one recording line as a JSON object or say which line is not one."""
    try:
        loaded = json.loads(line)
    except ValueError as exc:
        raise RecordingError(f"{path.name} line {number} is not JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise RecordingError(f"{path.name} line {number} is not a JSON object")
    return loaded


def _text(entry: dict[str, Any], key: str, path: Path, number: int) -> str:
    """Return one required non-empty string field of a recording line."""
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RecordingError(f"{path.name} line {number} must carry a non-empty {key}")
    return value


def _is_whole(value: object) -> TypeGuard[int]:
    """Return whether one JSON value is a whole number (a bool is not)."""
    return isinstance(value, int) and not isinstance(value, bool)


class RecordedModelProvider:
    """Answer the recorded request set from a recording, in order, with its latencies."""

    def __init__(
        self,
        source: RecordingSource,
        replies: tuple[RecordedReply, ...],
        *,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        """Hold one loaded recording and accept an injectable clock for tests."""
        self._source = source
        self._replies = replies
        self._position = 0
        self._sleep = sleep or asyncio.sleep

    @classmethod
    def load(
        cls, path: Path, *, sleep: Callable[[float], Awaitable[None]] | None = None
    ) -> "RecordedModelProvider":
        """Load one recording from disk and return the adapter that replays it."""
        source, replies = load_recording(path)
        return cls(source, replies, sleep=sleep)

    @property
    def source(self) -> RecordingSource:
        """Return what the recording came from, as its first line states."""
        return self._source

    @property
    def replies_left(self) -> int:
        """Return how many recorded replies have not been replayed yet."""
        return len(self._replies) - self._position

    async def summarize(self, request: ModelRequest) -> ModelSummary:
        """Replay the next recorded reply for exactly the request it answered."""
        if self._position >= len(self._replies):
            raise RecordingError(
                f"the recording holds {len(self._replies)} replies and every one has been "
                f"replayed; no reply is left for {request.exception_id}"
            )
        reply = self._replies[self._position]
        self._position += 1
        if reply.shipment_id != request.shipment_id:
            raise RecordingError(
                f"reply {reply.sequence} answered {reply.shipment_id}, not "
                f"{request.shipment_id}; the recording and the pinned request set disagree"
            )
        await self._sleep(reply.latency_ms / 1000)
        if reply.status == 200:
            return ModelSummary(summary=reply.response, provider=PROVIDER_LABEL)
        detail = f"recorded reply {reply.sequence} answered {reply.status}: {reply.error}"
        if reply.status >= 500:
            raise RetryableProviderError(detail)
        raise TerminalProviderError(detail)
