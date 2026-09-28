from __future__ import annotations

import ctypes
import sys
import threading
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from auto_trade.domain.exceptions import (
    InvalidSignalError,
    NoSignalAvailable,
    SignalSourceError,
)
from auto_trade.infrastructure.signals import NamedPipeSignalProvider

from ..helpers import signal_data

TOKEN = "pipe-test-token"
# The server writes and this side reads, so the instance is an outbound pipe:
# asking to read an inbound instance is denied by design.
PIPE_ACCESS_OUTBOUND = 0x00000002
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
ERROR_PIPE_CONNECTED = 535
INVALID_HANDLE_VALUE = -1

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="named pipes are Windows only")


def _kernel32() -> Any:
    """Bind the Win32 pipe signatures once, so handles are not truncated."""
    library: Any = ctypes.windll.kernel32
    library.CreateNamedPipeW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    library.CreateNamedPipeW.restype = ctypes.c_void_p
    library.ConnectNamedPipe.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    library.ConnectNamedPipe.restype = ctypes.c_int
    library.WriteFile.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    library.WriteFile.restype = ctypes.c_int
    for name in ("FlushFileBuffers", "DisconnectNamedPipe", "CloseHandle"):
        function = getattr(library, name)
        function.argtypes = [ctypes.c_void_p]
        function.restype = ctypes.c_int
    library.GetLastError.restype = ctypes.c_ulong
    return library


class PipeServer:
    """A minimal named-pipe writer, so the provider is tested against a real pipe.

    Using the Win32 API directly keeps the test free of a pywin32 dependency:
    the development and CI test set must not need the MT5 automation extras.
    """

    def __init__(self, lines: bytes) -> None:
        self.name = rf"\\.\pipe\auto_trade_test_{uuid.uuid4().hex}"
        self._lines = lines
        self._kernel32: Any = None
        self._thread: threading.Thread | None = None
        self._created = threading.Event()
        self.error: BaseException | None = None

    def __enter__(self) -> PipeServer:
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        # The client blocks until the instance exists, so a race here would look
        # like a missing pipe rather than a real failure.
        if not self._created.wait(timeout=10) and self.error is not None:
            raise self.error
        if self.error is not None:
            raise self.error
        return self

    def __exit__(self, *_args: object) -> None:
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _serve(self) -> None:
        try:
            self._kernel32 = _kernel32()
            handle = self._kernel32.CreateNamedPipeW(
                self.name,
                PIPE_ACCESS_OUTBOUND,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                1,
                65536,
                65536,
                0,
                None,
            )
            if handle == INVALID_HANDLE_VALUE:
                raise OSError("CreateNamedPipeW failed")
            self._created.set()
            connected = self._kernel32.ConnectNamedPipe(handle, None)
            if not connected and self._kernel32.GetLastError() != ERROR_PIPE_CONNECTED:
                raise OSError("ConnectNamedPipe failed")
            self._write(handle, self._lines)
            # The client is reading; closing without a flush race.
            self._kernel32.FlushFileBuffers(handle)
            self._kernel32.DisconnectNamedPipe(handle)
            self._kernel32.CloseHandle(handle)
        except BaseException as exc:  # noqa: BLE001
            self.error = exc

    def _write(self, handle: int, payload: bytes) -> None:
        assert self._kernel32 is not None
        written = ctypes.c_ulong(0)
        self._kernel32.WriteFile(handle, payload, len(payload), ctypes.byref(written), None)
        if written.value != len(payload):
            raise OSError(f"short write: {written.value} of {len(payload)}")


def lines(*payloads: object) -> bytes:
    return b"".join(json_line(payload) for payload in payloads)


def json_line(payload: object) -> bytes:
    import json

    return json.dumps(payload).encode("utf-8") + b"\n"


@pytest.fixture
def server_factory() -> Iterator[Callable[[bytes], PipeServer]]:
    servers: list[PipeServer] = []

    def start(payload: bytes) -> PipeServer:
        server = PipeServer(payload)
        server.__enter__()
        servers.append(server)
        return server

    yield start

    for server in servers:
        server.__exit__()


def test_pipe_provider_reads_an_authenticated_signal(
    server_factory: Callable[[bytes], PipeServer]
) -> None:
    server = server_factory(lines({"auth": TOKEN}, signal_data("pipe-1")))
    provider = NamedPipeSignalProvider(server.name, TOKEN)
    provider.start()
    try:
        received = provider.receive()
    finally:
        provider.stop()

    assert received.signal_id == "pipe-1"
    assert server.error is None


def test_pipe_provider_refuses_a_wrong_token(
    server_factory: Callable[[bytes], PipeServer]
) -> None:
    server = server_factory(lines({"auth": "not-the-token"}, signal_data("pipe-2")))
    provider = NamedPipeSignalProvider(server.name, TOKEN)
    provider.start()
    try:
        with pytest.raises(SignalSourceError, match="failed authentication"):
            provider.receive()
    finally:
        provider.stop()


def test_pipe_provider_refuses_a_remote_pipe() -> None:
    provider = NamedPipeSignalProvider(r"\\server\pipe\auto_trade_signals", TOKEN)

    with pytest.raises(SignalSourceError, match="local named pipe"):
        provider.start()


def test_pipe_provider_requires_a_token() -> None:
    provider = NamedPipeSignalProvider(r"\\.\pipe\auto_trade_signals", "")

    with pytest.raises(SignalSourceError, match="token"):
        provider.start()


def test_pipe_provider_is_inert_before_start() -> None:
    provider = NamedPipeSignalProvider(r"\\.\pipe\auto_trade_signals", TOKEN)

    with pytest.raises(NoSignalAvailable, match="not started"):
        provider.receive()


def test_pipe_provider_reports_a_missing_pipe() -> None:
    provider = NamedPipeSignalProvider(
        rf"\\.\pipe\auto_trade_absent_{uuid.uuid4().hex}", TOKEN
    )
    provider.start()
    try:
        with pytest.raises(SignalSourceError, match="could not be opened"):
            provider.receive()
    finally:
        provider.stop()


def test_pipe_provider_reports_a_closed_pipe(
    server_factory: Callable[[bytes], PipeServer]
) -> None:
    server = server_factory(lines({"auth": TOKEN}))
    provider = NamedPipeSignalProvider(server.name, TOKEN)
    provider.start()
    try:
        with pytest.raises(NoSignalAvailable):
            provider.receive()
    finally:
        provider.stop()


def test_pipe_provider_refuses_an_oversized_line(
    server_factory: Callable[[bytes], PipeServer]
) -> None:
    payload = lines({"auth": TOKEN}) + b"x" * (70 * 1024) + b"\n"
    server = server_factory(payload)
    provider = NamedPipeSignalProvider(server.name, TOKEN)
    provider.start()
    try:
        with pytest.raises(InvalidSignalError, match="newline"):
            provider.receive()
    finally:
        provider.stop()


def test_pipe_provider_rejects_a_line_that_is_not_a_signal(
    server_factory: Callable[[bytes], PipeServer]
) -> None:
    server = server_factory(lines({"auth": TOKEN}, {"id": "only-an-id"}))
    provider = NamedPipeSignalProvider(server.name, TOKEN)
    provider.start()
    try:
        with pytest.raises(InvalidSignalError):
            provider.receive()
    finally:
        provider.stop()


def test_pipe_provider_rejects_a_non_json_line(
    server_factory: Callable[[bytes], PipeServer]
) -> None:
    server = server_factory(lines({"auth": TOKEN}) + b"not json\n")
    provider = NamedPipeSignalProvider(server.name, TOKEN)
    provider.start()
    try:
        with pytest.raises(InvalidSignalError, match="not valid JSON"):
            provider.receive()
    finally:
        provider.stop()


def test_pipe_provider_requires_an_authentication_frame(
    server_factory: Callable[[bytes], PipeServer]
) -> None:
    server = server_factory(b"not json\n" + lines(signal_data("pipe-3")))
    provider = NamedPipeSignalProvider(server.name, TOKEN)
    provider.start()
    try:
        with pytest.raises(SignalSourceError, match="authentication frame"):
            provider.receive()
    finally:
        provider.stop()


def test_pipe_provider_stop_is_safe_when_never_connected() -> None:
    provider = NamedPipeSignalProvider(r"\\.\pipe\auto_trade_signals", TOKEN)
    provider.start()

    provider.stop()

    with pytest.raises(NoSignalAvailable, match="not started"):
        provider.receive()


def test_pipe_provider_handles_two_signals_in_one_session(
    server_factory: Callable[[bytes], PipeServer]
) -> None:
    server = server_factory(
        lines({"auth": TOKEN}, signal_data("pipe-4"), signal_data("pipe-5"))
    )
    provider = NamedPipeSignalProvider(server.name, TOKEN)
    provider.start()
    try:
        assert provider.receive().signal_id == "pipe-4"
        assert provider.receive().signal_id == "pipe-5"
    finally:
        provider.stop()


def test_pipe_server_reports_no_error(server_factory: Callable[[bytes], PipeServer]) -> None:
    server = server_factory(lines({"auth": TOKEN}, signal_data("pipe-6")))
    provider = NamedPipeSignalProvider(server.name, TOKEN)
    provider.start()
    try:
        provider.receive()
    finally:
        provider.stop()

    assert server.error is None, server.error


def test_pipe_provider_does_not_evaluate_anything_it_reads(
    server_factory: Callable[[bytes], PipeServer]
) -> None:
    """A payload is data. It is parsed as JSON and never executed."""
    hostile: dict[str, Any] = signal_data("pipe-7")
    hostile["comment"] = "__import__('os').system('echo pwned')"
    server = server_factory(lines({"auth": TOKEN}, hostile))
    provider = NamedPipeSignalProvider(server.name, TOKEN)
    provider.start()
    try:
        received = provider.receive()
    finally:
        provider.stop()

    assert received.comment == "__import__('os').system('echo pwned')"
