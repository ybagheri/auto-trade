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
from auto_trade.domain.models import ExecutionPolicy, RiskLimits
from auto_trade.infrastructure.configuration import AppConfig
from auto_trade.interfaces import StatusReporter, build_server, is_loopback
from auto_trade.interfaces.server import DashboardServer, kill_switch_path, render_page

TOKEN = "test-token-123"
NOW = datetime(2026, 9, 26, 12, 0, 0, tzinfo=UTC)


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
def server(
    config: AppConfig, kill_switch: FileKillSwitch
) -> Iterator[DashboardServer]:
    reporter = StatusReporter(
        config=config,
        ledger=JsonExecutionLedger(config.log_directory / "idempotency.json"),
        kill_switch=kill_switch,
    )
    instance = build_server("127.0.0.1", 0, reporter, kill_switch, TOKEN)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=5)


# -- loopback enforcement ---------------------------------------------


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "LOCALHOST"])
def test_loopback_hosts_are_accepted(host: str) -> None:
    assert is_loopback(host)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com", ""])
def test_non_loopback_hosts_are_rejected(host: str) -> None:
    assert not is_loopback(host)


def test_server_refuses_to_bind_a_public_address(
    config: AppConfig, kill_switch: FileKillSwitch
) -> None:
    reporter = StatusReporter(
        config,
        JsonExecutionLedger(config.log_directory / "idempotency.json"),
        kill_switch,
    )

    with pytest.raises(ValueError, match="loopback"):
        build_server("0.0.0.0", 0, reporter, kill_switch, TOKEN)


# -- kill switch ------------------------------------------------------


def test_file_kill_switch_survives_a_new_instance(log_dir: Path) -> None:
    path = kill_switch_path(log_dir)
    first = FileKillSwitch(path, clock=lambda: NOW)
    assert first.active is False

    first.activate()
    assert path.is_file()

    # A separate process would construct its own instance against the same file.
    second = FileKillSwitch(path)
    assert second.active is True
    assert "2026-09-26T12:00:00" in second.reason()

    second.reset()
    assert FileKillSwitch(path).active is False


def test_kill_switch_reset_is_safe_when_not_activated(log_dir: Path) -> None:
    FileKillSwitch(kill_switch_path(log_dir)).reset()
    assert not kill_switch_path(log_dir).exists()


# -- read-only API ----------------------------------------------------


def request(
    server: DashboardServer, path: str, token: str | None = None, post: bool = False
) -> tuple[int, str]:
    data = b"{}" if post else None
    req = urllib.request.Request(
        server.url.rstrip("/") + path, data=data, method="POST" if post else "GET"
    )
    if token:
        req.add_header("X-Auto-Trade-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            body = response.read().decode("utf-8")
            return response.status, body
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def test_health_endpoint(server: DashboardServer) -> None:
    status, body = request(server, "/api/health")
    assert status == HTTPStatus.OK
    assert json.loads(body)["status"] == "ok"


def test_status_endpoint_reports_safety_flags(server: DashboardServer) -> None:
    status, body = request(server, "/api/status")
    payload = json.loads(body)
    assert status == HTTPStatus.OK
    assert payload["safety"]["dry_run"] is True
    assert payload["safety"]["demo_only"] is True
    assert payload["safety"]["kill_switch_active"] is False
    assert payload["terminal"]["instance_name"] == "Alpari-MT5-Demo"


def test_risk_endpoint_lists_whitelist(server: DashboardServer) -> None:
    _, body = request(server, "/api/risk")
    assert json.loads(body)["allowed_symbols"] == ["BITCOIN"]


def test_metrics_endpoint_reports_nothing_measured_without_a_log(
    server: DashboardServer,
) -> None:
    """An empty log is not a healthy log, so no phase may claim to be measured."""
    status, body = request(server, "/api/metrics")
    payload = json.loads(body)
    assert status == HTTPStatus.OK
    assert payload["events"] == 0
    assert all(not entry["measured"] for entry in payload["latency_ms"].values())


def test_metrics_endpoint_counts_an_unresolved_attempt(
    server: DashboardServer, log_dir: Path
) -> None:
    """A crash between the click and the observation is visible on the dashboard.

    The audit tail is read back from disk, so the count outlives the process that
    produced it, which is the whole reason it is not held in memory.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "audit.log").write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {
                    "timestamp": "2026-09-28T09:00:00Z",
                    "component": "execution",
                    "event_type": "state",
                    "signal_id": "signal-1",
                    "execution_id": "exec-1",
                    "state": "EXECUTING",
                    "message": "EXECUTING",
                },
                {
                    "timestamp": "2026-09-28T09:00:01Z",
                    "component": "execution",
                    "event_type": "state",
                    "signal_id": "signal-1",
                    "execution_id": "exec-1",
                    "state": "VERIFYING",
                    "message": "VERIFYING",
                },
            )
        ),
        encoding="utf-8",
    )

    _, body = request(server, "/api/metrics")
    payload = json.loads(body)
    assert payload["counters"]["unresolved_attempts"] == 1
    assert payload["counters"]["unresolved_execution_ids"] == ["exec-1"]


def test_metrics_endpoint_rejects_a_non_numeric_tail(server: DashboardServer) -> None:
    status, body = request(server, "/api/metrics?tail=lots")
    assert status == HTTPStatus.BAD_REQUEST
    assert json.loads(body)["error"] == "tail must be an integer"


def test_the_dashboard_never_renders_a_zero_for_an_unmeasured_phase(
    server: DashboardServer, log_dir: Path
) -> None:
    """A dry run never clicked, so the click phases must render a dash, not 0 ms.

    The rendered page is checked rather than the endpoint, because a zero here
    would be read as an instant trade rather than as an absent measurement.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "audit.log").write_text(
        "\n".join(
            json.dumps(
                {
                    "timestamp": f"2026-09-28T09:00:0{index}Z",
                    "component": "execution",
                    "event_type": "state",
                    "signal_id": "signal-1",
                    "execution_id": "exec-1",
                    "state": name,
                    "message": name,
                }
            )
            for index, name in enumerate(
                ["SIGNAL_RECEIVED", "VALIDATED", "ORDER_READY", "DRY_RUN_COMPLETED"]
            )
        ),
        encoding="utf-8",
    )
    _, body = request(server, "/api/metrics")
    payload = json.loads(body)

    assert payload["latency_ms"]["click_to_outcome"]["measured"] is False
    assert payload["latency_ms"]["click_to_outcome"]["p50_ms"] is None

    page = render_page()
    assert 'id="latency"' in page
    # The renderer sends a dash for a null figure instead of a number.
    assert 'value === null || value === undefined' in page
    assert "metrics" in page


def test_positions_endpoint_fails_closed_without_ui_position_values(
    server: DashboardServer,
) -> None:
    _, body = request(server, "/api/positions")
    payload = json.loads(body)
    assert payload["status"] == "UNAVAILABLE"
    assert payload["positions"] == []
    assert "position" in payload["error"].lower()


def test_unknown_route_is_not_found(server: DashboardServer) -> None:
    status, _ = request(server, "/api/nope")
    assert status == HTTPStatus.NOT_FOUND


def test_index_serves_the_dashboard_page(server: DashboardServer) -> None:
    req = urllib.request.Request(server.url)
    with urllib.request.urlopen(req, timeout=10) as response:
        html = response.read().decode("utf-8")
    assert response.status == HTTPStatus.OK
    assert "auto-trade dashboard" in html
    assert "http-equiv" not in html  # no external assets


# -- mutating API is token guarded ------------------------------------


def test_emergency_stop_requires_a_token(server: DashboardServer) -> None:
    status, body = request(server, "/api/emergency-stop", post=True)
    assert status == HTTPStatus.FORBIDDEN
    assert json.loads(body)["error"] == "forbidden"


def test_emergency_stop_rejects_a_wrong_token(server: DashboardServer) -> None:
    status, _ = request(server, "/api/emergency-stop", token="wrong", post=True)
    assert status == HTTPStatus.FORBIDDEN


def test_emergency_stop_with_token_activates_the_switch(
    server: DashboardServer, kill_switch: FileKillSwitch
) -> None:
    status, body = request(server, "/api/emergency-stop", token=TOKEN, post=True)
    assert status == HTTPStatus.OK
    assert json.loads(body)["status"] == "STOPPED"
    assert kill_switch.active is True

    # The switch is durable, so a fresh reporter sees it too.
    _, status_body = request(server, "/api/status")
    assert json.loads(status_body)["safety"]["kill_switch_active"] is True


def test_resume_clears_the_switch(server: DashboardServer, kill_switch: FileKillSwitch) -> None:
    request(server, "/api/emergency-stop", token=TOKEN, post=True)
    assert kill_switch.active is True

    status, body = request(server, "/api/resume", token=TOKEN, post=True)
    assert status == HTTPStatus.OK
    assert json.loads(body)["status"] == "RESUMED"
    assert kill_switch.active is False


def test_token_may_be_supplied_as_a_query_parameter(server: DashboardServer) -> None:
    status, _ = request(server, f"/api/resume?token={TOKEN}", post=True)
    assert status == HTTPStatus.OK


def test_keepalive_survives_a_refused_post_with_a_body(server: DashboardServer) -> None:
    """A refused POST must still drain its body or the next request desynchronises."""
    for _ in range(3):
        status, _ = request(server, "/api/emergency-stop", post=True)
        assert status == HTTPStatus.FORBIDDEN

    status, body = request(server, "/api/health")
    assert status == HTTPStatus.OK
    assert json.loads(body)["status"] == "ok"
