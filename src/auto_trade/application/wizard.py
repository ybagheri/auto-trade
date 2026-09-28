from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..domain.exceptions import AutoTradeError

MANAGED_KEYS = (
    "AUTO_TRADE_TERMINAL_PATH",
    "AUTO_TRADE_DATA_PATH",
    "AUTO_TRADE_INSTANCE_NAME",
    "AUTO_TRADE_SIGNAL_DIR",
    "AUTO_TRADE_LOG_DIR",
    "AUTO_TRADE_ALLOWED_SYMBOLS",
    "AUTO_TRADE_MAX_VOLUME",
    "AUTO_TRADE_MAX_ORDERS_PER_MINUTE",
    "AUTO_TRADE_SIGNAL_EXPIRATION_SECONDS",
    "AUTO_TRADE_DRY_RUN",
    "AUTO_TRADE_DEMO_ONLY",
)

# The wizard writes the final execution control as false and never as anything
# else. Enabling a real order stays a deliberate, reviewed edit of the file.
EXECUTION_KEY = "AUTO_TRADE_ENABLE_EXECUTION"

Ask = Callable[[str, str], str]


class ConfigurationError(AutoTradeError):
    """Raised when an answer cannot produce a safe configuration."""


@dataclass(frozen=True)
class WizardAnswers:
    terminal_path: str
    data_path: str
    instance_name: str
    allowed_symbols: str
    max_volume: str
    max_orders_per_minute: int
    expiration_seconds: int
    signal_directory: str = "signals"
    log_directory: str = "logs"
    dry_run: bool = True
    demo_only: bool = True


@dataclass(frozen=True)
class EnvFile:
    lines: tuple[str, ...]
    values: dict[str, str]


def collect_answers(ask: Ask, defaults: WizardAnswers) -> WizardAnswers:
    """Ask for each setting, showing the current value as the default.

    An empty answer keeps the default, so the wizard is reviewable: the operator
    sees what is configured and changes only what they intend to.
    """

    def answer(prompt: str, default: str) -> str:
        supplied = ask(f"{prompt} [{default}]", default).strip()
        return supplied or default

    return WizardAnswers(
        terminal_path=answer("MT5 terminal executable path", defaults.terminal_path),
        data_path=answer("MT5 data directory", defaults.data_path),
        instance_name=answer(
            "MT5 window title words that identify the demo terminal", defaults.instance_name
        ),
        allowed_symbols=answer("Allowed symbols, comma separated", defaults.allowed_symbols),
        max_volume=answer("Maximum order volume", defaults.max_volume),
        max_orders_per_minute=int(
            answer("Maximum orders per minute", str(defaults.max_orders_per_minute))
        ),
        expiration_seconds=int(
            answer("Signal lifetime in seconds", str(defaults.expiration_seconds))
        ),
        signal_directory=answer("Signal directory", defaults.signal_directory),
        log_directory=answer("Log directory", defaults.log_directory),
        dry_run=_confirm(ask, "Keep dry-run enabled (no final order control)", defaults.dry_run),
        demo_only=_confirm(ask, "Keep demo-only policy enabled", defaults.demo_only),
    )


def _confirm(ask: Ask, prompt: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    answer = ask(f"{prompt} ({suffix})", "y" if default else "n").strip().lower()
    if not answer:
        return default
    if answer not in {"y", "n"}:
        raise ConfigurationError(f"{prompt}: answer must be y or n")
    return answer == "y"


def validate(answers: WizardAnswers) -> None:
    """Refuse answers that would point the application at the wrong terminal.

    A configuration file is written once and then trusted by every later run, so
    a typo in a path has to be caught here rather than at the moment an order
    dialog opens.
    """
    terminal = Path(answers.terminal_path)
    if not terminal.is_file():
        raise ConfigurationError(f"MT5 terminal executable does not exist: {terminal}")
    data_path = Path(answers.data_path)
    if not data_path.is_dir():
        raise ConfigurationError(f"MT5 data directory does not exist: {data_path}")
    if not answers.instance_name.strip():
        raise ConfigurationError(
            "an MT5 instance name is required: without it an unintended terminal "
            "could be driven"
        )
    if not _symbols(answers.allowed_symbols):
        raise ConfigurationError("at least one allowed symbol is required")
    try:
        volume = Decimal(answers.max_volume)
    except InvalidOperation as exc:
        raise ConfigurationError(f"max volume must be numeric: {answers.max_volume}") from exc
    if not volume.is_finite() or volume <= 0:
        raise ConfigurationError("max volume must be a positive finite number")
    if answers.max_orders_per_minute < 1:
        raise ConfigurationError("max orders per minute must be at least 1")
    if answers.expiration_seconds < 1:
        raise ConfigurationError("signal lifetime must be at least 1 second")


def _symbols(raw: str) -> list[str]:
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def render(answers: WizardAnswers) -> str:
    """Render the managed keys, always with the execution control disabled."""
    symbols = ",".join(_symbols(answers.allowed_symbols))
    return "\n".join(
        [
            f"AUTO_TRADE_TERMINAL_PATH={answers.terminal_path}",
            f"AUTO_TRADE_DATA_PATH={answers.data_path}",
            f"AUTO_TRADE_INSTANCE_NAME={answers.instance_name}",
            f"AUTO_TRADE_SIGNAL_DIR={answers.signal_directory}",
            f"AUTO_TRADE_LOG_DIR={answers.log_directory}",
            f"AUTO_TRADE_ALLOWED_SYMBOLS={symbols}",
            f"AUTO_TRADE_MAX_VOLUME={answers.max_volume}",
            f"AUTO_TRADE_MAX_ORDERS_PER_MINUTE={answers.max_orders_per_minute}",
            f"AUTO_TRADE_SIGNAL_EXPIRATION_SECONDS={answers.expiration_seconds}",
            f"AUTO_TRADE_DRY_RUN={str(answers.dry_run).lower()}",
            f"AUTO_TRADE_DEMO_ONLY={str(answers.demo_only).lower()}",
            f"{EXECUTION_KEY}=false",
        ]
    )


def apply_to_file(answers: WizardAnswers, target: Path, overwrite: bool = False) -> Path:
    """Write the answers into an env file, keeping settings the wizard never asks about.

    An existing file is not replaced wholesale: keys such as the strategy module
    and the HTTP signal token are preserved, and only the managed keys change.
    Without ``overwrite`` a managed key that already holds a different value is
    refused, so a deliberate configuration is never silently rewritten.
    """
    path = Path(target)
    existing = read_env_file(path)
    updates = dict(_pairs(render(answers)))
    conflicts = sorted(
        key
        for key, value in updates.items()
        if key in existing.values and existing.values[key] != value
    )
    if conflicts and not overwrite:
        raise ConfigurationError(
            f"{path.name} already configures {', '.join(conflicts)}; review it and pass "
            "--overwrite to replace the managed keys"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_merge(existing, updates), encoding="utf-8")
    return path


def read_env_file(path: Path) -> EnvFile:
    """Read key/value pairs from an env file, keeping the original line order."""
    lines: list[str] = []
    values: dict[str, str] = {}
    if Path(path).is_file():
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return EnvFile(lines=tuple(lines), values=values)


def _merge(existing: EnvFile, updates: dict[str, str]) -> str:
    merged: list[str] = []
    replaced: set[str] = set()
    for line in existing.lines:
        key = line.partition("=")[0].strip()
        if key in updates:
            merged.append(f"{key}={updates[key]}")
            replaced.add(key)
        else:
            merged.append(line)
    for key, value in updates.items():
        if key not in replaced:
            merged.append(f"{key}={value}")
    return "\n".join(merged).rstrip("\n") + "\n"


def _pairs(rendered: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line in rendered.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            pairs.append((key, value))
    return pairs
