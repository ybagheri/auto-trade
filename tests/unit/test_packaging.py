from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "packaging" / "auto-trade.spec"
INSTALLER = ROOT / "packaging" / "installer.iss"
LAUNCHER = ROOT / "packaging" / "launcher.py"
BUILD_SCRIPT = ROOT / "scripts" / "build-exe.ps1"
INSTALLER_SCRIPT = ROOT / "scripts" / "build-installer.ps1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", [SPEC, INSTALLER, LAUNCHER, BUILD_SCRIPT, INSTALLER_SCRIPT])
def test_packaging_assets_exist(path: Path) -> None:
    assert path.is_file(), f"packaging asset is missing: {path.relative_to(ROOT)}"


def test_spec_freezes_a_launcher_that_uses_absolute_imports() -> None:
    """``python -m auto_trade`` relies on a relative import that a frozen script lacks."""
    spec = read(SPEC)
    launcher = read(LAUNCHER)

    assert "launcher.py" in spec
    assert "__main__.py" not in spec
    assert "from auto_trade.cli import main" in launcher
    assert "from ." not in launcher


def test_spec_ships_the_dashboard_page() -> None:
    assert "dashboard.html" in read(SPEC)


def test_spec_carries_the_mt5_automation_dependencies() -> None:
    spec = read(SPEC)

    for name in ("pywinauto", "comtypes", "win32gui", "win32com.client"):
        assert name in spec


def test_build_script_runs_the_checks_before_packaging() -> None:
    script = read(BUILD_SCRIPT)

    assert "test.ps1" in script
    assert "pyinstaller" in script.lower()
    assert "diagnostics-bundle" in script


def test_installer_script_refuses_to_package_a_missing_build() -> None:
    assert "build-exe.ps1" in read(INSTALLER_SCRIPT)


def test_installer_installs_no_service_and_no_network_rule() -> None:
    """A safety-gated local tool must not become a persistent network listener."""
    directives = [
        line.lower()
        for line in read(INSTALLER).splitlines()
        if line.strip() and not line.strip().startswith(";")
    ]
    body = "\n".join(directives)

    for forbidden in ("netsh", "firewall", "[service]", "runasoriginaluser"):
        assert forbidden not in body
    assert "auto-trade.exe" in body


def test_installer_runs_only_read_only_commands_after_installing() -> None:
    run_section = read(INSTALLER).split("[Run]", 1)[1]
    commands = [line for line in run_section.splitlines() if line.startswith("Filename:")]

    assert len(commands) == 1
    assert "auto-trade.exe" in commands[0]
    assert 'Parameters: "diagnostics"' in commands[0]
    assert "execute" not in commands[0]


def test_build_extra_is_declared() -> None:
    metadata: dict[str, Any] = tomllib.loads(read(ROOT / "pyproject.toml"))

    extras = metadata["project"]["optional-dependencies"]
    assert any(requirement.startswith("pyinstaller") for requirement in extras["build"])
