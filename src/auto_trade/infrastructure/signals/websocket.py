from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
from typing import Any
from urllib.parse import urlsplit

from ...domain.exceptions import InvalidSignalError, NoSignalAvailable, SignalSourceError
from ...domain.models import TradeSignal
from ..net import MAX_RESPONSE_BYTES, constant_time_equals, is_loopback

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA
DEFAULT_TIMEOUT_SECONDS = 5.0
MAX_FRAGMENTS = 8


class _FrameError(SignalSourceError):
    """Raised when the peer violates the framing rules."""


class WebSocketSignalProvider:
    """Consumes one signal per text message from a loopback WebSocket endpoint.

    This is a small, strict RFC 6455 client written here rather than a
    dependency, because the project installs no runtime packages. It implements
    only what a push-style signal source needs, and it refuses everything else:

    - ``ws://`` on a loopback host only. ``wss://`` is refused rather than
      half-implemented, and a redirect or any non-loopback address is refused,
      so the session cannot be moved to a host the operator did not configure.
    - the first message must be an authentication frame carrying the token. A
      server that cannot present it is not the configured server, which is the
      only defence against a local process that binds the port first.
    - a masked frame from the server, a binary frame, a fragmented sequence that
      is not continued in order, an oversized frame or message, and a control
      frame that is fragmented or longer than 125 bytes are all refused.

    Trust is still limited. The peer learns the token, and a peer that has it
    can propose any signal; only the risk engine decides whether one may be
    acted on. TLS is not implemented, so this source must not be pointed at
    anything but loopback.
    """

    def __init__(
        self,
        url: str,
        token: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        self.url = url.strip()
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._token = token.strip()
        self._started = False
        self._socket: socket.socket | None = None
        self._buffer = b""
        self._authenticated = False

    def start(self) -> None:
        self._validate_url()
        if not self._token:
            raise SignalSourceError(
                "signal endpoint requires a token; set AUTO_TRADE_WS_SIGNAL_TOKEN"
            )
        if self.timeout <= 0:
            raise SignalSourceError("signal endpoint timeout must be greater than zero")
        if self.max_bytes <= 0:
            raise SignalSourceError("signal endpoint response limit must be greater than zero")
        self._started = True

    def stop(self) -> None:
        connection = self._socket
        self._socket = None
        self._buffer = b""
        self._authenticated = False
        self._started = False
        if connection is not None:
            try:
                connection.sendall(_close_frame(1000))
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass

    def receive(self) -> TradeSignal:
        if not self._started:
            raise NoSignalAvailable("signal provider is not started")
        if self._socket is None:
            self._connect()
        if not self._authenticated:
            self._authenticate()
        message = self._read_message()
        if not message:
            raise NoSignalAvailable("signal endpoint sent an empty message")
        try:
            raw: Any = json.loads(message)
        except json.JSONDecodeError as exc:
            raise InvalidSignalError("signal message is not valid JSON") from exc
        return TradeSignal.from_dict(raw)

    # -- connection ------------------------------------------------------

    def _validate_url(self) -> None:
        parts = urlsplit(self.url)
        if parts.scheme.lower() != "ws":
            raise SignalSourceError(
                f"signal endpoint must use ws:// on loopback, got {parts.scheme!r}; "
                "wss is not implemented"
            )
        host = parts.hostname or ""
        if not is_loopback(host):
            raise SignalSourceError(
                f"refusing signal endpoint at {host or self.url!r}: it must stay on loopback"
            )
        if parts.port is not None and not 1 <= parts.port <= 65535:
            raise SignalSourceError("signal endpoint port is out of range")

    def _connect(self) -> None:
        parts = urlsplit(self.url)
        host = parts.hostname or ""
        port = parts.port or 80
        try:
            connection = socket.create_connection((host, port), timeout=self.timeout)
        except OSError as exc:
            raise SignalSourceError(f"signal endpoint is unreachable: {exc}") from exc
        connection.settimeout(self.timeout)
        self._socket = connection
        self._buffer = b""
        try:
            self._handshake(parts.path or "/", host, port)
        except BaseException:
            self.stop()
            raise

    def _handshake(self, path: str, host: str, port: int) -> None:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        assert self._socket is not None
        self._socket.sendall(request.encode("ascii"))
        header = self._read_until(b"\r\n\r\n")
        first, _, rest = header.partition(b"\r\n")
        status = first.decode("latin-1")
        if " 101 " not in f" {status} ":
            raise SignalSourceError(f"signal endpoint refused the upgrade: {status}")
        fields = _headers(rest)
        expected = base64.b64encode(hashlib.sha1(f"{key}{GUID}".encode("ascii")).digest()).decode(
            "ascii"
        )
        if fields.get("upgrade", "").lower() != "websocket":
            raise SignalSourceError("signal endpoint did not upgrade to websocket")
        if "upgrade" not in fields.get("connection", "").lower():
            raise SignalSourceError("signal endpoint did not keep the connection upgraded")
        if fields.get("sec-websocket-accept") != expected:
            raise SignalSourceError("signal endpoint returned a wrong handshake accept key")

    def _read_until(self, marker: bytes) -> bytes:
        assert self._socket is not None
        while marker not in self._buffer:
            if len(self._buffer) > MAX_RESPONSE_BYTES:
                raise _FrameError("signal endpoint sent an oversized handshake")
            chunk = self._socket.recv(4096)
            if not chunk:
                raise SignalSourceError("signal endpoint closed during the handshake")
            self._buffer += chunk
        head, _, remainder = self._buffer.partition(marker)
        self._buffer = remainder
        return head

    # -- messages --------------------------------------------------------

    def _authenticate(self) -> None:
        message = self._read_message()
        try:
            frame: Any = json.loads(message)
        except json.JSONDecodeError as exc:
            raise SignalSourceError("signal endpoint did not send an authentication frame") from exc
        if not isinstance(frame, dict) or not constant_time_equals(
            str(frame.get("auth", "")), self._token
        ):
            raise SignalSourceError("signal endpoint failed authentication")
        self._authenticated = True

    def _read_message(self) -> str:
        fragments: list[bytes] = []
        total = 0
        expected_opcode: int | None = None
        for _ in range(MAX_FRAGMENTS):
            frame = self._read_frame()
            if frame["opcode"] == OPCODE_CLOSE:
                raise NoSignalAvailable("signal endpoint closed the session")
            if frame["opcode"] == OPCODE_PING:
                self._send(OPCODE_PONG, frame["payload"])
                continue
            if frame["opcode"] == OPCODE_PONG:
                continue
            if frame["opcode"] == OPCODE_BINARY:
                raise _FrameError("signal endpoint sent a binary message; only text is accepted")
            if frame["opcode"] == OPCODE_TEXT:
                if expected_opcode is not None:
                    raise _FrameError("signal endpoint started a new message before finishing one")
                expected_opcode = OPCODE_TEXT
            elif frame["opcode"] == OPCODE_CONTINUATION:
                if expected_opcode is None:
                    raise _FrameError("signal endpoint continued a message that never started")
            else:
                raise _FrameError(f"signal endpoint used an unexpected opcode {frame['opcode']}")
            total += len(frame["payload"])
            if total > self.max_bytes:
                raise InvalidSignalError(
                    f"signal message is larger than the {self.max_bytes} byte limit"
                )
            fragments.append(frame["payload"])
            if frame["fin"]:
                return _decode(b"".join(fragments))
        raise _FrameError(f"signal message used more than {MAX_FRAGMENTS} frames")

    def _read_frame(self) -> dict[str, Any]:
        header = self._read_exactly(2)
        first, second = header[0], header[1]
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        if first & 0x70:
            raise _FrameError("signal endpoint set a reserved frame bit")
        if second & 0x80:
            raise _FrameError("signal endpoint masked a frame; a server must not mask")
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exactly(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exactly(8))[0]
        control = opcode & 0x08
        if control and (not fin or length > 125):
            raise _FrameError("signal endpoint sent an invalid control frame")
        if length > self.max_bytes:
            raise InvalidSignalError(
                f"signal frame is larger than the {self.max_bytes} byte limit"
            )
        return {"fin": fin, "opcode": opcode, "payload": self._read_exactly(length)}

    def _read_exactly(self, count: int) -> bytes:
        assert self._socket is not None
        while len(self._buffer) < count:
            chunk = self._socket.recv(4096)
            if not chunk:
                raise SignalSourceError("signal endpoint closed the connection")
            self._buffer += chunk
        head, self._buffer = self._buffer[:count], self._buffer[count:]
        return head

    def _send(self, opcode: int, payload: bytes) -> None:
        connection = self._socket
        if connection is None:
            return
        try:
            connection.sendall(_frame(opcode, payload, mask=True))
        except OSError as exc:
            raise SignalSourceError(f"signal endpoint stopped accepting frames: {exc}") from exc


# -- framing helpers ---------------------------------------------------


def _frame(opcode: int, payload: bytes, mask: bool) -> bytes:
    header = bytes([0x80 | opcode])
    length = len(payload)
    mask_bit = 0x80 if mask else 0x00
    if length < 126:
        header += bytes([mask_bit | length])
    elif length < 1 << 16:
        header += bytes([mask_bit | 126]) + struct.pack("!H", length)
    else:
        header += bytes([mask_bit | 127]) + struct.pack("!Q", length)
    if not mask:
        return header + payload
    key = os.urandom(4)
    masked = bytes(byte ^ key[index % 4] for index, byte in enumerate(payload))
    return header + key + masked


def _close_frame(code: int) -> bytes:
    return _frame(OPCODE_CLOSE, struct.pack("!H", code), mask=True)


def _decode(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidSignalError("signal message is not valid UTF-8") from exc


def _headers(raw: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in raw.decode("latin-1").splitlines():
        name, separator, value = line.partition(":")
        if separator:
            fields[name.strip().lower()] = value.strip()
    return fields
