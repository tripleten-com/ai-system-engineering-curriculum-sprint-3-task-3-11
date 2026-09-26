"""Coldline.

===================

File:              tests/doubles/ollama_stub.py
Component:         Test doubles — Ollama stub
Purpose:           Answer like Ollama's generate endpoint, with failures selectable per request.
Interacts With:    src/adapters/model/ollama.py, the conformance tests, `poe ollama-stub`
Sprint/Task:       Sprint 3 — Project 3 / Task 3.11
Concepts:          Test double, fake server, fault injection, contract conformance
Tools:             Python 3.12, http.server, threading

A small fake Ollama. ``POST /api/generate`` answers the way Ollama does: one JSON object
with the generated text in ``response`` when the request says ``"stream": false``, and a
stream of JSON fragments when it does not, exactly as Ollama streams by default. The text
it generates is fixed in shape and echoes the prompt, so a summary names whatever the
prompt named. ``GET /api/tags`` deliberately lists no models: the latency harness asks it
first, and refuses to record a ``ran`` Ollama run against this stub.

Failures are selected per request. The conformance tests queue one with ``fail_next``;
``poe ollama-stub`` runs the stub in the foreground so a request sent by hand can select
one with the ``X-Coldline-Stub-Failure`` header:

    timeout           wait longer than the adapter's timeout before answering
    drop              close the connection without answering
    server_error      answer 503 with an error body
    client_error      answer 400 with an error body
    not_json          answer 200 with an HTML page
    missing_response  answer 200 with a JSON object that has no `response` field
    empty_response    answer 200 with an empty `response`
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from tests.runtime_config import host_port

# The model name the stub's replies carry. A parser that copies a reply's `model` field
# into the summary's label reports this, not the adapter's own name.
STUB_MODEL = "coldline-stub:latest"
GENERATE_PATH = "/api/generate"
TAGS_PATH = "/api/tags"
FAILURE_HEADER = "X-Coldline-Stub-Failure"
FAILURES = (
    "timeout",
    "drop",
    "server_error",
    "client_error",
    "not_json",
    "missing_response",
    "empty_response",
)
# How long the `timeout` failure waits before answering; the adapter under test uses a
# shorter per-request timeout, so its own timeout is what ends the call.
STALL_SECONDS = 2.0
STUB_PORT_SETTING = "COLDLINE_OLLAMA_STUB_HOST_PORT"
# Deliberately not Ollama's own 11434, so a stub in the foreground never collides with a
# real Ollama on the same machine.
DEFAULT_STUB_PORT = 11435


class OllamaStub:
    """Run the fake Ollama on a background thread and record what it was sent."""

    def __init__(self, *, host: str = "127.0.0.1", port: int = 0, verbose: bool = False) -> None:
        """Bind to ``host``:``port`` on ``start``; port 0 picks a free one."""
        self._host = host
        self._requested_port = port
        self._verbose = verbose
        self._server: _StubServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._queued: list[str] = []
        # Every body sent to the generate endpoint, decoded, or {"raw": text} when not JSON.
        self.requests: list[dict[str, Any]] = []

    @property
    def port(self) -> int:
        """Return the port the stub is listening on."""
        if self._server is None:
            raise RuntimeError("the stub is not started")
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        """Return the base URL an adapter points at to reach this stub."""
        return f"http://{self._host}:{self.port}"

    def start(self) -> None:
        """Start serving on a daemon thread."""
        if self._server is not None:
            return
        self._server = _StubServer((self._host, self._requested_port), _Handler, self)
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="ollama-stub", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop serving; a handler still stalling on purpose is left to end on its own."""
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._server = None
        self._thread = None

    def fail_next(self, kind: str) -> None:
        """Make the next generate request fail the given way."""
        if kind not in FAILURES:
            raise ValueError(f"unknown stub failure {kind!r}; choose one of {', '.join(FAILURES)}")
        with self._lock:
            self._queued.append(kind)

    def take_failure(self, header_value: str | None) -> str | None:
        """Return the failure the next request should produce, from the queue or the header."""
        with self._lock:
            if self._queued:
                return self._queued.pop(0)
        if header_value in FAILURES:
            return header_value
        return None

    def reset(self) -> None:
        """Forget recorded requests and queued failures."""
        with self._lock:
            self._queued.clear()
        self.requests.clear()

    def note(self, message: str) -> None:
        """Print one line about a request when running in the foreground."""
        if self._verbose:
            print(message, file=sys.stderr, flush=True)


class _StubServer(ThreadingHTTPServer):
    """Serve one stub; handler threads are daemons and never block a stop."""

    daemon_threads = True
    block_on_close = False

    def __init__(
        self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], stub: OllamaStub
    ) -> None:
        """Bind the socket and remember the stub the handlers report to."""
        super().__init__(address, handler)
        self.stub = stub


class _Handler(BaseHTTPRequestHandler):
    """Answer one request the way Ollama would, or the way the selected failure says."""

    def log_message(self, format: str, *args: Any) -> None:
        """Keep the default request log off the test output."""

    def do_GET(self) -> None:
        """Answer the root like Ollama does and refuse to list models."""
        if self.path == "/":
            self._send_text(200, "Ollama stub is running", "text/plain")
        elif self.path == TAGS_PATH:
            self._send_json(
                404,
                {"error": "the supplied stub lists no models; the ollama run needs a real Ollama"},
            )
        else:
            self._send_json(404, {"error": f"{self.path} is not served by the stub"})

    def do_POST(self) -> None:
        """Answer one generate request, or fail it the selected way."""
        stub = cast(_StubServer, self.server).stub
        if self.path != GENERATE_PATH:
            self._send_json(404, {"error": f"{self.path} is not served by the stub"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        try:
            decoded = json.loads(raw)
        except ValueError:
            decoded = None
        body: dict[str, Any] = decoded if isinstance(decoded, dict) else {"raw": raw}
        stub.requests.append(body)
        failure = stub.take_failure(self.headers.get(FAILURE_HEADER))
        prompt = body.get("prompt")
        streaming = body.get("stream") is not False
        stub.note(
            f"POST {GENERATE_PATH} model={body.get('model')!r} stream={body.get('stream')!r} "
            f"failure={failure or 'none'}"
        )
        try:
            self._answer(failure, prompt if isinstance(prompt, str) else "", streaming)
        except OSError:
            # The client gave up (a timeout that fired, a dropped connection); nothing to do.
            pass

    def _answer(self, failure: str | None, prompt: str, streaming: bool) -> None:
        """Send the reply the selected failure, or a normal request, calls for."""
        if failure == "timeout":
            time.sleep(STALL_SECONDS)
            failure = None
        if failure == "drop":
            self._drop()
            return
        if failure == "server_error":
            self._send_json(503, {"error": "model runner is overloaded, try again later"})
            return
        if failure == "client_error":
            self._send_json(400, {"error": "invalid request: the body is not what generate takes"})
            return
        if failure == "not_json":
            self._send_text(200, "<html><body><h1>502 Bad Gateway</h1></body></html>", "text/html")
            return
        if failure == "missing_response":
            self._send_json(200, {"model": STUB_MODEL, "created_at": _now(), "done": True})
            return
        if failure == "empty_response":
            self._send_json(200, _reply("") | {"done_reason": "length"})
            return
        text = _generated_text(prompt)
        if streaming:
            self._stream(text)
            return
        self._send_json(200, _reply(text))

    def _drop(self) -> None:
        """Close the connection without answering, as a crashed server does."""
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()

    def _stream(self, text: str) -> None:
        """Answer as Ollama streams: several JSON fragments, one per line, then `done`."""
        words = text.split(" ")
        fragments = [
            {"model": STUB_MODEL, "created_at": _now(), "response": word + " ", "done": False}
            for word in words[:3]
        ]
        fragments.append(_reply(" ".join(words[3:])) | {"done": True})
        payload = "".join(json.dumps(fragment) + "\n" for fragment in fragments).encode("utf-8")
        self._send_bytes(200, payload, "application/x-ndjson")

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        """Send one JSON object with the given status."""
        self._send_bytes(status, json.dumps(payload).encode("utf-8"), "application/json")

    def _send_text(self, status: int, text: str, content_type: str) -> None:
        """Send one text body with the given status and content type."""
        self._send_bytes(status, text.encode("utf-8"), content_type)

    def _send_bytes(self, status: int, payload: bytes, content_type: str) -> None:
        """Send one complete response and close the connection afterwards."""
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)


def _now() -> str:
    """Return a timestamp in the shape Ollama's `created_at` carries."""
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _generated_text(prompt: str) -> str:
    """Return the stub's fixed-shape summary, which echoes the prompt it was given."""
    one_line = " ".join(prompt.split())
    return f"Stub summary. The prompt read: {one_line}" if one_line else "Stub summary."


def _reply(text: str) -> dict[str, Any]:
    """Return a complete generate reply in the shape Ollama returns when it is done."""
    return {
        "model": STUB_MODEL,
        "created_at": _now(),
        "response": text,
        "done": True,
        "done_reason": "stop",
        "total_duration": 4_200_000,
        "load_duration": 900_000,
        "prompt_eval_count": 32,
        "eval_count": 24,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the stub in the foreground until interrupted."""
    parser = argparse.ArgumentParser(description="Run the supplied Ollama stub in the foreground.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--port",
        type=int,
        default=host_port(STUB_PORT_SETTING, DEFAULT_STUB_PORT),
        help=f"defaults to {STUB_PORT_SETTING} or {DEFAULT_STUB_PORT}",
    )
    args = parser.parse_args(argv)
    stub = OllamaStub(host=args.host, port=args.port, verbose=True)
    stub.start()
    print(
        f"Ollama stub listening on {stub.base_url}\n"
        f"  POST {GENERATE_PATH} with a JSON body; GET / answers like Ollama, GET {TAGS_PATH} "
        "lists no models\n"
        f"  select a failure per request with the {FAILURE_HEADER} header: "
        f"{', '.join(FAILURES)}\n"
        "  press Ctrl-C to stop",
        file=sys.stderr,
        flush=True,
    )
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        stub.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
