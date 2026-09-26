"""Coldline.

===================

File:              tests/contract/provider_contract.py
Component:         Contract tests — Provider helpers
Purpose:           Read the latency files, the answer sheet, the scaffold, and the committed text.
Interacts With:    docs/student/providers/*.json, submission.yaml, src/adapters/model/ollama.py
Sprint/Task:       Sprint 3 — Project 3
Concepts:          Generated evidence, content digest, scaffold boundary, committed secrets
Tools:             Python 3.12

The checks read the files the harness wrote exactly as a student commits them and
recompute the content digest the same way the harness did, so what they assert is what the
files show. They never run the harness: the emulator and the recorded fixture are
deterministic enough to compare against, and the Ollama run is a manual one by design.
"""

import ast
import json
import re
from pathlib import Path
from typing import Any, cast

import yaml

from loadtest.provider_latency import (
    GENERATOR,
    LATENCY_OVER,
    REQUEST_COUNT,
    SCHEMA,
    digest,
)
from loadtest.provider_latency import (
    latency_path as latency_path,
)

TASK_ROOT = Path(__file__).resolve().parents[2]
SCAFFOLD_PATH = TASK_ROOT / "src/adapters/model/ollama.py"
SCAFFOLD_REFERENCE = TASK_ROOT / "tests/fixtures/ollama-scaffold.txt"
RECORD_PATH = TASK_ROOT / "docs/student/task-3-11-provider-record.md"
SUBMISSION_PATH = TASK_ROOT / "submission.yaml"
# The three TODO regions of the scaffold, in the order they appear, each fenced by one
# begin and one end marker line.
TODO_REGIONS = ("request mapping", "response parsing", "error classification")
PROVIDERS = ("emulator", "hosted-fixture", "ollama")
# The harness's provider names mapped to the answer sheet's run keys.
RUN_KEYS = {"emulator": "emulator", "hosted-fixture": "hosted_fixture", "ollama": "ollama"}
# The four figures the sheet copies from each file, compared as written.
RUN_FIGURES = ("p50_ms", "p95_ms", "retryable_errors", "terminal_errors")
STATUSES = ("ran", "not_run")
PROVIDER_CHOICES = ("ollama", "hosted_api", "emulator")
TRIGGERS = ("retry_budget_exhausted", "latency_over_budget", "provider_unreachable")
NOTES_MAX_LENGTH = 600
# Committed text that would carry a credential or a setting assignment from the student's
# own shell. The Ollama setting names may be mentioned; an assignment of either may not.
KEY_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "API key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b|\bAIza[0-9A-Za-z_-]{30,}\b"),
    "authorization header": re.compile(
        r"(?i)\b(?:authorization|x-api-key)\s*[:=]\s*\S|\bBearer\s+[A-Za-z0-9._-]{16,}"
    ),
    "Ollama setting assignment": re.compile(r"COLDLINE_OLLAMA_(?:URL|MODEL)\s*[:=]"),
}
URL_PATTERN = re.compile(r"https?://[^\s'\"`)<>]+")
# Hosts that name one machine on a private network: an endpoint URL from the student's
# own setup, as the lesson puts it. Loopback is allowed where the supplied scaffold's own
# default appears.
LAN_HOST_PATTERN = re.compile(
    r"^https?://(?:10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)"
)


class ProviderCheckError(ValueError):
    """Report one actionable provider-evidence failure."""


def marker(region: str, edge: str) -> str:
    """Return one TODO region marker line as the scaffold writes it."""
    return f"# TODO(Task 3.11) {region}: {edge}"


# --- the latency files -------------------------------------------------------------------


def load_latency(provider: str) -> dict[str, Any] | None:
    """Return one provider's file as written, or None when it does not exist or is not JSON."""
    path = latency_path(provider)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cast(dict[str, Any], loaded) if isinstance(loaded, dict) else None


def _is_whole(value: object) -> bool:
    """Return whether one JSON value is a whole number (a bool is not)."""
    return isinstance(value, int) and not isinstance(value, bool)


def latency_problems(summary: dict[str, Any] | None, provider: str) -> list[str]:
    """Return every reason one file is not what `poe provider-latency` writes for a provider."""
    name = latency_path(provider).relative_to(TASK_ROOT).as_posix()
    if summary is None:
        return [
            f"{name} is missing or is not one JSON object; run "
            f"`poe provider-latency --provider {provider}`"
        ]
    problems: list[str] = []
    if summary.get("generator") != GENERATOR:
        problems.append(f"{name} was not written by {GENERATOR}")
    if summary.get("schema") != SCHEMA:
        problems.append(f"{name} does not carry the {SCHEMA} shape")
    if summary.get("provider") != provider:
        problems.append(f"{name} names provider {summary.get('provider')!r}, not {provider!r}")
    if summary.get("digest") != digest(summary):
        problems.append(f"{name} has been edited since {GENERATOR} wrote it (digest mismatch)")
    if summary.get("request_count") != REQUEST_COUNT:
        problems.append(f"{name}: request_count must be the pinned set's {REQUEST_COUNT}")
    for field_name in (*RUN_FIGURES, "successful_requests"):
        value = summary.get(field_name)
        if not _is_whole(value) or cast(int, value) < 0:
            problems.append(f"{name}: {field_name} must be a whole number")
    if _is_whole(summary.get("p50_ms")) and _is_whole(summary.get("p95_ms")):
        if summary["p50_ms"] > summary["p95_ms"]:
            problems.append(f"{name}: p50_ms cannot exceed p95_ms")
    counted = (
        summary.get("successful_requests"),
        summary.get("retryable_errors"),
        summary.get("terminal_errors"),
    )
    if (
        all(_is_whole(value) for value in counted)
        and sum(cast(int, value) for value in counted) != REQUEST_COUNT
    ):
        problems.append(f"{name}: successes and errors must add up to {REQUEST_COUNT} requests")
    if summary.get("latency_over") != LATENCY_OVER:
        problems.append(f"{name}: percentiles must be taken over {LATENCY_OVER}")
    requests = summary.get("requests")
    if not isinstance(requests, list) or len(requests) != REQUEST_COUNT:
        problems.append(f"{name}: requests must list every one of the {REQUEST_COUNT} sent")
    return problems


# --- the answer sheet ---------------------------------------------------------------------


def load_answers() -> dict[str, Any]:
    """Load the recorded answers; a blank sheet still lets every check run and report."""
    document = yaml.safe_load(SUBMISSION_PATH.read_text(encoding="utf-8"))
    recorded = document.get("answers") if isinstance(document, dict) else None
    return recorded if isinstance(recorded, dict) else {}


def mapping(container: dict[str, Any], key: str) -> dict[str, Any]:
    """Return one nested answers mapping, or an empty mapping when it is absent or not one."""
    value = container.get(key)
    return value if isinstance(value, dict) else {}


def figure_mismatches(block: dict[str, Any], summary: dict[str, Any], key: str) -> list[str]:
    """Compare one run entry's four figures with its file, as written."""
    mismatches: list[str] = []
    for field_name in RUN_FIGURES:
        if block.get(field_name) != summary.get(field_name):
            mismatches.append(
                f"answers.runs.{key}.{field_name} records {block.get(field_name)!r}; the file "
                f"says {summary.get(field_name)!r}"
            )
    return mismatches


# --- the scaffold ----------------------------------------------------------------------------


def structural_source(text: str) -> str:
    """Return the scaffold's structure with its three TODO regions blanked out.

    The regions are replaced by ``pass``, the result is parsed, and the syntax tree is
    dumped: formatting, comments, and the region bodies fall away, and what remains is
    every import, constant, signature, docstring, and statement outside the regions.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    kept: list[str] = []
    cursor = 0
    for region in TODO_REGIONS:
        begin = _find(lines, marker(region, "begin"), cursor, region)
        end = _find(lines, marker(region, "end"), begin + 1, region)
        indent = lines[begin][: len(lines[begin]) - len(lines[begin].lstrip())]
        kept.extend(lines[cursor:begin])
        kept.append(f"{indent}pass")
        cursor = end + 1
    kept.extend(lines[cursor:])
    try:
        tree = ast.parse("\n".join(kept))
    except SyntaxError as exc:
        raise ProviderCheckError(
            f"the scaffold outside its TODO regions does not parse: {exc}"
        ) from exc
    return ast.dump(tree)


def _find(lines: list[str], wanted: str, start: int, region: str) -> int:
    """Return the index of one marker line at or after ``start``."""
    for index in range(start, len(lines)):
        if lines[index].strip() == wanted:
            return index
    raise ProviderCheckError(
        f"the scaffold's {region} region marker {wanted!r} is missing or out of order; the "
        "three TODO regions must keep their begin and end marker lines"
    )


def scaffold_problems(student_text: str, reference_text: str) -> list[str]:
    """Return every reason the scaffold outside its three TODO regions is not as supplied."""
    try:
        student = structural_source(student_text)
        reference = structural_source(reference_text)
    except ProviderCheckError as exc:
        return [str(exc)]
    if student != reference:
        return [
            "src/adapters/model/ollama.py changed outside its three TODO regions: the imports, "
            "the constants, the constructor, from_settings, the transport in summarize, the "
            "MalformedReplyError class, and every signature and docstring must stay as supplied"
        ]
    return []


# --- committed text ------------------------------------------------------------------------


def forbidden_content(text: str, name: str, *, allow_loopback_urls: bool) -> list[str]:
    """Return every credential shape, setting assignment, or endpoint one committed file carries.

    Every file is scanned for credential shapes and for an assignment of the two Ollama
    settings. A file that may mention the scaffold's own loopback default (the scaffold
    and the record) is scanned for private-network endpoints; a file that has no business
    naming any endpoint (the answer sheet and the latency files) is scanned for every URL.
    """
    problems: list[str] = []
    for label, pattern in KEY_PATTERNS.items():
        if pattern.search(text):
            problems.append(f"{name} carries a {label}")
    for found in URL_PATTERN.findall(text):
        if not allow_loopback_urls:
            problems.append(f"{name} carries an endpoint URL: {found}")
        elif LAN_HOST_PATTERN.match(found):
            problems.append(f"{name} carries an endpoint URL from a private network: {found}")
    return problems
