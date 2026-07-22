"""
templates — code template engine for virgo.

Provides a simple substitution-based template system (no Jinja2
dependency) and a library of built-in templates for common
patterns.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent

# ===========================================================================
# Simple template engine
# ===========================================================================

_VAR_RE = re.compile(r"\{\{\s*(\w+)(?:\s*[:|]\s*(\w+))?\s*\}\}")


def _apply_filter(value: Any, filt: str) -> str:
    s = str(value)
    if filt == "upper":
        return s.upper()
    if filt == "lower":
        return s.lower()
    if filt == "capitalize":
        return s.capitalize()
    if filt == "title":
        return s.title()
    if filt == "strip":
        return s.strip()
    if filt == "int":
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return s
    if filt == "bool":
        return str(bool(value))
    if filt == "json":
        import json as _json

        try:
            return _json.dumps(value)
        except (TypeError, ValueError):
            return s
    return s


def render(template: str, **vars: Any) -> str:
    """Render a template by substituting ``{{var}}`` placeholders.

    Built-in filters (applied with ``:`` or ``|``):
      ``{{var:upper}}`` / ``{{var|upper}}``, ``lower``, ``capitalize``,
      ``title``, ``strip``, ``int``, ``bool``, ``json``.
    Unknown variables are left untouched.
    """

    def _replace(m: re.Match) -> str:
        name = m.group(1)
        filt = m.group(2)
        if name not in vars:
            return m.group(0)
        value = vars[name]
        if filt:
            value = _apply_filter(value, filt)
        return str(value)

    return _VAR_RE.sub(_replace, template)


# ===========================================================================
# Built-in templates
# ===========================================================================

CLI_SCRIPT = r'''"""
{{description}}
"""

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="{{description}}")
    parser.add_argument("--input", "-i", type=str, help="Input file path")
    parser.add_argument("--output", "-o", type=str, help="Output file path")
    args = parser.parse_args()

    if args.input:
        path = Path(args.input)
        if path.exists():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            print(f"{{name}}: read {len(lines)} lines from {args.input}")
        else:
            print(f"{{name}}: input not found: {args.input}", file=sys.stderr)
            return 1
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

DATA_PIPELINE = r'''"""
{{description}}
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any


def load_data(path: str) -> list[dict[str, Any]]:
    """Load data from a CSV or JSON file."""
    p = Path(path)
    if p.suffix == ".csv":
        with open(p, "r", encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    elif p.suffix == ".json":
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    else:
        raise ValueError(f"Unsupported format: {p.suffix}")


def transform(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize every record: trim strings and drop empty/None values."""
    def _clean(value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value

    out: list[dict[str, Any]] = []
    for row in data:
        new_row: dict[str, Any] = {}
        for k, v in row.items():
            cleaned = _clean(v)
            if cleaned in ("", None):
                continue
            new_row[k] = cleaned
        out.append(new_row)
    return out


def save_output(data: list[dict[str, Any]], path: str) -> None:
    """Save results to a JSON file."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description="{{description}}")
    parser.add_argument("--input", "-i", required=True, help="Input CSV/JSON path")
    parser.add_argument("--output", "-o", required=True, help="Output JSON path")
    args = parser.parse_args()

    data = load_data(args.input)
    result = transform(data)
    save_output(result, args.output)
    print(f"Processed {len(result)} records -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

WEB_SERVER = r'''"""
{{description}} — virgo-generated web server
"""

import http.server
import json
import sys
from pathlib import Path


class Handler(http.server.BaseHTTPRequestHandler):
    """Simple HTTP request handler."""

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json({"status": "ok"})
        else:
            self._json({"error": "not found"}, 404)

    def _json(self, data: dict, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    print(f"{{name}} listening on http://0.0.0.0:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

TEST_SUITE = r'''"""
Tests for {{target}}.
"""

import json
import os
import sys
import unittest
from pathlib import Path


class Test{{name|capitalize}}(unittest.TestCase):
    """Test suite for {{target}}."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        pass

    def test_basic(self) -> None:
        """Basic functionality test."""
        # TODO: implement test
        self.assertTrue(True)

    def test_edge_cases(self) -> None:
        """Edge cases."""
        # TODO: implement edge case tests
        pass


if __name__ == "__main__":
    unittest.main()
'''


# ===========================================================================
# Template registry
# ===========================================================================

BUILTIN_TEMPLATES: dict[str, dict[str, str]] = {
    "cli": {
        "name": "CLI Script",
        "description": "Command-line interface with argparse",
        "code": CLI_SCRIPT,
    },
    "data_pipeline": {
        "name": "Data Pipeline",
        "description": "CSV/JSON data processing pipeline",
        "code": DATA_PIPELINE,
    },
    "web_server": {
        "name": "Web Server",
        "description": "Minimal HTTP server using http.server",
        "code": WEB_SERVER,
    },
    "test_suite": {
        "name": "Test Suite",
        "description": "unittest scaffold with basic test cases",
        "code": TEST_SUITE,
    },
}


def list_templates() -> list[dict[str, str]]:
    """Return metadata for all built-in templates."""
    return [
        {"key": k, "name": v["name"], "description": v["description"]}
        for k, v in BUILTIN_TEMPLATES.items()
    ]


def generate(
    template_key: str,
    file_path: str,
    **vars: Any,
) -> str:
    """Generate a file from a built-in template.

    Parameters
    ----------
    template_key:
        One of: cli, data_pipeline, web_server, test_suite
    file_path:
        Where to write the generated file.
    vars:
        Template variables: name, description, target, etc.

    Returns the rendered code string (also written to disk).
    """
    if template_key not in BUILTIN_TEMPLATES:
        raise KeyError(
            f"Unknown template {template_key!r}. Available: {', '.join(BUILTIN_TEMPLATES)}"
        )

    code = render(BUILTIN_TEMPLATES[template_key]["code"], **vars)
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(code, encoding="utf-8")
    return code
