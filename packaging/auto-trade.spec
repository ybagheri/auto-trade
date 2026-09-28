# PyInstaller definition for the auto-trade Windows executable.
#
# Build with:  .\scripts\build-exe.ps1
# The script installs the build requirements into a throwaway virtual
# environment first, so a build never depends on whatever happens to be
# installed in the developer's interpreter.
#
# The result is a one-folder build on purpose. A single file would unpack itself
# into a temporary directory on every start, which adds a failure mode to a
# safety-gated tool for no benefit.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
PACKAGE_ROOT = ROOT / "src" / "auto_trade"

# The dashboard page is package data: without it the server refuses to serve and
# says so instead of rendering a blank page. The MT5 indicator, the scripts, and
# the documentation are copied next to the executable by scripts\build-exe.ps1,
# where an operator can see and run them.
datas = [(str(PACKAGE_ROOT / "interfaces" / "dashboard.html"), "auto_trade/interfaces")]

# pywinauto, comtypes, and pywin32 carry the MT5 UI automation. They are imported
# lazily, so they are not discovered by analysis and have to be named here.
hiddenimports = collect_submodules("pywinauto") + [
    "comtypes",
    "comtypes.client",
    "win32api",
    "win32com.client",
    "win32con",
    "win32gui",
    "win32process",
    "win32ui",
    "win32security",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "pytest", "mypy", "ruff", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="auto-trade",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "packaging" / "auto-trade.ico") if (ROOT / "packaging" / "auto-trade.ico").is_file() else None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="auto-trade",
)
