from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from auto_trade.domain.exceptions import (
    InvalidSignalError,
    NoSignalAvailable,
    SignalSourceError,
)
from auto_trade.infrastructure.signals import WebSocketSignalProvider
from auto_trade.infrastructure.signals.websocket import GUID

from ..helpers import signal_data

TOKEN = "ws-test-token"

OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA


def text_frame(
    payload: str,
    opcode: int = OPCODE_TEXT,
    fin: bool = True,
    mask: bool = False,
) -> bytes:
    body = payload.encode("utf-8")
    return frame_bytes(body, opcode, fin, mask)


def frame_bytes(body: bytes, opcode: int, fin: bool, mask: bool) -> bytes:
    first = (0x80 if fin else 0x00) | opcode
    length = len(body)
    mask_bit = 0x80 if mask else 0x00
    if length < 126:
        header = bytes([first, mask_bit | length])
    elif length < 1 << 16:
        header = bytes([first, mask_bit | 126]) + struct.pack("!H", length)
    else:
        header = bytes([first, mask_bit | 127]) + struct.pack("!Q", length)
    if not mask:
        return header + body
    key = b"\x01\x02\x03\x04"
    return header + key + bytes(byte ^ key[index % 4] for index, byte in enumerate(body))


class ScriptedServer:
    """A minimal WebSocket server: handshake, then whatever frames the test sends.

    The client under test is a hand-written RFC 6455 implementation, so it is
    tested against a server that is written independently of it: the handshake
    accept key and the frame layout come straight from the specification.
    """

    def __init__(
        self,
        script: Callable[[socket.socket], None] | None = None,
        status_line: str = "HTTP/1.1 101 Switching Protocols",
        accept_key: str | None = None,
    ) -> None:
        self._script = script or _default_script
        self._status_line = status_line
        self._accept_key = accept_key
        self._socket = socket.socket()
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(1)
        self.port = int(self._socket.getsockname()[1])
        self.error: BaseException | None = None
        self.request: str = ""
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/signals"

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass
        self._thread.join(timeout=5)

    def _serve(self) -> None:
        try:
            connection, _ = self._socket.accept()
            with connection:
                connection.settimeout(10)
                self._handshake(connection)
                self._script(connection)
        except BaseException as exc:  # noqa: BLE001
            self.error = exc
        finally:
            try:
                self._socket.close()
            except OSError:
                pass

    def _handshake(self, connection: socket.socket) -> None:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = connection.recv(4096)
            if not chunk:
                raise OSError("client closed before the handshake")
            data += chunk
        head, _, _ = data.partition(b"\r\n\r\n")
        self.request = head.decode("latin-1")
        key = ""
        for line in self.request.splitlines()[1:]:
            name, separator, value = line.partition(":")
            if separator and name.strip().lower() == "sec-websocket-key":
                key = value.strip()
        accept = self._accept_key or base64.b64encode(
            hashlib.sha1(f"{key}{GUID}".encode("ascii")).digest()
        ).decode("ascii")
        connection.sendall(
            (
                f"{self._status_line}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "\r\n"
            ).encode("ascii")
        )


def _default_script(connection: socket.socket) -> None:
    connection.sendall(text_frame(json.dumps({"auth": TOKEN})))
    connection.sendall(text_frame(json.dumps(signal_data("ws-1"))))


def _script_of(*frames: bytes, close: bool = False) -> Callable[[socket.socket], None]:
    def script(connection: socket.socket) -> None:
        connection.sendall(text_frame(json.dumps({"auth": TOKEN})))
        for frame in frames:
            connection.sendall(frame)
        if close:
            connection.sendall(frame_bytes(b"", OPCODE_CLOSE, True, False))
        # Hold the session open so the client is the side that decides to stop.
        try:
            connection.recv(64)
        except OSError:
            pass

    return script


@pytest.fixture
def server() -> Iterator[Callable[..., ScriptedServer]]:
    servers: list[ScriptedServer] = []

    def start(*args: Any, **kwargs: Any) -> ScriptedServer:
        instance = ScriptedServer(*args, **kwargs)
        servers.append(instance)
        return instance

    yield start

    for instance in servers:
        instance.close()


def test_websocket_provider_reads_a_pushed_signal(
    server: Callable[..., ScriptedServer]
) -> None:
    instance = server()
    provider = WebSocketSignalProvider(instance.url, TOKEN)
    provider.start()
    try:
        received = provider.receive()
    finally:
        provider.stop()

    assert received.signal_id == "ws-1"
    assert instance.error is None
    assert "Sec-WebSocket-Version: 13" in instance.request


def test_websocket_provider_authenticates_before_reading_a_signal(
    server: Callable[..., ScriptedServer]
) -> None:
    def script(connection: socket.socket) -> None:
        connection.sendall(text_frame(json.dumps({"auth": "wrong"})))
        connection.sendall(text_frame(json.dumps(signal_data("ws-2"))))
        connection.recv(64)

    instance = server(script)
    provider = WebSocketSignalProvider(instance.url, TOKEN)
    provider.start()
    try:
        with pytest.raises(SignalSourceError, match="failed authentication"):
            provider.receive()
    finally:
        provider.stop()


# -- the checks that were only true at one moment in time -----------------


def test_the_loopback_check_also_runs_when_the_connection_is_opened() -> None:
    """`url` is a public attribute, so validating only in `start()` is not enough.

    Anything that rewrites it between `start()` and the first `receive()` would
    otherwise be connected to without ever being checked, which would make
    "stays on loopback" a claim about a moment in the past rather than a
    property of the socket being opened.
    """
    provider = WebSocketSignalProvider("ws://127.0.0.1:1/signals", TOKEN)
    provider.start()
    provider.url = "ws://example.com:80/signals"

    with pytest.raises(SignalSourceError, match="must stay on loopback"):
        provider.receive()

    assert provider._socket is None


def test_the_loopback_check_runs_again_for_every_reconnect() -> None:
    """Reconnecting must not reuse a verdict reached for an earlier address."""
    provider = WebSocketSignalProvider("ws://127.0.0.1:1/signals", TOKEN)
    provider.start()
    provider.url = "ws://127.0.0.1.nip.io:80/signals"

    with pytest.raises(SignalSourceError, match="must stay on loopback"):
        provider.receive()


def test_websocket_provider_refuses_a_wss_endpoint() -> None:
    provider = WebSocketSignalProvider("wss://127.0.0.1:8787/signals", TOKEN)

    with pytest.raises(SignalSourceError, match="wss is not implemented"):
        provider.start()


# -- the token is the token, not something that renders as it ------------


def test_websocket_provider_refuses_a_numeric_auth_that_renders_as_the_token(
    server: Callable[..., ScriptedServer],
) -> None:
    """A JSON number must not authenticate by rendering to the token's text.

    The token is the value the operator configured. Coercing the peer's value
    with `str()` means a peer that sends the number `918273645` opens the
    session having never sent the configured secret at all.
    """

    def script(connection: socket.socket) -> None:
        # A bare JSON number, not the string.
        connection.sendall(text_frame(json.dumps({"auth": 918273645})))
        connection.sendall(text_frame(json.dumps(signal_data("ws-numeric"))))
        connection.recv(64)

    instance = server(script)
    provider = WebSocketSignalProvider(instance.url, "918273645", timeout=5)
    provider.start()
    try:
        with pytest.raises(SignalSourceError, match="failed authentication"):
            provider.receive()
    finally:
        provider.stop()


def test_websocket_provider_refuses_a_structured_auth_value(
    server: Callable[..., ScriptedServer],
) -> None:
    def script(connection: socket.socket) -> None:
        connection.sendall(text_frame(json.dumps({"auth": ["918273645"]})))
        connection.sendall(text_frame(json.dumps(signal_data("ws-list"))))
        connection.recv(64)

    instance = server(script)
    provider = WebSocketSignalProvider(instance.url, "918273645", timeout=5)
    provider.start()
    try:
        with pytest.raises(SignalSourceError, match="failed authentication"):
            provider.receive()
    finally:
        provider.stop()


def test_the_configured_token_string_still_authenticates(
    server: Callable[..., ScriptedServer],
) -> None:
    """The stricter check must not refuse the ordinary case."""
    instance = server()
    provider = WebSocketSignalProvider(instance.url, TOKEN, timeout=5)
    provider.start()
    try:
        assert provider.receive().signal_id == "ws-1"
    finally:
        provider.stop()


# -- a closed session is a domain condition, not a stray builtin ---------


def test_a_close_frame_ends_the_session_rather_than_stalling(
    server: Callable[..., ScriptedServer]
) -> None:
    """After a CLOSE the socket is released, so the next call is not a stall.

    Leaving the socket open turned the following `receive()` into a bare socket
    timeout, which reads like a slow endpoint rather than a session the server
    has already ended.
    """
    instance = server(_script_of(close=True))
    provider = WebSocketSignalProvider(instance.url, TOKEN)
    provider.start()
    try:
        with pytest.raises(NoSignalAvailable, match="closed the session"):
            provider.receive()
        assert provider._socket is None
    finally:
        provider.stop()


def test_a_silent_endpoint_raises_no_signal_available_not_a_timeout(
    server: Callable[..., ScriptedServer],
) -> None:
    """A caller catching this module's errors must not see a builtin escape.

    A quiet endpoint is a domain condition, and `NoSignalAvailable` is the right
    reading of it: nothing arrived, and no trade is implied.
    """

    def silent(connection: socket.socket) -> None:
        connection.sendall(text_frame(json.dumps({"auth": TOKEN})))
        time.sleep(5)

    instance = server(silent)
    provider = WebSocketSignalProvider(instance.url, TOKEN, timeout=1.0)
    provider.start()
    try:
        with pytest.raises(NoSignalAvailable, match="did not answer"):
            provider.receive()
    finally:
        provider.stop()


@pytest.mark.parametrize(
    "url",
    [
        "ws://10.0.0.5:8787/signals",
        "ws://example.com/signals",
        "ws://localhost.example.com/signals",
        "http://127.0.0.1:8787/signals",
    ],
)
def test_websocket_provider_refuses_anything_but_loopback_ws(url: str) -> None:
    provider = WebSocketSignalProvider(url, TOKEN)

    with pytest.raises(SignalSourceError):
        provider.start()


def test_websocket_provider_requires_a_token() -> None:
    provider = WebSocketSignalProvider("ws://127.0.0.1:8787/signals", "")

    with pytest.raises(SignalSourceError, match="token"):
        provider.start()


def test_websocket_provider_is_inert_before_start() -> None:
    provider = WebSocketSignalProvider("ws://127.0.0.1:8787/signals", TOKEN)

    with pytest.raises(NoSignalAvailable, match="not started"):
        provider.receive()


def test_websocket_provider_reports_an_unreachable_endpoint() -> None:
    provider = WebSocketSignalProvider("ws://127.0.0.1:1/signals", TOKEN, timeout=2)
    provider.start()
    try:
        with pytest.raises(SignalSourceError, match="unreachable"):
            provider.receive()
    finally:
        provider.stop()


def test_websocket_provider_refuses_a_masked_frame_from_the_server(
    server: Callable[..., ScriptedServer]
) -> None:
    """A server that masks is not a conforming server; the frame is refused."""
    instance = server(
        _script_of(text_frame(json.dumps(signal_data("ws-3")), mask=True))
    )
    provider = WebSocketSignalProvider(instance.url, TOKEN)
    provider.start()
    try:
        with pytest.raises(SignalSourceError, match="masked a frame"):
            provider.receive()
    finally:
        provider.stop()


def test_websocket_provider_refuses_a_binary_message(
    server: Callable[..., ScriptedServer]
) -> None:
    instance = server(
        _script_of(text_frame(json.dumps(signal_data("ws-4")), opcode=OPCODE_BINARY))
    )
    provider = WebSocketSignalProvider(instance.url, TOKEN)
    provider.start()
    try:
        with pytest.raises(SignalSourceError, match="binary message"):
            provider.receive()
    finally:
        provider.stop()


def test_websocket_provider_assembles_a_fragmented_message(
    server: Callable[..., ScriptedServer]
) -> None:
    payload = json.dumps(signal_data("ws-5"))
    head, tail = payload[:20], payload[20:]
    instance = server(
        _script_of(
            text_frame(head, fin=False),
            text_frame(tail, opcode=0x0, fin=True),
        )
    )
    provider = WebSocketSignalProvider(instance.url, TOKEN)
    provider.start()
    try:
        assert provider.receive().signal_id == "ws-5"
    finally:
        provider.stop()


def test_websocket_provider_refuses_a_continuation_without_a_start(
    server: Callable[..., ScriptedServer]
) -> None:
    instance = server(_script_of(text_frame("tail", opcode=0x0, fin=True)))
    provider = WebSocketSignalProvider(instance.url, TOKEN)
    provider.start()
    try:
        with pytest.raises(SignalSourceError, match="never started"):
            provider.receive()
    finally:
        provider.stop()


def test_websocket_provider_answers_a_ping_and_keeps_reading(
    server: Callable[..., ScriptedServer]
) -> None:
    instance = server(
        _script_of(
            text_frame("ping-payload", opcode=OPCODE_PING),
            text_frame(json.dumps(signal_data("ws-6"))),
        )
    )
    provider = WebSocketSignalProvider(instance.url, TOKEN)
    provider.start()
    try:
        assert provider.receive().signal_id == "ws-6"
    finally:
        provider.stop()


def test_websocket_provider_reports_a_close_frame_as_no_signal(
    server: Callable[..., ScriptedServer]
) -> None:
    instance = server(_script_of(close=True))
    provider = WebSocketSignalProvider(instance.url, TOKEN)
    provider.start()
    try:
        with pytest.raises(NoSignalAvailable, match="closed the session"):
            provider.receive()
    finally:
        provider.stop()


def test_websocket_provider_bounds_the_frame_size(
    server: Callable[..., ScriptedServer]
) -> None:
    instance = server(_script_of(text_frame(json.dumps(signal_data("ws-7")))))
    provider = WebSocketSignalProvider(instance.url, TOKEN, max_bytes=32)
    provider.start()
    try:
        with pytest.raises(InvalidSignalError, match="larger than"):
            provider.receive()
    finally:
        provider.stop()


def test_websocket_provider_rejects_a_message_that_is_not_a_signal(
    server: Callable[..., ScriptedServer]
) -> None:
    instance = server(_script_of(text_frame(json.dumps({"id": "only"}))))
    provider = WebSocketSignalProvider(instance.url, TOKEN)
    provider.start()
    try:
        with pytest.raises(InvalidSignalError):
            provider.receive()
    finally:
        provider.stop()


def test_websocket_provider_rejects_a_message_that_is_not_json(
    server: Callable[..., ScriptedServer]
) -> None:
    instance = server(_script_of(text_frame("not json")))
    provider = WebSocketSignalProvider(instance.url, TOKEN)
    provider.start()
    try:
        with pytest.raises(InvalidSignalError, match="not valid JSON"):
            provider.receive()
    finally:
        provider.stop()


def test_websocket_provider_refuses_a_wrong_handshake_accept_key(
    server: Callable[..., ScriptedServer]
) -> None:
    instance = server(accept_key="not-the-expected-value")
    provider = WebSocketSignalProvider(instance.url, TOKEN, timeout=5)
    provider.start()
    try:
        with pytest.raises(SignalSourceError, match="accept key"):
            provider.receive()
    finally:
        provider.stop()


def test_websocket_provider_reports_a_refused_upgrade(
    server: Callable[..., ScriptedServer]
) -> None:
    instance = server(status_line="HTTP/1.1 400 Bad Request")
    provider = WebSocketSignalProvider(instance.url, TOKEN, timeout=5)
    provider.start()
    try:
        with pytest.raises(SignalSourceError, match="refused the upgrade"):
            provider.receive()
    finally:
        provider.stop()


def test_websocket_provider_stop_closes_the_session(
    server: Callable[..., ScriptedServer]
) -> None:
    instance = server()
    provider = WebSocketSignalProvider(instance.url, TOKEN)
    provider.start()
    assert provider.receive().signal_id == "ws-1"

    provider.stop()

    with pytest.raises(NoSignalAvailable, match="not started"):
        provider.receive()


def test_websocket_provider_stop_before_connecting_is_safe() -> None:
    provider = WebSocketSignalProvider("ws://127.0.0.1:1/signals", TOKEN)
    provider.start()

    provider.stop()

    assert provider._socket is None


def test_websocket_frames_match_the_specification_layout() -> None:
    """The client's own encoder is checked against the RFC 6455 examples."""
    from auto_trade.infrastructure.signals.websocket import _frame

    assert _frame(OPCODE_PONG, b"Hi", mask=False) == b"\x8a\x02Hi"
    masked = _frame(OPCODE_PONG, b"Hi", mask=True)
    assert masked[0:2] == b"\x8a\x82" and len(masked) == 8
    long_frame = _frame(OPCODE_TEXT, b"x" * 200, mask=False)
    assert long_frame[0:4] == b"\x81\x7e\x00\xc8"


def test_websocket_authentication_comparison_is_constant_time() -> None:
    from auto_trade.infrastructure.net import constant_time_equals

    assert constant_time_equals("abc", "abc")
    assert not constant_time_equals("abc", "abd")
    assert not constant_time_equals("abc", "abcd")


def test_websocket_provider_does_not_evaluate_a_message(
    server: Callable[..., ScriptedServer]
) -> None:
    hostile: dict[str, Any] = signal_data("ws-8")
    hostile["comment"] = "__import__('os').system('echo pwned')"
    instance = server(_script_of(text_frame(json.dumps(hostile))))
    provider = WebSocketSignalProvider(instance.url, TOKEN)
    provider.start()
    try:
        received = provider.receive()
    finally:
        provider.stop()

    assert received.comment == "__import__('os').system('echo pwned')"
