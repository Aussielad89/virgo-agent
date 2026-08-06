"""Experimental feature pages — wrappers around standalone virgo_* modules."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .base import PageWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, QWidget
from .base import HERE, icon


class _ModuleRunnerPage(PageWidget):
    """Generic page that runs a virgo_* module CLI and shows output."""

    module_name: str = ""
    title: str = ""
    subtitle: str = ""

    def __init__(self) -> None:
        super().__init__(self.title, self.subtitle)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText(f"Output from {self.module_name} will appear here...")
        self.content.addWidget(self.output, 1)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton(f"{icon('rocket')}  Run")
        self.run_btn.clicked.connect(self._run)
        btn_row.addWidget(self.run_btn)
        btn_row.addStretch()
        self.content.addLayout(btn_row)
        self._btn_row = btn_row

    def _run(self) -> None:
        self.output.clear()
        self.output.append(f"<i>Running {self.module_name}...</i>")
        try:
            r = subprocess.run(
                [sys.executable, str(HERE / f"{self.module_name}.py")],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(HERE),
            )
            out = r.stdout.strip() or r.stderr.strip() or "(no output)"
            self.output.append(f"<pre>{out}</pre>")
        except subprocess.TimeoutExpired:
            self.output.append("<i>[Timed out]</i>")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")


class SonificationPage(_ModuleRunnerPage):
    module_name = "virgo_pipeline_sonification"
    title = "Pipeline Sonification"
    subtitle = "Hear pipeline phases as tones. Run --watch to auto-play on state changes."

    def __init__(self) -> None:
        super().__init__()
        self.run_btn.setText(f"{icon('play')}  Test Tone")
        self.watch_btn = QPushButton(f"{icon('refresh')}  Watch Pipeline")
        self.watch_btn.setCheckable(True)
        self.watch_btn.clicked.connect(self._toggle_watch)
        self._btn_row.addWidget(self.watch_btn)

    def _toggle_watch(self) -> None:
        if self.watch_btn.isChecked():
            self.output.append("<i>[Watcher started — will auto-play on pipeline state changes]</i>")
            try:
                from virgo_pipeline_sonification import start_watcher
                start_watcher()
            except Exception as exc:
                self.output.append(f"<i>[Error: {exc}]</i>")
        else:
            self.output.append("<i>[Watcher stopped]</i>")


class DreamsPage(_ModuleRunnerPage):
    module_name = "virgo_dreams"
    title = "Agent Dreams"
    subtitle = "Idle agent dream journal — replay memories, consolidate insights."

    def __init__(self) -> None:
        super().__init__()
        self.run_btn.setText(f"{icon('sparkle')}  Dream Now")
        self.brief_btn = QPushButton(f"{icon('calendar')}  Morning Briefing")
        self.brief_btn.clicked.connect(self._show_brief)
        self._btn_row.addWidget(self.brief_btn)

    def _run(self) -> None:
        try:
            from virgo_dreams import dream_now
            entry = dream_now()
            self.output.append(f"<pre>{json.dumps(entry, indent=2, default=str)}</pre>")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _show_brief(self) -> None:
        try:
            from virgo_dreams import get_morning_briefing
            brief = get_morning_briefing()
            self.output.append(f"<pre>{json.dumps(brief, indent=2, default=str)}</pre>")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")


class FlavorPage(_ModuleRunnerPage):
    module_name = "virgo_flavor"
    title = "Codebase Flavor"
    subtitle = "Profile the repo's style DNA — functional, OOP, async, etc."

    def __init__(self) -> None:
        super().__init__()
        self.run_btn.setText(f"{icon('search')}  Scan Repo")

    def _run(self) -> None:
        try:
            from virgo_flavor import scan_repo
            result = scan_repo()
            self.output.append(f"<pre>{json.dumps(result, indent=2, default=str)}</pre>")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")


class GhostPage(_ModuleRunnerPage):
    module_name = "virgo_ghost"
    title = "Ghost Mode"
    subtitle = "Run speculative edits in .virgo_ghost/ — manifest or discard later."

    def __init__(self) -> None:
        super().__init__()
        self.run_btn.setText(f"{icon('list')}  List Ghosts")
        self.manifest_btn = QPushButton(f"{icon('send')}  Manifest All")
        self.manifest_btn.clicked.connect(self._manifest_all)
        self.discard_btn = QPushButton(f"{icon('delete')}  Discard All")
        self.discard_btn.clicked.connect(self._discard_all)
        self._btn_row.addWidget(self.manifest_btn)
        self._btn_row.addWidget(self.discard_btn)

    def _run(self) -> None:
        try:
            from virgo_ghost import list_ghosts
            ghosts = list_ghosts()
            self.output.append(f"<pre>{json.dumps(ghosts, indent=2, default=str)}</pre>")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _manifest_all(self) -> None:
        try:
            from virgo_ghost import list_ghosts, manifest
            ghosts = list_ghosts()
            for g in ghosts:
                manifest(g["rel_path"])
            self.output.append(f"<i>[Manifested {len(ghosts)} ghost files]</i>")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _discard_all(self) -> None:
        try:
            from virgo_ghost import purge_ghosts
            count = purge_ghosts()
            self.output.append(f"<i>[Discarded {count} ghost files]</i>")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")


class ArchaeologyPage(_ModuleRunnerPage):
    module_name = "virgo_archaeology"
    title = "Codebase Archaeology"
    subtitle = "Explore git history — blame, timelines, and bisect introductions."

    def __init__(self) -> None:
        super().__init__()
        self.run_btn.setText(f"{icon('search')}  Load Timeline")


class EmpathyPage(_ModuleRunnerPage):
    module_name = "virgo_empathy"
    title = "Agent Empathy"
    subtitle = "Read repo mood from commits and calibrate agent tone."

    def __init__(self) -> None:
        super().__init__()
        self.run_btn.setText(f"{icon('heart')}  Analyze Mood")


class AuditPage(_ModuleRunnerPage):
    module_name = "virgo_audit"
    title = "Audit Chain"
    subtitle = "Immutable hash chain of pipeline runs for tamper-evident logging."

    def __init__(self) -> None:
        super().__init__()
        self.run_btn.setText(f"{icon('list')}  Verify Chain")
        self.verify_btn = QPushButton(f"{icon('check')}  Verify")
        self.verify_btn.clicked.connect(self._verify)
        self._btn_row.addWidget(self.verify_btn)

    def _run(self) -> None:
        try:
            from virgo_audit import tail
            entries = tail(10)
            self.output.append(f"<pre>{json.dumps(entries, indent=2, default=str)}</pre>")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _verify(self) -> None:
        try:
            from virgo_audit import verify_chain
            result = verify_chain()
            color = "#a6e3a1" if result.get("valid") else "#f38ba8"
            self.output.append(f"<pre style='color:{color};'>{json.dumps(result, indent=2)}</pre>")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")


class MemesPage(_ModuleRunnerPage):
    module_name = "virgo_memes"
    title = "Pipeline Memes"
    subtitle = "ASCII-art memes based on pipeline outcomes."

    def __init__(self) -> None:
        super().__init__()
        self.run_btn.setText(f"{icon('sparkle')}  Generate Meme")


class StigmergyPage(_ModuleRunnerPage):
    module_name = "virgo_stigmergy"
    title = "Stigmergic Heatmap"
    subtitle = "Pheromone trails across files — hot spots and danger zones."

    def __init__(self) -> None:
        super().__init__()
        self.run_btn.setText(f"{icon('fire')}  Heatmap")
        self.danger_btn = QPushButton(f"{icon('alert')}  Danger Zones")
        self.danger_btn.clicked.connect(self._show_danger)
        self._btn_row.addWidget(self.danger_btn)

    def _run(self) -> None:
        try:
            from virgo_stigmergy import heatmap
            result = heatmap()
            self.output.append(f"<pre>{json.dumps(result, indent=2, default=str)}</pre>")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _show_danger(self) -> None:
        try:
            from virgo_stigmergy import danger_zones
            zones = danger_zones()
            self.output.append(f"<pre>{json.dumps(zones, indent=2)}</pre>")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")


class DivergencePage(_ModuleRunnerPage):
    module_name = "virgo_divergence"
    title = "Pipeline Divergence"
    subtitle = "Git-like branching for agent runs — fork timelines and compare."

    def __init__(self) -> None:
        super().__init__()
        self.run_btn.setText(f"{icon('list')}  List Roots")
