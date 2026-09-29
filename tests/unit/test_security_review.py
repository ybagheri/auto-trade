"""Findings from the 2026-09-29 security review, each pinned here.

A review that only produces a document is worth little. Every finding below is
reproduced by a test that fails on the code as it was, so neither can come back
without a test going red.

The two that were fixed are the two that mattered:

1. A signal ``id`` was used unvalidated as a file name, so an id of ``../x``
   turned any signal source into an arbitrary file write.
2. A ``.env`` found in the current working directory pre-empted the reviewed one
   and could enable live execution, because that lookup happens first.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from auto_trade.cli.main import _signal_target
from auto_trade.domain.exceptions import AutoTradeError, InvalidSignalError
from auto_trade.domain.models import (
    SIGNAL_ID_PATTERN,
    ExecutionPolicy,
    RiskLimits,
    TradeSignal,
    validate_signal_id,
)
from auto_trade.infrastructure.configuration import AppConfig
from auto_trade.infrastructure.configuration.env_file import (
    EnvFileError,
    load_env_file_with_origin,
)

NOW = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


def signal_data(signal_id: str = "signal-1") -> dict[str, object]:
    return {
        "id": signal_id,
        "timestamp": "2026-09-29T07:00:00Z",
        "source": "test",
        "symbol": "EURUSD",
        "action": "BUY",
        "volume": 0.01,
    }


# -- finding 1: a signal id could name a path ----------------------------


@pytest.mark.parametrize(
    "signal_id",
    [
        "../../../../pwned",
        "..",
        ".",
        "..\\..\\windows",
        "a/b",
        "a\\b",
        "/absolute",
        "C:\\absolute",
        ".hidden",
        "",
        "   ",
        "has space",
        "semi;colon",
        "null\x00byte",
        "pipe|char",
        "star*",
        "x" * 129,
    ],
)
def test_a_signal_id_that_could_name_a_path_is_refused(signal_id: str) -> None:
    """This was an arbitrary file write reachable from any signal source."""
    with pytest.raises(InvalidSignalError):
        TradeSignal.from_dict(signal_data(signal_id))


@pytest.mark.parametrize(
    "signal_id",
    ["signal-1", "manual-20260929T062104Z", "a", "0", "A_b-c.1", "x" * 128],
)
def test_ordinary_generated_ids_are_still_accepted(signal_id: str) -> None:
    """The rule must not reject the ids this project actually produces."""
    signal = TradeSignal.from_dict(signal_data(signal_id))
    assert signal.signal_id == signal_id


def test_the_id_is_trimmed_rather_than_stored_with_spaces() -> None:
    assert validate_signal_id("  signal-1  ") == "signal-1"


def test_the_pattern_has_no_wildcard_characters() -> None:
    """A metacharacter would let a signal id become a glob in the providers."""
    for character in "*?[]":
        assert not SIGNAL_ID_PATTERN.match(f"id{character}")


def test_the_write_target_stays_inside_the_signal_directory(tmp_path: Path) -> None:
    signal = TradeSignal.from_dict(signal_data("signal-1"))
    target = _signal_target(tmp_path, signal)
    assert target.parent == tmp_path.resolve()


def test_the_write_target_is_contained_even_if_the_id_rule_were_widened(
    tmp_path: Path,
) -> None:
    """Defence in depth: the containment is a second, independent lock.

    The object is built without the constructor, which is the only way to
    simulate a future change to the id rule, and the write is still refused.
    """
    for escaping in ("../escaped", "..\\escaped", "a/../../escaped", "sub/../../up"):
        signal = TradeSignal.from_dict(signal_data("signal-1"))
        signal.signal_id = escaping
        with pytest.raises(AutoTradeError, match="outside"):
            _signal_target(tmp_path, signal)


def test_a_traversal_that_stays_inside_is_not_refused(tmp_path: Path) -> None:
    """Containment must not over-block: these land in the directory.

    `sub/../x` and a bare `..` both resolve to a file directly inside the
    directory, so refusing them would be a correctness bug rather than a safety
    win. The test exists so the containment check is not later "tightened" into
    something that breaks a legitimate id.
    """
    for contained in ("sub/../escaped-but-inside", ".."):
        signal = TradeSignal.from_dict(signal_data("signal-1"))
        signal.signal_id = contained
        target = _signal_target(tmp_path, signal)
        assert target.resolve().parent == tmp_path.resolve(), contained


def test_a_symlinked_directory_does_not_defeat_the_containment(tmp_path: Path) -> None:
    """The check is against the resolved path, not the string.

    Needs permission to create a symlink, so it is skipped on a machine without
    Developer Mode. The code path is the same one the string cases above
    exercise; what this adds is a path that only resolves correctly.
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available to this user")

    signal = TradeSignal.from_dict(signal_data("signal-1"))
    signal.signal_id = "..escaped-but-symlinked"

    with pytest.raises(AutoTradeError, match="outside"):
        _signal_target(link, signal)


# -- finding 2: an unreviewed .env could enable live execution -----------


def write_env(directory: Path, lines: list[str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ".env"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


@pytest.fixture
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start from a blank environment so no host variable decides the outcome."""
    for name in list(os.environ):
        if name.startswith("AUTO_TRADE_"):
            monkeypatch.delenv(name, raising=False)


def test_a_working_directory_env_file_is_reported_as_untrusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_environment: None
) -> None:
    write_env(tmp_path, ["AUTO_TRADE_DRY_RUN=true"])
    monkeypatch.chdir(tmp_path)

    origin = load_env_file_with_origin()

    assert origin.path == Path(".env")
    assert origin.trusted is False
    assert "current working directory" in origin.source


def test_the_checkouts_own_env_file_is_trusted_even_when_found_as_the_working_one(
    monkeypatch: pytest.MonkeyPatch, clean_environment: None
) -> None:
    """Trust is a property of which file, not of how it was found.

    Running from the project directory is the normal case, and flagging it would
    make the real installation unusable while fixing nothing: this is the file
    `configure` wrote and the operator reviewed.
    """
    checkout = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(checkout)
    monkeypatch.delenv("AUTO_TRADE_ENV_FILE", raising=False)

    origin = load_env_file_with_origin()

    assert origin.trusted is True, f"{origin.description} was wrongly called untrusted"


def test_the_checkout_env_file_is_trusted(
    monkeypatch: pytest.MonkeyPatch, clean_environment: None
) -> None:
    """`configure` writes this file and a person reviews it."""
    monkeypatch.setenv("AUTO_TRADE_ENV_FILE", str(Path(__file__).resolve().parents[2] / ".env"))

    origin = load_env_file_with_origin()

    assert origin.source == "$AUTO_TRADE_ENV_FILE"
    assert origin.trusted is True


def test_an_env_file_found_in_the_working_directory_cannot_enable_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_environment: None
) -> None:
    """The finding itself: a dropped .env turned a dry-run install into a live one."""
    write_env(
        tmp_path,
        [
            "AUTO_TRADE_TERMINAL_PATH=terminal64.exe",
            "AUTO_TRADE_DATA_PATH=.",
            "AUTO_TRADE_INSTANCE_NAME=Alpari-MT5-Demo",
            "AUTO_TRADE_ENABLE_EXECUTION=true",
            "AUTO_TRADE_DRY_RUN=false",
        ],
    )
    monkeypatch.chdir(tmp_path)

    config = AppConfig.from_env()

    assert config.policy.execution_enabled is True, "the setting is still read"
    assert config.live_execution_refusal(), "and it must still be refused"
    assert "current working directory" in config.live_execution_refusal()


def test_a_reviewed_env_file_may_enable_execution(
    monkeypatch: pytest.MonkeyPatch, clean_environment: None
) -> None:
    checkout = Path(__file__).resolve().parents[2]
    assert (checkout / ".env").is_file(), "this test needs the project's own .env"
    monkeypatch.setenv("AUTO_TRADE_ENABLE_EXECUTION", "true")
    monkeypatch.setenv("AUTO_TRADE_ENV_FILE", str(checkout / ".env"))

    config = AppConfig.from_env()

    assert config.env_file_trusted is True
    assert config.live_execution_refusal() == ""


def test_a_shell_variable_still_enables_execution_without_any_env_file(
    monkeypatch: pytest.MonkeyPatch, clean_environment: None
) -> None:
    """The supported way to enable a live test is the shell, and it must keep working."""
    monkeypatch.chdir(Path(__file__).resolve().parents[2])
    monkeypatch.setenv("AUTO_TRADE_ENABLE_EXECUTION", "true")
    monkeypatch.delenv("AUTO_TRADE_ENV_FILE", raising=False)

    config = AppConfig.from_env()

    assert config.policy.execution_enabled is True
    assert config.live_execution_refusal() == ""


def test_a_trusted_file_with_execution_disabled_is_never_refused(
    monkeypatch: pytest.MonkeyPatch, clean_environment: None
) -> None:
    monkeypatch.chdir(Path(__file__).resolve().parents[2])
    monkeypatch.setenv("AUTO_TRADE_ENV_FILE", str(Path(__file__).resolve().parents[2] / ".env"))

    config = AppConfig.from_env()

    assert config.live_execution_refusal() == ""


def test_the_origin_description_never_names_a_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_environment: None
) -> None:
    """The description is printed by diagnostics, so it must carry no secret."""
    write_env(
        tmp_path,
        ["AUTO_TRADE_API_TOKEN=super-secret-token", "AUTO_TRADE_DRY_RUN=true"],
    )
    monkeypatch.chdir(tmp_path)

    origin = load_env_file_with_origin()

    assert ".env" in origin.description
    assert "super-secret-token" not in origin.description


def test_a_malformed_env_file_is_refused_with_its_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_environment: None
) -> None:
    write_env(tmp_path, ["AUTO_TRADE_DRY_RUN=true", "not an assignment"])
    monkeypatch.chdir(tmp_path)

    with pytest.raises(EnvFileError, match=":2"):
        load_env_file_with_origin()


# -- reviewed and accepted, not defects ---------------------------------
#
# These are properties this project has on purpose. They are asserted so a
# future change that removes one has to be a decision, and so the review record
# states them rather than implying the surface is uniformly strict.


def test_a_signal_source_can_never_place_an_order(tmp_path: Path) -> None:
    """Every provider is a reader. None of them reaches a terminal or a ledger."""
    from auto_trade.infrastructure.signals import (
        FileSignalProvider,
        HttpSignalProvider,
        MT5BridgeSignalProvider,
        NamedPipeSignalProvider,
        WebSocketSignalProvider,
    )

    for provider in (
        FileSignalProvider(tmp_path),
        MT5BridgeSignalProvider(tmp_path),
        HttpSignalProvider("http://127.0.0.1:1/x", "t"),
        NamedPipeSignalProvider(r"\\.\pipe\x", "t"),
        WebSocketSignalProvider("ws://127.0.0.1:1/x", "t"),
    ):
        surface = {name for name in dir(provider) if not name.startswith("_")}
        assert not surface & {
            "execute_order",
            "close_position",
            "click",
            "submit",
            "send_order",
        }
        assert not hasattr(provider, "adapter")


def test_the_strategy_seam_exposes_no_execution_capability() -> None:
    """A market-analysis library may propose; it cannot reach the terminal."""
    from auto_trade.application.strategy import StrategyContext

    fields = set(StrategyContext.__dataclass_fields__)
    assert fields == {"symbol", "now", "positions", "account"}
    for name in fields:
        assert not name.startswith("_adapter")
        assert "terminal" not in name
        assert "ledger" not in name


def test_the_env_file_never_overrides_a_real_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_environment: None
) -> None:
    """`setdefault` is what stops a file from lowering a setting a person set."""
    write_env(tmp_path, ["AUTO_TRADE_DRY_RUN=false"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AUTO_TRADE_DRY_RUN", "true")

    load_env_file_with_origin()

    assert os.environ["AUTO_TRADE_DRY_RUN"] == "true"


def test_a_signal_is_written_as_data_and_never_evaluated(tmp_path: Path) -> None:
    """A payload that looks like code stays a string on the way through."""
    payload = signal_data("signal-1") | {"comment": "__import__('os').system('whoami')"}
    signal = TradeSignal.from_dict(payload)
    written = tmp_path / "out.json"
    written.write_text(json.dumps(signal.to_dict()), encoding="utf-8")

    reloaded = TradeSignal.from_dict(json.loads(written.read_text(encoding="utf-8")))

    assert reloaded.comment == "__import__('os').system('whoami')"
    assert isinstance(reloaded.comment, str)


# -- the configuration surface the review confirmed ----------------------


def test_diagnostics_would_report_the_env_file_origin(tmp_path: Path) -> None:
    """`diagnostics` is where an operator looks; the origin has to be visible there."""
    from auto_trade.cli.main import _diagnostics

    config = AppConfig(
        terminal_path=tmp_path / "terminal64.exe",
        data_path=tmp_path / "data",
        instance_name="Alpari-MT5-Demo",
        signal_directory=tmp_path / "signals",
        log_directory=tmp_path / "logs",
        policy=ExecutionPolicy(dry_run=True, demo_only=True),
        risk=RiskLimits(frozenset({"EURUSD"}), Decimal("1.0"), 5, 10),
        env_file=str(tmp_path / ".env"),
        env_file_trusted=False,
    )

    reported = _diagnostics(config)

    assert reported["env_file_trusted"] is False
    assert str(reported["env_file"]).endswith(".env")


def test_no_configuration_value_is_written_into_the_audit_log_by_the_reader() -> None:
    """The audit log is shared in a support bundle, so it must hold no token."""
    from auto_trade.domain.models import AuditEvent

    event = AuditEvent(component="test", event_type="test", message="nothing secret")
    serialised = json.dumps(event.to_dict())

    assert "TOKEN" not in serialised
    assert "token" not in serialised


# -- finding 5: a refused close left no record ---------------------------


def test_a_refused_close_is_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Somebody wanted an account changed and the project declined.

    A refusal printed to stderr lives in a scrollback, which is not a record. The
    trail is where an operator looks for an attempt.
    """
    from auto_trade.cli.main import main

    config = AppConfig(
        terminal_path=tmp_path / "terminal64.exe",
        data_path=tmp_path / "data",
        instance_name="Alpari-MT5-Demo",
        signal_directory=tmp_path / "signals",
        log_directory=tmp_path / "logs",
        policy=ExecutionPolicy(dry_run=True, demo_only=True),
        risk=RiskLimits(frozenset({"EURUSD"}), Decimal("1.0"), 5, 10),
    )
    monkeypatch.setattr(AppConfig, "from_env", classmethod(lambda cls: config))
    monkeypatch.delenv("AUTO_TRADE_ENABLE_CLOSE", raising=False)

    code = main(["close-position", "383094933", "--confirm-demo"])

    assert code == 2
    audit = (tmp_path / "logs" / "audit.log").read_text(encoding="utf-8")
    entries = [json.loads(line) for line in audit.splitlines() if line.strip()]
    refusals = [item for item in entries if item["event_type"] == "refused"]
    assert refusals, f"no refusal was recorded; the audit log held {audit!r}"
    assert refusals[0]["component"] == "position-close"
    assert "383094933" in refusals[0]["action"]
    assert "not in the execution ledger" in refusals[0]["message"]


def test_a_close_refusal_record_carries_no_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from auto_trade.cli.main import _audit_close_refusal

    config = AppConfig(
        terminal_path=tmp_path / "terminal64.exe",
        data_path=tmp_path / "data",
        instance_name="Alpari-MT5-Demo",
        signal_directory=tmp_path / "signals",
        log_directory=tmp_path / "logs",
        policy=ExecutionPolicy(dry_run=True, demo_only=True),
        risk=RiskLimits(frozenset({"EURUSD"}), Decimal("1.0"), 5, 10),
        api_token="super-secret-token",
    )

    _audit_close_refusal(config, "123", "closing is disabled")

    audit = (tmp_path / "logs" / "audit.log").read_text(encoding="utf-8")
    assert "super-secret-token" not in audit


# -- finding 3: a slow process query must refuse, not crash --------------


def test_a_timed_out_process_query_is_a_refusal_not_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Found by the suite failing under load, not by reading the code."""
    import subprocess

    from auto_trade.domain.exceptions import TerminalNotFoundError
    from auto_trade.infrastructure.terminal import discovery

    def timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=15)

    monkeypatch.setattr("subprocess.run", timeout)

    with pytest.raises(TerminalNotFoundError, match="timed out"):
        discovery.WindowsTerminalDiscovery._query("anything")


def test_unusable_process_query_output_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_trade.domain.exceptions import TerminalNotFoundError
    from auto_trade.infrastructure.terminal import discovery

    class Completed:
        returncode = 0
        stdout = "not json at all"

    monkeypatch.setattr("subprocess.run", lambda *a, **k: Completed())

    with pytest.raises(TerminalNotFoundError, match="usable JSON"):
        discovery.WindowsTerminalDiscovery._query("anything")


def test_a_blocked_shell_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_trade.domain.exceptions import TerminalNotFoundError
    from auto_trade.infrastructure.terminal import discovery

    def missing(*_args: object, **_kwargs: object) -> object:
        raise OSError("access is denied")

    monkeypatch.setattr("subprocess.run", missing)

    with pytest.raises(TerminalNotFoundError, match="could not query"):
        discovery.WindowsTerminalDiscovery._query("anything")
