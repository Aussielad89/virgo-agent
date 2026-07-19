# PyInstaller spec for building a standalone Virgo Desktop executable.
# Usage:  pyinstaller virgo_desktop.spec
# Output: dist/virgo_desktop/virgo_desktop.exe
import os

block_cipher = None

a = Analysis(
    ["virgo_desktop.py"],
    pathex=[os.path.dirname(os.path.abspath(__file__))],
    binaries=[],
    datas=[
        ("virgo_desktop_pages.py", "."),
        ("scaffolds", "scaffolds"),
        ("logo.ico", "."),
    ],
    hiddenimports=[
        "virgo_desktop_pages",
        "_console", "_log", "cli", "main", "memory", "tools", "orchestrator",
        "virgo_network_scanner", "virgo_diagnostics", "virgo_alerts",
        "virgo_fixer", "virgo_scaffold", "mcp_server",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="virgo_desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="logo.ico" if os.path.exists("logo.ico") else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="virgo_desktop",
)
