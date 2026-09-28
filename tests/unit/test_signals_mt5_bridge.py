from __future__ import annotations

import json
from pathlib import Path

import pytest

from auto_trade.domain.exceptions import InvalidSignalError, NoSignalAvailable
from auto_trade.infrastructure.signals import MT5BridgeSignalProvider

from ..helpers import signal_data


def write_signal(directory: Path, name: str, payload: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_bridge_provider_consumes_a_signal_written_by_mql5(tmp_path: Path) -> None:
    files = tmp_path / "MQL5" / "Files"
    write_signal(files, "auto_trade_signal_1.json", signal_data("bridge-1"))
    provider = MT5BridgeSignalProvider(files)
    provider.start()
    try:
        received = provider.receive()
    finally:
        provider.stop()

    assert received.signal_id == "bridge-1"
    assert not (files / "auto_trade_signal_1.json").exists()


def test_bridge_provider_ignores_unrelated_files(tmp_path: Path) -> None:
    """The position reader's snapshots must not be mistaken for signals."""
    files = tmp_path / "files"
    files.mkdir()
    (files / "auto_trade_positions_a.json").write_text(json.dumps({"positions": []}), "utf-8")
    (files / "notes.json").write_text(json.dumps(signal_data()), "utf-8")
    provider = MT5BridgeSignalProvider(files)
    provider.start()
    try:
        with pytest.raises(NoSignalAvailable):
            provider.receive()
    finally:
        provider.stop()


def test_bridge_provider_keeps_an_unparsable_file(tmp_path: Path) -> None:
    files = tmp_path / "files"
    files.mkdir()
    path = files / "auto_trade_signal_broken.json"
    path.write_text("{", encoding="utf-8")
    provider = MT5BridgeSignalProvider(files)
    provider.start()
    try:
        with pytest.raises(InvalidSignalError):
            provider.receive()
    finally:
        provider.stop()

    assert path.exists()


def test_bridge_provider_is_inert_before_start(tmp_path: Path) -> None:
    provider = MT5BridgeSignalProvider(tmp_path / "files")

    with pytest.raises(NoSignalAvailable, match="not started"):
        provider.receive()


def test_bridge_provider_tolerates_a_missing_directory(tmp_path: Path) -> None:
    provider = MT5BridgeSignalProvider(tmp_path / "not-there")
    provider.start()
    try:
        with pytest.raises(NoSignalAvailable):
            provider.receive()
    finally:
        provider.stop()


def test_bridge_provider_can_keep_the_file_for_evidence(tmp_path: Path) -> None:
    files = tmp_path / "files"
    path = write_signal(files, "auto_trade_signal_keep.json", signal_data("bridge-2"))
    provider = MT5BridgeSignalProvider(files, delete_after_read=False)
    provider.start()
    try:
        assert provider.receive().signal_id == "bridge-2"
    finally:
        provider.stop()

    assert path.exists()
