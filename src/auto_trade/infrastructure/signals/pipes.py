from __future__ import annotations

import json
import os
from typing import IO, Any

from ...domain.exceptions import InvalidSignalError, NoSignalAvailable, SignalSourceError
from ...domain.models import TradeSignal
from ..net import constant_time_equals

PIPE_PREFIX = "\\\\.\\pipe\\"
MAX_LINE_BYTES = 64 * 1024


class NamedPipeSignalProvider:
    """Consumes newline-delimited JSON from a local Windows named pipe.

    A pipe is the one channel with no port to guess and no listening socket of
    ours: the other side creates a named pipe, this side opens it by name. The
    boundary is the pipe's own security descriptor, which this class cannot see
    and does not pretend to check. What it does check is everything it can:

    - the name must be a local pipe (``\\\\.\\pipe\\name``). A UNC name such as
      ``\\\\host\\pipe\\name`` would send signals over the network, so it is
      refused;
    - the first line must be an authentication frame carrying the shared token,
      which proves the writer is the process that was configured and not a
      squatter that created the pipe first;
    - a line that is too long, or a payload that is not a valid signal, is
      rejected rather than buffered.

    Opening a pipe is a blocking call with no portable timeout, so
    ``start`` does not connect; the first ``receive`` does. A caller that must
    not block should run it on a thread it can abandon.
    """

    def __init__(self, pipe_name: str, token: str, encoding: str = "utf-8") -> None:
        self.pipe_name = pipe_name.strip()
        self.encoding = encoding
        self._token = token.strip()
        self._started = False
        self._file: IO[str] | None = None

    @property
    def path(self) -> str:
        return self.pipe_name

    def start(self) -> None:
        if not self.pipe_name.lower().startswith(PIPE_PREFIX):
            raise SignalSourceError(
                "signal pipe must be a local named pipe such as "
                rf"\\.\pipe\auto_trade_signals, got {self.pipe_name!r}"
            )
        if not self._token:
            raise SignalSourceError(
                "signal pipe requires a token; set AUTO_TRADE_PIPE_SIGNAL_TOKEN"
            )
        self._started = True

    def stop(self) -> None:
        handle = self._file
        self._file = None
        self._started = False
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def receive(self) -> TradeSignal:
        if not self._started:
            raise NoSignalAvailable("signal provider is not started")
        if self._file is None:
            self._connect()
        line = self._read_line()
        if line is None:
            raise NoSignalAvailable("signal pipe closed before a signal arrived")
        return self._parse(line)

    def _connect(self) -> None:
        try:
            handle = os.open(self.pipe_name, os.O_RDONLY)
        except OSError as exc:
            raise SignalSourceError(
                f"signal pipe {self.pipe_name!r} could not be opened: {exc.strerror or exc}"
            ) from exc
        self._file = os.fdopen(handle, "r", encoding=self.encoding, errors="replace")
        self._authenticate()

    def _authenticate(self) -> None:
        line = self._read_line()
        if line is None:
            raise SignalSourceError("signal pipe closed before authenticating")
        try:
            frame: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SignalSourceError("signal pipe did not send an authentication frame") from exc
        if not isinstance(frame, dict) or not constant_time_equals(
            str(frame.get("auth", "")), self._token
        ):
            raise SignalSourceError("signal pipe failed authentication")

    def _read_line(self) -> str | None:
        handle = self._file
        if handle is None:
            return None
        try:
            line = handle.readline(MAX_LINE_BYTES)
        except OSError:
            # A peer that disconnects mid-read surfaces as OSError, not as an
            # empty read, so it is reported as a closed pipe either way.
            return None
        if not line:
            return None
        if not line.endswith("\n"):
            # No newline inside the limit means the writer sent an oversized or
            # unterminated line; the rest of it must not be treated as a signal.
            self._discard()
            raise InvalidSignalError(
                f"signal pipe line is not newline terminated within {MAX_LINE_BYTES} bytes"
            )
        return line.strip()

    def _discard(self) -> None:
        handle = self._file
        if handle is None:
            return
        try:
            handle.readline(MAX_LINE_BYTES)
        except OSError:
            pass

    @staticmethod
    def _parse(line: str) -> TradeSignal:
        try:
            raw: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            raise InvalidSignalError("pipe signal is not valid JSON") from exc
        return TradeSignal.from_dict(raw)
