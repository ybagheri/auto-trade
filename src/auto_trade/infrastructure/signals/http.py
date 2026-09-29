from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit
from urllib.request import OpenerDirector, Request, build_opener

from ...domain.exceptions import (
    InvalidSignalError,
    NoSignalAvailable,
    SignalSourceError,
)
from ...domain.models import TradeSignal
from ..net import (
    MAX_RESPONSE_BYTES,
    LoopbackOnlyRedirectHandler,
    NonLoopbackRedirectError,
    is_loopback,
    split_loopback_url,
)

DEFAULT_TIMEOUT_SECONDS = 5.0
IDLE_STATUSES = frozenset({204, 404, 503})
AUTH_STATUSES = frozenset({401, 403})


class HttpSignalProvider:
    """Fetches one signal per ``receive`` call from a loopback HTTP endpoint.

    The endpoint is treated as untrusted input. It must be an explicit loopback
    URL, it must authenticate with a bearer token, redirects are refused, the
    response is size-bounded, and a payload that is not a valid signal is
    rejected rather than retried. This is a read-only signal source: it exposes
    no endpoint and can never place an order.
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
        self._opener: OpenerDirector | None = None

    def start(self) -> None:
        try:
            split_loopback_url(self.url, "signal endpoint")
        except ValueError as exc:
            raise SignalSourceError(str(exc)) from exc
        if not self._token:
            raise SignalSourceError(
                "signal endpoint requires a token; set AUTO_TRADE_HTTP_SIGNAL_TOKEN"
            )
        if self.timeout <= 0:
            raise SignalSourceError("signal endpoint timeout must be greater than zero")
        if self.max_bytes <= 0:
            raise SignalSourceError("signal endpoint response limit must be greater than zero")
        self._opener = build_opener(LoopbackOnlyRedirectHandler())
        self._started = True

    def stop(self) -> None:
        self._opener = None
        self._started = False

    def receive(self) -> TradeSignal:
        opener = self._opener
        if not self._started or opener is None:
            raise NoSignalAvailable("signal provider is not started")
        request = Request(
            self.url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with opener.open(request, timeout=self.timeout) as response:
                body: bytes = response.read(self.max_bytes + 1)
                final_host = urlsplit(response.geturl()).hostname or ""
        except urllib.error.HTTPError as exc:
            if exc.code in IDLE_STATUSES:
                raise NoSignalAvailable(f"signal endpoint has no signal (HTTP {exc.code}") from exc
            if exc.code in AUTH_STATUSES:
                raise SignalSourceError(
                    f"signal endpoint rejected the configured token (HTTP {exc.code})"
                ) from exc
            raise SignalSourceError(f"signal endpoint returned HTTP {exc.code}") from exc
        except NonLoopbackRedirectError as exc:
            # Checked before the generic URLError so a refused redirect keeps
            # reporting itself as the policy refusal it is, not as a dead host.
            raise SignalSourceError(f"signal endpoint {exc.reason}") from exc
        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError) as exc:
            raise SignalSourceError(f"signal endpoint is unreachable: {_reason(exc)}") from exc

        if not is_loopback(final_host):
            raise SignalSourceError(
                f"signal response came from non-loopback host {final_host!r}"
            )
        if len(body) > self.max_bytes:
            raise InvalidSignalError(
                f"signal response is larger than the {self.max_bytes} byte limit"
            )
        if not body.strip():
            raise NoSignalAvailable("signal endpoint returned an empty body")
        try:
            raw: Any = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidSignalError("signal response is not valid JSON") from exc
        return TradeSignal.from_dict(raw)


def _reason(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    return str(reason) if reason else str(exc) or type(exc).__name__
