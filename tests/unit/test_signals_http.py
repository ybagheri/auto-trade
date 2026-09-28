from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable, Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from auto_trade.domain.exceptions import (
    InvalidSignalError,
    NoSignalAvailable,
    SignalSourceError,
)
from auto_trade.infrastructure.net import is_loopback, safe_url_summary
from auto_trade.infrastructure.signals import HttpSignalProvider

from ..helpers import signal_data

TOKEN = "http-test-token"

Responder = Callable[[BaseHTTPRequestHandler], tuple[int, bytes, dict[str, str]]]


def json_signal(signal_id: str = "signal-http-1") -> bytes:
    return json.dumps(signal_data(signal_id)).encode("utf-8")


def authenticated(responder: Responder) -> Responder:
    """Wrap a responder so it only answers a request carrying the bearer token."""

    def handler(request: BaseHTTPRequestHandler) -> tuple[int, bytes, dict[str, str]]:
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return HTTPStatus.UNAUTHORIZED, b'{"error": "unauthorized"}', {}
        return responder(request)

    return handler


def _make_handler(responder: Responder) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            status, body, headers = responder(self)
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

    return Handler


@pytest.fixture
def source() -> Iterator[Callable[[Responder], str]]:
    """Start a loopback HTTP server for one test and yield a URL factory."""
    servers: list[ThreadingHTTPServer] = []
    threads: list[threading.Thread] = []

    def start(responder: Responder) -> str:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(responder))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        threads.append(thread)
        return f"http://127.0.0.1:{server.server_address[1]}/signals/next"

    yield start

    for server in servers:
        server.shutdown()
        server.server_close()
    for thread in threads:
        thread.join(timeout=5)


def provider_for(url: str, token: str = TOKEN, **kwargs: Any) -> HttpSignalProvider:
    provider = HttpSignalProvider(url, token, **kwargs)
    provider.start()
    return provider


# -- normal operation --------------------------------------------------


def test_provider_receives_an_authenticated_signal(
    source: Callable[[Responder], str]
) -> None:
    url = source(authenticated(lambda _request: (HTTPStatus.OK, json_signal(), {})))

    provider = provider_for(url)
    try:
        signal = provider.receive()
    finally:
        provider.stop()

    assert signal.signal_id == "signal-http-1"
    assert signal.symbol == "EURUSD"


def test_provider_waits_for_the_next_signal(
    source: Callable[[Responder], str]
) -> None:
    """The endpoint may hand out a signal only once, so an idle answer is normal."""
    remaining = [1]

    def once(_request: BaseHTTPRequestHandler) -> tuple[int, bytes, dict[str, str]]:
        if remaining[0] == 0:
            return HTTPStatus.NO_CONTENT, b"", {}
        remaining[0] -= 1
        return HTTPStatus.OK, json_signal("signal-http-2"), {}

    provider = provider_for(source(authenticated(once)))
    try:
        assert provider.receive().signal_id == "signal-http-2"
        with pytest.raises(NoSignalAvailable):
            provider.receive()
    finally:
        provider.stop()


# -- fail-closed configuration -----------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5:8787/signals/next",
        "http://example.com/signals/next",
        "http://localhost.example.com/signals/next",
        "ftp://127.0.0.1/signals/next",
        "file:///C:/signals/next.json",
    ],
)
def test_provider_refuses_a_source_that_is_not_loopback_http(url: str) -> None:
    provider = HttpSignalProvider(url, TOKEN)

    with pytest.raises(SignalSourceError):
        provider.start()


def test_provider_requires_a_token() -> None:
    provider = HttpSignalProvider("http://127.0.0.1:8787/signals/next", "")

    with pytest.raises(SignalSourceError, match="token"):
        provider.start()


def test_provider_requires_a_positive_timeout() -> None:
    provider = HttpSignalProvider("http://127.0.0.1:8787/signals/next", TOKEN, timeout=0)

    with pytest.raises(SignalSourceError, match="timeout"):
        provider.start()


def test_provider_is_inert_before_it_is_started() -> None:
    provider = HttpSignalProvider("http://127.0.0.1:8787/signals/next", TOKEN)

    with pytest.raises(NoSignalAvailable, match="not started"):
        provider.receive()


def test_provider_is_inert_after_it_is_stopped(
    source: Callable[[Responder], str]
) -> None:
    url = source(authenticated(lambda _request: (HTTPStatus.OK, json_signal(), {})))
    provider = provider_for(url)
    provider.stop()

    with pytest.raises(NoSignalAvailable, match="not started"):
        provider.receive()


# -- untrusted responses -----------------------------------------------


def test_provider_reports_a_rejected_token(
    source: Callable[[Responder], str]
) -> None:
    """A wrong token is an operator error and must not look like an idle source."""
    url = source(lambda _request: (HTTPStatus.UNAUTHORIZED, b"{}", {}))
    provider = provider_for(url)
    try:
        with pytest.raises(SignalSourceError, match="rejected the configured token"):
            provider.receive()
    finally:
        provider.stop()


def test_provider_reports_a_server_error(
    source: Callable[[Responder], str]
) -> None:
    url = source(authenticated(lambda _request: (HTTPStatus.INTERNAL_SERVER_ERROR, b"", {})))
    provider = provider_for(url)
    try:
        with pytest.raises(SignalSourceError, match="HTTP 500"):
            provider.receive()
    finally:
        provider.stop()


def test_provider_reports_an_unreachable_endpoint() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    provider = provider_for(f"http://127.0.0.1:{port}/signals/next", timeout=2)

    with pytest.raises(SignalSourceError, match="unreachable"):
        provider.receive()


def test_provider_refuses_a_redirect_off_loopback(
    source: Callable[[Responder], str]
) -> None:
    """Following the redirect would resend the token to a host nobody configured."""
    url = source(
        authenticated(
            lambda _request: (
                HTTPStatus.FOUND,
                b"",
                {"Location": "http://example.com/signals/next"},
            )
        )
    )
    provider = provider_for(url)
    try:
        with pytest.raises(SignalSourceError, match="non-loopback"):
            provider.receive()
    finally:
        provider.stop()


def test_provider_bounds_the_response_size(
    source: Callable[[Responder], str]
) -> None:
    url = source(authenticated(lambda _request: (HTTPStatus.OK, json_signal(), {})))
    provider = provider_for(url, max_bytes=32)
    try:
        with pytest.raises(InvalidSignalError, match="larger than"):
            provider.receive()
    finally:
        provider.stop()


def test_provider_rejects_a_body_that_is_not_json(
    source: Callable[[Responder], str]
) -> None:
    url = source(authenticated(lambda _request: (HTTPStatus.OK, b"not json", {})))
    provider = provider_for(url)
    try:
        with pytest.raises(InvalidSignalError, match="not valid JSON"):
            provider.receive()
    finally:
        provider.stop()


def test_provider_rejects_a_body_that_is_not_a_signal(
    source: Callable[[Responder], str]
) -> None:
    url = source(authenticated(lambda _request: (HTTPStatus.OK, b'{"id": "x"}', {})))
    provider = provider_for(url)
    try:
        with pytest.raises(InvalidSignalError):
            provider.receive()
    finally:
        provider.stop()


def test_provider_reports_an_empty_body_as_idle(
    source: Callable[[Responder], str]
) -> None:
    url = source(authenticated(lambda _request: (HTTPStatus.OK, b"   ", {})))
    provider = provider_for(url)
    try:
        with pytest.raises(NoSignalAvailable):
            provider.receive()
    finally:
        provider.stop()


# -- shared network policy ---------------------------------------------


def test_loopback_policy_rejects_lookalike_hosts() -> None:
    assert is_loopback("127.0.0.1")
    assert not is_loopback("127.0.0.1.example.com")
    assert not is_loopback("0.0.0.0")


def test_url_summary_drops_credentials_and_query() -> None:
    summary = safe_url_summary("http://user:secret@127.0.0.1:8787/signals/next?token=secret")

    assert summary == "http://127.0.0.1:8787/signals/next"
    assert "secret" not in summary
    assert safe_url_summary("") == ""
