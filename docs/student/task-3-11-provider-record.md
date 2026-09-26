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

_Write your evidence here._

## Step 2 - Classify the failures

The four situations the transport surfaces (connection refused or dropped, timeout, a
status code, a body that could not be parsed), the status codes you treated as retryable
and as terminal, the error you raise for each, and why. Then the `poe conformance` line
that reports every test passing against both adapters, with none skipped.

_Write your evidence here._

## Step 3 - Measure the emulator and the recorded hosted provider

The closing line of `poe provider-latency --provider emulator` and of
`poe provider-latency --provider hosted-fixture`, the emulator's delay setting during your
run, and the provider, model, and recording time named on the fixture's first line. One
sentence on what the p95 of each run means for a dispatcher waiting on a bad request.

_Write your evidence here._

## Step 4 - Measure a local Ollama by hand

If the run happened: the model name, the machine's CPU or GPU and memory, the time of the
run, what else ran on the machine at the time, and the closing line of
`poe provider-latency --provider ollama`. If it did not: what you tried and what stopped it,
so a reader can tell a blocked machine from a skipped Step. Either way, one sentence on what
a model on your own machine does and does not tell Elena about a self-hosted provider.

_Write your evidence here._

## Step 5 - Record the primary and fallback decision

The four decision answers in `submission.yaml` and the reasoning behind them in Elena's
terms: what a dispatcher waits during a normal summary on each provider, what on-call does
when the switch happens, which condition the worker can see that triggers it, and what
you would need to measure before promising either. Close with whether a server built for
serving open models would change your choice, and why.

_Write your evidence here._
