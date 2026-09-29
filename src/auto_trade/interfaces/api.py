"""A token-authenticated, loopback-only, read-only HTTP API for local programs.

The dashboard serves a human who can see the page. This serves another process:
a monitoring script, a second operator tool, a status line in another
application. That difference is the whole design, and it decides the three
properties below.

**It is authenticated, and it is the only local surface that is.** The
dashboard's read endpoints are open on loopback, which is acceptable for a page
a person opened deliberately but is not acceptable for an endpoint a program
calls on a schedule: a monitoring agent that reports "kill switch active" or
"there is one unresolved attempt" is a status feed, and an unauthenticated one
can be read, or spoofed, by anything else on the machine. Every route here
requires the token, reads included.

**The token is not accepted in a query string.** A URL is written to proxy logs,
browser history, and `Referer` headers. The dashboard tolerates `?token=` because
a hand-written fetch from a browser cannot always set a header; a program can,
so the API refuses the query form and says why. There is no `from` exception to
make for the caller who finds it inconvenient.

**It cannot place, modify, or close an order.** No route here reaches a
terminal, an order dialog, or the execution workflow. The only mutating routes
are the durable stop and its reset, which can only make the system more
conservative. An operator who wants an order placed still runs the CLI, which
re-runs every gate and requires `--confirm-demo` by hand.

Everything is served by the same `StatusReporter` the dashboard uses, so the two
surfaces cannot disagree about what they report. See docs/API.md.
"""

from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Callable, Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..application.kill_switch import FileKillSwitch
from ..infrastructure.net import constant_time_equals, is_loopback
from .status import StatusReporter

API_PREFIX = "/api/v1"
TOKEN_HEADER = "X-Auto-Trade-Token"
MAX_BODY_BYTES = 64 * 1024
DEFAULT_TAIL = 2000
MAX_TAIL = 5000

ReadRoute = Callable[[StatusReporter, Mapping[str, list[str]]], dict[str, Any]]
ActionRoute = Callable[[], dict[str, Any]]


def _read_routes() -> Mapping[str, ReadRoute]:
    """The read routes, built once so the router and the documentation agree.

    A route table that is written twice, once in code and once in a table in a
    document, drifts silently. This returns the code's own view of what exists.
    """
    return {
        "/health": lambda reporter, _query: {
            "status": "ok",
            "kill_switch_active": reporter.kill_switch.active,
        },
        "/status": lambda reporter, _query: reporter.status(),
        "/risk": lambda reporter, _query: reporter.risk(),
        "/positions": lambda reporter, _query: reporter.positions(),
        "/signals": lambda reporter, _query: reporter.signals(),
        "/executions": lambda reporter, _query: reporter.executions(),
        "/metrics": lambda reporter, query: reporter.metrics(_tail(query)),
        "/logs": lambda reporter, query: reporter.logs(_tail(query)),
    }


def _tail(query: Mapping[str, list[str]]) -> int:
    """Read the ``tail`` parameter, refusing anything that is not a whole number.

    A negative or absurd value is clamped rather than rejected: the reporter
    already bounds the number of lines it will read, and a caller asking for
    more than the cap gets the cap rather than an error.
    """
    raw = (query.get("tail") or [str(DEFAULT_TAIL)])[0]
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("tail must be an integer") from exc
    return max(1, min(value, MAX_TAIL))


READ_ROUTES: Mapping[str, ReadRoute] = _read_routes()


class LocalApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        reporter: StatusReporter,
        kill_switch: FileKillSwitch,
        token: str,
        audit: Callable[..., None] | None = None,
    ) -> None:
        super().__init__(address, LocalApiRequestHandler)
        self.reporter = reporter
        self.kill_switch = kill_switch
        self.token = token
        self._audit = audit
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        host = str(self.server_address[0])
        port = int(self.server_address[1])
        if ":" in host:
            host = f"[{host}]"
        return f"http://{host}:{port}{API_PREFIX}/"

    def _record(self, event_type: str, message: str) -> None:
        """Audit a control action, without the token that authorised it.

        The dashboard does not audit its own control actions, which is a gap: an
        emergency stop raised over HTTP leaves no record of who raised it. This
        surface records both directions, because the reset is the action worth
        watching — it is the one that removes a stop.
        """
        if self._audit is None:
            return
        from ..domain.models import AuditEvent

        self._audit(
            AuditEvent(
                component="local-api",
                event_type=event_type,
                message=message,
                action=event_type.upper(),
            )
        )

    def emergency_stop(self) -> dict[str, Any]:
        with self._lock:
            self.kill_switch.activate()
        self._record("control", "durable stop activated through the local API")
        return {
            "status": "STOPPED",
            "kill_switch_active": True,
            "reason": self.kill_switch.reason(),
        }

    def resume(self) -> dict[str, Any]:
        with self._lock:
            self.kill_switch.reset()
        self._record("control", "durable stop cleared through the local API")
        return {
            "status": "RESUMED",
            "kill_switch_active": False,
            "reason": "",
        }


class LocalApiRequestHandler(BaseHTTPRequestHandler):
    server_version = "auto-trade-api"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------

    @property
    def api(self) -> LocalApiServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _route_of(self, path: str) -> str:
        """Reduce a request path to a route name, or ``""`` when it is not ours.

        The prefix must be followed by a separator or the end of the path, so
        `/api/v10/health` is not treated as this API's `/health`.
        """
        normalised = "/" + path.strip("/")
        if normalised == API_PREFIX:
            return ""
        if not normalised.startswith(API_PREFIX + "/"):
            return ""
        remainder = normalised[len(API_PREFIX) + 1 :].strip("/")
        return f"/{remainder}" if remainder else ""

    def _token_supplied_in_query(self, query: Mapping[str, list[str]]) -> bool:
        return bool((query.get("token") or [""])[0])

    def _authorised(self) -> bool:
        return constant_time_equals(
            self.headers.get(TOKEN_HEADER, "").strip(), self.api.token
        )

    def _reject(self, status: HTTPStatus, error: str, detail: str) -> None:
        self._send_json({"error": error, "detail": detail}, status)

    def _drain_body(self) -> None:
        """Read and discard the request body.

        With HTTP/1.1 keep-alive an unread body stays in the socket buffer, so
        the next request on the same connection is parsed starting mid-body and
        every response after it is wrong. The body is therefore consumed before
        *any* reply, including a refusal: a rejected request must not corrupt
        the connection that carried it.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if length <= 0:
            return
        self.rfile.read(min(length, MAX_BODY_BYTES))

    def _require_token(self) -> bool:
        """Authenticate, or explain precisely why the request was refused."""
        if not self.api.token:
            self._reject(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "not_configured",
                "the local API has no token, so it is refusing every request",
            )
            return False
        if not self._authorised():
            self._reject(
                HTTPStatus.UNAUTHORIZED,
                "unauthorized",
                f"every route requires the {TOKEN_HEADER} header, including the "
                "read-only ones",
            )
            return False
        return True

    def _route(self) -> str:
        """Authenticate, then resolve the route.

        Authentication is checked before routing so that an unauthenticated
        caller cannot learn which routes exist by reading the difference
        between a 401 and a 404.
        """
        if not self._require_token():
            return ""
        route = self._route_of(urlparse(self.path).path)
        if not route:
            self._reject(
                HTTPStatus.NOT_FOUND,
                "not_found",
                f"this API is served under {API_PREFIX}/; there is no route here",
            )
            return ""
        return route

    def _not_exposed(self, route: str) -> None:
        """Answer a route that would change an account.

        Execution is refused with an explanation instead of a bare 404 so a
        caller that guesses finds the boundary stated rather than inferring
        that it must be trying a different verb or path. The message names the
        CLI instead, because that is the route that still exists.
        """
        self._reject(
            HTTPStatus.FORBIDDEN,
            "not_exposed",
            f"{route} is deliberately not exposed: this API can only read state and "
            "operate the durable stop. Placing an order or closing a position stays "
            "in the CLI, where every gate and an explicit --confirm-demo apply.",
        )

    # -- routing ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        self._drain_body()
        query = parse_qs(urlparse(self.path).query)
        if self._token_supplied_in_query(query):
            self._reject(
                HTTPStatus.BAD_REQUEST,
                "token_in_query",
                f"the token is not accepted as a query parameter; send it in the "
                f"{TOKEN_HEADER} header, because a URL is written to proxy logs, "
                "history, and Referer headers",
            )
            return
        route = self._route()
        if not route:
            return
        reader = READ_ROUTES.get(route)
        if reader is None:
            # Every non-read route answers the same way whatever the verb, so
            # there is no combination of method and path that reaches anything.
            self._not_exposed(route)
            return
        try:
            self._send_json(reader(self.api.reporter, query))
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        self._drain_body()
        route = self._route()
        if not route:
            return
        actions: Mapping[str, ActionRoute] = {
            "/emergency-stop": self.api.emergency_stop,
            "/resume": self.api.resume,
        }
        action = actions.get(route)
        if action is not None:
            self._send_json(action())
            return
        if route in READ_ROUTES:
            self._reject(
                HTTPStatus.METHOD_NOT_ALLOWED,
                "read_only",
                f"{route} is a read route and this API never changes state through it",
            )
            return
        self._not_exposed(route)


def build_api_server(
    host: str,
    port: int,
    reporter: StatusReporter,
    kill_switch: FileKillSwitch,
    token: str,
    audit: Callable[..., None] | None = None,
) -> LocalApiServer:
    """Create the local API server, refusing any non-loopback bind address.

    The token is required rather than generated here. The dashboard may print a
    generated token to a console a person is watching, but an API meant for
    another program has no such moment: a token nobody can read is a service
    that quietly answers 401 forever. A caller that wants a generated token asks
    for one on the command line instead.
    """
    if not is_loopback(host):
        raise ValueError(
            f"refusing to bind the local API to {host!r}: it is authenticated and can "
            "operate the durable stop, so it must listen on loopback only"
        )
    if not token.strip():
        raise ValueError(
            "the local API requires a token; set AUTO_TRADE_API_TOKEN or pass --token"
        )
    return LocalApiServer((host, port), reporter, kill_switch, token.strip(), audit)


def generate_api_token() -> str:
    """Mint a token for an operator who did not configure one."""
    return secrets.token_urlsafe(24)
