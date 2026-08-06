# Quickstart — Virgo Desktop

## Install

```bash
# Recommended (installs PyQt6 + FastAPI + dev tools)
pip install -e .[web,dev]

# Minimal (desktop only)
pip install pyqt6
```

> **Note:** If your system Python lacks PyQt6, the launcher auto-searches for another
> interpreter that has it. You can also run explicitly:
> `C:/Python314/python.exe virgo_desktop.py`

---

## Run

```bash
python virgo_desktop.py
# or via the entry point:
virgo-desktop
```

The first launch creates these gitignored state files next to the script:

| File | Purpose |
|------|---------|
| `.virgo_desktop_config.json` | Theme, sidebar order/collapse, last page |
| `.virgo_desktop_geom.json` | Window position & size |
| `.virgo_pipeline_ui.json` | Pipeline splitter positions |
| `.virgo_themes.json` | Your custom themes |
| `.virgo_chat_history/` | Saved chat sessions |
| `.virgo_prompts/` | Prompt templates |

---

## First pipeline

1. Open the **Pipeline** page (default on launch).
2. Enter a goal in the **Goal** box, e.g. `build a web scraper that fetches Hacker News headlines`.
3. Toggle **LLM: ON** to use your local Ollama model, or leave it off for deterministic demo mode.
4. Set **Iterations** (default 5) and click **▶ Run**.
5. Watch the animated DAG update live as the 4-phase state machine runs:
   `Discover → Plan → Generate → Test → Fix`.
6. Click any phase node to re-run just that phase.

---

## Chat

1. Open the **Chat** page.
2. Pick a **Model** from the dropdown (auto-populated from Ollama if running).
3. Choose a **Persona** (Default, Researcher, Concise, Teacher, Sarcastic, Coder).
4. Type a message and press Enter. Streaming replies appear token-by-token.

### Slash commands

| Command | Action |
|---------|--------|
| `/help` or `/?` | Show available commands |
| `/tools` | List registered tools |
| `/clear` | Wipe current chat history |
| `/read <path>` | Read a file into context |
| `/web <url>` | Fetch a URL and include it |
| `/py <code>` | Execute Python and show result |
| `/search <query>` | Web search + local memory recall |
| `/mem` | Search memory for relevant past runs |
| `/remember <note>` | Save a note to long-term memory |
| `/remember` | Remember the last exchange |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| **PyQt6 missing** | `pip install pyqt6` or run with a Python that has it (`C:/Python314/python.exe virgo_desktop.py`) |
| **Ollama not running** | Start Ollama, then pull a model: `ollama pull qwen2.5-coder:7b`. Chat falls back to echo mode if unreachable. |
| **DPI warning on Windows** | Harmless. Qt logs `QFont::setPointSize: Point size <= 0 (-1)` because Windows sizes fonts in pixels. Text renders correctly; the app suppresses the known-benign line. |
| **Page crashes the app** | The desktop app installs a global `sys.excepthook` that prints tracebacks instead of aborting. Check the terminal/console output for the error. |
| **Geometry stuck / off-screen** | Delete `.virgo_desktop_geom.json` and relaunch. |
| **Plugins missing** | Some pages (Web Dashboard, Font Picker, Sync, Automation, Model Manager) are optional. If their dependencies are absent they are hidden from the sidebar automatically. |
