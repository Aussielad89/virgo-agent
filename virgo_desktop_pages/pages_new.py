"""New feature pages for Virgo Desktop."""
from __future__ import annotations

from .base import *  # noqa: F401,F403
from .base import HERE, OUTDIR, icon, _beep, _set_layout_visible
from .base import _StopStream, _GuiStream  # noqa: F401


class PheromoneTrailPage(PageWidget):
    def __init__(self) -> None:
        super().__init__(
            "Pheromone Trails",
            "Living navigation overlay: recently touched files glow brighter, failed files dim.",
        )
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Pheromone trail data will appear here...")
        self.content.addWidget(self.output, 1)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton(f"{icon('fire')}  Refresh Heatmap")
        self.run_btn.clicked.connect(self._refresh)
        btn_row.addWidget(self.run_btn)
        self.clear_btn = QPushButton(f"{icon('delete')}  Clear Trails")
        self.clear_btn.clicked.connect(self._clear)
        btn_row.addWidget(self.clear_btn)
        self.content.addLayout(btn_row)

    def on_activate(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        try:
            from virgo_pheromone import heatmap, recent_trails
            hm = heatmap()
            recent = recent_trails()
            self.output.clear()
            self.output.append("<b>Hot Files</b>")
            for f in hm.get("hot_files", []):
                self.output.append(f"  {f['path']}: {f['score']}")
            self.output.append("")
            self.output.append("<b>Recent Trails</b>")
            for t in recent:
                self.output.append(f"  {t['path']} visits={t['visits']} score={t['score']}")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _clear(self) -> None:
        try:
            from virgo_pheromone import clear_trails
            clear_trails()
            self.output.append("Trails cleared.")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")


class SoundscapePage(PageWidget):
    def __init__(self) -> None:
        super().__init__(
            "Soundscape",
            "Ambient audio that reflects the agent's current state.",
        )
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Soundscape controls will appear here...")
        self.content.addWidget(self.output, 1)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton(f"{icon('play')}  Start")
        self.start_btn.clicked.connect(self._start)
        btn_row.addWidget(self.start_btn)
        self.stop_btn = QPushButton(f"{icon('stop')}  Stop")
        self.stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self.stop_btn)
        self.content.addLayout(btn_row)

        self.phase_combo = QComboBox()
        self.phase_combo.addItems([
            "idle", "discover", "plan", "generate", "test", "fix", "error", "done"
        ])
        self.phase_combo.setCurrentText("idle")
        self.content.addWidget(QLabel("Phase:"))
        self.content.addWidget(self.phase_combo)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        self.content.addWidget(QLabel("Volume:"))
        self.content.addWidget(self.volume_slider)

    def _start(self) -> None:
        try:
            from virgo_soundscape import start, set_phase, set_volume
            phase = self.phase_combo.currentText()
            volume = self.volume_slider.value() / 100.0
            set_phase(phase)
            set_volume(volume)
            result = start(phase, volume)
            self.output.append(f"Soundscape started: {result}")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _stop(self) -> None:
        try:
            from virgo_soundscape import stop
            result = stop()
            self.output.append(f"Soundscape stopped: {result}")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")


class EmpathyUIPage(PageWidget):
    def __init__(self) -> None:
        super().__init__(
            "Empathy UI",
            "Agent empathy-adaptive interface: calmer when frustrated, energetic when confident.",
        )
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Empathy UI data will appear here...")
        self.content.addWidget(self.output, 1)

        btn_row = QHBoxLayout()
        self.compute_btn = QPushButton(f"{icon('refresh')}  Compute Adaptation")
        self.compute_btn.clicked.connect(self._compute)
        btn_row.addWidget(self.compute_btn)
        self.reset_btn = QPushButton(f"{icon('delete')}  Reset History")
        self.reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(self.reset_btn)
        self.content.addLayout(btn_row)

    def _compute(self) -> None:
        try:
            from virgo_empathy_ui import compute_adaptation, get_empathy_state
            state = get_empathy_state()
            adapt = compute_adaptation()
            self.output.clear()
            self.output.append("<b>Empathy State</b>")
            self.output.append(f"  Mood: {state.mood}")
            self.output.append(f"  Tone: {state.tone}")
            self.output.append(f"  Frustration: {state.frustration}")
            self.output.append(f"  Confidence: {state.confidence}")
            self.output.append(f"  Curiosity: {state.curiosity}")
            self.output.append(f"  Risk Appetite: {state.risk_appetite}")
            self.output.append("")
            self.output.append("<b>UI Adaptation</b>")
            self.output.append(f"  Accent Saturation: {adapt.accent_saturation}")
            self.output.append(f"  Animation Speed: {adapt.animation_speed}")
            self.output.append(f"  Toast Duration: {adapt.toast_duration_ms}ms")
            self.output.append(f"  Sidebar Expanded: {adapt.sidebar_expanded}")
            self.output.append(f"  Notification Freq: {adapt.notification_frequency}")
            self.output.append(f"  Glow Intensity: {adapt.glow_intensity}")
            self.output.append(f"  Border Radius: {adapt.border_radius}")
            self.output.append(f"  Font Scale: {adapt.font_size_scale}")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _reset(self) -> None:
        try:
            from virgo_empathy_ui import reset_adaptation
            reset_adaptation()
            self.output.append("Adaptation history reset.")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")


class GhostReplayPage(PageWidget):
    def __init__(self) -> None:
        super().__init__(
            "Ghost Replay",
            "Visual replay of previous pipeline runs as animated flow graphs.",
        )
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Replay data will appear here...")
        self.content.addWidget(self.output, 1)

        btn_row = QHBoxLayout()
        self.list_btn = QPushButton(f"{icon('list')}  List Sessions")
        self.list_btn.clicked.connect(self._list_sessions)
        btn_row.addWidget(self.list_btn)
        self.load_btn = QPushButton(f"{icon('play')}  Load Replay")
        self.load_btn.clicked.connect(self._load_replay)
        btn_row.addWidget(self.load_btn)
        self.export_btn = QPushButton(f"{icon('export')}  Export")
        self.export_btn.clicked.connect(self._export)
        btn_row.addWidget(self.export_btn)
        self.content.addLayout(btn_row)

        self.session_id_input = QLineEdit()
        self.session_id_input.setPlaceholderText("Session ID to replay")
        self.content.addWidget(self.session_id_input)

    def _list_sessions(self) -> None:
        try:
            from virgo_ghost_replay import list_sessions
            sessions = list_sessions()
            self.output.clear()
            for s in sessions:
                self.output.append(f"{s['session_id']}: {s['goal']} [{s['status']}]")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _load_replay(self) -> None:
        sid = self.session_id_input.text().strip()
        if not sid:
            self.output.append("Enter a session ID first.")
            return
        try:
            from virgo_ghost_replay import load_replay
            session = load_replay(sid)
            if session is None:
                self.output.append(f"No replay data for session '{sid}'")
                return
            self.output.clear()
            self.output.append(f"Session: {session.session_id}")
            self.output.append(f"Goal: {session.goal}")
            self.output.append(f"Nodes: {len(session.nodes)}")
            self.output.append(f"Edges: {len(session.edges)}")
            self.output.append(f"Checkpoints: {len(session.checkpoints)}")
            self.output.append(f"Status: {session.status}")
            self.output.append("")
            for node in session.nodes[:20]:
                self.output.append(f"  [{node.type}] {node.label} ({node.status})")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _export(self) -> None:
        sid = self.session_id_input.text().strip()
        if not sid:
            self.output.append("Enter a session ID first.")
            return
        try:
            from virgo_ghost_replay import export_replay
            result = export_replay(sid)
            self.output.append(result)
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")


class DNAFingerprintPage(PageWidget):
    def __init__(self) -> None:
        super().__init__(
            "DNA Fingerprint",
            "Visual codebase style fingerprint - radial chart and barcode.",
        )
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Fingerprint data will appear here...")
        self.content.addWidget(self.output, 1)

        btn_row = QHBoxLayout()
        self.fingerprint_btn = QPushButton(f"{icon('search')}  Compute Fingerprint")
        self.fingerprint_btn.clicked.connect(self._fingerprint)
        btn_row.addWidget(self.fingerprint_btn)
        self.barcode_btn = QPushButton(f"{icon('barcode')}  Show Barcode")
        self.barcode_btn.clicked.connect(self._barcode)
        btn_row.addWidget(self.barcode_btn)
        self.history_btn = QPushButton(f"{icon('clock')}  History")
        self.history_btn.clicked.connect(self._history)
        btn_row.addWidget(self.history_btn)
        self.content.addLayout(btn_row)

    def _fingerprint(self) -> None:
        try:
            from virgo_dna_fingerprint import track_fingerprint
            result = track_fingerprint()
            self.output.clear()
            self.output.append("<b>Fingerprint</b>")
            self.output.append(f"  Project: {result['fingerprint']['project_name']}")
            self.output.append(f"  Dominant: {result['fingerprint']['dominant']}")
            self.output.append(f"  Files Scanned: {result['fingerprint']['files_scanned']}")
            self.output.append(f"  Radial Points: {len(result['radial_points'])}")
            self.output.append("")
            self.output.append("<b>Barcode</b>")
            self.output.append(result['barcode'])
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _barcode(self) -> None:
        try:
            from virgo_dna_fingerprint import compute_fingerprint, fingerprint_to_barcode
            fp = compute_fingerprint()
            self.output.clear()
            self.output.append(fingerprint_to_barcode(fp))
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _history(self) -> None:
        try:
            from virgo_dna_fingerprint import load_history
            history = load_history()
            self.output.clear()
            for entry in history[-10:]:
                ts = entry.get('timestamp', '')[:19]
                pn = entry.get('project_name', '')
                dom = entry.get('dominant', '')
                self.output.append(f"[{ts}] {pn} - {dom}")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")


class DreamVizPage(PageWidget):
    def __init__(self) -> None:
        super().__init__(
            "Dream Visualizer",
            "Agent dream journal as evolving constellation and mind map.",
        )
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Dream constellation will appear here...")
        self.content.addWidget(self.output, 1)

        btn_row = QHBoxLayout()
        self.constellation_btn = QPushButton(f"{icon('star')}  Constellation")
        self.constellation_btn.clicked.connect(self._constellation)
        btn_row.addWidget(self.constellation_btn)
        self.ascii_btn = QPushButton(f"{icon('terminal')}  ASCII Art")
        self.ascii_btn.clicked.connect(self._ascii)
        btn_row.addWidget(self.ascii_btn)
        self.timeline_btn = QPushButton(f"{icon('clock')}  Timeline")
        self.timeline_btn.clicked.connect(self._timeline)
        btn_row.addWidget(self.timeline_btn)
        self.stats_btn = QPushButton(f"{icon('chart')}  Stats")
        self.stats_btn.clicked.connect(self._stats)
        btn_row.addWidget(self.stats_btn)
        self.content.addLayout(btn_row)

    def _constellation(self) -> None:
        try:
            from virgo_dream_viz import build_constellation
            result = build_constellation()
            self.output.clear()
            self.output.append(f"Nodes: {len(result['nodes'])}")
            self.output.append(f"Edges: {len(result['edges'])}")
            self.output.append(f"Dreams: {result['dream_count']}")
            self.output.append(f"Insights: {result['insight_count']}")
            self.output.append("")
            for node in result['nodes'][:20]:
                self.output.append(f"  [{node['category']}] {node['text'][:60]}")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _ascii(self) -> None:
        try:
            from virgo_dream_viz import build_constellation, render_ascii
            result = build_constellation()
            self.output.clear()
            self.output.append(render_ascii(result))
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _timeline(self) -> None:
        try:
            from virgo_dream_viz import get_dream_timeline
            timeline = get_dream_timeline()
            self.output.clear()
            for d in timeline[:10]:
                ts = d.get('timestamp', '')[:19]
                self.output.append(f"[{ts}] {len(d.get('dreams', []))} dreams")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _stats(self) -> None:
        try:
            from virgo_dream_viz import get_category_stats
            stats = get_category_stats()
            self.output.clear()
            for cat, count in sorted(stats.items(), key=lambda x: -x[1]):
                self.output.append(f"  {cat}: {count}")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")


class SwarmDashboardPage(PageWidget):
    def __init__(self) -> None:
        super().__init__(
            "Swarm Dashboard",
            "Real-time monitoring of multiple agent instances working in parallel.",
        )
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Swarm status will appear here...")
        self.content.addWidget(self.output, 1)

        btn_row = QHBoxLayout()
        self.status_btn = QPushButton(f"{icon('refresh')}  Refresh Status")
        self.status_btn.clicked.connect(self._refresh)
        btn_row.addWidget(self.status_btn)
        self.register_btn = QPushButton(f"{icon('add')}  Register Agent")
        self.register_btn.clicked.connect(self._register)
        btn_row.addWidget(self.register_btn)
        self.reset_btn = QPushButton(f"{icon('delete')}  Reset")
        self.reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(self.reset_btn)
        self.content.addLayout(btn_row)

        self.agent_id_input = QLineEdit()
        self.agent_id_input.setPlaceholderText("Agent ID to register")
        self.content.addWidget(self.agent_id_input)

    def _refresh(self) -> None:
        try:
            from virgo_swarm_dashboard import get_swarm_state
            swarm = get_swarm_state()
            self.output.clear()
            self.output.append(f"<b>Swarm Health</b>: {swarm.swarm_health:.2f}")
            self.output.append(f"<b>Active Agents</b>: {len(swarm.agents)}")
            self.output.append(f"<b>Total Messages</b>: {swarm.total_messages}")
            self.output.append(f"<b>Total Conflicts</b>: {swarm.total_conflicts}")
            self.output.append(f"<b>Bottlenecks</b>: {swarm.bottleneck_agents}")
            self.output.append("")
            for agent in swarm.agents:
                self.output.append(
                    f"  [{agent.agent_id}] {agent.name} - "
                    f"status={agent.status} task='{agent.current_task}' "
                    f"cpu={agent.cpu_pct}% mem={agent.memory_mb}MB "
                    f"sent={agent.messages_sent} recv={agent.messages_received} "
                    f"conflicts={agent.conflicts}"
                )
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _register(self) -> None:
        agent_id = self.agent_id_input.text().strip()
        if not agent_id:
            self.output.append("Enter an agent ID first.")
            return
        try:
            from virgo_swarm_dashboard import register_agent
            lane = register_agent(agent_id)
            self.output.append(f"Registered agent: {lane.name}")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _reset(self) -> None:
        try:
            from virgo_swarm_dashboard import reset_swarm
            reset_swarm()
            self.output.append("Swarm state reset.")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")


class PluginShellPage(PageWidget):
    def __init__(self) -> None:
        super().__init__(
            "Plugin Shell",
            "Modular plugin system: browse, enable/disable, and manage desktop plugins.",
        )
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Plugin registry will appear here...")
        self.content.addWidget(self.output, 1)

        btn_row = QHBoxLayout()
        self.discover_btn = QPushButton(f"{icon('search')}  Discover")
        self.discover_btn.clicked.connect(self._discover)
        btn_row.addWidget(self.discover_btn)
        self.enabled_btn = QPushButton(f"{icon('check')}  Enabled Only")
        self.enabled_btn.clicked.connect(self._show_enabled)
        btn_row.addWidget(self.enabled_btn)
        self.content.addLayout(btn_row)

        self.plugin_list = QListWidget()
        self.plugin_list.setMinimumHeight(200)
        self.content.addWidget(self.plugin_list)

        action_row = QHBoxLayout()
        self.enable_btn = QPushButton(f"{icon('check')}  Enable")
        self.enable_btn.clicked.connect(self._enable_plugin)
        action_row.addWidget(self.enable_btn)
        self.disable_btn = QPushButton(f"{icon('x')}  Disable")
        self.disable_btn.clicked.connect(self._disable_plugin)
        action_row.addWidget(self.disable_btn)
        self.content.addLayout(action_row)

    def _discover(self) -> None:
        try:
            from virgo_plugin_shell import discover_plugins
            plugins = discover_plugins()
            self.plugin_list.clear()
            for p in plugins:
                self.plugin_list.addItem(f"{p.icon} {p.display_name} [{p.name}] (group: {p.group}, priority: {p.priority})")
            self.output.append(f"Discovered {len(plugins)} plugin(s)")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _show_enabled(self) -> None:
        try:
            from virgo_plugin_shell import get_enabled_plugins
            plugins = get_enabled_plugins()
            self.plugin_list.clear()
            for p in plugins:
                self.plugin_list.addItem(f"{p.icon} {p.display_name} [{p.name}]")
            self.output.append(f"{len(plugins)} enabled plugin(s)")
        except Exception as exc:
            self.output.append(f"<i>[Error: {exc}]</i>")

    def _enable_plugin(self) -> None:
        item = self.plugin_list.currentItem()
        if item is None:
            return
        text = item.text()
        import re
        m = re.search(r"\[([^\]]+)\]", text)
        if m:
            from virgo_plugin_shell import enable_plugin
            ok = enable_plugin(m.group(1))
            self.output.append(f"Enabled: {ok}")

    def _disable_plugin(self) -> None:
        item = self.plugin_list.currentItem()
        if item is None:
            return
        text = item.text()
        import re
        m = re.search(r"\[([^\]]+)\]", text)
        if m:
            from virgo_plugin_shell import disable_plugin
            ok = disable_plugin(m.group(1))
            self.output.append(f"Disabled: {ok}")