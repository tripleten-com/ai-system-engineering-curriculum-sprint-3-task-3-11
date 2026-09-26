"""Coldline.

===================

File:              tests/contract/test_provider_contract.py
Component:         Contract tests — Provider comparison
Purpose:           Check the scaffold boundary, the latency files, the answers, committed text.
Interacts With:    src/adapters/model/ollama.py, docs/student/providers/*.json, submission.yaml
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Scaffold boundary, generated evidence, field-for-field comparison, decision
Tools:             Python 3.12, pytest

Every check here is static: it reads the scaffold, the files `poe provider-latency` wrote,
the answer sheet, and the committed text. None of them runs the harness or calls a model,
and none reads the provider record: the record is the defense material. The conformance
tests beside this module exercise the adapter itself. `poe contract` skips this whole module
because it is marked `assessed`; `poe provider-checks`, `poe provider-contract`, and
`poe verify` run it.
"""

from typing import Any

import pytest

from tests.contract import provider_contract as provider

pytestmark = [pytest.mark.assessed]


@pytest.fixture(scope="module")
def answers() -> dict[str, Any]:
    """Load the recorded answers once."""
    return provider.load_answers()


@pytest.fixture(scope="module")
def latency() -> dict[str, dict[str, Any] | None]:
    """Load every provider's latency file once, as written, or None where it is absent."""
    return {name: provider.load_latency(name) for name in provider.PROVIDERS}


def test_only_the_three_todo_parts_of_the_scaffold_changed() -> None:
    """Outside its three TODO regions, the Ollama scaffold is exactly the supplied text."""
    problems = provider.scaffold_problems(
        provider.SCAFFOLD_PATH.read_text(encoding="utf-8"),
        provider.SCAFFOLD_REFERENCE.read_text(encoding="utf-8"),
    )
    assert problems == [], "\n".join(problems)


def test_emulator_and_hosted_fixture_latency_files_are_unedited_harness_output(
    latency: dict[str, dict[str, Any] | None],
) -> None:
    """Both Step 3 files exist and are exactly as `poe provider-latency` wrote them."""
    problems: list[str] = []
    for name in ("emulator", "hosted-fixture"):
        problems.extend(provider.latency_problems(latency[name], name))
    assert problems == [], "\n".join(problems)


def test_recorded_run_figures_match_their_latency_files_field_for_field(
    answers: dict[str, Any], latency: dict[str, dict[str, Any] | None]
) -> None:
    """answers.runs.emulator and answers.runs.hosted_fixture ran, with their files' figures."""
    runs = provider.mapping(answers, "runs")
    mismatches: list[str] = []
    for name in ("emulator", "hosted-fixture"):
        key = provider.RUN_KEYS[name]
        summary = latency[name]
        assert summary is not None, (
            f"{provider.latency_path(name).name} is missing; run "
            f"`poe provider-latency --provider {name}`"
        )
        block = provider.mapping(runs, key)
        if block.get("status") != "ran":
            mismatches.append(f"answers.runs.{key}.status must be ran; the harness wrote its file")
        mismatches.extend(provider.figure_mismatches(block, summary, key))
    assert mismatches == [], "\n".join(mismatches)


def test_ollama_run_is_recorded_with_its_file_or_as_not_run_without_one(
    answers: dict[str, Any], latency: dict[str, dict[str, Any] | None]
) -> None:
    """answers.runs.ollama is ran with a matching committed file, or not_run with none."""
    block = provider.mapping(provider.mapping(answers, "runs"), "ollama")
    status = block.get("status")
    summary = latency["ollama"]
    path = provider.latency_path("ollama")
    if status == "ran":
        assert summary is not None, (
            "answers.runs.ollama.status is ran, but docs/student/providers/ollama-latency.json "
            "is not committed; commit the file the harness wrote, or record not_run"
        )
        problems = provider.latency_problems(summary, "ollama")
        assert problems == [], "\n".join(problems)
        mismatches = provider.figure_mismatches(block, summary, "ollama")
        assert mismatches == [], "\n".join(mismatches)
    elif status == "not_run":
        missing = [name for name in provider.RUN_FIGURES if block.get(name) is not None]
        assert missing == [], (
            f"answers.runs.ollama is not_run, so its figures must be null; got {missing}"
        )
        assert not path.exists(), (
            "answers.runs.ollama is not_run, but docs/student/providers/ollama-latency.json is "
            "committed; a run that happened is recorded as ran, and one that did not leaves "
            "no file"
        )
    else:
        pytest.fail(
            f"answers.runs.ollama.status must be one of {', '.join(provider.STATUSES)}; "
            f"got {status!r}"
        )


def test_decision_holds_allowed_values_and_differs_between_primary_and_fallback(
    answers: dict[str, Any],
) -> None:
    """primary, fallback, and fallback_trigger are allowed values, and the note is bounded."""
    problems: list[str] = []
    for field_name in ("primary", "fallback"):
        if answers.get(field_name) not in provider.PROVIDER_CHOICES:
            problems.append(
                f"answers.{field_name} must be one of {', '.join(provider.PROVIDER_CHOICES)}"
            )
    if answers.get("primary") == answers.get("fallback"):
        problems.append("answers.primary and answers.fallback must name two different providers")
    if answers.get("fallback_trigger") not in provider.TRIGGERS:
        problems.append(f"answers.fallback_trigger must be one of {', '.join(provider.TRIGGERS)}")
    notes = answers.get("notes")
    if not isinstance(notes, str) or not notes.strip():
        problems.append("answers.notes must name the fixture's provider and the limits of the runs")
    elif len(notes) > provider.NOTES_MAX_LENGTH:
        problems.append(f"answers.notes must be at most {provider.NOTES_MAX_LENGTH} characters")
    assert problems == [], "\n".join(problems)


def test_no_api_key_or_local_endpoint_is_committed() -> None:
    """No permitted file carries a credential, an Ollama setting assignment, or an endpoint."""
    problems: list[str] = []
    scanned = [
        (provider.SUBMISSION_PATH, False),
        (provider.RECORD_PATH, True),
        (provider.SCAFFOLD_PATH, True),
    ]
    scanned.extend((provider.latency_path(name), False) for name in provider.PROVIDERS)
    for path, allow_loopback in scanned:
        if not path.is_file():
            continue
        problems.extend(
            provider.forbidden_content(
                path.read_text(encoding="utf-8"),
                path.relative_to(provider.TASK_ROOT).as_posix(),
                allow_loopback_urls=allow_loopback,
            )
        )
    assert problems == [], "\n".join(problems)
