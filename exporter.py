"""
exporter — export virgo pipeline results as HTML reports
and markdown summaries.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent

# ===========================================================================
# Markdown export
# ===========================================================================


def to_markdown(state: Any, title: str | None = None) -> str:
    """Render a WorkspaceState as a Markdown document."""
    lines: list[str] = []
    lines.append(f"# {title or 'virgo — Pipeline Report'}")
    lines.append("")
    lines.append(f"- **Goal:** {getattr(state, 'goal', 'N/A')}")
    lines.append(f"- **Phase:** {getattr(state, 'phase', 'N/A')}")
    lines.append(
        f"- **Result:** {'✅ PASS' if getattr(state, 'loop_passed', False) else '❌ FAIL'}"
    )
    lines.append(f"- **WTF iterations:** {getattr(state, 'iteration', 0)}")
    lines.append(f"- **Generated files:** {len(getattr(state, 'generated_files', []))}")
    lines.append("")
    lines.append("## Plan")
    lines.append("")
    lines.append("```")
    lines.append(getattr(state, "plan", "*No plan*"))
    lines.append("```")
    lines.append("")

    # Discovered files
    discovered = getattr(state, "discovered_files", [])
    if discovered:
        lines.append("## Discovered Files")
        lines.append("")
        lines.append("| File | Size | Format |")
        lines.append("|------|------|--------|")
        for df in discovered:
            fmt = (df.sample or {}).get("format", "") if hasattr(df, "sample") else ""
            sz = f"{df.size:,} B" if hasattr(df, "size") else ""
            lines.append(f"| {getattr(df, 'path', '')} | {sz} | {fmt} |")
        lines.append("")

    # Generated files
    generated = getattr(state, "generated_files", [])
    if generated:
        lines.append("## Generated Files")
        lines.append("")
        for gf in generated:
            status = "✅ PASS" if getattr(gf, "passed", False) else "❌ FAIL"
            lines.append(f"### `{getattr(gf, 'path', '')}` — {status}")
            lines.append("")
            lines.append("```python")
            lines.append(getattr(gf, "content", "*No content*"))
            lines.append("```")
            lines.append("")

    # Test logs
    logs = getattr(state, "test_logs", [])
    if logs:
        lines.append("## Test Logs")
        lines.append("")
        for tl in logs:
            status = "✅ PASS" if getattr(tl, "passed", True) else "❌ FAIL"
            lines.append(f"### `{getattr(tl, 'file', '')}` — {status}")
            lines.append("")
            if getattr(tl, "stdout", ""):
                lines.append("**stdout:**")
                lines.append("```")
                lines.append(tl.stdout[:500])
                lines.append("```")
            if getattr(tl, "stderr", ""):
                lines.append("**stderr:**")
                lines.append("```")
                lines.append(tl.stderr[:500])
                lines.append("```")
            lines.append("")

    return "\n".join(lines)


# ===========================================================================
# HTML export
# ===========================================================================

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>virgo — {title}</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{
      background:#0d0d12; color:#c0c0d0; font-family:system-ui,sans-serif;
      padding:2rem; max-width:960px; margin:0 auto;
    }}
    h1 {{ color:#00ffff; font-size:1.8rem; margin-bottom:0.25rem; }}
    h2 {{ color:#fff; font-size:1.3rem; margin:1.5rem 0 0.5rem; }}
    h3 {{ color:#ccc; font-size:1rem; margin:1rem 0 0.25rem; }}
    .meta {{ color:#888; font-size:0.85rem; margin-bottom:1.5rem; }}
    .badge {{
      display:inline-block; padding:0.2rem 0.6rem; border-radius:4px;
      font-size:0.8rem; font-weight:600;
    }}
    .badge-pass {{ background:#003322; color:#00ff88; }}
    .badge-fail {{ background:#330011; color:#ff4466; }}
    table {{ width:100%; border-collapse:collapse; font-size:0.85rem; margin:0.5rem 0; }}
    th,td {{ text-align:left; padding:0.4rem 0.6rem; border-bottom:1px solid #1e1e2a; }}
    th {{ color:#00ffff; font-weight:500; }}
    pre {{
      background:#0a0a0f; border:1px solid #1a1a2a; border-radius:6px;
      padding:1rem; font-family:"JetBrains Mono","Fira Code",monospace;
      font-size:0.8rem; line-height:1.5; overflow-x:auto; margin:0.5rem 0;
    }}
    .log {{ max-height:300px; overflow-y:auto; }}
    a {{ color:#00ccff; }}
    .plan {{ white-space:pre-wrap; }}
  </style>
</head>
<body>
  <h1>virgo</h1>
  <div class="meta">{title} — {date}</div>

  <table>
    <tr><th>Goal</th><td>{goal}</td></tr>
    <tr><th>Phase</th><td>{phase}</td></tr>
    <tr><th>Result</th><td>{result_badge}</td></tr>
    <tr><th>WTF Iterations</th><td>{iteration}</td></tr>
    <tr><th>Files Generated</th><td>{file_count}</td></tr>
  </table>

  <h2>Plan</h2>
  <pre class="plan">{plan}</pre>

  {discovered_section}

  {generated_section}

  {logs_section}
</body>
</html>
"""


def to_html(state: Any, title: str | None = None) -> str:
    """Render a WorkspaceState as an HTML document."""
    goal = getattr(state, "goal", "N/A")
    phase = getattr(state, "phase", "N/A")
    passed = getattr(state, "loop_passed", False)
    iteration = getattr(state, "iteration", 0)
    plan = getattr(state, "plan", "*No plan*")

    result_badge = (
        '<span class="badge badge-pass">PASS</span>'
        if passed
        else '<span class="badge badge-fail">FAIL</span>'
    )

    # Discovered files table
    discovered = getattr(state, "discovered_files", [])
    if discovered:
        rows = ""
        for df in discovered:
            fmt = (df.sample or {}).get("format", "") if hasattr(df, "sample") else ""
            sz = f"{df.size:,} B" if hasattr(df, "size") else ""
            rows += f"<tr><td>{getattr(df, 'path', '')}</td><td>{sz}</td><td>{fmt}</td></tr>\n"
        discovered_section = f"""\
<h2>Discovered Files</h2>
<table>
  <tr><th>File</th><th>Size</th><th>Format</th></tr>
  {rows}
</table>"""
    else:
        discovered_section = ""

    # Generated files
    generated = getattr(state, "generated_files", [])
    if generated:
        gf_sections = ""
        for gf in generated:
            status = "PASS" if getattr(gf, "passed", False) else "FAIL"
            badge = (
                f'<span class="badge badge-pass">{status}</span>'
                if getattr(gf, "passed", False)
                else f'<span class="badge badge-fail">{status}</span>'
            )
            code = getattr(gf, "content", "")
            gf_sections += f"""\
<h3>{getattr(gf, "path", "")}  {badge}</h3>
<pre>{_escape_html(code)}</pre>
"""
        generated_section = f"<h2>Generated Files</h2>\n{gf_sections}"
    else:
        generated_section = ""

    # Test logs
    logs = getattr(state, "test_logs", [])
    if logs:
        log_sections = ""
        for tl in logs:
            status = "PASS" if getattr(tl, "passed", True) else "FAIL"
            badge = (
                f'<span class="badge badge-pass">{status}</span>'
                if getattr(tl, "passed", True)
                else f'<span class="badge badge-fail">{status}</span>'
            )
            stdout = _escape_html(getattr(tl, "stdout", "")[:800])
            stderr = _escape_html(getattr(tl, "stderr", "")[:800])
            log_sections += f"""\
<h3>{getattr(tl, "file", "")}  {badge}</h3>
<div class="log">
{"<pre>STDOUT:<br>" + stdout + "</pre>" if stdout else ""}
{'<pre style="color:#ff6677;">STDERR:<br>' + stderr + "</pre>" if stderr else ""}
</div>
"""
        logs_section = f"<h2>Test Logs</h2>\n{log_sections}"
    else:
        logs_section = ""

    return _HTML_TEMPLATE.format(
        title=title or "Pipeline Report",
        date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        goal=_escape_html(goal),
        phase=phase,
        result_badge=result_badge,
        iteration=iteration,
        file_count=len(generated),
        plan=_escape_html(plan),
        discovered_section=discovered_section,
        generated_section=generated_section,
        logs_section=logs_section,
    )


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ===========================================================================
# File writers
# ===========================================================================


def export_markdown(state: Any, path: str, title: str | None = None) -> Path:
    """Export state as a Markdown file."""
    p = Path(path)
    p.write_text(to_markdown(state, title), encoding="utf-8")
    return p


def export_html(state: Any, path: str, title: str | None = None) -> Path:
    """Export state as an HTML file."""
    p = Path(path)
    p.write_text(to_html(state, title), encoding="utf-8")
    return p
