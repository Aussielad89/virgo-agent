# Troubleshooting — Virgo Desktop

## Launch failures

### PyQt6 not installed / `ImportError`

**Fix:** Install PyQt6 in the interpreter you are using:

```bash
pip install pyqt6
```

If you have multiple Pythons, run with the one that has it:

```bash
C:/Python314/python.exe virgo_desktop.py
```

The launcher (`_ensure_pyqt6`) will also auto-search `C:\Python3*` and re-exec under a
PyQt6-capable interpreter if the current one is missing the package.

### `QFrame` NameError (older versions)

In versions prior to the current refactor, some pages referenced `QFrame` without
importing it from `PyQt6.QtWidgets`, causing a `NameError` at import time.

**Status:** Fixed in the current codebase. All page modules import `QFrame` explicitly
from `PyQt6.QtWidgets`.

If you see this error, update to the latest source.

---

## Display & rendering

### DPI-awareness warning on Windows

Qt may log:

```
QFont::setPointSize: Point size <= 0 (-1)
```

**Cause:** On Windows the system font is sized in pixels. `QFont.pointSize()` resolves
to `-1` for pixel-sized fonts, and Qt emits the warning for every widget.

**Impact:** None. Text renders correctly.

**Status:** The desktop app installs a `qInstallMessageHandler` that suppresses this
exact known-benign line.

### Blurry text / scaling

If the UI looks tiny on a high-DPI display, set the environment variable before
launching:

```bash
set QT_ENABLE_HIGHDPI_SCALING=1
python virgo_desktop.py
```

---

## Runtime issues

### Ollama connection failed

The Chat page and Settings page probe `http://localhost:11434` to list models and
stream replies.

**Fixes:**
1. Start Ollama: `ollama serve`
2. Pull a model: `ollama pull qwen2.5-coder:7b`
3. Check the status-bar Ollama dot (top-right). Green = reachable, red = unreachable.

If Ollama is unreachable, Chat falls back to **echo mode** and the status bar shows
`Ollama: unreachable`.

### Optional pages / plugins missing

Several pages depend on optional packages or modules that may not be installed:

| Page | Dependency | Symptom if missing |
|------|-----------|-------------------|
| Web Dashboard | `PyQt6-WebEngine` | Tab hidden from sidebar |
| Model Manager | `virgo_model_manager.py` | Page unavailable |
| Desktop Automation | `virgo_desktop_automation.py` | Page unavailable |
| Sync | `virgo_desktop_sync.py` | Page unavailable |
| Font Picker | `virgo_font_picker.py` | Page unavailable |
| Agent pages (Artifacts, Budget, Memory, RAG, Timeline) | `virgo_agent_pages.py` | Pages unavailable |

Missing modules are caught at import time and the pages are silently omitted from
navigation.

### A page crashes / freezes the app

The desktop app installs a global `sys.excepthook` that prints tracebacks instead of
aborting. One bad page cannot kill the whole window.

**Steps:**
1. Check the terminal/console where you launched the app for the traceback.
2. Note the page name and exception type.
3. Restart the app; your last page, theme, and sidebar order are restored automatically.

---

## Crash reports

Unhandled exceptions are recorded by `virgo_crash.py`:

- **Directory:** `.virgo_crash_reports/`
- **Files:** `<timestamp>_<pid>.json` (rolling buffer of 5)
- **Latest pointer:** `.virgo_last_crash` contains the path to the newest report

Each report includes:
- UTC timestamp, Python version, platform
- Exception type, message, full traceback
- Last active page (when available)
- Tail of the log file (if `VIRGO_LOG_FILE` is set)

### Viewing reports

```bash
# List reports
python virgo_crash.py list

# Show a specific report
python virgo_crash.py show .virgo_crash_reports/20260805_123456_1234.json

# Clear all reports
python virgo_crash.py clear
```

---

## Resetting state

If the UI becomes corrupted (stuck off-screen, broken sidebar order, bad theme),
delete or edit the relevant config file and relaunch:

| Problem | File to delete / edit |
|---------|----------------------|
| Window off-screen / wrong size | `.virgo_desktop_geom.json` |
| Sidebar order or collapse broken | `.virgo_desktop_config.json` |
| Bad custom theme | `.virgo_themes.json` |
| Pipeline splitter stuck | `.virgo_pipeline_ui.json` |
| Corrupt chat history | `.virgo_chat_history/` |
| Corrupt prompt templates | `.virgo_prompts/` |
| All local desktop state | Delete all files above (they are regenerated on launch) |

> All of these files are gitignored. Deleting them is safe and non-destructive to your
> source code.

---

## Logs

The desktop app uses `_log.py`. Set the log level and optional file via environment
variables:

```bash
set VIRGO_LOG_LEVEL=DEBUG
set VIRGO_LOG_FILE=virgo_desktop.log
python virgo_desktop.py
```

Log file tail is also captured in crash reports for easier diagnosis.
