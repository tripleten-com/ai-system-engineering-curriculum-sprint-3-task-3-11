# Supplied provider recording

## Provenance

`hosted-recorded.jsonl` is the recorded hosted provider that Task 3.11's latency harness
replays as `poe provider-latency --provider hosted-fixture`. It was written for this
curriculum. Its first line names the provider and model the recording is presented as
coming from, `Tessellate Inference API` and `tessellate-summarize-1`, and the time of the
recording; the twenty lines after it are one reply each, in the order of the harness's
pinned request set (`loadtest/provider_latency.py`), with the latency the harness waits
before replaying each one.

Both names are fictional. The replies are synthetic text in the shape a hosted summary
service returns for the pinned readings, and the latencies are a synthetic afternoon's
distribution chosen to teach one comparison: most replies well inside the worker's
per-attempt timeout, a long tail that still finishes inside it, and one server error the
resilient wrapper would retry. Nothing here was captured from a real endpoint, no request
left any machine, and no credential was used or is needed. Sprints 1-4 are emulator-only.

## Synthetic

This is a teaching fixture. It carries no measurement of any real provider, no vendor
statement, no customer configuration, and no credential. The figures a replay produces
describe the recording, not any hosted service's real latency, availability, or cost.

## Licence

Licence: TripleTen curriculum content, written for this Task and distributed with the Task
repository.

## How it is read

The fixture adapter, `src/adapters/model/recorded.py`, reads the file once and answers the
harness's requests in recorded order: it waits the recorded latency, then returns the
recorded text as a summary labelled `hosted-fixture`, or raises `RetryableProviderError`
for a recorded 5xx and `TerminalProviderError` for a recorded 4xx. It refuses a request that
is not the one the recording answered at that position, so the pinned request set and the
recording cannot drift apart silently. The replay is what the `hosted_fixture` run entry in
`submission.yaml` describes; the `hosted_api` answer values name the provider the recording
stands for.
