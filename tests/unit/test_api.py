"""The local API is authenticated on every route and can only read.

Each test here exists because of a way this API could be wrong that a reader
would otherwise have to take on trust. The dangerous failure is not a crash: it
is a route that answers when it should refuse, because a monitoring script
reading "kill switch inactive" or "no unresolved attempts" acts on that answer
whether or not the caller was entitled to it.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from http import HTTPStatus
from pathlib import Path

import pytest

from auto_trade.application.kill_switch import FileKillSwitch
from auto_trade.application.ledger import JsonExecutionLedger
from auto_trade.domain.models import AuditEvent, ExecutionPolicy, RiskLimits
from auto_trade.infrastructure.api_client import ApiError, LocalApiClient
from auto_trade.infrastructure.configuration import AppConfig
from auto_trade.interfaces import StatusReporter, build_api_server
from auto_trade.interfaces.api import READ_ROUTES, LocalApiServer, generate_api_token
from auto_trade.interfaces.server import kill_switch_path

TOKEN = "api-test-token-456"
NOW = datetime(2026, 9, 29, 9, 0, 0, tzinfo=UTC)


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture
def kill_switch(log_dir: Path) -> FileKillSwitch:
    return FileKillSwitch(kill_switch_path(log_dir), clock=lambda: NOW)


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        terminal_path=tmp_path / "terminal64.exe",
        data_path=tmp_path / "data",
        instance_name="Alpari-MT5-Demo",
        signal_directory=tmp_path / "signals",
        log_directory=tmp_path / "logs",
        policy=ExecutionPolicy(dry_run=True, demo_only=True),
        risk=RiskLimits(frozenset({"BITCOIN"}), Decimal("1.0"), 5, 10),
    )


@pytest.fixture
def events() -> list[AuditEvent]:
    return []


@pytest.fixture
def server(
    config: AppConfig, kill_switch: FileKillSwitch, events: list[AuditEvent]
) -> Iterator[LocalApiServer]:
    reporter = StatusReporter(
        config=config,
        ledger=JsonExecutionLedger(config.log_directory / "idempotency.json"),
        kill_switch=kill_switch,
    )
    instance = build_api_server(
        "127.0.0.1", 0, reporter, kill_switch, TOKEN, audit=events.append
    )
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=5)


def request(
    server: LocalApiServer,
    path: str,
    token: str | None = None,
    post: bool = False,
) -> tuple[int, str]:
    data = b"{}" if post else None
    req = urllib.request.Request(
        server.url.rstrip("/") + path, data=data, method="POST" if post else "GET"
    )
    if token:
        req.add_header("X-Auto-Trade-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


# -- every route is authenticated, reads included ------------------------


def test_an_unauthenticated_read_is_refused(server: LocalApiServer) -> None:
    """A read is refused without a token, which is what separates this from the dashboard."""
    status, body = request(server, "/status")
    assert status == HTTPStatus.UNAUTHORIZED
    assert json.loads(body)["error"] == "unauthorized"


def test_an_unauthenticated_kill_switch_report_is_refused(server: LocalApiServer) -> None:
    status, _ = request(server, "/health")
    assert status == HTTPStatus.UNAUTHORIZED


def test_a_wrong_token_is_refused(server: LocalApiServer) -> None:
    status, _ = request(server, "/status", token="not-the-token")
    assert status == HTTPStatus.UNAUTHORIZED


@pytest.mark.parametrize("route", sorted(READ_ROUTES))
def test_no_read_route_answers_without_a_token(server: LocalApiServer, route: str) -> None:
    """Every route in the table is covered, so a new one cannot be added unauthenticated."""
    status, _ = request(server, route)
    assert status == HTTPStatus.UNAUTHORIZED, f"{route} answered without a token"


@pytest.mark.parametrize("route", sorted(READ_ROUTES))
def test_every_read_route_answers_with_a_token(server: LocalApiServer, route: str) -> None:
    status, _ = request(server, route, token=TOKEN)
    assert status == HTTPStatus.OK, f"{route} refused an authenticated read"


def test_the_token_is_not_accepted_in_the_query_string(server: LocalApiServer) -> None:
    """A URL reaches proxy logs, history, and Referer headers, so this form is refused."""
    status, body = request(server, f"/status?token={TOKEN}")
    assert status == HTTPStatus.BAD_REQUEST
    assert json.loads(body)["error"] == "token_in_query"


def test_a_query_token_is_refused_before_authentication(server: LocalApiServer) -> None:
    status, _ = request(server, "/status?token=wrong-too")
    assert status == HTTPStatus.BAD_REQUEST


def test_the_error_body_never_echoes_the_token(server: LocalApiServer) -> None:
    _, body = request(server, "/status", token="wrong-secret-value")
    assert "wrong-secret-value" not in body


# -- the server cannot be bound to a network address --------------------


def test_api_refuses_to_bind_a_public_address(
    config: AppConfig, kill_switch: FileKillSwitch
) -> None:
    reporter = StatusReporter(
        config,
        JsonExecutionLedger(config.log_directory / "idempotency.json"),
        kill_switch,
    )

    with pytest.raises(ValueError, match="loopback"):
        build_api_server("0.0.0.0", 0, reporter, kill_switch, TOKEN)


def test_api_refuses_to_start_without_a_token(
    config: AppConfig, kill_switch: FileKillSwitch
) -> None:
    """A generated token would be one nobody can read, answering 401 forever."""
    reporter = StatusReporter(
        config,
        JsonExecutionLedger(config.log_directory / "idempotency.json"),
        kill_switch,
    )

    with pytest.raises(ValueError, match="requires a token"):
        build_api_server("127.0.0.1", 0, reporter, kill_switch, "   ")


def test_a_generated_token_is_long_and_distinct() -> None:
    first, second = generate_api_token(), generate_api_token()
    assert len(first) >= 32
    assert first != second


def test_a_server_built_without_the_factory_refuses_rather_than_serves_open(
    config: AppConfig, kill_switch: FileKillSwitch
) -> None:
    """`build_api_server` makes this unreachable; a direct construction must not serve open.

    An empty token must never mean "no authentication". If a future caller
    constructs the server directly and bypasses the factory, the answer is still
    a refusal on every route.
    """
    reporter = StatusReporter(
        config,
        JsonExecutionLedger(config.log_directory / "idempotency.json"),
        kill_switch,
    )
    instance = LocalApiServer(("127.0.0.1", 0), reporter, kill_switch, "")
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        status, _ = request(instance, "/status")
        assert status == HTTPStatus.SERVICE_UNAVAILABLE
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=5)


# -- nothing here can change an account ---------------------------------


@pytest.mark.parametrize(
    "route",
    [
        "/execute",
        "/orders",
        "/order",
        "/place-order",
        "/close",
        "/close-position",
        "/reconcile",
        "/dry-run",
        "/signal",
    ],
)
def test_an_account_changing_route_is_refused_with_a_reason(
    server: LocalApiServer, route: str
) -> None:
    """The refusal explains itself, so a caller does not try another verb instead."""
    status, body = request(server, route, token=TOKEN)
    assert status == HTTPStatus.FORBIDDEN
    payload = json.loads(body)
    assert payload["error"] == "not_exposed"
    assert "CLI" in payload["detail"]


def test_the_refusal_also_applies_to_post(server: LocalApiServer) -> None:
    status, _ = request(server, "/execute", token=TOKEN, post=True)
    assert status == HTTPStatus.FORBIDDEN


def test_an_execution_route_is_refused_without_a_token_too(server: LocalApiServer) -> None:
    """Authentication is checked first, so the route table is not a disclosure."""
    status, _ = request(server, "/execute")
    assert status == HTTPStatus.UNAUTHORIZED


def test_posting_to_a_read_route_is_refused(server: LocalApiServer) -> None:
    status, body = request(server, "/status", token=TOKEN, post=True)
    assert status == HTTPStatus.METHOD_NOT_ALLOWED
    assert json.loads(body)["error"] == "read_only"


def test_a_path_outside_the_version_prefix_is_not_found(server: LocalApiServer) -> None:
    """The unversioned dashboard path is not an API route, so a caller cannot drift onto it."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/api/status",
        headers={"X-Auto-Trade-Token": TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    assert status == HTTPStatus.NOT_FOUND


@pytest.mark.parametrize("path", ["/api/v10/status", "/api/v1x/status", "/api/v1"])
def test_a_near_miss_prefix_is_not_a_route(server: LocalApiServer, path: str) -> None:
    """`/api/v10/status` must not be read as this API's `/status`."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}{path}",
        headers={"X-Auto-Trade-Token": TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    assert status == HTTPStatus.NOT_FOUND


# -- the durable stop ---------------------------------------------------


def test_emergency_stop_requires_a_token(
    server: LocalApiServer, kill_switch: FileKillSwitch
) -> None:
    status, _ = request(server, "/emergency-stop", post=True)
    assert status == HTTPStatus.UNAUTHORIZED
    assert not kill_switch.active


def test_emergency_stop_activates_the_durable_switch(
    server: LocalApiServer, kill_switch: FileKillSwitch
) -> None:
    status, body = request(server, "/emergency-stop", token=TOKEN, post=True)
    assert status == HTTPStatus.OK
    assert json.loads(body)["status"] == "STOPPED"
    assert FileKillSwitch(kill_switch_path(kill_switch.path.parent)).active is True


def test_resume_clears_the_switch(
    server: LocalApiServer, kill_switch: FileKillSwitch
) -> None:
    request(server, "/emergency-stop", token=TOKEN, post=True)
    assert kill_switch.active is True

    status, body = request(server, "/resume", token=TOKEN, post=True)
    assert status == HTTPStatus.OK
    assert json.loads(body)["status"] == "RESUMED"
    assert not kill_switch.active


def test_both_control_directions_are_audited(
    server: LocalApiServer, events: list[AuditEvent]
) -> None:
    """The dashboard leaves no record of a stop raised over HTTP; this surface does."""
    request(server, "/emergency-stop", token=TOKEN, post=True)
    request(server, "/resume", token=TOKEN, post=True)

    assert [event.event_type for event in events] == ["control", "control"]
    assert all(event.component == "local-api" for event in events)


def test_an_audit_record_never_contains_the_token(
    server: LocalApiServer, events: list[AuditEvent]
) -> None:
    request(server, "/emergency-stop", token=TOKEN, post=True)

    assert events
    assert TOKEN not in json.dumps(events[0].to_dict())


def test_a_read_is_not_audited_as_a_control(
    server: LocalApiServer, events: list[AuditEvent]
) -> None:
    request(server, "/status", token=TOKEN)
    assert events == []


# -- reporting matches the dashboard ------------------------------------


def test_status_reports_the_same_safety_flags_as_the_dashboard(server: LocalApiServer) -> None:
    _, body = request(server, "/status", token=TOKEN)
    payload = json.loads(body)

    assert payload["safety"]["dry_run"] is True
    assert payload["safety"]["demo_only"] is True
    assert payload["terminal"]["instance_name"] == "Alpari-MT5-Demo"


def test_risk_reports_the_whitelist(server: LocalApiServer) -> None:
    _, body = request(server, "/risk", token=TOKEN)
    assert json.loads(body)["allowed_symbols"] == ["BITCOIN"]


def test_positions_fail_closed_without_a_snapshot(server: LocalApiServer) -> None:
    """"Cannot see positions" must stay distinguishable from "no positions"."""
    _, body = request(server, "/positions", token=TOKEN)
    payload = json.loads(body)
    assert payload["status"] == "UNAVAILABLE"
    assert payload["positions"] == []


def test_metrics_reports_nothing_measured_without_a_log(server: LocalApiServer) -> None:
    _, body = request(server, "/metrics", token=TOKEN)
    payload = json.loads(body)
    assert all(not entry["measured"] for entry in payload["latency_ms"].values())


def test_a_non_numeric_tail_is_refused(server: LocalApiServer) -> None:
    status, body = request(server, "/metrics?tail=lots", token=TOKEN)
    assert status == HTTPStatus.BAD_REQUEST
    assert json.loads(body)["error"] == "tail must be an integer"


def test_an_oversized_tail_is_clamped_not_refused(server: LocalApiServer) -> None:
    status, _ = request(server, "/logs?tail=10000000", token=TOKEN)
    assert status == HTTPStatus.OK


# -- keep-alive is not corrupted by a refusal ---------------------------


def test_a_refused_request_leaves_the_connection_usable(server: LocalApiServer) -> None:
    """An unread body would desynchronise the next request on the same connection."""
    for _ in range(3):
        status, _ = request(server, "/status")
        assert status == HTTPStatus.UNAUTHORIZED

    status, body = request(server, "/status", token=TOKEN)
    assert status == HTTPStatus.OK
    assert json.loads(body)["terminal"]["instance_name"] == "Alpari-MT5-Demo"


def test_a_refused_post_to_an_unknown_route_leaves_the_connection_usable(
    server: LocalApiServer,
) -> None:
    for _ in range(3):
        status, _ = request(server, "/execute", post=True)
        assert status == HTTPStatus.UNAUTHORIZED

    status, _ = request(server, "/status", token=TOKEN)
    assert status == HTTPStatus.OK


# -- the client ---------------------------------------------------------


def test_client_reads_status(server: LocalApiServer) -> None:
    with LocalApiClient(server.url, TOKEN) as client:
        payload = client.status()
    assert payload["safety"]["dry_run"] is True


def test_client_reports_a_rejected_token_as_a_refusal(server: LocalApiServer) -> None:
    """A wrong token is not an outage, so the message must not invite a retry."""
    with LocalApiClient(server.url, "wrong") as client:
        with pytest.raises(ApiError, match="rejected the configured token"):
            client.status()


def test_client_is_inert_before_it_is_started(server: LocalApiServer) -> None:
    with pytest.raises(ApiError, match="not started"):
        LocalApiClient(server.url, TOKEN).status()


def test_client_engages_the_durable_stop(
    server: LocalApiServer, kill_switch: FileKillSwitch
) -> None:
    with LocalApiClient(server.url, TOKEN) as client:
        assert client.emergency_stop()["status"] == "STOPPED"
        assert kill_switch.active is True
        assert client.resume()["status"] == "RESUMED"
    assert not kill_switch.active


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5:8766/api/v1",
        "http://example.com/api/v1",
        "http://localhost.example.com/api/v1",
    ],
)
def test_client_refuses_an_endpoint_that_is_not_on_loopback(url: str) -> None:
    with pytest.raises(ApiError, match="loopback"):
        LocalApiClient(url, TOKEN).start()


def test_client_refuses_a_scheme_that_is_not_http(url: str = "ftp://127.0.0.1/api/v1") -> None:
    with pytest.raises(ApiError, match="http or https"):
        LocalApiClient(url, TOKEN).start()


def test_client_requires_a_token() -> None:
    with pytest.raises(ApiError, match="requires a token"):
        LocalApiClient("http://127.0.0.1:8766/api/v1", "").start()


def test_client_bounds_the_response_size(server: LocalApiServer) -> None:
    with LocalApiClient(server.url, TOKEN, max_bytes=16) as client:
        with pytest.raises(ApiError, match="larger than"):
            client.status()


def test_the_client_has_no_method_that_can_place_an_order() -> None:
    """The boundary is enforced by the server too, but it should be visible here as well."""
    forbidden = {"execute", "order", "place_order", "close", "close_position", "reconcile"}
    assert not forbidden & set(dir(LocalApiClient))
