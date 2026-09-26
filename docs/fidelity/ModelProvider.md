# ModelProvider fidelity

The active adapter is an in-process deterministic simulation. It returns a fixed-format summary
from the supplied synthetic reading and waits for the configured local latency. It proves the
application contract, asynchronous composition, deterministic tests, and local telemetry behavior.

It does not prove hosted-model availability, output quality, token accounting, safety behavior,
provider throttling, network failure behavior, or cost. No live endpoint or credential is used.
The fixed delay is not a performance measurement, capacity test, latency target, or availability
claim.

## Second adapter, stub, and recording (Task 3.11)

The worker still composes the emulator; nothing in `compose.yaml` or `src/worker/bootstrap.py`
changes. Task 3.11 adds three things beside it, exercised by the conformance tests and the
latency harness only.

The Ollama adapter (`src/adapters/model/ollama.py`) speaks Ollama's generate endpoint over
HTTP. Against the supplied stub (`tests/doubles/ollama_stub.py`) it proves the port contract,
the request and reply mapping, and the classification of connection errors, timeouts, and
status codes. The stub's replies and timing are fixed and fake: they prove nothing about any
model's output, load time, or latency. Against a real Ollama on a student's own machine, the
harness measures that machine, with whatever model, hardware, and other load it had at the
time; it does not measure what a server built for serving open models would do.

The recorded hosted provider (`infra/provider-fixtures/hosted-recorded.jsonl`, replayed by
`src/adapters/model/recorded.py`) is synthetic teaching data in the shape of one hosted
provider's replies and latencies; see its README. A replay proves the harness and the
comparison, not any hosted service's real latency, availability, quotas, or cost. No endpoint
is called and no credential exists. CI never calls a real model.
