from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from auto_trade.domain.exceptions import SignalSourceError
from auto_trade.domain.models import ExecutionPolicy, RiskLimits
from auto_trade.infrastructure.configuration import AppConfig
from auto_trade.infrastructure.signals import (
    HttpSignalProvider,
    NamedPipeSignalProvider,
    WebSocketSignalProvider,
)


def config_for(tmp_path: Path, **overrides: object) -> AppConfig:
    values: dict[str, object] = {
        "terminal_path": tmp_path / "terminal64.exe",
        "data_path": tmp_path / "data",
        "instance_name": "Alpari-MT5-Demo",
        "signal_directory": tmp_path / "signals",
        "log_directory": tmp_path / "logs",
        "policy": ExecutionPolicy(dry_run=True, demo_only=True),
        "risk": RiskLimits(frozenset({"EURUSD"}), Decimal("1.0"), 5, 10),
    }
    values.update(overrides)
    return AppConfig(**values)  # type: ignore[arg-type]


def test_no_source_is_configured_by_default(tmp_path: Path) -> None:
    assert config_for(tmp_path).signal_source() is None


def test_http_source_is_selected(tmp_path: Path) -> None:
    config = config_for(
        tmp_path,
        http_signal_url="http://127.0.0.1:8787/signals/next",
        http_signal_token="token",
    )

    source = config.signal_source()

    assert isinstance(source, HttpSignalProvider)
    assert source.url == "http://127.0.0.1:8787/signals/next"


def test_pipe_source_is_selected(tmp_path: Path) -> None:
    config = config_for(
        tmp_path,
        pipe_signal_name=r"\\.\pipe\auto_trade_signals",
        pipe_signal_token="token",
    )

    assert isinstance(config.signal_source(), NamedPipeSignalProvider)


def test_websocket_source_is_selected(tmp_path: Path) -> None:
    config = config_for(
        tmp_path,
        ws_signal_url="ws://127.0.0.1:8787/signals",
        ws_signal_token="token",
    )

    assert isinstance(config.signal_source(), WebSocketSignalProvider)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ({"http_signal_url": "http://127.0.0.1:1/x"}, {"ws_signal_url": "ws://127.0.0.1:1/x"}),
        (
            {"http_signal_url": "http://127.0.0.1:1/x"},
            {"pipe_signal_name": r"\\.\pipe\auto_trade_signals"},
        ),
        (
            {"ws_signal_url": "ws://127.0.0.1:1/x"},
            {"pipe_signal_name": r"\\.\pipe\auto_trade_signals"},
        ),
    ],
)
def test_two_configured_sources_are_refused(
    tmp_path: Path, first: dict[str, str], second: dict[str, str]
) -> None:
    """Ambiguity is a configuration error, not something to resolve by precedence."""
    config = config_for(tmp_path, **{**first, **second})

    with pytest.raises(SignalSourceError, match="more than one signal source"):
        config.signal_source()


def test_a_url_without_a_token_still_configures_a_source(tmp_path: Path) -> None:
    """The provider, not the configuration, decides that a token is mandatory."""
    config = config_for(tmp_path, http_signal_url="http://127.0.0.1:8787/signals/next")

    source = config.signal_source()

    assert source is not None
    with pytest.raises(SignalSourceError, match="token"):
        source.start()
