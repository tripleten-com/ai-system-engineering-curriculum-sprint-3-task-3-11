"""Coldline.

===================

File:              tests/contract/test_submission.py
Component:         Contract tests — Test Submission
Purpose:           Tests for the public answer and path checks for this Task's submission.
Interacts With:    Published interfaces and repository boundaries
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Compatibility, ownership, export safety
Tools:             Python 3.12, pytest
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.contract.submission_validation import (
    SubmissionError,
    _load_one_document,
    main,
    validate_changed_paths,
    validate_submission,
)

ROOT = Path(__file__).parents[2]
SCHEMA = ROOT / "docs/contracts/submission.schema.json"
RECORD = "docs/student/task-3-11-provider-record.md"
PERMITTED = (
    "src/adapters/model/ollama.py",
    RECORD,
    "docs/student/providers/emulator-latency.json",
    "docs/student/providers/hosted-fixture-latency.json",
    "docs/student/providers/ollama-latency.json",
    "submission.yaml",
)


def _run(**overrides: Any) -> dict[str, Any]:
    """Return one well-formed run entry that ran."""
    entry: dict[str, Any] = {
        "status": "ran",
        "p50_ms": 251,
        "p95_ms": 262,
        "retryable_errors": 0,
        "terminal_errors": 0,
    }
    entry.update(overrides)
    return entry


def _not_run() -> dict[str, Any]:
    """Return one well-formed run entry that did not happen."""
    return {
        "status": "not_run",
        "p50_ms": None,
        "p95_ms": None,
        "retryable_errors": None,
        "terminal_errors": None,
    }


def valid_answers(**overrides: Any) -> dict[str, object]:
    """Return a complete answer sheet in the published shape."""
    answers: dict[str, Any] = {
        "runs": {
            "emulator": _run(),
            "hosted_fixture": _run(p50_ms=641, p95_ms=1642, retryable_errors=1),
            "ollama": _not_run(),
        },
        "primary": "emulator",
        "fallback": "hosted_api",
        "fallback_trigger": "provider_unreachable",
        "notes": "The fixture names one hosted provider; one run each proves one afternoon.",
    }
    answers.update(overrides)
    return {"answers": answers}


def _with_runs(**runs: dict[str, Any]) -> dict[str, object]:
    """Return a complete sheet with some run entries replaced."""
    answers = valid_answers()
    mapping = answers["answers"]
    assert isinstance(mapping, dict)
    mapping["runs"] = {**mapping["runs"], **runs}
    return answers


def _task_root(tmp_path: Path, submission_text: str) -> Path:
    """Stage a minimal Task root the public verifier can validate."""
    (tmp_path / "docs/contracts").mkdir(parents=True)
    (tmp_path / "submission.yaml").write_text(submission_text, encoding="utf-8")
    (tmp_path / "submission-sample.yaml").write_text(
        (ROOT / "submission-sample.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "docs/contracts/submission.schema.json").write_text(
        SCHEMA.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return tmp_path


def _with_record(root: Path, text: str) -> None:
    """Place a provider record with the given text beside the staged answer sheet."""
    (root / "docs/student").mkdir(parents=True, exist_ok=True)
    (root / RECORD).write_text(text, encoding="utf-8")


def test_a_complete_sheet_is_well_formed(tmp_path: Path) -> None:
    """The public schema accepts a complete sheet without judging its correctness."""
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers()))

    validate_submission(root / "submission.yaml", SCHEMA)


def test_a_sheet_with_every_run_ran_is_well_formed(tmp_path: Path) -> None:
    """An Ollama run that happened is recorded like the other two."""
    root = _task_root(tmp_path, yaml.safe_dump(_with_runs(ollama=_run(p50_ms=4210, p95_ms=9870))))

    validate_submission(root / "submission.yaml", SCHEMA)


def test_blank_template_fails_with_field_address(tmp_path: Path) -> None:
    """An untouched answer sheet must identify the first incomplete field."""
    root = _task_root(
        tmp_path, (ROOT / "tests/fixtures/submission-template.yaml").read_text(encoding="utf-8")
    )

    with pytest.raises(SubmissionError, match="answers.runs.emulator.status"):
        validate_submission(root / "submission.yaml", SCHEMA)


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"primary": "openai"}, "primary"),
        ({"fallback": "stub"}, "fallback"),
        ({"fallback_trigger": "slow_afternoon"}, "fallback_trigger"),
        ({"fallback_trigger": True}, "fallback_trigger"),
        ({"notes": "n" * 601}, "notes"),
    ],
    ids=["unknown-primary", "unknown-fallback", "prose-trigger", "boolean-trigger", "long-notes"],
)
def test_values_outside_the_published_contract_are_rejected(
    tmp_path: Path, overrides: dict[str, Any], message: str
) -> None:
    """The public schema must name the field it rejected, and reject the right ones."""
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers(**overrides)))

    with pytest.raises(SubmissionError, match=message):
        validate_submission(root / "submission.yaml", SCHEMA)


@pytest.mark.parametrize(
    "entry,message",
    [
        (_run(status="skipped"), "runs.emulator"),
        (_run(p50_ms=-1), "runs.emulator.p50_ms"),
        (_run(p95_ms=262.5), "runs.emulator.p95_ms must be a whole number"),
        (_run(retryable_errors="none"), "runs.emulator.retryable_errors must be a whole number"),
        (_run(terminal_errors=None), "runs.emulator.terminal_errors must be a whole number"),
        (_run(status="not_run"), "runs.emulator.p50_ms must be null"),
    ],
    ids=[
        "unknown-status",
        "negative-figure",
        "fractional-figure",
        "prose-figure",
        "ran-with-null",
        "not-run-with-figures",
    ],
)
def test_run_entries_outside_the_published_contract_are_rejected(
    tmp_path: Path, entry: dict[str, Any], message: str
) -> None:
    """A run entry's status decides its figures' type, and the check names the field."""
    root = _task_root(tmp_path, yaml.safe_dump(_with_runs(emulator=entry)))

    with pytest.raises(SubmissionError, match=message):
        validate_submission(root / "submission.yaml", SCHEMA)


def test_a_missing_run_entry_is_rejected(tmp_path: Path) -> None:
    """All three providers are required; two of them is not a comparison."""
    answers = valid_answers()
    mapping = answers["answers"]
    assert isinstance(mapping, dict)
    del mapping["runs"]["hosted_fixture"]
    root = _task_root(tmp_path, yaml.safe_dump(answers))

    with pytest.raises(SubmissionError, match="hosted_fixture"):
        validate_submission(root / "submission.yaml", SCHEMA)


def test_primary_and_fallback_must_differ(tmp_path: Path) -> None:
    """A fallback that is the primary is no fallback, and the schema cannot say so alone."""
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers(fallback="emulator")))

    with pytest.raises(SubmissionError, match="two different providers"):
        validate_submission(root / "submission.yaml", SCHEMA)


@pytest.mark.parametrize(
    "field",
    ["conformance_passed", "instructor_approved", "defense_recording_url", "ollama_url"],
)
def test_no_self_attestation_or_endpoint_field_is_accepted(tmp_path: Path, field: str) -> None:
    """Reject a self-approval, a pass boolean, a recording URL, or an endpoint."""
    answers = valid_answers()
    mapping = answers["answers"]
    assert isinstance(mapping, dict)
    mapping[field] = True
    root = _task_root(tmp_path, yaml.safe_dump(answers))

    with pytest.raises(SubmissionError, match="Additional properties"):
        validate_submission(root / "submission.yaml", SCHEMA)


def test_exact_sample_copy_is_rejected(tmp_path: Path) -> None:
    """The published sample must not be accepted as a student submission."""
    root = _task_root(tmp_path, (ROOT / "submission-sample.yaml").read_text(encoding="utf-8"))

    with pytest.raises(SubmissionError, match="fictional sample"):
        validate_submission(
            root / "submission.yaml",
            SCHEMA,
            sample_path=root / "submission-sample.yaml",
        )


def test_only_the_six_permitted_paths_may_change() -> None:
    """The scaffold, the record, the three latency files, the sheet; nothing else."""
    validate_changed_paths(list(PERMITTED))

    for protected in (
        "src/adapters/model/deterministic.py",
        "src/adapters/model/resilient.py",
        "src/adapters/model/recorded.py",
        "src/adapters/model/__init__.py",
        "src/ports/model_provider.py",
        "src/domain/errors.py",
        "src/worker/bootstrap.py",
        "src/worker/config.py",
        "loadtest/provider_latency.py",
        "infra/provider-fixtures/hosted-recorded.jsonl",
        "tests/doubles/ollama_stub.py",
        "tests/contract/test_model_provider_conformance.py",
        "tests/contract/test_provider_contract.py",
        "tests/fixtures/ollama-scaffold.txt",
        "tests/student/test_my_adapter.py",
        "docs/student/providers/stub-latency.json",
        "docs/student/providers/notes.md",
        "compose.yaml",
        ".env",
        ".github/workflows/task.yml",
        "docs/student/runbook.md",
        "pyproject.toml",
        "README.md",
    ):
        with pytest.raises(SubmissionError, match="protected path changed"):
            validate_changed_paths([protected])


def test_public_entrypoint_reports_an_incomplete_answer_sheet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Catch a verifier entrypoint that skips the real submission contract."""
    root = _task_root(
        tmp_path, (ROOT / "tests/fixtures/submission-template.yaml").read_text(encoding="utf-8")
    )
    _with_record(root, (ROOT / RECORD).read_text(encoding="utf-8"))

    assert main(root, changed_paths=[]) == 1
    assert "answers.runs.emulator.status is incomplete" in capsys.readouterr().err


def test_public_entrypoint_rejects_an_untouched_provider_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A complete answer sheet with the template record still in place is incomplete."""
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers()))
    _with_record(root, (ROOT / RECORD).read_text(encoding="utf-8"))

    assert main(root, changed_paths=[]) == 1
    assert "template markers" in capsys.readouterr().err


def test_public_entrypoint_accepts_a_completed_sheet_and_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With every marker replaced and the paths inside the boundary, the check passes."""
    root = _task_root(tmp_path, yaml.safe_dump(valid_answers()))
    _with_record(root, "# Task 3.11 provider record\n\n## Step 1\n\nMy own request and reply.\n")

    assert main(root, changed_paths=list(PERMITTED)) == 0
    assert "Task 3.11 answer verification passed" in capsys.readouterr().out


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "answers: {value: first, value: second}\n",
        "answers: &answer {value: fictional}\n",
        "answers: *missing\n",
        "answers: {<<: {value: fictional}}\n",
        "answers: {value: 2026-09-04}\n",
        "answers: {value: !custom fictional}\n",
        "answers: {1: fictional}\n",
    ],
    ids=["duplicate-key", "anchor", "alias", "merge-key", "date", "custom-tag", "non-string-key"],
)
def test_non_json_yaml_constructs_are_rejected(tmp_path: Path, unsafe_text: str) -> None:
    """Reject restricted syntax before schema validation can mask a parser defect."""
    submission = tmp_path / "submission.yaml"
    submission.write_text(unsafe_text, encoding="utf-8")

    with pytest.raises(SubmissionError, match="restricted YAML"):
        _load_one_document(submission)


def test_multiple_yaml_documents_are_rejected(tmp_path: Path) -> None:
    """A second document cannot supply or replace the answer mapping."""
    submission = tmp_path / "submission.yaml"
    submission.write_text("answers: {}\n---\nanswers: {}\n", encoding="utf-8")

    with pytest.raises(SubmissionError, match="exactly one YAML mapping"):
        _load_one_document(submission)
