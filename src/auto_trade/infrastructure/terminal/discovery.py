from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ...domain.exceptions import TerminalNotFoundError
from ...domain.models import TerminalProfile


class WindowsTerminalDiscovery:
    def discover(self, profile: TerminalProfile) -> TerminalProfile:
        terminal = Path(profile.terminal_path)
        if not terminal.is_file():
            raise TerminalNotFoundError(f"MT5 executable not found: {terminal}")
        if not Path(profile.data_path).is_dir():
            raise TerminalNotFoundError(f"MT5 data path not found: {profile.data_path}")
        command = (
            "Get-CimInstance Win32_Process -Filter \"Name='terminal64.exe'\" | "
            "Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
        )
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
        records = raw if isinstance(raw, list) else [raw]
        matches = [
            record
            for record in records
            if str(record.get("ExecutablePath", "")).lower() == str(terminal).lower()
        ]
        if not matches:
            raise TerminalNotFoundError("configured MT5 process is not running")
        if profile.instance_name:
            title_matches = [
                record
                for record in matches
                if profile.instance_name.lower() in str(record).lower()
            ]
            if title_matches:
                matches = title_matches
        return profile
