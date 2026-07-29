"""Export session as a self-contained HTML document."""

import json
from pathlib import Path


def export_session(session_id: str, output_path: str | Path) -> Path:
    repo_root = Path(__file__).resolve().parent
    sessions_dir = repo_root / ".virgo_memory" / "sessions"
    session_file = sessions_dir / f"{session_id}.json"
    if not session_file.exists():
        raise FileNotFoundError(f"Session not found: {session_id}")

    with session_file.open("r", encoding="utf-8") as f:
        session = json.load(f)

    css = self._css()
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>Session {session_id}</title>
<style>{css}</style>
</head>
<body>
<h1>Session {session_id}</h1>
<pre>{_escape(json.dumps(session, indent=2))}</pre>
</body>
</html>"""

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write(html)
    return out


def _css() -> str:
    return (
        "body{font-family:system-ui,sans-serif;background:#0d1117;color:#c9d1d9;margin:2rem;}"
        "pre{background:#161b22;padding:1rem;border-radius:6px;overflow:auto;}"
        "h1{font-weight:400;}"
    )


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
