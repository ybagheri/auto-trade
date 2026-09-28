from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from auto_trade.application.wizard import (
    EXECUTION_KEY,
    ConfigurationError,
    WizardAnswers,
    apply_to_file,
    collect_answers,
    read_env_file,
    render,
    validate,
)


def answers_for(tmp_path: Path, **overrides: object) -> WizardAnswers:
    terminal = tmp_path / "terminal64.exe"
    terminal.write_text("MZ", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    values: dict[str, object] = {
        "terminal_path": str(terminal),
        "data_path": str(data),
        "instance_name": "Alpari-MT5-Demo",
        "allowed_symbols": "eurusd, xauusd",
        "max_volume": "1.0",
        "max_orders_per_minute": 5,
        "expiration_seconds": 10,
    }
    values.update(overrides)
    return WizardAnswers(**values)  # type: ignore[arg-type]


def ask_from(responses: list[str]) -> Callable[[str, str], str]:
    pending = list(responses)

    def ask(prompt: str, default: str) -> str:
        return pending.pop(0) if pending else default

    return ask


# -- collection --------------------------------------------------------


def test_collect_answers_keeps_defaults_for_empty_answers(tmp_path: Path) -> None:
    defaults = answers_for(tmp_path)

    collected = collect_answers(ask_from([]), defaults)

    assert collected == defaults


def test_collect_answers_reads_every_question(tmp_path: Path) -> None:
    prompts: list[str] = []

    def ask(prompt: str, default: str) -> str:
        prompts.append(prompt)
        return default

    collect_answers(ask, answers_for(tmp_path))

    assert len(prompts) == 11
    assert any("terminal executable path" in prompt for prompt in prompts)
    assert any("demo-only" in prompt for prompt in prompts)


def test_collect_answers_applies_supplied_values(tmp_path: Path) -> None:
    defaults = answers_for(tmp_path)
    responses = [str(tmp_path / "other64.exe"), "", "", "XAUUSD", "0.5", "2", "30", "", "", "n", ""]

    collected = collect_answers(ask_from(responses), defaults)

    assert collected.terminal_path == str(tmp_path / "other64.exe")
    assert collected.allowed_symbols == "XAUUSD"
    assert collected.max_volume == "0.5"
    assert collected.max_orders_per_minute == 2
    assert collected.expiration_seconds == 30
    assert collected.dry_run is False
    assert collected.demo_only is True


def test_collect_answers_rejects_an_unreadable_confirmation(tmp_path: Path) -> None:
    responses = [""] * 9 + ["maybe", ""]

    with pytest.raises(ConfigurationError, match="must be y or n"):
        collect_answers(ask_from(responses), answers_for(tmp_path))


# -- validation --------------------------------------------------------


def test_validate_accepts_a_reachable_terminal(tmp_path: Path) -> None:
    validate(answers_for(tmp_path))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"terminal_path": "C:/does-not-exist/terminal64.exe"}, "executable does not exist"),
        ({"data_path": "C:/does-not-exist/data"}, "data directory does not exist"),
        ({"instance_name": "   "}, "instance name is required"),
        ({"allowed_symbols": " , "}, "at least one allowed symbol"),
        ({"max_volume": "abc"}, "must be numeric"),
        ({"max_volume": "0"}, "positive finite number"),
        ({"max_orders_per_minute": 0}, "at least 1"),
        ({"expiration_seconds": 0}, "at least 1 second"),
    ],
)
def test_validate_refuses_unsafe_answers(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        validate(answers_for(tmp_path, **overrides))


# -- rendering and writing ---------------------------------------------


def test_render_always_disables_execution(tmp_path: Path) -> None:
    rendered = render(answers_for(tmp_path))

    assert f"{EXECUTION_KEY}=false" in rendered
    assert "AUTO_TRADE_ALLOWED_SYMBOLS=EURUSD,XAUUSD" in rendered
    assert "AUTO_TRADE_DRY_RUN=true" in rendered


def test_apply_to_file_writes_a_new_file(tmp_path: Path) -> None:
    answers = answers_for(tmp_path)
    validate(answers)

    written = apply_to_file(answers, tmp_path / "config" / ".env")

    values = read_env_file(written).values
    assert values["AUTO_TRADE_TERMINAL_PATH"] == answers.terminal_path
    assert values[EXECUTION_KEY] == "false"


def test_apply_to_file_refuses_to_change_a_deliberate_value(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text(
        "AUTO_TRADE_INSTANCE_NAME=My-Demo\nAUTO_TRADE_STRATEGY=example_strategy:build\n",
        encoding="utf-8",
    )
    answers = answers_for(tmp_path)

    with pytest.raises(ConfigurationError, match="already configures"):
        apply_to_file(answers, target)

    assert "My-Demo" in target.read_text(encoding="utf-8")


def test_apply_to_file_overwrite_keeps_unmanaged_settings(tmp_path: Path) -> None:
    target = tmp_path / ".env"
    target.write_text(
        "# kept comment\n"
        "AUTO_TRADE_INSTANCE_NAME=My-Demo\n"
        "AUTO_TRADE_STRATEGY=example_strategy:build\n"
        "AUTO_TRADE_HTTP_SIGNAL_TOKEN=keep-me\n",
        encoding="utf-8",
    )
    answers = answers_for(tmp_path)

    apply_to_file(answers, target, overwrite=True)

    content = target.read_text(encoding="utf-8")
    values = read_env_file(target).values
    assert values["AUTO_TRADE_INSTANCE_NAME"] == "Alpari-MT5-Demo"
    assert values["AUTO_TRADE_STRATEGY"] == "example_strategy:build"
    assert values["AUTO_TRADE_HTTP_SIGNAL_TOKEN"] == "keep-me"
    assert "# kept comment" in content
    assert content.count("AUTO_TRADE_INSTANCE_NAME") == 1


def test_apply_to_file_reuses_an_identical_value(tmp_path: Path) -> None:
    answers = answers_for(tmp_path)
    target = tmp_path / ".env"
    apply_to_file(answers, target)

    apply_to_file(answers, target)

    assert read_env_file(target).values["AUTO_TRADE_TERMINAL_PATH"] == answers.terminal_path
