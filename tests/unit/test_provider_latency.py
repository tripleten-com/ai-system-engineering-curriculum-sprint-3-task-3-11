"""Coldline.

===================

File:              tests/unit/test_provider_latency.py
Component:         Unit tests — Provider latency harness
Purpose:           Unit tests for the pinned request set, the figures, and the supplied recording.
Interacts With:    loadtest/provider_latency.py, infra/provider-fixtures/hosted-recorded.jsonl
Sprint/Task:       Sprint 3 — Project 3 / Task 3.11
Concepts:          Fast feedback, percentiles, generated evidence, fixture consistency
Tools:             Python 3.12, pytest
"""

import pytest

from adapters.model.recorded import load_recording
from loadtest import provider_latency as harness


def test_pinned_request_set_is_twenty_distinct_excursions() -> None:
    """Twenty requests, each a distinct exception, alternating above and below the range."""
    requests = harness.pinned_requests()

    assert len(requests) == harness.REQUEST_COUNT == 20
    assert len({request.exception_id for request in requests}) == 20
    assert len({request.shipment_id for request in requests}) == 20
    for index, request in enumerate(requests, start=1):
        outside = request.temperature_c > request.allowed_max_c or (
            request.temperature_c < request.allowed_min_c
        )
        assert outside, f"request {index} is inside the handling range"
        assert (request.temperature_c > request.allowed_max_c) == (index % 2 == 1)


def test_the_supplied_recording_answers_the_pinned_request_set_in_order() -> None:
    """The fixture's replies name the pinned shipments, one each, in the harness's order."""
    source, replies = load_recording(harness.FIXTURE_PATH)

    assert source.request_count == harness.REQUEST_COUNT
    assert [reply.shipment_id for reply in replies] == [
        request.shipment_id for request in harness.pinned_requests()
    ]
    assert source.provider and source.model and source.recorded_at


def test_percentile_uses_the_nearest_rank() -> None:
    """p50 is the value half the requests finished within; p95 the value 95 of 100 did."""
    values = [float(value) for value in range(1, 21)]

    assert harness.percentile(values, 0.50) == 10.0
    assert harness.percentile(values, 0.95) == 19.0
    assert harness.percentile([7.0], 0.95) == 7.0


def test_summary_carries_whole_figures_error_counts_and_a_digest() -> None:
    """The file the checks read has whole-millisecond percentiles, both counts, and a digest."""
    observations = [
        harness.Observation(index, f"exc-{index}", "ok", 100.0 + index, "label")
        for index in range(1, 19)
    ]
    observations.append(harness.Observation(19, "exc-19", "retryable", 1800.0, "503"))
    observations.append(harness.Observation(20, "exc-20", "terminal", 20.0, "400"))

    summary = harness.build_summary("emulator", observations, {"latency_ms": 100})

    assert summary["request_count"] == 20 and summary["successful_requests"] == 18
    assert summary["retryable_errors"] == 1 and summary["terminal_errors"] == 1
    assert summary["p50_ms"] == 109 and summary["p95_ms"] == 118
    assert summary["digest"] == harness.digest(summary)
    edited = {**summary, "p95_ms": 117}
    assert harness.digest(edited) != summary["digest"]


def test_summary_needs_at_least_one_successful_request() -> None:
    """A run in which nothing answered has no latency to record and writes nothing."""
    observations = [harness.Observation(1, "exc-1", "retryable", 50.0, "refused")]

    with pytest.raises(harness.HarnessError, match="no request"):
        harness.build_summary("ollama", observations, {})


def test_recorded_error_details_carry_no_endpoint_url() -> None:
    """A transport message that quotes the endpoint is written with the URL replaced."""
    detail = "Server error '503' for url 'http://192.168.1.20:11434/api/generate'\nretry"

    redacted = harness.redact(detail)

    assert "192.168" not in redacted and "http" not in redacted
    assert redacted == f"Server error '503' for url '{harness.REDACTED_ENDPOINT}' retry"


def test_emulator_latency_follows_the_worker_setting_or_its_default() -> None:
    """The emulator run uses COLDLINE_MODEL_LATENCY_MS when set, else the worker's default."""
    default, _ = harness.worker_defaults()

    assert harness.emulator_latency_ms({}) == default
    assert harness.emulator_latency_ms({harness.EMULATOR_LATENCY_SETTING: "40"}) == 40
    with pytest.raises(harness.HarnessError, match="whole number"):
        harness.emulator_latency_ms({harness.EMULATOR_LATENCY_SETTING: "fast"})
    with pytest.raises(harness.HarnessError, match="negative"):
        harness.emulator_latency_ms({harness.EMULATOR_LATENCY_SETTING: "-1"})
