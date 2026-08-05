"""Virgo Desktop pages — plugins (split from the monolith)."""
from __future__ import annotations

from .base import *  # noqa: F401,F403 — shared Qt imports + helpers
from .base import HERE, OUTDIR, icon, _beep, _set_layout_visible
from .base import _StopStream, _GuiStream  # noqa: F401

class PluginsPage(PageWidget):
    """Browse, create, and manage virgo plugins."""

    def __init__(self) -> None:
        super().__init__(
            "Plugins",
            "Dynamic tool plugins loaded from plugins/ and ~/.virgo/plugins/.",
        )

        self._add_row(
            QPushButton(f"{icon('refresh')}  Refresh", clicked=self._refresh),
            QPushButton(f"{icon('run')}  Reload enabled", clicked=self._reload_all),
            QPushButton(f"{icon('file')}  New plugin", clicked=self._new_plugin),
        )

        self.list = QListWidget()
        self.list.setMinimumHeight(200)
        self._add(self.list)

        self._add_row(
            QPushButton(f"{icon('file')}  Open", clicked=self._open),
            QPushButton(f"{icon('refresh')}  Toggle enable", clicked=self._toggle),
            QPushButton(f"{icon('delete')}  Delete", clicked=self._delete),
        )

        self.status = QLabel("No plugins found.")
        self._add(self.status)

        self._enabled: set[str] = set()

    def on_activate(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self.list.clear()
        try:
            from plugins import discover

            files = discover()
        except Exception as exc:
            self.status.setText(f"Error: {exc}")
            return
        if not files:
            self.status.setText("No plugins in plugins/ or ~/.virgo/plugins/")
            return
        for f in files:
            item = QListWidgetItem(f"{f.parent.name}/{f.name}")
            item.setData(256, str(f))  # Qt.UserRole
            self.list.addItem(item)
            self._enabled.add(str(f))
        self.status.setText(f"{len(files)} plugin(s)")

    def _reload_all(self) -> None:
        try:
            from plugins import discover, load_path
            from tools import ToolRegistry

            reg = ToolRegistry()
            loaded = 0
            for f in discover():
                if str(f) in self._enabled:
                    load_path(f, reg)
                    loaded += 1
            self.status.setText(f"Reloaded {loaded} enabled plugin(s)")
        except Exception as exc:
            self.status.setText(f"Reload error: {exc}")

    def _selected(self) -> str | None:
        it = self.list.currentItem()
        return it.data(256) if it else None

    def _open(self) -> None:
        p = self._selected()
        if not p:
            self.status.setText("Select a plugin first.")
            return
        from virgo_desktop import _open_file

        _open_file(p)

    def _toggle(self) -> None:
        p = self._selected()
        if not p:
            self.status.setText("Select a plugin first.")
            return
        if p in self._enabled:
            self._enabled.discard(p)
            self.status.setText(f"Disabled {Path(p).name}")
        else:
            self._enabled.add(p)
            self.status.setText(f"Enabled {Path(p).name}")

    def _delete(self) -> None:
        p = self._selected()
        if not p:
            self.status.setText("Select a plugin first.")
            return
        try:
            Path(p).unlink()
            self.status.setText(f"Deleted {Path(p).name}")
        except Exception as exc:
            self.status.setText(f"Delete failed: {exc}")
        self._refresh()

    def _new_plugin(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("New plugin")
        dlg.resize(540, 440)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("File name (e.g. my_tool.py):"))
        name_edit = QLineEdit("my_tool.py")
        layout.addWidget(name_edit)
        layout.addWidget(QLabel("Code:"))
        code_edit = QPlainTextEdit()
        code_edit.setPlainText(
            "def register(registry):\n"
            "    from tools import Tool\n"
            "    def run(query: str) -> str:\n"
            '        return f"echo: {query}"\n'
            '    registry.register(Tool(name="my tool", fn=run,\n'
            '                             description="Example plugin tool"))\n'
        )
        layout.addWidget(code_edit, 1)
        btns = QHBoxLayout()
        ok = QPushButton("Create")
        cancel = QPushButton("Cancel")
        btns.addStretch()
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

        def do_create() -> None:
            name = name_edit.text().strip()
            if not name.endswith(".py"):
                name += ".py"
            try:
                from plugins import create_plugin

                create_plugin(name, code_edit.toPlainText())
                self.status.setText(f"Created {name}")
                dlg.accept()
                self._refresh()
            except Exception as exc:
                self.status.setText(f"Create failed: {exc}")

        ok.clicked.connect(do_create)
        cancel.clicked.connect(dlg.reject)
        dlg.exec()


class McpPage(PageWidget):
    """Configure Virgo as an MCP server and connect to external MCP servers."""

    def __init__(self) -> None:
        super().__init__(
            "MCP",
            "Expose Virgo tools to MCP hosts, or connect to external MCP servers.",
        )

        # ── Expose Virgo (server mode) ──
        srv = self._section("Expose Virgo (act as MCP server)")
        srv.layout().addWidget(
            QLabel(  # type: ignore
                "Register this in your MCP host (Claude Desktop, Cursor, etc.):"
            )
        )
        self.config_view = QPlainTextEdit()
        self.config_view.setReadOnly(True)
        self.config_view.setMaximumHeight(150)
        try:
            cfg = {
                "mcpServers": {
                    "virgo": {
                        "command": sys.executable,
                        "args": [str(HERE / "mcp_server.py")],
                    }
                }
            }
            self.config_view.setPlainText(json.dumps(cfg, indent=2))
            from mcp_server import PROTOCOL_VERSION, SERVER_INFO, _build_registry

            reg = _build_registry()
            info = (
                f"Protocol {PROTOCOL_VERSION} · {SERVER_INFO['name']} "
                f"v{SERVER_INFO['version']} · {len(reg.list())} tool(s) exposed"
            )
        except Exception as exc:
            info = f"Could not build registry: {exc}"
        srv.layout().addWidget(self.config_view)  # type: ignore
        copy_row = QHBoxLayout()
        copy_row.addWidget(QPushButton(f"{icon('file')}  Copy config", clicked=self._copy_config))
        copy_row.addStretch()
        srv.layout().addLayout(copy_row)  # type: ignore
        srv.layout().addWidget(QLabel(info))  # type: ignore

        # ── Connect to MCP servers (client mode) ──
        cli = self._section("Connect to MCP servers")
        cli.layout().addWidget(
            QLabel(  # type: ignore
                "Discovered from .mcp.json / claude_desktop_config.json / ~/.gemini"
            )
        )
        self.server_list = QListWidget()
        self.server_list.setMinimumHeight(120)
        self.server_list.currentItemChanged.connect(self._on_select_server)
        cli.layout().addWidget(self.server_list)  # type: ignore
        self.server_status = QLabel("No servers discovered yet.")
        cli.layout().addWidget(self.server_status)  # type: ignore
        self.tools_view = QPlainTextEdit()
        self.tools_view.setReadOnly(True)
        self.tools_view.setMaximumHeight(130)
        cli.layout().addWidget(self.tools_view)  # type: ignore

        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(
            QPushButton(f"{icon('refresh')}  Refresh", clicked=self._refresh_servers)
        )
        ctrl_row.addWidget(QPushButton(f"{icon('file')}  Add server", clicked=self._add_server))
        ctrl_row.addWidget(QPushButton(f"{icon('run')}  Test selected", clicked=self._test_server))
        ctrl_row.addStretch()
        cli.layout().addLayout(ctrl_row)  # type: ignore

        self._servers: dict[str, list[str]] = {}

    def on_activate(self) -> None:
        self._refresh_servers()

    def _copy_config(self) -> None:
        QApplication.clipboard().setText(self.config_view.toPlainText())
        self.server_status.setText("Config copied to clipboard.")

    def _refresh_servers(self) -> None:
        self.server_list.clear()
        self._servers = {}
        try:
            from mcp_bridge import discover_mcp_servers

            specs = discover_mcp_servers()
        except Exception as exc:
            self.server_status.setText(f"Error: {exc}")
            return
        if not specs:
            self.server_status.setText("No MCP servers discovered.")
            return
        for name, cmd in specs.items():
            item = QListWidgetItem(f"{name}  —  {' '.join(cmd)}")
            item.setData(256, name)  # Qt.UserRole
            self.server_list.addItem(item)
            self._servers[name] = cmd
        self.server_status.setText(f"{len(specs)} server(s) discovered.")

    def _add_server(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Add MCP server")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Name:"))
        name_edit = QLineEdit("myserver")
        layout.addWidget(name_edit)
        layout.addWidget(QLabel("Command (e.g. python server.py --port 8080):"))
        cmd_edit = QLineEdit()
        layout.addWidget(cmd_edit)
        btns = QHBoxLayout()
        ok = QPushButton("Add")
        cancel = QPushButton("Cancel")
        btns.addStretch()
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)

        def do_add() -> None:
            name = name_edit.text().strip()
            cmd = cmd_edit.text().strip().split()
            if not name or not cmd:
                return
            cfg_path = HERE / ".mcp.json"
            data: dict[str, Any] = {"mcpServers": {}}
            if cfg_path.exists():
                try:
                    data = json.loads(cfg_path.read_text())
                    data.setdefault("mcpServers", {})
                except Exception:
                    pass
            data["mcpServers"][name] = {"command": cmd[0], "args": cmd[1:]}
            cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            dlg.accept()
            self._refresh_servers()

        ok.clicked.connect(do_add)
        cancel.clicked.connect(dlg.reject)
        dlg.exec()

    def _selected_server(self) -> str | None:
        it = self.server_list.currentItem()
        return it.data(256) if it else None

    def _on_select_server(self, current, _prev) -> None:
        name = self._selected_server()
        if name and name in self._servers:
            self.server_status.setText(f"{name}: {' '.join(self._servers[name])}")

    def _test_server(self) -> None:
        name = self._selected_server()
        if not name or name not in self._servers:
            self.server_status.setText("Select a discovered server first.")
            return
        cmd = self._servers[name]
        self.tools_view.clear()
        self.server_status.setText(f"Testing {name}...")
        try:
            from mcp_bridge import McpServer

            srv = McpServer(name, cmd)
            if srv.start(timeout=15):
                tools = srv.list_tool_specs()
                self.tools_view.setPlainText(
                    "\n".join(f"- {t.get('name')}: {t.get('description', '')}" for t in tools)
                )
                self.server_status.setText(f"{name}: {len(tools)} tool(s) reachable")
                srv.stop()
            else:
                self.server_status.setText(f"{name}: could not start / unreachable")
        except Exception as exc:
            self.server_status.setText(f"Test failed: {exc}")


