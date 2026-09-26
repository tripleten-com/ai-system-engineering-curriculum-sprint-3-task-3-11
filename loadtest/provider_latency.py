"""Coldline.

===================

File:              loadtest/provider_latency.py
Component:         Load test — Provider latency harness (Task 3.11)
Purpose:           Send the pinned request set to one ModelProvider; record latency and errors.
Interacts With:    The emulator, the Ollama adapter, the recorded fixture adapter,
                    infra/provider-fixtures/hosted-recorded.jsonl, docs/student/providers/
Sprint/Task:       Sprint 3 — Project 3 / Task 3.11
Concepts:          Latency percentiles, error classes, generated evidence, content digest
Tools:             Python 3.12, asyncio, httpx

``poe provider-latency --provider <name>`` is the whole measurement. It builds one adapter,
sends it the pinned request set (the same twenty requests for every provider, one after
another, through the adapter alone with no resilient wrapper), and writes
``docs/student/providers/<name>-latency.json``: the provider label, the number of requests,
the p50 and p95 latency in whole milliseconds over the requests that returned a summary,
and the number that failed as retryable and as terminal. The file carries a generator
marker and a content digest that the contract checks recompute; never edit it, rerun.

- ``emulator``: the deterministic emulator the worker uses, with the worker's own delay
  setting (``COLDLINE_MODEL_LATENCY_MS`` from the shell or the local ``.env``, else the
  worker's default).
- ``hosted-fixture``: the recorded hosted provider, replayed from the fixture with each
  recorded latency; nothing leaves the machine.
- ``ollama``: the Ollama adapter against a real Ollama named by ``COLDLINE_OLLAMA_URL`` and
  ``COLDLINE_OLLAMA_MODEL`` (shell or local ``.env``). The harness first asks that endpoint
  to list its models and refuses one that lists none, which is what the supplied stub does:
  a ``ran`` Ollama figure comes from a real Ollama or not at all. Never part of CI.

A failure the adapter lets escape unclassified (anything but ``RetryableProviderError`` or
``TerminalProviderError``) stops the run: an adapter whose Step 2 is incomplete has no
error counts to record.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from adapters.model.deterministic import DeterministicModelProvider
from adapters.model.ollama import MODEL_SETTING, URL_SETTING, OllamaModelProvider
from adapters.model.recorded import RecordedModelProvider, RecordingError
from domain.contracts import ModelRequest, ModelSummary
from domain.errors import RetryableProviderError, TerminalProviderError
from ports import ModelProvider
from worker.config import WorkerSettings

TASK_ROOT = Path(__file__).resolve().parents[1]
LATENCY_DIR = TASK_ROOT / "docs/student/providers"
FIXTURE_PATH = TASK_ROOT / "infra/provider-fixtures/hosted-recorded.jsonl"
GENERATOR = "poe provider-latency"
SCHEMA = "coldline-provider-latency/1"
PROVIDERS = ("emulator", "ollama", "hosted-fixture")
REQUEST_COUNT = 20
EMULATOR_LATENCY_SETTING = "COLDLINE_MODEL_LATENCY_MS"
# Generous on purpose: the first requests to a freshly started Ollama load the model, and
# the lesson asks for them to be recorded as they were rather than cut off.
OLLAMA_TIMEOUT_SECONDS = 60.0
TAGS_PATH = "/api/tags"
LATENCY_OVER = "successful_requests"
# An error message from the transport can quote the endpoint it was sent to. The file is
# committed and the endpoint is the student's own, so every URL in a recorded detail is
# replaced before the file is written; the contract check refuses a latency file that
# carries one.
URL_PATTERN = re.compile(r"https?://[^\s'\"`)<>]+")
REDACTED_ENDPOINT = "<endpoint>"


class HarnessError(RuntimeError):
    """Report one actionable failure of the harness without a stack trace."""


@dataclass(frozen=True)
class Observation:
    """Record one request's outcome and how long the adapter took to produce it."""

    sequence: int
    exception_id: str
    outcome: str
    latency_ms: float
    detail: str


# --- the pinned request set -------------------------------------------------------------------


def pinned_requests() -> tuple[ModelRequest, ...]:
    """Return the twenty requests every provider is sent, alternating above and below."""
    requests: list[ModelRequest] = []
    for index in range(1, REQUEST_COUNT + 1):
        above = index % 2 == 1
        step = (index % 5) + 1
        temperature = 8.0 + 0.4 * step if above else 2.0 - 0.3 * step
        requests.append(
            ModelRequest(
                exception_id=f"exc-latency-{index:03d}",
                shipment_id=f"shipment-latency-{index:03d}",
                temperature_c=round(temperature, 1),
                allowed_min_c=2.0,
                allowed_max_c=8.0,
            )
        )
    return tuple(requests)


# --- host configuration -------------------------------------------------------------------


def _dotenv_values(path: Path) -> dict[str, str]:
    """Read the simple key-value form used by this Task's local `.env` file."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def settings() -> dict[str, str]:
    """Return the local `.env` values with the shell's own on top, as Docker Compose does."""
    return {**_dotenv_values(TASK_ROOT / ".env"), **os.environ}


def worker_defaults() -> tuple[int, int]:
    """Return the worker's default emulator delay and per-attempt timeout, in milliseconds."""
    fields = WorkerSettings.model_fields
    return int(fields["model_latency_ms"].default), int(fields["model_timeout_ms"].default)


# --- the three providers ------------------------------------------------------------------


def emulator_latency_ms(values: dict[str, str]) -> int:
    """Return the emulator delay the run uses: the worker's setting, or its default."""
    default, _ = worker_defaults()
    raw = values.get(EMULATOR_LATENCY_SETTING)
    if raw is None:
        return default
    try:
        latency = int(raw)
    except ValueError as exc:
        raise HarnessError(f"{EMULATOR_LATENCY_SETTING} must be a whole number of ms") from exc
    if latency < 0:
        raise HarnessError(f"{EMULATOR_LATENCY_SETTING} must not be negative")
    return latency


def require_model_listed(base_url: str, model: str) -> None:
    """Refuse an endpoint that is not a real Ollama with the named model pulled."""
    try:
        response = httpx.get(f"{base_url}{TAGS_PATH}", timeout=5.0)
    except httpx.HTTPError as exc:
        raise HarnessError(
            f"no Ollama answered at {URL_SETTING}: {exc}. Install and start Ollama, or record "
            "the run as not_run"
        ) from exc
    if response.status_code != 200:
        raise HarnessError(
            f"the endpoint at {URL_SETTING} answered {response.status_code} on {TAGS_PATH} and "
            "lists no models; the supplied stub never does. Point it at a real Ollama, never "
            "at the stub"
        )
    try:
        listed = response.json().get("models", [])
    except (ValueError, AttributeError) as exc:
        raise HarnessError(
            f"the endpoint at {URL_SETTING} lists models in a shape Ollama does not"
        ) from exc
    names = {
        str(entry.get(key))
        for entry in listed
        if isinstance(entry, dict)
        for key in ("name", "model")
        if entry.get(key)
    }
    if model not in names and f"{model}:latest" not in names:
        raise HarnessError(
            f"{MODEL_SETTING}={model!r} is not pulled into this Ollama; it lists "
            f"{', '.join(sorted(names)) or 'nothing'}. Pull the model, or name one it lists"
        )


def build_provider(
    name: str, values: dict[str, str]
) -> tuple[ModelProvider, dict[str, Any], Callable[[], Awaitable[None]] | None]:
    """Return the adapter for one provider name, its recorded settings, and a closer."""
    if name == "emulator":
        latency = emulator_latency_ms(values)
        return (
            DeterministicModelProvider(latency_ms=latency),
            {"latency_ms": latency, "latency_setting": EMULATOR_LATENCY_SETTING},
            None,
        )
    if name == "hosted-fixture":
        try:
            recorded = RecordedModelProvider.load(FIXTURE_PATH)
        except RecordingError as exc:
            raise HarnessError(str(exc)) from exc
        source = recorded.source
        if source.request_count != REQUEST_COUNT:
            raise HarnessError(
                f"the recording answers {source.request_count} requests; the pinned set has "
                f"{REQUEST_COUNT}"
            )
        return (
            recorded,
            {
                "recording": FIXTURE_PATH.relative_to(TASK_ROOT).as_posix(),
                "source_provider": source.provider,
                "source_model": source.model,
                "source_recorded_at": source.recorded_at,
            },
            None,
        )
    if name == "ollama":
        try:
            ollama = OllamaModelProvider.from_settings(
                values, timeout_seconds=OLLAMA_TIMEOUT_SECONDS
            )
        except ValueError as exc:
            raise HarnessError(
                f"{exc}; set {URL_SETTING} and {MODEL_SETTING} in the shell or the local .env"
            ) from exc
        require_model_listed(ollama.base_url, ollama.model)
        # The endpoint is deliberately not recorded: the file is committed, the URL is yours.
        return (
            ollama,
            {"model": ollama.model, "timeout_seconds": OLLAMA_TIMEOUT_SECONDS},
            ollama.aclose,
        )
    raise HarnessError(f"unknown provider {name!r}; choose one of {', '.join(PROVIDERS)}")


# --- the measurement -------------------------------------------------------------------------


def redact(detail: str) -> str:
    """Return one recorded detail with every URL in it replaced, and on one line."""
    return " ".join(URL_PATTERN.sub(REDACTED_ENDPOINT, detail).split())


async def measure(provider: ModelProvider, requests: tuple[ModelRequest, ...]) -> list[Observation]:
    """Send every request in order and record each outcome with its latency."""
    observations: list[Observation] = []
    for sequence, request in enumerate(requests, start=1):
        started = time.perf_counter()
        outcome = "ok"
        detail = ""
        try:
            summary = await provider.summarize(request)
        except RetryableProviderError as exc:
            outcome, detail = "retryable", redact(str(exc))
        except TerminalProviderError as exc:
            outcome, detail = "terminal", redact(str(exc))
        except RecordingError as exc:
            raise HarnessError(str(exc)) from exc
        except Exception as exc:
            raise HarnessError(
                f"the provider let {type(exc).__name__} escape unclassified on request "
                f"{sequence} ({exc}); every failure must reach the harness as "
                "RetryableProviderError or TerminalProviderError (Step 2)"
            ) from exc
        else:
            if not isinstance(summary, ModelSummary) or not summary.summary.strip():
                raise HarnessError(
                    f"the provider returned an empty summary for request {sequence}; a reply "
                    "with no text is malformed, not a summary"
                )
            detail = summary.provider
        latency_ms = (time.perf_counter() - started) * 1000
        observation = Observation(sequence, request.exception_id, outcome, latency_ms, detail)
        observations.append(observation)
        print(
            f"request {sequence:>2}  {outcome:<9}  {latency_ms:8.1f} ms  "
            + (f"({detail})" if outcome != "ok" else ""),
            flush=True,
        )
    return observations


def percentile(values: list[float], fraction: float) -> float:
    """Return the nearest-rank percentile of the values."""
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def digest(summary: dict[str, Any]) -> str:
    """Return the content digest of a summary, over everything but the digest itself.

    ``tests/contract/provider_contract.py`` recomputes this from the committed file exactly
    the same way; the two must stay identical.
    """
    body = {key: value for key, value in summary.items() if key != "digest"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_summary(
    name: str, observations: list[Observation], recorded_settings: dict[str, Any]
) -> dict[str, Any]:
    """Assemble the file the checks read; the digest is added last."""
    successes = [entry.latency_ms for entry in observations if entry.outcome == "ok"]
    if not successes:
        raise HarnessError(
            f"no request to {name} returned a summary, so there is no latency to record; "
            "nothing was written"
        )
    _, timeout_ms = worker_defaults()
    summary: dict[str, Any] = {
        "generator": GENERATOR,
        "schema": SCHEMA,
        "provider": name,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "request_count": len(observations),
        "successful_requests": len(successes),
        "retryable_errors": sum(1 for entry in observations if entry.outcome == "retryable"),
        "terminal_errors": sum(1 for entry in observations if entry.outcome == "terminal"),
        "p50_ms": int(round(percentile(successes, 0.50))),
        "p95_ms": int(round(percentile(successes, 0.95))),
        "latency_over": LATENCY_OVER,
        "worker_per_attempt_timeout_ms": timeout_ms,
        "settings": recorded_settings,
        "requests": [
            {**asdict(entry), "latency_ms": round(entry.latency_ms, 1)} for entry in observations
        ],
    }
    summary["digest"] = digest(summary)
    return summary


def latency_path(name: str) -> Path:
    """Return where the harness writes one provider's file."""
    return LATENCY_DIR / f"{name}-latency.json"


async def run(name: str) -> Path:
    """Run the harness against one provider and write its file."""
    provider, recorded_settings, closer = build_provider(name, settings())
    try:
        print(f"provider {name}: sending {REQUEST_COUNT} pinned requests", flush=True)
        observations = await measure(provider, pinned_requests())
    finally:
        if closer is not None:
            await closer()
    summary = build_summary(name, observations, recorded_settings)
    path = latency_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"wrote {path.relative_to(TASK_ROOT).as_posix()}: {summary['request_count']} requests, "
        f"p50 {summary['p50_ms']} ms, p95 {summary['p95_ms']} ms, "
        f"{summary['retryable_errors']} retryable, {summary['terminal_errors']} terminal",
        flush=True,
    )
    return path


def main(argv: list[str] | None = None) -> int:
    """Run the harness for one provider from the command line."""
    parser = argparse.ArgumentParser(description="Measure one ModelProvider's latency.")
    parser.add_argument("--provider", required=True, choices=PROVIDERS)
    args = parser.parse_args(argv)
    try:
        asyncio.run(run(args.provider))
    except HarnessError as exc:
        print(f"provider latency failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("provider latency interrupted; nothing was written", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
