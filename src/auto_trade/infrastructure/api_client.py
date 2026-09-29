"""A client for the local read-only API.

This is the counterpart to `interfaces/api.py`. It exists so that a monitoring
script or a second operator tool does not have to re-implement the three rules
that make the call safe: authenticate on every request, stay on loopback, and
never follow a redirect that would carry the token somewhere else.

It is a *reader*. There is no method here that places, modifies, or closes an
order, and that is deliberate rather than an oversight of the surface: the
client is the part of this project another process is most likely to hold, and
the API it talks to refuses those routes anyway. Adding a method that could
not work would only make the boundary harder to see. See docs/API.md.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit
from urllib.request import OpenerDirector, Request, build_opener

from ..domain.exceptions import AutoTradeError
from .net import (
    MAX_RESPONSE_BYTES,
    LoopbackOnlyRedirectHandler,
    NonLoopbackRedirectError,
    is_loopback,
    split_loopback_url,
)

DEFAULT_TIMEOUT_SECONDS = 5.0
TOKEN_HEADER = "X-Auto-Trade-Token"


class ApiError(AutoTradeError):
    """Raised when the local API is misconfigured, unreachable, or refuses a call."""


class LocalApiClient:
    """Reads state from the local API, and operates the durable stop.

    The endpoint is treated as untrusted in the same way the signal provider
    treats its source, and for the same reason: it is configured by a human in
    an environment file, so a typo must fail closed rather than connect
    somewhere else.
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
            split_loopback_url(self.url, "local API endpoint")
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        if not self._token:
            raise ApiError(
                "local API requires a token; set AUTO_TRADE_API_TOKEN"
            )
        if self.timeout <= 0:
            raise ApiError("local API timeout must be greater than zero")
        if self.max_bytes <= 0:
            raise ApiError("local API response limit must be greater than zero")
        self._opener = build_opener(LoopbackOnlyRedirectHandler())
        self._started = True

    def stop(self) -> None:
        self._opener = None
        self._started = False

    def get(self, route: str) -> dict[str, Any]:
        """Read one route, for example ``/status`` or ``/metrics?tail=500``."""
        return self._call("GET", route, None)

    def emergency_stop(self) -> dict[str, Any]:
        """Engage the durable stop. This is the one call that changes state."""
        return self._call("POST", "/emergency-stop", {})

    def resume(self) -> dict[str, Any]:
        """Clear the durable stop."""
        return self._call("POST", "/resume", {})

    def status(self) -> dict[str, Any]:
        """Convenience for the route a monitoring script polls."""
        return self.get("/status")

    def metrics(self, tail: int = 2000) -> dict[str, Any]:
        return self.get(f"/metrics?tail={int(tail)}")

    def positions(self) -> dict[str, Any]:
        return self.get("/positions")

    def _call(self, method: str, route: str, body: dict[str, Any] | None) -> dict[str, Any]:
        opener = self._opener
        if not self._started or opener is None:
            raise ApiError("local API client is not started")
        target = self.url.rstrip("/") + route
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            target,
            data=data,
            headers={
                TOKEN_HEADER: self._token,
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if data else {}),
            },
            method=method,
        )
        try:
            with opener.open(request, timeout=self.timeout) as response:
                payload: bytes = response.read(self.max_bytes + 1)
                final_host = urlsplit(response.geturl()).hostname or ""
        except urllib.error.HTTPError as exc:
            # A 401 or 403 here is the API working: it refuses a caller that
            # cannot prove it holds the token. Reporting it as an outage would
            # teach the caller to retry, which is the wrong lesson.
            if exc.code in {401, 403}:
                raise ApiError(
                    f"local API rejected the configured token (HTTP {exc.code})"
                ) from exc
            raise ApiError(f"local API returned HTTP {exc.code}") from exc
        except NonLoopbackRedirectError as exc:
            raise ApiError(f"local API {exc.reason}") from exc
        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError) as exc:
            raise ApiError(f"local API is unreachable: {_reason(exc)}") from exc

        if not is_loopback(final_host):
            raise ApiError(f"local API response came from non-loopback host {final_host!r}")
        if len(payload) > self.max_bytes:
            raise ApiError(f"local API response is larger than the {self.max_bytes} byte limit")
        try:
            parsed: Any = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("local API response is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ApiError("local API response is not a JSON object")
        return parsed

    def __enter__(self) -> LocalApiClient:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


def _reason(exc: BaseException) -> str:
    reason = getattr(exc, "reason", None)
    return str(reason) if reason else str(exc) or type(exc).__name__
