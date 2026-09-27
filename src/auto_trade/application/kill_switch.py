from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ..domain.models import utc_now
from ..domain.protocols import KillSwitch


class FileKillSwitch(KillSwitch):
    """A kill switch that survives process exit and is shared between processes.

    The in-memory switch only protects the workflow instance that owns it, which
    makes it useless as an emergency stop: a separate process, a restarted
    application, or a second operator session would not see it. This
    implementation records the state in a sentinel file so every process sharing
    the same log directory observes the same stop, and the stop outlives a crash.
    """

    def __init__(self, path: Path, clock: Callable[[], datetime] = utc_now) -> None:
        super().__init__()
        self.path = Path(path)
        self.clock = clock

    def activate(self) -> None:
        super().activate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stamp = self.clock()
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        self.path.write_text(f"activated {stamp.isoformat()}\n", encoding="utf-8")

    def reset(self) -> None:
        super().reset()
        self.path.unlink(missing_ok=True)

    @property
    def active(self) -> bool:
        return super().active or self.path.is_file()

    def reason(self) -> str:
        if not self.path.is_file():
            return ""
        try:
            return self.path.read_text(encoding="utf-8").strip()
        except OSError:
            return "activated (reason unreadable)"

    @staticmethod
    def now() -> datetime:
        return utc_now()
