from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ...domain.exceptions import AutoTradeError


class EnvFileError(AutoTradeError):
    """Raised when a dotenv-style configuration file is malformed."""


@dataclass(frozen=True)
class EnvFileOrigin:
    """Which env file was loaded, and whether the operator can be said to have chosen it.

    An env file is a trust boundary, not just a bag of settings. The checkout's
    own ``.env`` was written by ``configure`` and reviewed; a ``.env`` that
    happens to sit in whatever directory the process was launched from was put
    there by whoever wrote that directory, and the current-directory lookup comes
    *first*, so it silently pre-empts the reviewed file. That matters most for
    ``AUTO_TRADE_ENABLE_EXECUTION``, where a dropped file would turn a dry-run
    installation into a live one.
    """

    path: Path | None
    source: str
    trusted: bool

    @property
    def description(self) -> str:
        if self.path is None:
            return "no env file was loaded"
        state = "reviewed or explicitly chosen" if self.trusted else "NOT a reviewed file"
        return f"{self.path} ({self.source}, {state})"


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
    origin = load_env_file_with_origin(path)
    return origin.path


def load_env_file_with_origin(path: Path | None = None) -> EnvFileOrigin:
    """Load the env file and report where it came from, and whether it was chosen.

    Trust is a property of *which file* was loaded, not of how it was found.
    Running from the checkout is normal and its own ``.env`` is the reviewed
    file, so that lookup is trusted too. What is not trusted is a ``.env`` that
    belongs to some other directory: that one was put there by whoever wrote that
    directory, it pre-empts the checkout's file because the lookup order checks
    it first, and it can therefore turn a dry-run installation into a live one
    without a person editing anything.
    """
    if path is not None:
        return _load(path, "explicit path")
    override = os.getenv("AUTO_TRADE_ENV_FILE")
    if override:
        return _load(Path(override), "$AUTO_TRADE_ENV_FILE")
    local = Path(".env")
    if local.is_file():
        return _load(local, "current working directory")
    checkout = _checkout_env_file()
    if checkout is not None:
        return _load(checkout, "project checkout")
    return EnvFileOrigin(path=None, source="none", trusted=True)


def _is_reviewed_file(target: Path) -> bool:
    """Whether *target* is this project's own ``.env``.

    The checkout file is the one next to the ``pyproject.toml`` that this package
    was loaded from, so it is the file ``configure`` writes and a person reviews.
    An explicit path or ``$AUTO_TRADE_ENV_FILE`` is a person naming a file and is
    taken at their word; only the current-directory lookup needs this check.
    """
    checkout = _checkout_env_file()
    if checkout is None:
        return False
    try:
        return target.resolve() == checkout.resolve()
    except OSError:
        return False


def _load(target: Path, source: str) -> EnvFileOrigin:
    if not target.is_file():
        return EnvFileOrigin(path=None, source=source, trusted=True)
    trusted = source != "current working directory" or _is_reviewed_file(target)
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
    return EnvFileOrigin(path=target, source=source, trusted=trusted)


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
