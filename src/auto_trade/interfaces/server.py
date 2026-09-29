from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..application.kill_switch import FileKillSwitch
from ..infrastructure.net import constant_time_equals, is_loopback
from .status import StatusReporter

MAX_BODY_BYTES = 64 * 1024

ActionHandler = Callable[[], dict[str, Any]]


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        reporter: StatusReporter,
        kill_switch: FileKillSwitch,
        token: str,
    ) -> None:
        super().__init__(address, DashboardRequestHandler)
        self.reporter = reporter
        self.kill_switch = kill_switch
        self.token = token
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        host = str(self.server_address[0])
        port = int(self.server_address[1])
        if ":" in host:
            host = f"[{host}]"
        return f"http://{host}:{port}/"

    def emergency_stop(self) -> dict[str, Any]:
        with self._lock:
            self.kill_switch.activate()
        return {
            "status": "STOPPED",
            "kill_switch_active": True,
            "reason": self.kill_switch.reason(),
        }

    def resume(self) -> dict[str, Any]:
        with self._lock:
            self.kill_switch.reset()
        return {
            "status": "RESUMED",
            "kill_switch_active": False,
            "reason": "",
        }


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server_version = "auto-trade-dashboard"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # -- plumbing ---------------------------------------------------------

    @property
    def dashboard(self) -> DashboardServer:
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

    def _send_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
            "connect-src 'self'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self, query: dict[str, list[str]]) -> bool:
        supplied = self.headers.get("X-Auto-Trade-Token", "")
        if not supplied:
            supplied = (query.get("token") or [""])[0]
        if not supplied:
            return False
        return constant_time_equals(supplied, self.dashboard.token)

    def _reject_unauthorised(self) -> None:
        self._send_json(
            {
                "error": "forbidden",
                "detail": "mutating endpoints require the X-Auto-Trade-Token header "
                "or a token query parameter",
            },
            HTTPStatus.FORBIDDEN,
        )

    def _drain_body(self) -> None:
        """Read and discard the request body.

        The body must be consumed before any reply. With HTTP/1.1 keep-alive an
        unread body stays in the socket buffer, so the next request on the same
        connection is parsed starting mid-body and every response after it is
        wrong. This holds for a refusal and for an unknown route, not only for
        a request that is acted on.

        Nothing here parses the body: no endpoint on this surface takes one, so
        a malformed body is discarded rather than interpreted.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if length <= 0:
            return
        # An oversized body is dropped up to the cap rather than left buffered.
        self.rfile.read(min(length, MAX_BODY_BYTES))

    # -- routing ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        reporter = self.dashboard.reporter

        if route == "/":
            self._send_html(render_page())
            return
        if route == "/api/health":
            self._send_json({"status": "ok", "kill_switch_active": reporter.kill_switch.active})
            return
        if route == "/api/status":
            self._send_json(reporter.status())
            return
        if route == "/api/risk":
            self._send_json(reporter.risk())
            return
        if route == "/api/positions":
            self._send_json(reporter.positions())
            return
        if route == "/api/signals":
            self._send_json(reporter.signals())
            return
        if route == "/api/executions":
            self._send_json(reporter.executions())
            return
        if route == "/api/metrics":
            tail = (query.get("tail") or ["2000"])[0]
            try:
                self._send_json(reporter.metrics(int(tail)))
            except ValueError:
                self._send_json({"error": "tail must be an integer"}, HTTPStatus.BAD_REQUEST)
            return
        if route == "/api/logs":
            tail = (query.get("tail") or ["200"])[0]
            try:
                self._send_json(reporter.logs(int(tail)))
            except ValueError:
                self._send_json({"error": "tail must be an integer"}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"error": "not found", "path": route}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        # The body is consumed before routing, so an unknown route answers 404
        # on a connection that is still in a known state.
        self._drain_body()

        actions: dict[str, ActionHandler] = {
            "/api/emergency-stop": self.dashboard.emergency_stop,
            "/api/resume": self.dashboard.resume,
        }
        action = actions.get(route)
        if action is None:
            self._send_json({"error": "not found", "path": route}, HTTPStatus.NOT_FOUND)
            return
        if not self._authorised(query):
            self._reject_unauthorised()
            return
        self._send_json(action())


def build_server(
    host: str,
    port: int,
    reporter: StatusReporter,
    kill_switch: FileKillSwitch,
    token: str | None = None,
) -> DashboardServer:
    """Create a dashboard server, refusing any non-loopback bind address."""
    if not is_loopback(host):
        raise ValueError(
            f"refusing to bind the dashboard to {host!r}: it can activate the kill "
            "switch, so it must listen on loopback only"
        )
    return DashboardServer(
        (host, port),
        reporter,
        kill_switch,
        token or secrets.token_urlsafe(24),
    )


def kill_switch_path(log_directory: Path) -> Path:
    return Path(log_directory) / "KILL_SWITCH"


def _page_path() -> Path:
    return Path(__file__).resolve().parent / "dashboard.html"


def render_page() -> str:
    try:
        return _page_path().read_text(encoding="utf-8")
    except OSError:
        return (
            "<!doctype html><meta charset=utf-8><title>auto-trade</title>"
            "<p>Dashboard assets are missing. Expected "
            f"<code>{_page_path()}</code>.</p>"
        )
