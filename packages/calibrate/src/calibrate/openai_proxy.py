# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""A loopback proxy that lets the Runvil gateway reach OpenAI's reasoning models.

Runvil's harness client speaks the convention of self-hosted servers (vLLM,
llama.cpp): "no thinking" is `chat_template_kwargs.enable_thinking = false`,
and the output limit is `max_tokens`. OpenAI's reasoning models, such as
gpt-6-luna, refuse all three of those with a 400: an unknown parameter, a
renamed one, and any `temperature` but 1 unless reasoning is switched off with
`reasoning_effort = "none"`. paperweight's Lua asks for temperature 0.3.

The proxy sits between the gateway and api.openai.com and rewrites only the
request body (`rewrite_request`); responses, streamed or not, pass through
byte for byte. It holds the API key, read once from an environment variable,
so the gateway's endpoint key is a placeholder and the real key exists in one
process only. It binds to loopback and is meant for calibration runs, not
production.

    uv run python -m calibrate.openai_proxy --port 18090 --key-env OPENAI_API_KEY_V2
"""

from __future__ import annotations

import argparse
import http.client
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

log = logging.getLogger("calibrate.openai_proxy")

UPSTREAM = "https://api.openai.com"
DEFAULT_PORT = 18090
UPSTREAM_TIMEOUT_SECONDS = 600
CHUNK_BYTES = 8192
# Response headers that describe the upstream connection, not the body.
HOP_HEADERS = frozenset({"connection", "transfer-encoding", "keep-alive", "content-length",
                         "content-encoding"})


def rewrite_request(body: dict) -> dict:
    """The chat request as OpenAI's reasoning models accept it.

    - `chat_template_kwargs` is dropped. When it does not ask for thinking,
      `reasoning_effort` becomes "none" unless the caller set one; when it
      does, the model's own default effort stands.
    - `max_tokens` becomes `max_completion_tokens`.
    Everything else passes through unchanged.
    """
    out = dict(body)
    kwargs = out.pop("chat_template_kwargs", None)
    wants_thinking = isinstance(kwargs, dict) and kwargs.get("enable_thinking") is True
    if not wants_thinking:
        out.setdefault("reasoning_effort", "none")
    if "max_tokens" in out:
        out.setdefault("max_completion_tokens", out["max_tokens"])
        del out["max_tokens"]
    return out


def message_chars(body: dict) -> int:
    """Characters of message content in a chat request: about 4 per input token."""
    total = 0
    for message in body.get("messages") or []:
        if isinstance(message, dict):
            content = message.get("content")
            total += len(content) if isinstance(content, str) else len(json.dumps(content or ""))
    return total


class _Counter:
    def __init__(self, max_requests: int | None) -> None:
        self.lock = threading.Lock()
        self.max_requests = max_requests
        self.admitted = 0
        self.requests = 0
        self.failures = 0
        self.chars = 0

    def admit(self, chars: int) -> bool:
        """Reserves a slot under the cap; False once the cap is spent."""
        with self.lock:
            if self.max_requests is not None and self.admitted >= self.max_requests:
                return False
            self.admitted += 1
            self.chars += chars
            return True

    def add(self, ok: bool) -> tuple[int, int, int]:
        with self.lock:
            self.requests += 1
            self.failures += 0 if ok else 1
            return self.requests, self.failures, self.chars


def make_handler(api_key: str, upstream: str = UPSTREAM,
                 max_requests: int | None = None) -> type[BaseHTTPRequestHandler]:
    """The proxy's request handler. With `max_requests`, every chat request past
    that many is refused with a 429 and never reaches the upstream."""
    target = urlsplit(upstream)
    counter = _Counter(max_requests)

    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.0: the connection closes after each response, so a streamed
        # body needs no length and no chunked framing.
        protocol_version = "HTTP/1.0"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
            return None

        def _forward(self, method: str, body: bytes | None) -> None:
            conn = http.client.HTTPSConnection(target.hostname or "", target.port or 443,
                                               timeout=UPSTREAM_TIMEOUT_SECONDS)
            headers = {"Authorization": f"Bearer {api_key}", "Accept": self.headers.get("Accept", "*/*")}
            if body is not None:
                headers["Content-Type"] = "application/json"
            try:
                conn.request(method, self.path, body=body, headers=headers)
                resp = conn.getresponse()
                self.send_response(resp.status)
                for name, value in resp.getheaders():
                    if name.lower() not in HOP_HEADERS:
                        self.send_header(name, value)
                self.end_headers()
                while chunk := resp.read1(CHUNK_BYTES):
                    self.wfile.write(chunk)
                    self.wfile.flush()
                n, failed, chars = counter.add(resp.status < 400)
                if resp.status >= 400 or n % 250 == 0:
                    log.info("%s %s -> %d (%d requests, %d failed, about %.2fM input tokens)",
                             method, self.path, resp.status, n, failed, chars / 4e6)
            except OSError as error:
                # One failed call is reported to the caller and counted; the proxy keeps serving.
                counter.add(False)
                log.warning("%s %s failed upstream: %s", method, self.path, error)
                self.send_error(502, "upstream unreachable")
            finally:
                conn.close()

        def do_GET(self) -> None:
            self._forward("GET", None)

        def do_POST(self) -> None:
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                self.send_error(400, "request body is not JSON")
                return
            if self.path.rstrip("/").endswith("/chat/completions") and isinstance(body, dict):
                if not counter.admit(message_chars(body)):
                    log.warning("request cap of %s reached: refusing %s", counter.max_requests, self.path)
                    self.send_error(429, "the proxy's request cap is reached")
                    return
                body = rewrite_request(body)
            self._forward("POST", json.dumps(body).encode("utf-8"))

    return Handler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="openai-proxy: %(message)s")
    parser = argparse.ArgumentParser(description="Loopback proxy from the Runvil gateway to OpenAI.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--key-env", default="OPENAI_API_KEY", help="environment variable holding the API key")
    parser.add_argument("--max-requests", type=int, help="refuse chat requests past this many (a spending cap)")
    args = parser.parse_args()
    api_key = os.environ.get(args.key_env, "").strip()
    if not api_key:
        raise SystemExit(f"openai-proxy: {args.key_env} is not set")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(api_key, max_requests=args.max_requests))
    log.info("listening on 127.0.0.1:%d, forwarding to %s, cap %s", args.port, UPSTREAM,
             args.max_requests or "none")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
