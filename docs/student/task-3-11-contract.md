# Task 3.11 — Second ModelProvider adapter and provider comparison contract

Your repository is the finished Project 3 system. Its worker asks one model provider for
every temperature summary, and when that provider is slow the resilient wrapper bounds the
wait, retries, and then gives up. This Task gives the worker a second provider it could turn
to, proves the two behave the same at the boundary, and measures which of them Coldline
should call first. You complete three `TODO` parts of a supplied Ollama adapter scaffold,
prove it meets the same contract as the emulator with the supplied conformance tests, measure
three providers with the supplied latency harness, and record a structured primary and
fallback decision with the limits of what your measurements show. You never touch the port,
the domain errors, the wrapper, the emulator, the stub, the fixture, the harness, or a test.

## What is assessed, and by whom

| Assessed | By |
|---|---|
| The pull request changes only `src/adapters/model/ollama.py`, `docs/student/task-3-11-provider-record.md`, `submission.yaml`, and the latency files under `docs/student/providers/` | Automated, in this repository (`poe answers`, and `poe verify` repeats it) |
| The answer sheet has the published shape, every enumerated field holds an allowed value, `primary` differs from `fallback`, and the provider record has no template marker left | Automated (same command) |
| Outside its three `TODO` regions, `src/adapters/model/ollama.py` is exactly the supplied scaffold | Automated, in this repository (`poe provider-checks`) |
| The Ollama adapter satisfies the port, returns a non-empty summary labelled `ollama` that names the shipment, and sends a body carrying the model name, `stream: false`, and every field of the request | Automated, against the supplied stub (same command) |
| Connection errors, timeouts, and 5xx replies raise `RetryableProviderError`; 4xx and malformed replies raise `TerminalProviderError`; through the resilient wrapper a retryable failure is retried and a terminal one ends at once | Automated, against the supplied stub (same command) |
| `docs/student/providers/emulator-latency.json` and `hosted-fixture-latency.json` are the unedited output of `poe provider-latency`, and `answers.runs.emulator` and `answers.runs.hosted_fixture` are `ran` with figures equal to their files | Automated (same command) |
| `answers.runs.ollama` is `ran` with a matching, unedited `ollama-latency.json`, or `not_run` with null figures and no file | Automated (same command) |
| No API key, no assignment of the two Ollama settings, and no endpoint URL from your machine appears in any permitted file | Automated (same command) |
| `answers.primary`, `answers.fallback`, and `answers.fallback_trigger` | Protected automated check, after you submit on the platform |
| Your provider record, your notes, and your reasoning | Your instructor, if the Add-On evidence is referenced at the Project Defense |

## The supplied pieces

| Supplied | Where | What it does |
|---|---|---|
| The adapter scaffold | `src/adapters/model/ollama.py` | Implements `ModelProvider` against Ollama's `POST /api/generate`. The transport is complete: the asynchronous HTTP client, the per-request timeout, and the two settings names, `COLDLINE_OLLAMA_URL` and `COLDLINE_OLLAMA_MODEL`, which a caller passes in. Three parts are `TODO`, each between a `begin` and an `end` marker line: `_build_request_body`, `_parse_reply`, and `_classify_failure`. |
| The conformance tests | `tests/contract/test_model_provider_conformance.py`, `poe conformance` | One suite of what any `ModelProvider` must do. The port rows run against the emulator and the Ollama adapter; the transport rows (the request body and each failure's classification) run against the Ollama adapter alone. The module starts and stops its own stub. |
| The stub | `tests/doubles/ollama_stub.py`, `poe ollama-stub` | A small fake Ollama: one JSON object when the request says `"stream": false`, a stream of fragments when it does not. Failures are selected per request: `timeout`, `drop`, `server_error`, `client_error`, `not_json`, `missing_response`, `empty_response`. Its `GET /api/tags` lists no models, so the harness refuses it for an `ollama` run. |
| The recorded hosted provider | `infra/provider-fixtures/hosted-recorded.jsonl`, replayed by `src/adapters/model/recorded.py` | Its first line names the provider and model the recording is presented as coming from and when; twenty replies follow, each with the latency the replay waits. Both names are fictional and every reply is synthetic; nothing is sent anywhere. |
| The latency harness | `loadtest/provider_latency.py`, `poe provider-latency --provider <name>` | Sends the same twenty pinned requests to `emulator`, `hosted-fixture`, or `ollama` through the adapter alone and writes `docs/student/providers/<name>-latency.json`. |
| The record template | `docs/student/task-3-11-provider-record.md` | One section per Step. |

## The five Steps

### Step 1 — Map the request and parse the reply

Complete `_build_request_body`: a JSON object with the scaffold's model name, a `prompt` that
names the shipment, the reading, and both bounds and asks for one short operational summary,
and `stream` set to `false`. Complete `_parse_reply`: return
`ModelSummary(summary=<the reply's response text, stripped>, provider="ollama")`, and raise
`MalformedReplyError` for a missing or empty `response`. Run `poe ollama-stub`, send it one
request with `curl`, and paste the body and the reply into Step 1 of the record. Run
`poe conformance`: every emulator row passes, and against the Ollama adapter the request-body
and summary rows pass while the failure rows still fail.

### Step 2 — Classify the failures

Complete `_classify_failure`: a timeout, a connection refused or dropped, and a 5xx status
raise `RetryableProviderError`; a 4xx status and a malformed reply raise
`TerminalProviderError`; chain the original with `from`. Run `poe conformance` until every row
passes against both adapters with none skipped, and write the four situations and your
classification into Step 2 of the record.

### Step 3 — Measure the emulator and the recorded hosted provider

Run `poe provider-latency --provider emulator` and `poe provider-latency --provider
hosted-fixture`. Copy each file's `p50_ms`, `p95_ms`, `retryable_errors`, and
`terminal_errors` into `answers.runs.emulator` and `answers.runs.hosted_fixture` with
`status: ran`, exactly as written. Commit both files unedited. Note the fixture's source
provider, model, and recording time, and the emulator's delay setting, in Step 3.

### Step 4 — Measure a local Ollama by hand

Install Ollama, pull one small model, set `COLDLINE_OLLAMA_URL` and `COLDLINE_OLLAMA_MODEL` in
your shell or an uncommitted `.env`, and run `poe provider-latency --provider ollama`. Copy
the figures into `answers.runs.ollama` with `status: ran` and commit the file. If Ollama
cannot run where you are, record `status: not_run`, set the four figures to `null`, commit no
`ollama-latency.json`, and write what you tried and what stopped it in Step 4. Never point
this run at the stub; the harness refuses it, and a `ran` built on it would be a false record.

### Step 5 — Record the primary and fallback decision

Fill `answers.primary` and `answers.fallback` (each one of `ollama`, `hosted_api`,
`emulator`, and they must differ), `answers.fallback_trigger` (one of
`retry_budget_exhausted`, `latency_over_budget`, `provider_unreachable`), and `answers.notes`
(at most 600 characters: the provider on the fixture's first line, one limit of what your
runs prove about each of the primary and the fallback, and whether a server built for serving
open models would change your choice). Write the reasoning in Step 5 of the record.

## Commands

```shell
poe ollama-stub                              # the stub in the foreground, for curl
poe conformance                              # the conformance suite against both adapters
poe provider-latency --provider emulator     # writes docs/student/providers/emulator-latency.json
poe provider-latency --provider hosted-fixture
poe provider-latency --provider ollama       # manual; needs a real Ollama you installed
poe answers                                  # the static half: answer format, record markers, permitted-path boundary
poe provider-checks                          # the assessed checks: conformance, scaffold boundary, files, answers
poe provider-contract                        # both halves together; the check poe verify runs for this Task
poe verify                                   # the full public path
```

`poe conformance`, the harness, and `poe provider-contract` need no running stack and call no
real model; `poe verify` starts the stack for the inherited smoke and end-to-end checks. Keep
any host-port override in place for every command; the foreground stub listens on
`COLDLINE_OLLAMA_STUB_HOST_PORT` (11435 by default) and can be moved the same way.

## What the harness writes

Every field below is written by `poe provider-latency`, and the checks read the file as written:

| Field | Meaning |
|---|---|
| `provider` | The provider label: `emulator`, `hosted-fixture`, or `ollama` |
| `request_count`, `successful_requests` | The twenty pinned requests sent, and how many returned a summary |
| `p50_ms`, `p95_ms` | Nearest-rank percentiles, in whole milliseconds, over the requests that returned a summary |
| `retryable_errors`, `terminal_errors` | How many requests the adapter raised as `RetryableProviderError` and as `TerminalProviderError` |
| `latency_over` | `successful_requests`: what the percentiles were taken over |
| `worker_per_attempt_timeout_ms` | The worker's per-attempt timeout, from its settings, for comparison with the p95 |
| `settings` | What the run used: the emulator's delay and its setting name; the fixture path and the provider, model, and recording time from its first line; or the Ollama model name and the harness timeout. Never the endpoint |
| `requests` | One entry per request: `sequence`, `exception_id`, `outcome` (`ok`, `retryable`, `terminal`), `latency_ms`, and a detail with any URL replaced |
| `recorded_at`, `generator`, `schema`, `digest` | When the run was made, the generator marker, the file's shape, and a SHA-256 content digest over the rest of the file |

## What the checks verify

Each row of the lesson's Check-list maps to one or more checks:

| Check-list row | Check | What it looks at |
|---|---|---|
| The only code changed in `src/adapters/model/ollama.py` is the three `TODO` parts, and everything else is as supplied | `test_only_the_three_todo_parts_of_the_scaffold_changed`, `test_submission_change_stays_within_the_permitted_diff` | The scaffold with its three regions blanked, parsed and compared with the supplied text the same way; and the diff from the merge base against the six permitted files |
| `poe conformance` passes every test against the emulator and against the Ollama adapter pointed at the stub, with none skipped | `test_adapter_satisfies_the_model_provider_port` and every other row of `tests/contract/test_model_provider_conformance.py` | One suite, the port rows against both adapters, the transport rows against the Ollama adapter, with a stub the module starts itself |
| A successful Ollama call returns a `ModelSummary` with `provider` `ollama` and a non-empty summary | `test_a_successful_call_returns_a_non_empty_summary_with_the_adapters_own_label[ollama]`, `test_the_summary_names_the_shipment_it_was_asked_about[ollama]`, `test_the_request_body_carries_the_model_the_stream_flag_and_every_field_of_the_request` | The label is the adapter's own name, the text is non-empty and names the shipment, and the body the stub received carries the model, `stream: false`, and every request value |
| Connection errors, timeouts, and 5xx replies raise `RetryableProviderError`; 4xx and malformed replies raise `TerminalProviderError` | `test_a_refused_connection_is_raised_as_retryable`, `test_a_dropped_connection_is_raised_as_retryable`, `test_a_timeout_is_raised_as_retryable`, `test_a_server_error_is_raised_as_retryable`, `test_a_rejected_request_is_raised_as_terminal`, `test_a_reply_that_is_not_json_is_raised_as_terminal`, `test_a_reply_without_a_response_field_is_raised_as_terminal`, `test_an_empty_response_is_raised_as_terminal`, `test_the_resilient_wrapper_retries_a_retryable_failure_and_stops_on_a_terminal_one` | Each failure the stub can produce, raised as exactly the expected class; and through the worker's wrapper, one 503 retried to success and one 400 ended at once |
| The emulator and hosted-fixture files were written by the harness and are committed unchanged, and their run entries are `ran` with figures equal to their files | `test_emulator_and_hosted_fixture_latency_files_are_unedited_harness_output`, `test_recorded_run_figures_match_their_latency_files_field_for_field` | Both files parse, carry the generator marker and shape, recompute their digest, count twenty requests whose outcomes add up, and take their percentiles over the successes; each entry is `ran` with the four figures equal to the file's, as written |
| `answers.runs.ollama` is `ran` with a committed, unchanged file and matching figures, or `not_run` with `null` figures and no file | `test_ollama_run_is_recorded_with_its_file_or_as_not_run_without_one` | The status, the file's presence, its digest, and the figures, together |
| `answers.primary`, `answers.fallback`, and `answers.fallback_trigger` use their allowed values, `primary` differs from `fallback`, and `answers.notes` is non-empty and at most 600 characters | `test_decision_holds_allowed_values_and_differs_between_primary_and_fallback` (and the schema) | The three enumerations, the two providers differing, and the note's length; the values themselves are compared with the protected answer key after you submit |
| No API key and no endpoint URL from your machine appears in any committed file | `test_no_api_key_or_local_endpoint_is_committed` | The sheet, the record, the scaffold, and the latency files, scanned for credential shapes, an assignment of either Ollama setting, and endpoint URLs (the scaffold's own loopback default is allowed where it belongs) |
| The provider record replaces every template marker | `tests/contract/submission_validation.py` (`poe answers`) | `docs/student/task-3-11-provider-record.md` no longer contains `_Write your evidence here._` |
| The pull request modifies only the permitted files | `tests/contract/submission_validation.py` (`poe answers`) and `test_submission_change_stays_within_the_permitted_diff` | The diff from the merge base with `main` against the six-file allowlist, with no directory prefix exempted |

Every check is static and needs no Docker; the conformance module starts its own stub.
`poe contract` skips both modules because they are marked `assessed`; `poe provider-checks`,
`poe provider-contract`, and `poe verify` run them. A fresh checkout passes the port rows
against both adapters and every row against the emulator, and fails the request-body, summary,
and classification rows against the Ollama adapter, because the three `TODO` parts are this
Task's work; it also fails the harness-file, run-figure, Ollama-run, and decision checks until
the runs are made and the answers written. The scaffold-boundary and committed-secret checks
pass on the starter and are meant to.

## Student-editable paths

- `src/adapters/model/ollama.py` (the three `TODO` parts only)
- `docs/student/task-3-11-provider-record.md`
- `submission.yaml`
- `docs/student/providers/emulator-latency.json`, written by the harness only
- `docs/student/providers/hosted-fixture-latency.json`, written by the harness only
- `docs/student/providers/ollama-latency.json`, written by the harness only, and only if your run happened

That is the whole list. The scaffold's transport, constructor, and imports, the port, the
domain errors, the resilient wrapper, the emulator, the stub, the fixture, the harness, the
conformance tests, the transport adapters, `compose.yaml`, every test, and both workflows stay
as supplied. A latency file you edit by hand fails the digest check; a figure you disagree with
is a reason to rerun, never to retype. Keep `COLDLINE_OLLAMA_URL` and `COLDLINE_OLLAMA_MODEL`
in your shell or an uncommitted `.env`. Before you push, run `git status` and
`git diff --stat` against your merge base: if anything besides the permitted files changed,
the public check reports the boundary violation rather than your work.

## What this local run does not prove

The stub's replies and timing are fixed and fake: they prove the adapter speaks the contract
and nothing about any model's output or latency. The recording is one synthetic afternoon from
one place, replayed with its recorded waits; it proves the harness and the comparison, not any
hosted service's real latency, availability, quota, or cost. A model on your laptop measures
your laptop, with whatever model, hardware, and other load it had at the time; it does not
measure what a server built for serving open models would do. Say which of these bears on
your answer in the record and in `answers.notes`.
