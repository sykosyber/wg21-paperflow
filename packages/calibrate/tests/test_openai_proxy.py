# Copyright (c) 2026 sykosyber (mateorobles100@icloud.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
"""The proxy's request rewrite, and the proxy end to end against a fake upstream."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from calibrate import openai_proxy


def test_no_thinking_becomes_reasoning_effort_none() -> None:
    out = openai_proxy.rewrite_request({
        "model": "m", "messages": [], "temperature": 0.3, "max_tokens": 50,
        "chat_template_kwargs": {"enable_thinking": False}})
    assert out == {"model": "m", "messages": [], "temperature": 0.3,
                   "max_completion_tokens": 50, "reasoning_effort": "none"}


def test_no_kwargs_at_all_also_turns_reasoning_off() -> None:
    assert openai_proxy.rewrite_request({"model": "m"})["reasoning_effort"] == "none"


def test_asking_for_thinking_keeps_the_model_default() -> None:
    out = openai_proxy.rewrite_request({"model": "m", "chat_template_kwargs": {"enable_thinking": True}})
    assert "reasoning_effort" not in out and "chat_template_kwargs" not in out


def test_an_explicit_effort_and_limit_are_kept() -> None:
    out = openai_proxy.rewrite_request({"model": "m", "reasoning_effort": "low",
                                        "max_tokens": 9, "max_completion_tokens": 20})
    assert out["reasoning_effort"] == "low" and out["max_completion_tokens"] == 20
    assert "max_tokens" not in out


def test_the_input_is_not_mutated() -> None:
    body = {"model": "m", "max_tokens": 5, "chat_template_kwargs": {"enable_thinking": False}}
    openai_proxy.rewrite_request(body)
    assert body == {"model": "m", "max_tokens": 5, "chat_template_kwargs": {"enable_thinking": False}}


class _Upstream(BaseHTTPRequestHandler):
    seen: list[tuple[str, dict, str]] = []

    def log_message(self, *args) -> None:
        return None

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append((self.path, body, self.headers["Authorization"]))
        payload = b'data: {"choices":[{"delta":{"content":"SCORE: 1"}}]}\n\ndata: [DONE]\n\n'
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def proxied(monkeypatch):
    """Starts a fake upstream and a proxy in front of it; yields a request function."""
    servers = []
    _Upstream.seen = []

    def start(max_requests=None):
        upstream = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        # The proxy speaks HTTPS upstream; for the test, point it at plain HTTP.
        monkeypatch.setattr(openai_proxy.http.client, "HTTPSConnection", openai_proxy.http.client.HTTPConnection)
        handler = openai_proxy.make_handler("test-key", f"http://127.0.0.1:{upstream.server_address[1]}",
                                            max_requests=max_requests)
        proxy = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        servers.extend([proxy, upstream])

        def send() -> tuple[int, str, str]:
            req = urllib.request.Request(
                f"http://127.0.0.1:{proxy.server_address[1]}/v1/chat/completions",
                data=json.dumps({"model": "gpt-6-luna", "messages": [{"role": "user", "content": "x"}],
                                 "stream": True, "temperature": 0.3, "max_tokens": 64,
                                 "chat_template_kwargs": {"enable_thinking": False}}).encode(),
                headers={"Content-Type": "application/json", "Authorization": "Bearer gateway-placeholder"})
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status, resp.headers["Content-Type"], resp.read().decode()
            except urllib.error.HTTPError as error:
                return error.code, "", ""
        return send

    yield start
    for server in servers:
        server.shutdown()


def test_the_proxy_rewrites_and_passes_the_response_through(proxied) -> None:
    status, ctype, text = proxied()()
    assert (status, ctype) == (200, "text/event-stream")
    assert "SCORE: 1" in text and text.endswith("data: [DONE]\n\n")
    path, body, auth = _Upstream.seen[0]
    assert path == "/v1/chat/completions"
    assert auth == "Bearer test-key"
    assert body["reasoning_effort"] == "none" and body["max_completion_tokens"] == 64
    assert "chat_template_kwargs" not in body and "max_tokens" not in body


def test_the_request_cap_refuses_without_reaching_the_upstream(proxied) -> None:
    send = proxied(max_requests=2)
    assert [send()[0] for _ in range(4)] == [200, 200, 429, 429]
    assert len(_Upstream.seen) == 2


def test_message_chars() -> None:
    assert openai_proxy.message_chars({"messages": [{"role": "user", "content": "abcd"},
                                                    {"role": "system", "content": "ef"}]}) == 6
