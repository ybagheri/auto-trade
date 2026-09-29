from __future__ import annotations

import ctypes
import json
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from ...domain.exceptions import TerminalNotFoundError
from ...domain.models import TerminalProfile

_TITLE_WAIT_SECONDS = 6.0

# Bounds the only subprocess this project runs. A slow answer is not an answer,
# and 15s is unchanged from the original value: the fix here is that a timeout is
# now a refusal, not an exception.
_PROCESS_QUERY_TIMEOUT_SECONDS = 15.0

_PROCESS_QUERY = (
    "Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | "
    "Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
)


class ResolvedTerminal:
    """The one running terminal a profile identifies, and how it was pinned.

    ``process_id`` is the anchor everything else hangs off. A window title is
    not an identity: several MT5 instances on one machine routinely share one,
    because the title carries the account and the account name is not unique.
    """

    def __init__(
        self,
        process_id: int,
        window_title: str,
        executable_path: str,
        data_path: str,
        candidates_considered: int,
    ) -> None:
        self.process_id = process_id
        self.window_title = window_title
        self.executable_path = executable_path
        self.data_path = data_path
        self.candidates_considered = candidates_considered

    def to_dict(self) -> dict[str, object]:
        return {
            "process_id": self.process_id,
            "window_title": self.window_title,
            "executable_path": self.executable_path,
            "data_path": self.data_path,
            "terminals_with_this_executable": self.candidates_considered,
        }


class WindowsTerminalDiscovery:
    def discover(self, profile: TerminalProfile) -> TerminalProfile:
        self.resolve(profile)
        return profile

    def resolve(self, profile: TerminalProfile) -> ResolvedTerminal:
        """Find the single running terminal this profile names, or fail closed.

        The executable path is the primary key and the data directory is checked
        alongside it, because two instances of the same build on one machine are
        told apart by their data directory and by nothing else. The instance name
        is only ever used to *narrow* a set that the path already selected, so a
        title that several windows share cannot make the wrong terminal look
        like the right one.
        """
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
        considered = len(matches)

        wanted = profile.instance_name.strip().lower()
        if wanted:
            matches = self._match_instance(matches, wanted, profile.instance_name)

        if len(matches) > 1:
            process_ids = ", ".join(str(_process_id(record)) for record in matches)
            raise TerminalNotFoundError(
                "configured MT5 is ambiguous, several instances matched "
                f"(pids: {process_ids}); narrow instance_name or close the extras"
            )
        chosen = matches[0]
        return ResolvedTerminal(
            process_id=_process_id(chosen),
            window_title=self._window_titles().get(_process_id(chosen), ""),
            executable_path=str(chosen.get("ExecutablePath", "")),
            data_path=profile.data_path,
            candidates_considered=considered,
        )

    def _match_instance(
        self,
        matches: list[dict[str, object]],
        wanted: str,
        instance_name: str,
    ) -> list[dict[str, object]]:
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
        """Query the process list, turning every failure mode into a refusal.

        PowerShell is launched in a subprocess, so it can fail in ways that are
        not this code's fault: a machine busy enough to exceed the timeout, a
        policy that blocks the cmdlet, output that is not the JSON asked for.
        Each of those used to escape as an unhandled exception, so a loaded
        machine made `diagnostics` die with a traceback instead of reporting
        that the terminal could not be identified. A discovery failure is a
        refusal, and a refusal is reported.
        """
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                check=False,
                timeout=_PROCESS_QUERY_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise TerminalNotFoundError(
                "querying MT5 processes timed out after "
                f"{_PROCESS_QUERY_TIMEOUT_SECONDS:.0f}s; the machine may be busy, and a "
                "slow answer is not an answer"
            ) from exc
        except OSError as exc:
            raise TerminalNotFoundError(
                f"could not query MT5 processes: {type(exc).__name__}: {exc}"
            ) from exc
        if completed.returncode != 0:
            raise TerminalNotFoundError("could not query MT5 processes")
        try:
            raw = json.loads(completed.stdout or "[]")
        except ValueError as exc:
            raise TerminalNotFoundError(
                "the MT5 process query did not return usable JSON"
            ) from exc
        if isinstance(raw, dict):
            return [raw]
        if not isinstance(raw, list):
            raise TerminalNotFoundError("the MT5 process query returned an unexpected shape")
        return [item for item in raw if isinstance(item, dict)]

    @staticmethod
    def _window_titles() -> dict[int, str]:
        user32 = getattr(ctypes, "windll").user32
        titles: dict[int, str] = {}
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            wintypes.HWND,
            wintypes.LPARAM,
        )

        def collect(handle: int, _parameter: int) -> bool:
            if not user32.IsWindowVisible(handle):
                return True
            process_id = wintypes.DWORD()
            user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
            length = user32.GetWindowTextLengthW(handle)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(handle, buffer, length + 1)
                titles[int(process_id.value)] = buffer.value
            return True

        user32.EnumWindows(callback_type(collect), 0)
        return titles


def _process_id(record: dict[str, object]) -> int:
    value = record.get("Id", record.get("ProcessId"))
    try:
        return int(str(value))
    except (TypeError, ValueError) as exc:
        raise TerminalNotFoundError("MT5 process record has no usable process id") from exc
