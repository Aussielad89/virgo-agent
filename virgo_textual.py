"""
virgo_textual — Textual-based TUI dashboard for the virgo agent framework.

A modern, interactive dashboard with keyboard navigation, real-time
output display, and category-organized tools.

Usage:
    python -m virgo_textual
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.screen import Screen, ModalScreen
from textual.widgets import (
    Button, Footer, Header, Input, Label, ListItem,
    ListView, RichLog, Static, Tree,
)
from textual.widgets.tree import TreeNode

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
CONFIG_PATH = HERE / "dashboard.json"

from _console import icon


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"categories": [], "title": "VIRGO AGENT FRAMEWORK", "exit_key": "X"}


CONFIG = _load_config()


def _build_entries() -> list[dict]:
    entries = []
    for cat in CONFIG.get("categories", []):
        for entry in cat.get("entries", []):
            entries.append(entry)
    return entries


ENTRIES = _build_entries()


# ── Output screen: shows live subprocess output ─────────────────────────

class OutputScreen(ModalScreen):
    """Full-screen modal that runs a script and shows live output."""

    def __init__(self, entry: dict) -> None:
        super().__init__()
        self.entry = entry
        self.process: asyncio.subprocess.Process | None = None

    def compose(self) -> ComposeResult:
        label = self.entry.get("label", "Running...")
        yield Static(f"[bold]{icon('rocket')} {label}[/bold]", id="output-title")
        yield RichLog(id="output-log", highlight=True, markup=True, wrap=True)
        yield Static("", id="output-status")

    async def on_mount(self) -> None:
        self.title = f"Executing: {self.entry.get('label', '')}"
        log_widget = self.query_one("#output-log", RichLog)
        status = self.query_one("#output-status", Static)
        await log_widget.write(f"[bold]{icon('rocket')} Starting...[/bold]\n")

        action = self.entry.get("action", "script")
        script = self.entry.get("script", "")

        try:
            if action == "script":
                args = self.entry.get("args", "")
                cmd = [sys.executable, str(HERE / script)] + args.split()
                if args:
                    cmd += args.split()
                await log_widget.write(f"[dim]{' '.join(cmd)}[/dim]\n\n")

                self.process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                async def read_stream(stream, tag: str):
                    while True:
                        line = await stream.readline()
                        if not line:
                            break
                        text = line.decode("utf-8", errors="replace").rstrip()
                        if text:
                            await log_widget.write(f"{text}\n")

                await asyncio.gather(
                    read_stream(self.process.stdout, "out"),
                    read_stream(self.process.stderr, "err"),
                )

                await self.process.wait()
                rc = self.process.returncode or 0
                if rc == 0:
                    await status.update(f"[bold green]{icon('pass')} Completed (exit {rc})[/bold green]")
                else:
                    await status.update(f"[bold red]{icon('fail')} Failed (exit {rc})[/bold red]")

            elif action == "pipeline":
                await log_widget.write("[yellow]Pipeline requires interactive input — use the console dashboard for this.[/yellow]\n")
                await status.update("[bold yellow]Not available in TUI mode[/bold yellow]")

            elif action == "view":
                file_name = self.entry.get("file", "")
                candidate = str(HERE / file_name) if not os.path.isabs(file_name) else file_name
                if os.path.exists(candidate):
                    content = Path(candidate).read_text(encoding="utf-8")
                    await log_widget.write(f"[bold]{icon('file')} {candidate}[/bold]\n\n{content}\n")
                    await status.update(f"[bold green]{icon('pass')} Loaded {file_name}[/bold green]")
                else:
                    await log_widget.write(f"[yellow]{icon('warn')} {candidate} not found. Run the tool first.[/yellow]\n")
                    await status.update("[bold yellow]File not found[/bold yellow]")

            elif action == "search_history":
                outdir = HERE / "output"
                search_files = sorted(outdir.glob("virgo_search_memory_*.json"), reverse=True)
                if not search_files:
                    search_files = list(outdir.glob("virgo_search_memory.json"))
                if search_files:
                    for sf in search_files[:10]:
                        try:
                            data = json.loads(sf.read_text(encoding="utf-8"))
                            engine = data.get("engine", "web")
                            results = data.get("results", [])
                            first = results[0]["title"][:60] if results else "(empty)"
                            await log_widget.write(f"  {sf.name}  [{engine}]  {first}\n")
                        except Exception:
                            await log_widget.write(f"  {sf.name}  (corrupt)\n")
                    await status.update(f"[bold]Found {min(len(search_files), 10)} search history files[/bold]")
                else:
                    await log_widget.write("[yellow]No search history found.[/yellow]\n")
                    await status.update("[bold yellow]No history[/bold yellow]")

            elif action == "scaffold_list":
                cmd = [sys.executable, str(HERE / "virgo_scaffold.py"), "list"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                await log_widget.write(result.stdout or result.stderr or "(no output)")
                await status.update(f"[bold green]{icon('pass')} Done[/bold green]")

            elif action == "scaffold_gen":
                await log_widget.write("[yellow]Scaffold generation requires interactive input — use the console dashboard.[/yellow]\n")
                await status.update("[bold yellow]Use console dashboard[/bold yellow]")

            else:
                await log_widget.write(f"[red]Unknown action: {action}[/red]\n")

        except Exception as e:
            await log_widget.write(f"[bold red]{icon('error')} Error: {e}[/bold red]\n")
            await status.update(f"[bold red]Error[/bold red]")

    def key_q(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.terminate()
        self.dismiss()


# ── Main dashboard screen ──────────────────────────────────────────────

class DashboardScreen(Screen):
    """Main dashboard with category-organized tool list."""

    def compose(self) -> ComposeResult:
        categories = CONFIG.get("categories", [])
        title = CONFIG.get("title", "VIRGO AGENT FRAMEWORK")

        yield Header(show_clock=True)
        yield Container(
            Static(f"[bold]{icon('virgo')} {title}[/bold]", id="dash-title"),
            Horizontal(
                Vertical(
                    *self._build_category_trees(categories),
                    id="category-panel",
                ),
                ScrollableContainer(
                    Static("[dim]Select a tool to see details[/dim]", id="detail-panel"),
                    id="detail-container",
                ),
                id="main-layout",
            ),
            Footer(),
            id="app-container",
        )

    def _build_category_trees(self, categories: list[dict]) -> list[Tree]:
        trees = []
        for cat in categories:
            heading = cat.get("heading", "Tools")
            tree = Tree(f"[bold]{heading}[/bold]", id=f"tree-{heading.lower().replace(' ', '-')}")
            tree.root.expand()
            for entry in cat.get("entries", []):
                label = entry.get("label", "???")
                key = entry.get("key", "??")
                tree.root.add_leaf(f"[{key}] {label}", data=entry)
            trees.append(tree)
        return trees

    @on(Tree.NodeSelected)
    def handle_tree_select(self, event: Tree.NodeSelected) -> None:
        entry = event.node.data
        if entry:
            self._show_detail(entry)

    def _show_detail(self, entry: dict) -> None:
        panel = self.query_one("#detail-panel", Static)
        action = entry.get("action", "script")
        lines = [
            f"[bold]{icon('tool')} {entry.get('label', 'Unknown')}[/bold]",
            f"  Key: {entry.get('key', '??')}",
            f"  Action: {action}",
        ]
        if action == "script":
            lines.append(f"  Script: {entry.get('script', '')} {entry.get('args', '')}")
        elif action == "view":
            lines.append(f"  File: {entry.get('file', '')}")
        elif action == "scaffold_gen":
            lines.append(f"  Scaffold: {entry.get('scaffold', '')}")
        lines.append("")
        lines.append("[dim]Press Enter to run, Esc to go back[/dim]")
        panel.update("\n".join(lines))

    def key_enter(self) -> None:
        """Run the currently selected tool."""
        for tree in self.query(Tree):
            if tree.has_focus:
                node = tree.cursor_node
                if node and node.data:
                    self.push_screen(OutputScreen(node.data))

    def key_q(self) -> None:
        self.app.exit()

    def key_escape(self) -> None:
        self.app.exit()


# ── App ────────────────────────────────────────────────────────────────

class VirgoTextualApp(App):
    """Textual TUI dashboard for Virgo Agent Framework."""

    TITLE = "Virgo Dashboard"
    CSS = """
    Screen {
        background: $surface;
    }

    #app-container {
        height: 100%;
        padding: 0 1;
    }

    #dash-title {
        text-align: center;
        padding: 1 0;
        text-style: bold;
        width: 100%;
    }

    #main-layout {
        height: 1fr;
    }

    #category-panel {
        width: 46%;
        min-width: 40;
        border: solid $primary;
        padding: 0 1;
        overflow: auto;
    }

    Tree {
        height: auto;
        margin-bottom: 1;
    }

    Tree > .tree--label {
        text-style: bold;
    }

    #detail-container {
        width: 54%;
        min-width: 40;
        border: solid $secondary;
        padding: 1;
    }

    #detail-panel {
        height: 100%;
    }

    #detail-panel Static {
        padding: 1;
    }

    OutputScreen {
        align: center middle;
    }

    OutputScreen #output-title {
        padding: 1 2;
        text-style: bold;
        width: 100%;
        background: $primary;
        color: $text;
    }

    OutputScreen #output-log {
        width: 100%;
        height: 1fr;
        border: solid $primary;
        padding: 1;
    }

    OutputScreen #output-status {
        padding: 1 2;
        width: 100%;
        text-align: center;
        background: $surface;
    }

    Footer {
        background: $panel;
    }

    Vertical {
        height: auto;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("escape", "quit", "Quit", show=False),
        Binding("enter", "run_selected", "Run", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        categories = CONFIG.get("categories", [])
        title = CONFIG.get("title", "VIRGO AGENT FRAMEWORK")

        trees = []
        for cat in categories:
            heading = cat.get("heading", "Tools")
            tree = Tree(f"[bold]{heading}[/bold]", id=f"tree-{heading.lower().replace(' ', '-')}")
            tree.root.expand()
            for entry in cat.get("entries", []):
                label = entry.get("label", "???")
                key = entry.get("key", "??")
                tree.root.add_leaf(f"[{key}] {label}", data=entry)
            trees.append(tree)

        yield Container(
            Static(f"[bold]{icon('virgo')} {title}[/bold]", id="dash-title"),
            Horizontal(
                Vertical(*trees, id="category-panel"),
                ScrollableContainer(
                    Static("[dim]Select a tool to see details[/dim]", id="detail-panel"),
                    id="detail-container",
                ),
                id="main-layout",
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        """Focus the first tree."""
        first_tree = self.query(Tree).first()
        if first_tree:
            first_tree.focus()

    @on(Tree.NodeSelected)
    def handle_tree_select(self, event: Tree.NodeSelected) -> None:
        entry = event.node.data
        if entry:
            self._show_detail(entry)

    def _show_detail(self, entry: dict) -> None:
        panel = self.query_one("#detail-panel", Static)
        action = entry.get("action", "script")
        lines = [
            f"[bold]{icon('tool')} {entry.get('label', 'Unknown')}[/bold]",
            f"  Key: {entry.get('key', '??')}",
            f"  Action: {action}",
        ]
        if action == "script":
            lines.append(f"  Script: {entry.get('script', '')} {entry.get('args', '')}")
        elif action == "view":
            lines.append(f"  File: {entry.get('file', '')}")
        elif action == "scaffold_gen":
            lines.append(f"  Scaffold: {entry.get('scaffold', '')}")
        lines.append("")
        lines.append("[dim]Press Enter to run, q or Esc to quit[/dim]")
        panel.update("\n".join(lines))

    def action_run_selected(self) -> None:
        """Run the currently selected tool."""
        for tree in self.query(Tree):
            if tree.has_focus or True:
                node = tree.cursor_node
                if node and node.data:
                    self.push_screen(OutputScreen(node.data))
                    break


def main():
    app = VirgoTextualApp()
    app.run()


if __name__ == "__main__":
    main()
