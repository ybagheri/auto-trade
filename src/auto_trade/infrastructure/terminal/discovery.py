from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from ...domain.exceptions import TerminalNotFoundError
from ...domain.models import TerminalProfile

_TITLE_WAIT_SECONDS = 6.0

_PROCESS_QUERY = (
    "Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | "
    "Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
)

_WINDOW_QUERY = "Get-Process -Name terminal64 -ErrorAction SilentlyContinue | \
Select-Object Id,MainWindowTitle | ConvertTo-Json -Compress"


class WindowsTerminalDiscovery:
    def discover(self, profile: TerminalProfile) -> TerminalProfile:
        terminal = Path(profile.terminal_path)
        if not terminal.is_file():
            raise TerminalNotFoundError(f"MT5 executable not found: {terminal}")
        if not Path(profile.data_path).is_dir():
            raise TerminalNotFoundError(f"MT5 data path not found: {profile.data_path}")

        processes = self._query(_PROCESS_QUERY)
        matches = [
            record
            for record in processes
            if str(record.get("ExecutablePath", "")).lower() == str(terminal).lower()
        ]
        if not matches:
            raise TerminalNotFoundError("configured MT5 process is not running")

        wanted = profile.instance_name.strip().lower()
        if wanted:
            matched = self._match_instance(matches, wanted, profile.instance_name)
            matches = matched

        if len(matches) > 1:
            process_ids = ", ".join(str(_process_id(record)) for record in matches)
            raise TerminalNotFoundError(
                "configured MT5 is ambiguous, several instances matched "
                f"(pids: {process_ids}); narrow instance_name or close the extras"
            )
        return profile

    def _match_instance(
        self,
        matches: list[dict[str, object]],
        wanted: str,
        instance_name: str,
    ) -> list[dict[str, object]]:
        """Match the window title, retrying briefly while the window is still opening.

        A freshly launched terminal already has a process but no window title for a
        short while. Failing immediately there is correct but unhelpful, so the
        title is polled for a bounded time. The check still fails closed: if no
        title ever matches, discovery refuses rather than guessing.
        """
        deadline = time.monotonic() + _TITLE_WAIT_SECONDS
        while True:
            titles = self._window_titles()
            matched = [
                record
                for record in matches
                if wanted in titles.get(_process_id(record), "").lower()
            ]
            if matched or time.monotonic() >= deadline:
                break
            time.sleep(0.5)
        if not matched:
            raise TerminalNotFoundError(
                f"no running terminal matches instance name {instance_name!r}"
            )
        return matched

    @staticmethod
    def _query(command: str) -> list[dict[str, object]]:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if completed.returncode != 0:
            raise TerminalNotFoundError("could not query MT5 processes")
        raw = json.loads(completed.stdout or "[]")
        if isinstance(raw, dict):
            return [raw]
        return list(raw)

    @classmethod
    def _window_titles(cls) -> dict[int, str]:
        titles: dict[int, str] = {}
        for record in cls._query(_WINDOW_QUERY):
            process_id = _process_id(record)
            if process_id is not None:
                titles[process_id] = str(record.get("MainWindowTitle") or "")
        return titles


def _process_id(record: dict[str, object]) -> int:
    value = record.get("Id", record.get("ProcessId"))
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise TerminalNotFoundError("MT5 process record has no usable process id") from exc
