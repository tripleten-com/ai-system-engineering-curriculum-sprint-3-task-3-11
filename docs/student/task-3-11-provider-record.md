# Task 3.11 provider record

This record is the answer to Elena's question about what was measured and what could not
be. It is not graded by the automated checks; they read `submission.yaml`, the three TODO
parts of `src/adapters/model/ollama.py`, and the latency files under
`docs/student/providers/`. Replace every italic placeholder line below with your own
observations; `poe verify` fails while any placeholder remains. Paste request bodies,
replies, test names, and harness lines as you saw them, and keep the outputs yours: every
figure here comes from your own runs on your own machine. Never paste an API key, and never
paste the lines that assign `COLDLINE_OLLAMA_URL` and `COLDLINE_OLLAMA_MODEL` in your shell
or `.env`; the model's name on its own belongs in Step 4, the endpoint does not belong
anywhere here.

## Step 1 - Map the request and parse the reply

The request body you sent the stub by hand and the reply it returned, exactly as `curl`
printed them (bodies and replies, not the address you sent them to). Then the
`poe conformance` result after both Step 1 parts: which tests pass against the emulator,
which pass against the Ollama adapter, and the names of the tests that still fail.

I ran `poe ollama-stub` in one process and sent it the body my `_build_request_body`
produces for the conformance suite's pinned request, saved to a file without a byte-order
mark and posted with `curl.exe --data-binary @body.json`.

Request body (`POST /api/generate`):

```json
{"model": "coldline-stub:latest", "prompt": "You are a cold-chain operations assistant. Write one short operational summary, at most two sentences, of this temperature excursion.\nException: exc-conformance-001\nShipment: shipment-conformance-001\nMeasured temperature: 9.2 C\nAllowed range: 2.0 C to 8.0 C\nName the shipment, state how far the reading is outside the allowed range, and say what operations should do next.", "stream": false}
```

Reply, exactly as `curl` printed it:

```json
{"model": "coldline-stub:latest", "created_at": "2026-09-30T07:32:10.143286Z", "response": "Stub summary. The prompt read: You are a cold-chain operations assistant. Write one short operational summary, at most two sentences, of this temperature excursion. Exception: exc-conformance-001 Shipment: shipment-conformance-001 Measured temperature: 9.2 C Allowed range: 2.0 C to 8.0 C Name the shipment, state how far the reading is outside the allowed range, and say what operations should do next.", "done": true, "done_reason": "stop", "total_duration": 4200000, "load_duration": 900000, "prompt_eval_count": 32, "eval_count": 24}
```

The stub's own log line for that request read
`POST /api/generate model='coldline-stub:latest' stream=False failure=none`. With
`"stream": false` the whole reply is one JSON object, and the generated text sits in
`response`. I also sent the same body with `X-Coldline-Stub-Failure: empty_response` to see
what a malformed reply looks like before Step 2 touches it: the same object shape, but
`"response": ""` with `"done_reason": "length"`. That is the reply my parser must refuse
rather than turn into an empty summary.

What I wrote from that: `_build_request_body` returns
`{"model": self.model, "prompt": <the prompt above>, "stream": False}`, and `_parse_reply`
takes `reply["response"]`, refuses it with `MalformedReplyError` when it is missing, not a
string, or blank once stripped, and otherwise returns
`ModelSummary(summary=<the stripped text>, provider=PROVIDER_LABEL)`. The label is the
constant `"ollama"`, not the reply's `model` field, which here would have stored
`coldline-stub:latest` — a label that would change with every model pull.

`poe conformance` after Step 1: **9 failed, 7 passed in 6.11s**. Every row passed against
the emulator. Against the Ollama adapter the port row, the two summary rows and the
request-body row passed:

- `test_adapter_satisfies_the_model_provider_port[emulator]` and `[ollama]`
- `test_a_successful_call_returns_a_non_empty_summary_with_the_adapters_own_label[emulator]`
  and `[ollama]`
- `test_the_summary_names_the_shipment_it_was_asked_about[emulator]` and `[ollama]`
- `test_the_request_body_carries_the_model_the_stream_flag_and_every_field_of_the_request`

The nine that still failed are all the error-classification rows, which Step 2 repairs:

- `test_a_refused_connection_is_raised_as_retryable`
- `test_a_dropped_connection_is_raised_as_retryable`
- `test_a_timeout_is_raised_as_retryable`
- `test_a_server_error_is_raised_as_retryable`
- `test_a_rejected_request_is_raised_as_terminal`
- `test_a_reply_that_is_not_json_is_raised_as_terminal`
- `test_a_reply_without_a_response_field_is_raised_as_terminal`
- `test_an_empty_response_is_raised_as_terminal`
- `test_the_resilient_wrapper_retries_a_retryable_failure_and_stops_on_a_terminal_one`

## Step 2 - Classify the failures

The four situations the transport surfaces (connection refused or dropped, timeout, a
status code, a body that could not be parsed), the status codes you treated as retryable
and as terminal, the error you raise for each, and why. Then the `poe conformance` line
that reports every test passing against both adapters, with none skipped.

The supplied transport hands `_classify_failure` one of four things, and I sort them on the
single question the resilient wrapper asks: could a later attempt succeed?

| Situation the transport surfaces | Exception it hands me | I raise | Why |
| --- | --- | --- | --- |
| Connection refused or dropped | `httpx.TransportError` | `RetryableProviderError` | The provider is down, restarting or mid-crash. The request was never judged, so the same request may succeed in a second. |
| Request timed out | `httpx.TimeoutException` | `RetryableProviderError` | Slow is not wrong. A model that was loading or a queue that was long may answer inside the timeout next time. |
| Server answered 5xx (the stub sends 503) | `httpx.HTTPStatusError` | `RetryableProviderError` | The server accepted the request and failed on its own side: overloaded or broken for now, not for good. |
| Server answered 4xx (the stub sends 400) | `httpx.HTTPStatusError` | `TerminalProviderError` | The request itself is what the provider rejected. Every retry sends the identical body, so the whole budget would be spent on a call that cannot succeed. |
| Body could not be parsed: not JSON, no `response` field, or an empty `response` | `MalformedReplyError` | `TerminalProviderError` | The provider is not speaking the generate contract. Retrying a contract mismatch changes nothing, and returning it would store an empty summary in a dispatcher's record. |

Status codes: **4xx terminal, 5xx retryable**, decided on `exc.response.status_code`. I
sorted on the range rather than on "not 200" deliberately; treating every non-200 as
retryable would turn a rejected request into a full retry budget and then report the
provider as down. Every raise chains the original with `from exc`, so the transport's own
message survives in the log. `httpx.TimeoutException` is a subclass of
`httpx.TransportError`, so the timeout branch is tested first; and the final branch raises
`TerminalProviderError` rather than letting anything escape, because the wrapper treats an
unclassified exception as retryable and would hide a terminal failure behind retries.

I checked the mapping directly by sending each stub failure through the adapter and
printing the class it raised:

```text
drop               -> RetryableProviderError: the Ollama connection failed: Server disconnected without sending a response.
timeout            -> RetryableProviderError: the Ollama request timed out:
server_error       -> RetryableProviderError: Ollama answered with status 503
client_error       -> TerminalProviderError: Ollama rejected the request with status 400
not_json           -> TerminalProviderError: Ollama returned a malformed reply: the reply body is not one JSON object; a stream of JSON fragments arrives when the request leaves `stream` unset or true
missing_response   -> TerminalProviderError: Ollama returned a malformed reply: the reply carries no generated text; the generate contract puts it in a non-empty `response` field
empty_response     -> TerminalProviderError: Ollama returned a malformed reply: the reply carries no generated text; the generate contract puts it in a non-empty `response` field
no failure         -> returned a summary, provider='ollama'
refused            -> RetryableProviderError: the Ollama connection failed: All connection attempts failed
```

`poe conformance` after Step 2:

```text
collected 16 items

tests\contract\test_model_provider_conformance.py ................       [100%]

============================= 16 passed in 3.87s ==============================
```

Sixteen passed, none skipped, none failed — every row against the emulator and every row
against the Ollama adapter, including
`test_the_resilient_wrapper_retries_a_retryable_failure_and_stops_on_a_terminal_one`,
which is the one that proves the classification is worth something: the wrapper sent two
requests for the 503 and exactly one for the 400.

## Step 3 - Measure the emulator and the recorded hosted provider

The closing line of `poe provider-latency --provider emulator` and of
`poe provider-latency --provider hosted-fixture`, the emulator's delay setting during your
run, and the provider, model, and recording time named on the fixture's first line. One
sentence on what the p95 of each run means for a dispatcher waiting on a bad request.

Closing line of `poe provider-latency --provider emulator`:

```text
wrote docs/student/providers/emulator-latency.json: 20 requests, p50 256 ms, p95 264 ms, 0 retryable, 0 terminal
```

Closing line of `poe provider-latency --provider hosted-fixture`:

```text
wrote docs/student/providers/hosted-fixture-latency.json: 20 requests, p50 654 ms, p95 1645 ms, 1 retryable, 0 terminal
```

Both runs were made on 2026-09-30 (the files record `recorded_at`
`2026-09-30T07:34:21+00:00` and `2026-09-30T07:34:41+00:00`). Twenty requests each, the
same pinned set.

**The emulator's delay setting during my run.** The file records
`"settings": {"latency_ms": 250, "latency_setting": "COLDLINE_MODEL_LATENCY_MS"}`. I set
nothing, so this is the worker's own default of 250 ms from
`model_latency_ms` in `src/worker/config.py`. That is why the twenty measurements sit in a
narrow band from 251.1 to 264.3 ms: the emulator sleeps for a configured interval, so what
the harness measured is that constant plus a few milliseconds of Python overhead, not a
model doing work.

**The fixture's first line.** Provider **Tessellate Inference API**, model
**tessellate-summarize-1**, recorded **2026-08-14T15:20:00Z**. The harness copied the same
three values into `hosted-fixture-latency.json` under `settings.source_provider`,
`settings.source_model` and `settings.source_recorded_at`. The name and the replies are
fictional and synthetic, per `infra/provider-fixtures/README.md`; the replay waits each
recorded latency locally and sends nothing anywhere.

**Errors.** The emulator had none. The hosted fixture had one retryable and no terminal:
request 7 replayed a recorded 503, `upstream model runner overloaded; retry after a short
wait`, after 1814.5 ms. My Step 2 classification is what turned that into a `retryable`
count rather than an unclassified crash of the run. The percentiles are taken over the
nineteen requests that returned a summary, which is why the hosted p95 of 1645 ms is lower
than the 1814.5 ms the failed request cost.

**What the p95 means for a dispatcher.** On the emulator a dispatcher waits about a
quarter of a second even on a bad request (p95 264 ms, only 8 ms above the p50), because a
fixed delay has no bad afternoon; on the hosted provider the ordinary wait is about
two-thirds of a second but one summary in twenty took 1.6 seconds or more (p95 1645 ms,
2.5 times the p50), which is the wait Elena's floor actually feels — and it is inside, but
not far inside, the worker's 2000 ms per-attempt timeout.

## Step 4 - Measure a local Ollama by hand

If the run happened: the model name, the machine's CPU or GPU and memory, the time of the
run, what else ran on the machine at the time, and the closing line of
`poe provider-latency --provider ollama`. If it did not: what you tried and what stopped it,
so a reader can tell a blocked machine from a skipped Step. Either way, one sentence on what
a model on your own machine does and does not tell Elena about a self-hosted provider.

The run happened. Ollama was already installed on this machine and the small model
`llama3.2:1b` was already pulled into it, so I started the server, pointed the two settings
at it from my shell only, and ran the harness. Neither setting is written down here or in
any committed file.

- **Model:** `llama3.2:1b` — 1.2B parameters, `Q8_0` quantization, GGUF, 1.3 GB on disk, as
  Ollama's own `/api/tags` reported it. This is the "one small instruction-tuned model" the
  Step asks for; a larger one would change the latency, not the contract.
- **Machine:** 12th Gen Intel Core i7-1265U, 10 cores / 12 threads, 31.8 GB RAM, Windows 11
  Pro. **No discrete GPU** — the only graphics is Intel Iris Xe integrated with 2 GB, so
  this generation ran on the CPU.
- **Time of the run:** 2026-09-30, 07:38:20 UTC (the file's `recorded_at`). The twenty
  requests took 95.9 s wall clock end to end.
- **What else ran at the time:** the full Coldline Compose stack was up throughout —
  PostgreSQL, Redis, LocalStack, Prometheus, Alertmanager, Grafana, Jaeger, the API and the
  worker, nine containers — plus my editor and a browser. I did not quiet the machine for
  the run, so these figures include ordinary background load. That is honest but it is also
  a reason not to read them as a clean benchmark.

Closing line of `poe provider-latency --provider ollama`:

```text
wrote docs/student/providers/ollama-latency.json: 20 requests, p50 4358 ms, p95 6730 ms, 0 retryable, 0 terminal
```

Every one of the twenty requests returned a summary: no retryable and no terminal errors,
so the adapter I wrote in Steps 1 and 2 speaks the real Ollama protocol and not only the
stub's imitation of it. The first request cost 8322.6 ms against a 4358 ms median, which is
the model being loaded into memory; after that the spread ran from 2692.7 ms to 6730.4 ms.
The harness recorded the first request as it was rather than discarding it, which is
correct — a cold start is a real wait for whoever is on the floor when it happens.

The figure that matters for Step 5: **both the p50 and the p95 are far above the worker's
2000 ms per-attempt timeout** (`model_timeout_ms` in `src/worker/config.py`, which the
harness also records in the file as `worker_per_attempt_timeout_ms`). On this machine, with
this model, essentially *every* call would be cut off by the resilient wrapper before it
finished — not one bad call in twenty, but all of them.

**What this does and does not tell Elena.** It tells her the adapter works against the real
Ollama protocol, that a self-hosted provider needs no credential and no network, and that
on a mid-range laptop CPU with a 1B model a summary costs roughly four and a half seconds.
It does not tell her what a self-hosted provider would cost Coldline: this measures one
laptop, one small model, on CPU only, with nine containers and a browser competing for it.
A server built for serving — a GPU, batching, a model kept resident — is a different
machine and would produce different numbers, and I have not measured one.

## Step 5 - Record the primary and fallback decision

The four decision answers in `submission.yaml` and the reasoning behind them in Elena's
terms: what a dispatcher waits during a normal summary on each provider, what on-call does
when the switch happens, which condition the worker can see that triggers it, and what
you would need to measure before promising either. Close with whether a server built for
serving open models would change your choice, and why.

The four answers in `submission.yaml`:

```yaml
primary: "hosted_api"
fallback: "ollama"
fallback_trigger: "retry_budget_exhausted"
```

**The three runs side by side**, all twenty pinned requests through the adapter alone, all
on my machine on 2026-09-30, against the worker's 2000 ms per-attempt timeout:

| Provider | p50 | p95 | retryable | terminal |
| --- | ---: | ---: | ---: | ---: |
| emulator | 256 ms | 264 ms | 0 | 0 |
| hosted-fixture (`hosted_api`) | 654 ms | 1645 ms | 1 | 0 |
| ollama (this laptop) | 4358 ms | 6730 ms | 0 | 0 |

**What a dispatcher waits during a normal summary.** On the hosted provider, about
two-thirds of a second, and under 1.7 s even on the slow one in twenty. On a self-hosted
Ollama as I measured it, four and a half seconds normally and nearly seven on a slow one.
On the emulator, a quarter of a second — but the emulator does not read the excursion and
write about it; it fills in a fixed sentence. It is the right thing for the worker to call
in a local checkout and the wrong thing to send Elena's floor, so I did not name it as
either the primary or the reserve.

**Why `hosted_api` is the primary.** It is the only one of the three whose whole
distribution fits inside the budget the worker already enforces: p95 1645 ms against a
2000 ms per-attempt timeout. Ollama on this machine does not merely have a bad tail — its
*median* is more than twice the timeout, so the wrapper would cut off essentially every
call. Choosing on the p95 rather than the p50 is the point here: the p50 gap between hosted
and Ollama is 3.7 s, but it is the 1645 ms versus 6730 ms comparison that decides whether
the summaries arrive at all on a bad afternoon.

**Why `ollama` is the reserve.** It is the answer to what Elena actually asked for:
somewhere else to send the summaries. It needs no credential, no quota and no network, so
the failure that takes out a hosted service does not take it out too — the two fail for
different reasons, which is the whole value of a reserve. My run proves the adapter speaks
the real protocol and that all twenty requests came back as summaries with no errors. It is
slower, and the record says so plainly rather than calling it fine.

**The condition the worker can see: `retry_budget_exhausted`.** Both of Elena's incidents
were the service being *slow*, not refusing connections, so `provider_unreachable` is too
narrow — it would leave the exact case she complained about unhandled. `latency_over_budget`
does not match my figures either: the hosted p95 of 1645 ms is *below* the 2000 ms timeout,
so I would be claiming a condition my own measurements do not show. What my Step 2
classification does produce is this: a timeout, a dropped connection and a 5xx all become
`RetryableProviderError`, the resilient wrapper retries them within its attempt budget
(`model_provider_max_attempts`, 2), and when the attempts are spent it raises
`RetryableProviderError` to the worker. That raise is the observable event, it covers both
slow and down with one condition, and the hosted fixture already produced one of them in my
run — the recorded 503 on request 7.

**What on-call does when the switch happens.** Nothing, and that is the improvement.
Today the on-call engineer's answer to Elena is "nothing is broken on our side, so we
wait". With this trigger the worker moves to Ollama on its own after the budget is spent,
and on-call's job becomes telling dispatch that summaries are now slower — four to seven
seconds instead of under two — rather than telling them to wait for an unknown period.
The `provider` label on each stored summary, `ollama` instead of `hosted-fixture`, is the
trace that says which one answered.

**What I would need to measure before promising either.** For the hosted provider: real
figures instead of a replay. The fixture is one synthetic recording from one afternoon;
it says nothing about that service's availability over a season, its rate limits, its
behaviour under Coldline's real peak concurrency, or its cost. For Ollama: the same twenty
requests on the hardware Coldline would actually run, not my laptop with nine containers
and a browser beside it, and with a model chosen for summary quality rather than for being
small enough to finish. I would also want to see the summaries judged for usefulness — all
three runs measured latency, and none of them measured whether the text is any good.

**Would a server built for serving open models change my choice?** It could, and that is
the honest answer rather than yes or no. A vLLM-style server with a GPU, continuous
batching and the model kept resident attacks exactly the thing that disqualifies Ollama
today: my 4358 ms median is a cold-ish CPU generation, and those are the costs such a
server is built to remove. If it brought the p95 inside the 2000 ms timeout, the argument
for the hosted provider as primary would be much weaker, because self-hosting also removes
the credential, the quota and the dependency on someone else's afternoon. But I ran nothing
for it. Until someone measures it on the hardware Coldline would buy, it stays a reason to
run the experiment, not a reason to change the answer.
