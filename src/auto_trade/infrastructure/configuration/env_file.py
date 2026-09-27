from __future__ import annotations

import os
from pathlib import Path

from ...domain.exceptions import AutoTradeError


class EnvFileError(AutoTradeError):
    """Raised when a dotenv-style configuration file is malformed."""


def load_env_file(path: Path | None = None) -> Path | None:
    """Load ``KEY=VALUE`` pairs into ``os.environ`` without overriding real env vars.

    Resolution order:

    1. ``path`` when given.
    2. ``$AUTO_TRADE_ENV_FILE`` when set.
    3. ``.env`` in the current working directory.
    4. ``.env`` in the project checkout, when running from a source tree.

    The working directory alone is not a safe default: a tool launched from a
    shortcut, a scheduled task, or another project would silently fall back to
    built-in defaults instead of the configured terminal.

    Supports comments, blank lines, an optional ``export`` prefix, and single or
    double quoted values. Unquoted values collapse ``\\\\`` to ``\\`` so Windows
    paths can be written the way they are quoted in ``.env.example``.
    """
    target = path or _discover_env_file()
    if target is None or not target.is_file():
        return None
    for number, raw_line in enumerate(
        target.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise EnvFileError(f"{target.name}:{number} is not a KEY=VALUE assignment")
        name = key.strip()
        if not name.isidentifier():
            raise EnvFileError(f"{target.name}:{number} has an invalid variable name")
        os.environ.setdefault(name, _unquote(value.strip()))
    return target


def _discover_env_file() -> Path | None:
    override = os.getenv("AUTO_TRADE_ENV_FILE")
    if override:
        return Path(override)
    local = Path(".env")
    if local.is_file():
        return local
    return _checkout_env_file()


def _checkout_env_file() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if (parent / "pyproject.toml").is_file() and candidate.is_file():
            return candidate
    return None


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value.replace("\\\\", "\\")
