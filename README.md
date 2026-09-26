# Coldline Task 3.11 — Optional Task 11: Second ModelProvider adapter and provider comparison

This checkpoint is the complete, settled Coldline platform from Task 3.7, with a second model
provider set beside the one the worker calls. The worker asks one `ModelProvider` for every
temperature summary; today that is the deterministic emulator, and when it is slow the resilient
wrapper bounds the wait, retries, and gives up. This Task supplies an adapter scaffold for
Ollama, a program that serves open models over a local HTTP endpoint, with its transport done
and three parts marked `TODO`; a conformance suite that states what any `ModelProvider` must
do and runs it against both adapters; a stub that answers like Ollama with scripted failures; a
recorded hosted provider replayed from a fixture; and a latency harness that sends the same
pinned requests to each provider. You complete the three parts, prove the adapter conforms,
measure three providers, and record a structured primary and fallback decision. The worker
keeps calling the emulator throughout; nothing in `compose.yaml` or the worker's composition
changes. This Task is optional.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/tripleten-com/ai-system-engineering-curriculum-sprint-3-task-3-11/tree/main)

## Start the system

Prerequisites are Python 3.12, git, and Docker with Compose v2. The supplied bootstrap supports
macOS arm64/x86-64, Windows x86-64, and Linux x86-64/aarch64, and installs pinned uv 0.11.8
under `.tools/bin`. If your computer cannot run the stack locally, use the Codespaces button
above.

On macOS and most Linux distributions the interpreter is `python3`; substitute it wherever these
commands say `python`.

```shell
python infra/scripts/bootstrap.py
./.tools/bin/uv sync --frozen
./.tools/bin/uv run --frozen poe preflight
./.tools/bin/uv run --frozen poe start
./.tools/bin/uv run --frozen poe ready
```

PowerShell and POSIX wrappers are available under `infra/scripts/`. After uv is on `PATH`, the
shorter `uv run --frozen poe <task>` form works.

| Service | Local URL | Purpose |
|---|---|---|
| API | `http://localhost:8000` | Submit exception workflows and retrieval queries |
| Grafana | `http://localhost:3000` | Use the focused diagnostics dashboard |
| Prometheus | `http://localhost:9090` | Query bounded metrics and inspect the deployed alert rule |
| Alertmanager | `http://localhost:9093` | Inspect firing and resolved alerts |
| Jaeger | `http://localhost:16686` | Inspect local traces; the Ollama adapter's `summarize` leaves a span labelled `ollama` |
| LocalStack S3/SQS | `http://localhost:4566` | Inspect the emulated object-storage and queue endpoint |

Each of these ports can be overridden by setting the matching `COLDLINE_API_HOST_PORT`,
`COLDLINE_GRAFANA_HOST_PORT`, `COLDLINE_PROMETHEUS_HOST_PORT`, `COLDLINE_ALERTMANAGER_HOST_PORT`,
`COLDLINE_JAEGER_HOST_PORT`, or `COLDLINE_LOCALSTACK_HOST_PORT` environment variable in your shell
environment or a local `.env` file (copy `.env.example`) if a default collides with something
already running on your machine. Keep the override in place for every `poe` command. The
foreground stub, `poe ollama-stub`, listens on `COLDLINE_OLLAMA_STUB_HOST_PORT` (11435 by
default, never Ollama's own 11434) and can be moved the same way.

PostgreSQL, Redis, worker metrics, and OTLP remain inside the Compose network. Codespaces uses the
same `compose.yaml` and keeps every forwarded port private. Redis keeps running in this Task only
for an earlier checkpoint's own contract test; no composition root reads it anymore. Nothing in
the stack calls Ollama: the adapter is exercised by the conformance tests and the harness only.

## Command path

For this Task, run the supplied commands in this order:

```text
poe start
poe ready
poe conformance
poe provider-latency --provider emulator
poe provider-latency --provider hosted-fixture
poe verify
```

Between `poe conformance` and `poe verify` sit the five Steps of the lesson: the request
mapping and reply parsing, then `poe conformance`; the failure classification, then
`poe conformance` again; the two harness runs above and their figures copied into
`submission.yaml`; a manual `poe provider-latency --provider ollama` against an Ollama you
install yourself, or a recorded `not_run`; and the decision. `poe conformance` and the harness
need no running stack; `poe verify` starts one for the inherited checks.

| Command | Use |
|---|---|
| `poe ollama-stub` | Run the supplied stub in the foreground so you can send it a generate request by hand with `curl`; it answers like Ollama, and the `X-Coldline-Stub-Failure` header selects one failure per request. `poe conformance` never needs this copy |
| `poe conformance` | Run the conformance suite against the emulator and against your Ollama adapter pointed at a stub the tests start and stop themselves; no stack, no real model |
| `poe provider-latency --provider <name>` | Send the pinned request set to `emulator`, `hosted-fixture`, or `ollama` and write `docs/student/providers/<name>-latency.json` with the label, the request count, the p50 and p95 in milliseconds, the error counts by class, a generator marker, and a digest. Never edit the file; rerun. The `ollama` run needs a real Ollama named by `COLDLINE_OLLAMA_URL` and `COLDLINE_OLLAMA_MODEL`, refuses the stub, and is never part of CI |
| `poe answers` | The static half of this Task's own check: the answer sheet's format, the provider record's template markers, and the diff from your merge base against the six permitted files |
| `poe provider-checks` | The assessed checks: the conformance suite, the scaffold outside its three `TODO` parts, the two harness files' digests and the figures copied from them, the Ollama run recorded with its file or as `not_run` without one, the decision's allowed values, and no key or endpoint in any committed file |
| `poe provider-contract` | `poe answers` and `poe provider-checks` together; the check `poe verify` runs for this Task. Static: it starts its own stub and calls no real model |
| `poe verify` | The public student verification path: it runs the unit tests, starts the stack, ingests the corpus, runs `poe provider-contract`, then the smoke tests, the end-to-end workflow, and the supplied student tests |
| `poe queue-contract`, `poe slo-contract`, `poe gate-contract`, `poe runbook-contract` | The inherited Task 3.3 through 3.6 checks over the settled checkpoint; still runnable, not part of this Task's verify path |
| `poe contract` | Check interfaces, boundaries, submissions, and repository structure |
| `poe smoke` | Check the initialized running platform |
| `poe e2e` | Run the external API-to-worker workflow |
| `poe student-tests` | Run the supplied tests under `tests/student/`; this Task permits no additions there |
| `poe dev-failure-lab`, `poe trigger-alert-load`, `poe verify-alert-recovery`, `poe inject-failure`, `poe redrive` | Inherited exercises from Tasks 3.3, 3.4, and 3.6, still runnable; not part of this Task |
| `poe restart` | Restart the existing API and worker containers **without rebuilding** |
| `poe stop` | Remove containers and the network, keeping named volumes |
| `poe reset` | Remove containers, the network, and local named volumes |

For Task 3.11, `poe verify` runs the unit tests, starts the stack, ingests the supplied corpus,
runs `poe answers`, runs the provider checks (the conformance suite against its own stub and the
static checks over the scaffold, the harness files, and the answers), then the smoke tests and
the end-to-end exception workflow against the unchanged worker, and the supplied student tests.
It never calls a real Ollama or a hosted endpoint. The inherited Task 3.3 through 3.6 checks are
not in this path; they were qualified against the settled checkpoint and remain runnable on
their own.

## The scaffold, the stub, the fixture, and the harness

`src/adapters/model/ollama.py` is the Ollama adapter scaffold. Its transport is supplied and
complete: the asynchronous HTTP client, the per-request timeout, the two settings names, and
`summarize` itself, which posts the body the request-mapping part builds to `/api/generate` and
hands the decoded reply to the parsing part. Three parts are marked `TODO`, each between a
`begin` and an `end` marker line: `_build_request_body` (the `ModelRequest` to the JSON body
Ollama accepts), `_parse_reply` (Ollama's reply to the `ModelSummary` the worker stores), and
`_classify_failure` (what went wrong, as `RetryableProviderError` or `TerminalProviderError`
from `src/domain/errors.py`). Change nothing outside those three regions: the public check
compares everything else in the file with the supplied text.

`tests/doubles/ollama_stub.py` is the stub: a small fake Ollama whose `POST /api/generate`
answers one JSON object when the request says `"stream": false` and a stream of fragments when
it does not, exactly as Ollama does. Its `GET /api/tags` lists no models on purpose, so the
harness refuses to record an Ollama run against it. The conformance tests queue a failure per
request; by hand, the `X-Coldline-Stub-Failure` header selects one of `timeout`, `drop`,
`server_error`, `client_error`, `not_json`, `missing_response`, or `empty_response`.

`infra/provider-fixtures/hosted-recorded.jsonl` is the recorded hosted provider. Its first line
names the provider and model it is presented as coming from and when; the twenty lines after it
are one reply each, with the latency the replay waits before answering. `src/adapters/model/
recorded.py` replays it through the same port. Both names are fictional and every reply is
synthetic; see [the fixture's README](infra/provider-fixtures/README.md). No request leaves your
machine.

`loadtest/provider_latency.py`, `poe provider-latency --provider <name>`, sends the same twenty
pinned requests to one provider through the adapter alone, with no resilient wrapper, and writes
`docs/student/providers/<name>-latency.json`. The p50 and p95 are nearest-rank percentiles in
whole milliseconds over the requests that returned a summary; the two error counts are the
requests the adapter raised as retryable and as terminal. A failure the adapter lets escape
unclassified stops the run: an adapter whose Step 2 is incomplete has no error counts to record.
The emulator run uses the worker's own delay setting (`COLDLINE_MODEL_LATENCY_MS`, or the
worker's default); the file records which.

## Folder map

```text
repository root/
├── docs/                Student guidance, public contracts, and fidelity notes
│   ├── contracts/       Machine-readable public contracts
│   ├── fidelity/        Local-runtime boundary notes, including the ModelProvider record
│   ├── architecture/    Supplied vector engine technical profiles, in prose
│   ├── retrieval/       Supplied retrieval pipeline reference
│   └── student/         This Task's contract and provider record, the supplied Task 6 runbook,
│                        and providers/, where poe provider-latency writes its files
├── config/              Retrieval configuration, settled and supplied from Sprint 2
├── infra/               Local setup and runtime configuration
│   ├── containers/      The API and worker Dockerfiles, with the build identity arguments
│   ├── observability/   Prometheus, Alertmanager, and Grafana configuration
│   ├── provider-fixtures/ The recorded hosted provider and its provenance record
│   ├── release/         The supplied Task 3.1 release manifest, unchanged
│   ├── corpus/          Supplied synthetic corpus, query set, and designated investigation
│   ├── judge/           Supplied cached judge evidence and its provenance record
│   ├── profiles/        Supplied engine and emulator profiles, and their provenance record
│   └── postgres/        Database initialization and the migration baseline stamp
├── loadtest/            Supplied traffic profile and this Task's provider-latency harness
├── migrations/          Alembic environment, revision template, and revisions
├── src/
│   ├── api/             HTTP application code, the retrieval and document paths, composition
│   ├── worker/          Background application code, including the dead-letter depth poller
│   ├── domain/          Shared domain code, contracts, the failure taxonomy, service and repository contracts
│   ├── ports/           Application interfaces
│   └── adapters/        Technology-specific implementations: the emulator, the resilient
│                        wrapper, the Ollama scaffold, the recorded-fixture replay, and the rest
└── tests/
    ├── unit/            Isolated behavior checks
    ├── benchmark/       Supplied evaluation harness, metrics, and adoption policy
    ├── contract/        Interface, retrieval, and repository checks, this Task's conformance
    │                    suite, and its provider checks
    ├── diagnostics/     Supplied stage inspector
    ├── doubles/         Supplied deterministic test doubles, including the Ollama stub
    ├── failure/         Supplied failure-lab and exercise scripts from Tasks 3.3, 3.4, and 3.6 — not this Task's work
    ├── fixtures/        The blank answer sheet and the supplied scaffold text the checks compare
    ├── student/         Supplied student tests; no additions in this Task
    ├── smoke/           Running-platform checks
    └── e2e/             Supplied workflow tools and checks
```

## Overview

Use the Optional Task 11 lesson (Task 3.11 in this repository) to decide what to do. This
README covers local setup and repository orientation.

1. `README.md` — local setup, commands, and permitted changes.
2. [`docs/student/task-3-11-contract.md`](docs/student/task-3-11-contract.md) — what this Task
   assesses and who assesses it, the five Steps, the commands, every field the harness writes,
   the mapping from the lesson's Check-list to each check, and the six permitted paths.
3. [`src/adapters/model/ollama.py`](src/adapters/model/ollama.py) — the scaffold; each `TODO`
   part's docstring says what it receives and what it must return or raise.
4. [`tests/contract/test_model_provider_conformance.py`](tests/contract/test_model_provider_conformance.py)
   — what any `ModelProvider` must do, as the tests that say so.
5. [`docs/student/task-3-11-provider-record.md`](docs/student/task-3-11-provider-record.md) — the
   record template, one section per Step; replace every marker with your own observations.
6. [`infra/provider-fixtures/README.md`](infra/provider-fixtures/README.md) — where the recorded
   hosted provider comes from and what a replay of it does and does not prove.

The application source lives in five flat packages:

| Package | Responsibility |
|---|---|
| `api` | HTTP delivery, API use cases, the retrieval workflow, versioned routes, configuration, and composition |
| `worker` | Background processing, retries, the dead-letter depth poller, configuration, and composition |
| `domain` | Provider-neutral contracts, state rules, identity, redaction, embedding, chunking, fusion, access constraints, failure classification, service and repository contracts |
| `ports` | Exactly five visible application interfaces |
| `adapters` | PostgreSQL, pgvector retrieval, LocalStack SQS/DLQ, S3-compatible object storage, the deterministic emulator, the Ollama adapter, the recorded-fixture replay, the resilient model-provider wrapper, logs, traces |

`src/api/bootstrap.py` and `src/worker/bootstrap.py` compose each process from its settings and
adapters; the worker still composes the emulator inside the resilient wrapper. Process settings
live in `src/api/config.py` and `src/worker/config.py`. The Ollama adapter reads no setting
itself: the harness passes `COLDLINE_OLLAMA_URL` and `COLDLINE_OLLAMA_MODEL` in from your shell
or local `.env`, and neither belongs in any committed file.

## The five ports

Find the available interfaces in `src/ports/`. A port describes an application capability; an
adapter provides it using a concrete technology.

| Port | General responsibility |
|---|---|
| `ModelProvider` | Call an AI model service |
| `Retriever` | Look up relevant context or documents |
| `ObjectStore` | Store large binary objects or files |
| `JobQueue` | Publish and consume background work |
| `SecretProvider` | Read API keys and credentials |

`ModelProvider` now has three adapters beside the resilient wrapper: the emulator the worker
calls, the Ollama adapter you complete, and the recorded-fixture replay. One port, one method,
and the same two error classes from each; see [ModelProvider fidelity](docs/fidelity/ModelProvider.md)
for what each adapter does and does not prove. LocalStack SQS, with a bound dead-letter queue,
still carries `JobQueue`, unchanged from Task 3.3.

## Test levels

| Level | Requires Compose | Main question |
|---|---:|---|
| Unit | No | Does one responsibility behave correctly, including failures? |
| Contract | Some | Do interfaces, schemas, paths, and dependency rules stay compatible? |
| Smoke | Yes | Did the complete local platform initialize and become observable? |
| E2E | Yes | Can an external client complete the supplied workflow? |

Contract checks marked `runtime` need the running stack, and checks marked `assessed` read your
work. `poe contract` skips both; `poe provider-checks` runs this Task's two assessed modules,
neither of which needs the stack. A fresh Task 3.11 checkout passes every conformance row against
the emulator and the two port rows against the Ollama adapter, and fails the rows about the
request body, the summary, and each failure's classification against the Ollama adapter, because
the three `TODO` parts are this Task's work; it also fails the harness-file, run-figure, Ollama-run,
and decision checks until the runs are made and the answers written. The scaffold-boundary and
committed-secret checks pass on the starter and are meant to.

## Submission checks

Run `poe verify` locally before opening your student pull request. Public GitHub CI repeats
the student checks, running `poe provider-contract` first so a boundary violation or a failing
adapter fails fast, then `poe start`, `poe ingest`, and `poe verify`. The values of
`answers.primary`, `answers.fallback`, and `answers.fallback_trigger` are compared with a
protected answer key after you submit on the platform; the public checks confirm their format
and their allowed values only. Follow the Task lesson's submission policy: this Task is optional
and gates nothing.

## Task boundary

Task 3.11 asks you to complete the three `TODO` parts, run the harness, fill the answer sheet,
and complete the provider record. The only student-editable paths are:

- `src/adapters/model/ollama.py` (the three `TODO` parts only)
- `docs/student/task-3-11-provider-record.md`
- `submission.yaml`
- `docs/student/providers/*-latency.json` (written by the harness, never edited by hand)

Change only the three `TODO` parts of the scaffold. Keep its transport, constructor, and
imports, the port, the domain errors, the resilient wrapper, the emulator, the stub, the fixture,
the harness, the conformance tests, the transport adapters, `compose.yaml`, every test file, and
both workflows exactly as supplied. Never put an API key or an endpoint URL from your machine in
any committed file, and never edit a latency file: the check recomputes its digest, and a figure
you disagree with is a reason to rerun. The public check compares the diff from your merge base
against the six permitted files and reports any other change as a boundary violation.

### Student walkthrough

See **Optional Task 11: Second ModelProvider adapter and provider comparison** in your course
platform for the full walkthrough. In outline: read `docs/student/task-3-11-contract.md`, start
the stack, complete the request mapping and the reply parsing, send the stub one request by hand
and run `poe conformance`; complete the classification and run `poe conformance` until it passes
in full; run the harness against `emulator` and `hosted-fixture` and copy their figures; run it
against your own Ollama or record `not_run`; fill the decision and the record; check
`git diff --stat` shows only the permitted files; run `poe verify`; open your pull request and
submit on the platform.

## Operational limits

This local system does not authenticate users, terminate TLS, or manage production secrets.
The Compose PostgreSQL password and the LocalStack access keys are local-only non-secret
credentials. Never place real credentials, personal data, or production records in this
repository.

Alertmanager here is configured with a "default" receiver that has no notification integration:
alerts are queryable through its own API but never sent anywhere real. Never add a webhook, email,
Slack, or paid integration; Sprints 1-4 are emulator-only and never call a hosted endpoint. The
hosted provider in this Task is a replayed recording, and CI never calls a real model. An Ollama
you install for Step 4 runs on your own machine; do not add a real endpoint, a paid cloud
resource, or a live model call to any test or workflow.

The stub's replies and timing are fixed and fake, so they prove the contract and nothing about
any model. The recording is one synthetic afternoon from one place. A model on your laptop
measures your laptop, with whatever hardware and other load it had at the time; it does not
measure what a server built for serving open models would do. Say so in your record and in
`answers.notes`.

Named volumes preserve local PostgreSQL, Redis, Prometheus, Alertmanager, Grafana, and Jaeger state
across `poe stop`. LocalStack object and queue contents are deliberately not persisted; the
initializer re-uploads the supplied corpus artifacts and re-provisions the queue on every start.
The `poe reset` command deletes the named volumes. This topology makes no backup, replication,
high-availability, disaster-recovery, capacity, latency-SLO, or availability claim beyond the one
alert Task 3.4 configures, the one CI gate Task 3.5 wires to it, and the one bounded recovery
Task 3.6's failure lab demonstrates.

See [JobQueue fidelity](docs/fidelity/JobQueue.md),
[ModelProvider fidelity](docs/fidelity/ModelProvider.md),
[ObjectStore fidelity](docs/fidelity/ObjectStore.md), and
[Retriever fidelity](docs/fidelity/Retriever.md) for the active adapter boundaries. The
[local runtime evidence](docs/fidelity/local-runtime.md) records the current measurement and its
qualification limits.
