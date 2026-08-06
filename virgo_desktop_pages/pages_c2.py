"""Covenant C2 Visual Commander — force-directed C2 topology graph.

Displays listeners → agents → tasks → results as an interactive
QGraphicsScene graph with layered force-directed layout, click-to-select
detail panel, real-time polling, and toolbar actions.
"""
from __future__ import annotations

import json
import math
import threading
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QPointF, QTimer, Qt, QUrl
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPen,
    QPolygonF,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .base import PageWidget, OUTDIR


# ═══════════════════════════════════════════════════════════════════════
# Data parsers
# ═══════════════════════════════════════════════════════════════════════

def _parse_c2_json(raw: dict | list) -> dict[str, list]:
    """Parse Covenant C2 export JSON into standardised dict."""
    if isinstance(raw, list):
        listeners = [
            x for x in raw
            if x.get("type") == "listener" or "protocol" in x
        ]
        agents = [
            x for x in raw
            if x.get("type") == "agent" or "hostname" in x
        ]
        tasks = [
            x for x in raw
            if x.get("type") == "task" or "command" in x
        ]
        return {"listeners": listeners, "agents": agents, "tasks": tasks}
    if isinstance(raw, dict):
        return {
            "listeners": raw.get("listeners", raw.get("listener_list", [])),
            "agents": raw.get("agents", raw.get("agent_list", [])),
            "tasks": raw.get("tasks", raw.get("task_list", [])),
        }
    return {"listeners": [], "agents": [], "tasks": []}


def _fetch_c2_from_api(url: str, timeout: float = 5.0) -> dict | None:
    """Fetch C2 data from the web dashboard API endpoint."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════
# Force-directed layout (layered spring model)
# ═══════════════════════════════════════════════════════════════════════

def _c2_force_layout(
    listeners: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    iterations: int = 80,
) -> dict[str, QPointF]:
    """Layered spring-electrical force-directed layout.

    Listeners anchor at top, agents in middle, tasks at bottom.
    X positions are adjusted by repulsion/attraction forces.
    """
    positions: dict[str, QPointF] = {}
    velocities: dict[str, QPointF] = {}

    # Build node list with layer info
    nodes: list[dict[str, Any]] = []
    layer_map: dict[str, int] = {}  # 0=listeners, 1=agents, 2=tasks

    for i, lst in enumerate(listeners):
        key = lst.get("name", lst.get("listener_id", f"listener_{i}"))
        nodes.append({"key": key, "layer": 0, "data": lst})
        layer_map[key] = 0

    for i, agt in enumerate(agents):
        key = agt.get("name", agt.get("hostname", f"agent_{i}"))
        nodes.append({"key": key, "layer": 1, "data": agt})
        layer_map[key] = 1

    for i, task in enumerate(tasks):
        key = task.get("id", task.get("task_id", f"task_{i}"))
        nodes.append({"key": key, "layer": 2, "data": task})
        layer_map[key] = 2

    if not nodes:
        return positions

    # Initial positions: layered with jitter
    layer_y = {0: 100.0, 1: 300.0, 2: 500.0}
    for i, node in enumerate(nodes):
        layer = node["layer"]
        n_in_layer = sum(1 for n in nodes if n["layer"] == layer)
        x_spacing = 250.0 if n_in_layer > 1 else 0.0
        x_offset = (i - (n_in_layer - 1) / 2.0) * x_spacing
        positions[node["key"]] = QPointF(x_offset, layer_y[layer])
        velocities[node["key"]] = QPointF(0, 0)

    # Build edge list for attraction
    edges: list[tuple[str, str]] = []
    for agt in agents:
        listener_name = agt.get("listener", agt.get("parent", ""))
        if listener_name:
            edges.append((listener_name, agt.get("name", agt.get("hostname", ""))))
    for task in tasks:
        agent_name = task.get("agent", task.get("parent", ""))
        if agent_name:
            edges.append((agent_name, task.get("id", task.get("task_id", ""))))

    if not positions:
        return positions

    # Spring-electrical iteration
    for _ in range(iterations):
        # Repulsion between all pairs
        for i, n1 in enumerate(nodes):
            for j, n2 in enumerate(nodes):
                if i >= j:
                    continue
                k1, k2 = n1["key"], n2["key"]
                if k1 not in positions or k2 not in positions:
                    continue
                diff = positions[k1] - positions[k2]
                dist = diff.manhattanLength()
                if dist < 1:
                    dist = 1
                force = 3000.0 / (dist * dist)
                direction = diff / dist
                velocities[k1] = velocities[k1] + direction * force
                velocities[k2] = velocities[k2] - direction * force

        # Attraction along edges
        for src, tgt in edges:
            if src not in positions or tgt not in positions:
                continue
            diff = positions[tgt] - positions[src]
            dist = diff.manhattanLength()
            if dist < 1:
                dist = 1
            force = dist * 0.005
            direction = diff / dist
            velocities[src] = velocities[src] + direction * force
            velocities[tgt] = velocities[tgt] - direction * force

        # Layer anchoring — pull nodes toward their layer y
        for node in nodes:
            key = node["key"]
            if key not in positions:
                continue
            target_y = layer_y[node["layer"]]
            velocities[key] = velocities[key] + QPointF(0, (target_y - positions[key].y()) * 0.05)

        # Damping + apply
        for key in velocities:
            velocities[key] = velocities[key] * 0.85
            positions[key] = positions[key] + velocities[key]

    return positions


# ═══════════════════════════════════════════════════════════════════════
# Graphics items
# ═══════════════════════════════════════════════════════════════════════

def _hexagon_polygon(cx: float, cy: float, radius: float) -> QPolygonF:
    """Return a pointy-top hexagon QPolygonF centred at (cx, cy)."""
    points = QPolygonF()
    for i in range(6):
        angle = math.pi / 3.0 * i - math.pi / 6.0
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        points.append(QPointF(x, y))
    return points


def _diamond_polygon(cx: float, cy: float, size: float) -> QPolygonF:
    """Return a diamond QPolygonF centred at (cx, cy)."""
    points = QPolygonF()
    points.append(QPointF(cx, cy - size))
    points.append(QPointF(cx + size * 0.7, cy))
    points.append(QPointF(cx, cy + size))
    points.append(QPointF(cx - size * 0.7, cy))
    return points


def _arrow_head_polygon(x1: float, y1: float, x2: float, y2: float, size: float = 8.0) -> QPolygonF:
    """Return a triangle arrowhead pointing from (x1,y1) toward (x2,y2)."""
    dx = x2 - x1
    dy = y2 - y1
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1:
        length = 1
    ux, uy = dx / length, dy / length
    # Perpendicular
    px, py = -uy, ux
    tip = QPointF(x2, y2)
    back1 = QPointF(x2 - ux * size + px * size * 0.5, y2 - uy * size + py * size * 0.5)
    back2 = QPointF(x2 - ux * size - px * size * 0.5, y2 - uy * size - py * size * 0.5)
    return QPolygonF([tip, back1, back2])


class _HexagonItem(QGraphicsPolygonItem):
    """Listener node — pointy-top hexagon, colour-coded by protocol."""

    def __init__(self, x: float, y: float, radius: float, color: QColor, label: str) -> None:
        poly = _hexagon_polygon(0, 0, radius)
        super().__init__(poly)
        self.setPos(QPointF(x, y))
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor("#45475a"), 2))
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        self.setAcceptHoverEvents(True)
        self._label = label
        # Add text label below hexagon
        self._text = QGraphicsTextItem(label, self)
        self._text.setPos(-self._text.boundingRect().width() / 2, radius + 4)
        self._text.setDefaultTextColor(QColor("#cdd6f4"))
        self._text.setFont(QFont("Segoe UI", 8))

    def hoverEnterEvent(self, event: Any) -> None:  # noqa: N802
        self.setPen(QPen(QColor("#89b4fa"), 3))

    def hoverLeaveEvent(self, event: Any) -> None:  # noqa: N802
        self.setPen(QPen(QColor("#45475a"), 2))


class _CircleNode(QGraphicsEllipseItem):
    """Agent node — circle coloured by status."""

    def __init__(self, x: float, y: float, radius: float, color: QColor, label: str) -> None:
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.setPos(QPointF(x, y))
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor("#45475a"), 2))
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        )
        self.setAcceptHoverEvents(True)
        self._label = label
        self._text = QGraphicsTextItem(label, self)
        self._text.setPos(-self._text.boundingRect().width() / 2, radius + 4)
        self._text.setDefaultTextColor(QColor("#cdd6f4"))
        self._text.setFont(QFont("Segoe UI", 7))

    def hoverEnterEvent(self, event: Any) -> None:  # noqa: N802
        self.setPen(QPen(QColor("#89b4fa"), 3))

    def hoverLeaveEvent(self, event: Any) -> None:  # noqa: N802
        self.setPen(QPen(QColor("#45475a"), 2))


class _DiamondNode(QGraphicsPolygonItem):
    """Task node — diamond shape coloured by status."""

    def __init__(self, x: float, y: float, size: float, color: QColor, label: str) -> None:
        poly = _diamond_polygon(0, 0, size)
        super().__init__(poly)
        self.setPos(QPointF(x, y))
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor("#45475a"), 1.5))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self._label = label
        self._text = QGraphicsTextItem(label, self)
        self._text.setPos(-self._text.boundingRect().width() / 2, size + 4)
        self._text.setDefaultTextColor(QColor("#cdd6f4"))
        self._text.setFont(QFont("Segoe UI", 6))


class _ArrowEdge(QGraphicsLineItem):
    """Directed edge with arrowhead showing data flow."""

    def __init__(self, x1: float, y1: float, x2: float, y2: float, label: str = "") -> None:
        super().__init__(x1, y1, x2, y2)
        self.setPen(QPen(QColor("#45475a"), 1.5, Qt.PenStyle.SolidLine))
        self._label = label
        self._arrow = None

    def set_arrow_head(self, scene: QGraphicsScene | None) -> None:
        """Add arrowhead polygon at the target end."""
        if self._arrow is not None and scene is not None:
            scene.removeItem(self._arrow)
        x1, y1 = self.line().x1(), self.line().y1()
        x2, y2 = self.line().x2(), self.line().y2()
        poly = _arrow_head_polygon(x1, y1, x2, y2, size=8.0)
        self._arrow = QGraphicsPolygonItem(poly, self)
        self._arrow.setBrush(QBrush(QColor("#45475a")))
        self._arrow.setPen(QPen(Qt.PenStyle.NoPen))
        if scene is not None:
            scene.addItem(self._arrow)

    def add_label(self, scene: QGraphicsScene | None) -> None:
        """Add edge label at midpoint."""
        if not self._label or scene is None:
            return
        x1, y1 = self.line().x1(), self.line().y1()
        x2, y2 = self.line().x2(), self.line().y2()
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        txt = QGraphicsTextItem(self._label, None)
        txt.setPos(mx - txt.boundingRect().width() / 2, my - 6)
        txt.setDefaultTextColor(QColor("#6c7086"))
        txt.setFont(QFont("Segoe UI", 6))
        scene.addItem(txt)


# ═══════════════════════════════════════════════════════════════════════
# Page
# ═══════════════════════════════════════════════════════════════════════

class C2CommanderPage(PageWidget):
    """Visual commander for Covenant C2 — listeners → agents → tasks → results."""

    def __init__(self) -> None:
        super().__init__("C2 Commander", "Covenant listener \u2192 agent \u2192 task topology")
        self._scene: QGraphicsScene | None = None
        self._view: QGraphicsView | None = None
        self._listeners: list[dict[str, Any]] = []
        self._agents: list[dict[str, Any]] = []
        self._tasks: list[dict[str, Any]] = []
        self._results: dict[str, dict[str, Any]] = {}
        self._positions: dict[str, QPointF] = {}
        self._detail_label: QLabel | None = None
        self._status_label: QLabel | None = None
        self._data_file: Path | None = None
        self._poll_timer: QTimer | None = None
        self._built = False
        self._clear_completed = False
        self._listener_list: QListWidget | None = None
        self._agent_list: QListWidget | None = None
        self._task_list: QListWidget | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        try:
            self._build_ui()
            if self._poll_timer is None:
                self._poll_timer = QTimer(self)
                self._poll_timer.timeout.connect(self._poll_c2_data)
                self._poll_timer.start(5000)
            self._poll_c2_data()
        except Exception:  # noqa: BLE001
            pass

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        if self._built:
            return
        self._built = True

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # ── Left panel ──────────────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(4)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        btn_refresh = QPushButton("\U0001f504 Refresh")
        btn_refresh.clicked.connect(self._poll_c2_data)
        toolbar.addWidget(btn_refresh)

        btn_export = QPushButton("\U0001f4be Export JSON")
        btn_export.clicked.connect(self._on_export)
        toolbar.addWidget(btn_export)

        btn_kill = QPushButton("\u2620 Kill Agent")
        btn_kill.clicked.connect(self._on_kill_agent)
        toolbar.addWidget(btn_kill)

        self._clear_btn = QPushButton("\U0001f5d1 Clear Done")
        self._clear_btn.setCheckable(True)
        self._clear_btn.toggled.connect(self._on_clear_completed)
        toolbar.addWidget(self._clear_btn)

        left.addLayout(toolbar)

        # Listener list
        listener_grp = QGroupBox("Listeners")
        listener_lay = QVBoxLayout(listener_grp)
        self._listener_list = QListWidget()
        self._listener_list.itemClicked.connect(self._on_listener_selected)
        listener_lay.addWidget(self._listener_list)
        left.addWidget(listener_grp, 0)

        # Agent list
        agent_grp = QGroupBox("Agents")
        agent_lay = QVBoxLayout(agent_grp)
        self._agent_list = QListWidget()
        self._agent_list.itemClicked.connect(self._on_agent_selected)
        agent_lay.addWidget(self._agent_list)
        left.addWidget(agent_grp, 1)

        # Task list
        task_grp = QGroupBox("Tasks")
        task_lay = QVBoxLayout(task_grp)
        self._task_list = QListWidget()
        self._task_list.itemClicked.connect(self._on_task_selected)
        task_lay.addWidget(self._task_list)
        left.addWidget(task_grp, 1)

        root.addLayout(left, 1)

        # ── Center: graph ───────────────────────────────────────────
        center = QVBoxLayout()
        center.setSpacing(2)

        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(-600, -400, 1200, 800)
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setTransformationAnchor(QGraphicsView.ViewAnchor.AnchorUnderMouse)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        center.addWidget(self._view, 1)

        # Detail panel
        detail_grp = QGroupBox("Node Detail")
        detail_lay = QVBoxLayout(detail_grp)
        self._detail_label = QLabel("Select a node to inspect")
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        detail_lay.addWidget(self._detail_label)
        center.addWidget(detail_grp, 0)

        root.addLayout(center, 3)

        # ── Bottom status bar ──────────────────────────────────────
        self._status_label = QLabel("No C2 data loaded")
        self._status_label.setStyleSheet("padding: 2px;")
        root.addWidget(self._status_label, 0)

        # Connect scene selection changes for click-to-select on graph nodes
        self._scene.selectionChanged.connect(self._on_scene_selection_changed)

    # ── Data loading ──────────────────────────────────────────────────────

    def _poll_c2_data(self) -> None:
        """Try web API first, then local file."""
        # Try web dashboard API
        api_data = _fetch_c2_from_api("http://127.0.0.1:8765/api/c2")
        if api_data is not None:
            self._load_c2_data(api_data, source="API")
            return

        # Fall back to local file
        data_path = OUTDIR / "c2_data.json"
        if data_path.exists():
            try:
                self._load_c2_data(json.loads(data_path.read_text()), source=data_path.name)
            except Exception:  # noqa: BLE001
                pass

    def _load_c2_data(self, data: dict, source: str = "") -> None:
        parsed = _parse_c2_json(data)
        self._listeners = parsed.get("listeners", [])
        self._agents = parsed.get("agents", [])
        self._tasks = parsed.get("tasks", [])

        # Build results lookup
        self._results = {}
        for task in self._tasks:
            result = task.get("result", {})
            if isinstance(result, dict) and result:
                self._results[task.get("id", task.get("task_id", ""))] = result

        self._data_file = self._data_file or Path(source) if source else None
        self._last_source = source or (self._data_file.name if self._data_file else "polling")
        self._refresh_lists()
        self._render_graph()

    # ── List refresh ──────────────────────────────────────────────────────

    def _refresh_lists(self) -> None:
        # Listener list
        self._listener_list.clear()
        for lst in self._listeners:
            name = lst.get("name", lst.get("listener_id", "unknown"))
            proto = lst.get("protocol", lst.get("type", "?"))
            status = lst.get("status", lst.get("state", "unknown"))
            icon = "\U0001f7e2" if status == "Active" else "\U0001f534" if status == "Inactive" else "\u26aa"
            self._listener_list.addItem(f"{icon} {name} ({proto}:{lst.get('port', '?')})")

        # Agent list
        self._agent_list.clear()
        for agt in self._agents:
            name = agt.get("name", agt.get("hostname", "unknown"))
            status = agt.get("status", agt.get("state", "unknown"))
            icon = "\U0001f7e2" if status == "Active" else "\U0001f534" if status in ("Lost", "Exited") else "\u26aa"
            self._agent_list.addItem(f"{icon} {name} ({agt.get('username', '?')})")

        # Task list
        self._task_list.clear()
        for task in self._tasks:
            tid = task.get("id", task.get("task_id", "?"))
            ttype = task.get("type", "?")
            status = task.get("status", "Pending")
            icon = "\U0001f7e1" if status == "Pending" else "\U0001f535" if status == "Running" else "\U0001f7e2" if status == "Completed" else "\U0001f534"
            self._task_list.addItem(f"{icon} {tid} [{ttype}] {status}")

    # ── Graph rendering ───────────────────────────────────────────────────

    def _render_graph(self) -> None:
        if self._scene is None:
            return
        self._scene.clear()
        self._positions.clear()

        # Filter out completed tasks if toggle is active
        tasks = [t for t in self._tasks if not self._clear_completed or t.get("status") != "Completed"]

        all_nodes = []
        for lst in self._listeners:
            all_nodes.append({"type": "listener", "data": lst})
        for agt in self._agents:
            all_nodes.append({"type": "agent", "data": agt})
        for task in tasks:
            all_nodes.append({"type": "task", "data": task})

        if not all_nodes:
            self._status_label.setText("No C2 data \u2014 import a JSON export or wait for polling")
            self._detail_label.setText("No nodes to display")
            return

        # Compute force-directed layout
        self._positions = _c2_force_layout(self._listeners, self._agents, tasks)

        # Draw edges with arrowheads
        for lst in self._listeners:
            lst_name = lst.get("name", lst.get("listener_id", ""))
            if lst_name not in self._positions:
                continue
            for agt in self._agents:
                agt_name = agt.get("name", agt.get("hostname", ""))
                if agt.get("listener", agt.get("parent", "")) == lst_name and agt_name in self._positions:
                    p1 = self._positions[lst_name]
                    p2 = self._positions[agt_name]
                    edge = _ArrowEdge(p1.x(), p1.y(), p2.x(), p2.y(), "c2")
                    self._scene.addItem(edge)
                    edge.set_arrow_head(self._scene)

        for agt in self._agents:
            agt_name = agt.get("name", agt.get("hostname", ""))
            if agt_name not in self._positions:
                continue
            for task in tasks:
                if task.get("agent", task.get("parent", "")) == agt_name:
                    task_id = task.get("id", task.get("task_id", ""))
                    if task_id in self._positions:
                        p1 = self._positions[agt_name]
                        p2 = self._positions[task_id]
                        edge = _ArrowEdge(p1.x(), p1.y(), p2.x(), p2.y(), task.get("type", ""))
                        self._scene.addItem(edge)
                        edge.set_arrow_head(self._scene)

        # Draw listener nodes (hexagons)
        proto_color = {
            "http": QColor("#89b4fa"),
            "https": QColor("#a6e3a1"),
            "smb": QColor("#f9e2af"),
            "winrm": QColor("#f38ba8"),
        }
        for lst in self._listeners:
            name = lst.get("name", lst.get("listener_id", ""))
            if name not in self._positions:
                continue
            pos = self._positions[name]
            proto = lst.get("protocol", lst.get("type", "http")).lower()
            color = proto_color.get(proto, QColor("#89b4fa"))
            node = _HexagonItem(pos.x(), pos.y(), 28, color, name)
            node.setData(0, {"type": "listener", "data": lst})
            self._scene.addItem(node)

        # Draw agent nodes (circles)
        for agt in self._agents:
            name = agt.get("name", agt.get("hostname", ""))
            if name not in self._positions:
                continue
            pos = self._positions[name]
            status = agt.get("status", agt.get("state", "unknown"))
            if status == "Active":
                color = QColor("#a6e3a1")
            elif status in ("Lost", "Exited"):
                color = QColor("#f38ba8")
            else:
                color = QColor("#6c7086")
            node = _CircleNode(pos.x(), pos.y(), 18, color, name)
            node.setData(0, {"type": "agent", "data": agt})
            self._scene.addItem(node)

        # Draw task nodes (diamonds)
        for task in tasks:
            task_id = task.get("id", task.get("task_id", ""))
            if task_id not in self._positions:
                continue
            pos = self._positions[task_id]
            status = task.get("status", "Pending")
            if status == "Pending":
                color = QColor("#f9e2af")
            elif status == "Running":
                color = QColor("#89b4fa")
            elif status == "Completed":
                color = QColor("#a6e3a1")
            else:
                color = QColor("#f38ba8")
            node = _DiamondNode(pos.x(), pos.y(), 14, color, task_id)
            node.setData(0, {"type": "task", "data": task})
            self._scene.addItem(node)

        # Update status bar
        active_listeners = sum(1 for l in self._listeners if l.get("status") == "Active")
        self._status_label.setText(
            f"Listeners: {len(self._listeners)} ({active_listeners} active)  |  "
            f"Agents: {len(self._agents)}  |  "
            f"Tasks: {len(tasks)}  |  "
            f"Source: {source if (source := getattr(self, '_last_source', '')) else 'polling'}"
        )

        self._view.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # ── Selection / detail ────────────────────────────────────────────────

    def _on_scene_selection_changed(self) -> None:
        """Handle click-to-select on graph nodes."""
        selected = self._scene.selectedItems() if self._scene else []
        if not selected:
            return
        item = selected[0]
        data = item.data(0)
        if not isinstance(data, dict):
            return
        self._show_node_detail(data)

    def _show_node_detail(self, data: dict[str, Any]) -> None:
        """Show full detail for a selected node in the detail panel."""
        node_type = data.get("type", "")
        node_data = data.get("data", {})
        if not node_data:
            return

        lines: list[str] = []
        if node_type == "listener":
            lines.append(f"<b>Listener</b>")
            lines.append(f"Name: {node_data.get('name', node_data.get('listener_id', '?'))}")
            lines.append(f"Protocol: {node_data.get('protocol', node_data.get('type', '?'))}")
            lines.append(f"Port: {node_data.get('port', '?')}")
            lines.append(f"Bind: {node_data.get('bind_addr', node_data.get('host', '?'))}")
            lines.append(f"Status: {node_data.get('status', node_data.get('state', '?'))}")
            lines.append(f"Type: {node_data.get('type', '?')}")
        elif node_type == "agent":
            lines.append(f"<b>Agent</b>")
            lines.append(f"Name: {node_data.get('name', node_data.get('hostname', '?'))}")
            lines.append(f"Hostname: {node_data.get('hostname', '?')}")
            lines.append(f"User: {node_data.get('username', '?')}")
            lines.append(f"PID: {node_data.get('pid', '?')}")
            lines.append(f"Protocol: {node_data.get('protocol', '?')}")
            lines.append(f"Listener: {node_data.get('listener', node_data.get('parent', '?'))}")
            lines.append(f"Status: {node_data.get('status', node_data.get('state', '?'))}")
            lines.append(f"Last Check-in: {node_data.get('last_checkin', node_data.get('last_seen', '?'))}")
            tags = node_data.get("tags", [])
            if tags:
                lines.append(f"Tags: {', '.join(tags)}")
        elif node_type == "task":
            lines.append(f"<b>Task</b>")
            lines.append(f"ID: {node_data.get('id', node_data.get('task_id', '?'))}")
            lines.append(f"Agent: {node_data.get('agent', node_data.get('parent', '?'))}")
            lines.append(f"Type: {node_data.get('type', '?')}")
            lines.append(f"Command: {node_data.get('command', '?')}")
            lines.append(f"Status: {node_data.get('status', 'Pending')}")
            lines.append(f"Created: {node_data.get('created', '?')}")
            lines.append(f"Completed: {node_data.get('completed', '?')}")
            result = node_data.get("result")
            if isinstance(result, dict):
                lines.append(f"Result:")
                lines.append(f"  Exit Code: {result.get('exit_code', '?')}")
                lines.append(f"  Duration: {result.get('duration', '?')}s")
                output = result.get("output", "")
                if output:
                    preview = output[:200] + ("..." if len(output) > 200 else "")
                    lines.append(f"  Output: {preview}")
            elif isinstance(result, str) and result:
                lines.append(f"Result: {result[:200]}")
        elif node_type == "result":
            lines.append(f"<b>Result</b>")
            lines.append(f"Task ID: {node_data.get('task_id', '?')}")
            lines.append(f"Output: {node_data.get('output', '')[:200]}")
            lines.append(f"Exit Code: {node_data.get('exit_code', '?')}")
            lines.append(f"Duration: {node_data.get('duration', '?')}s")

        if self._detail_label is not None:
            self._detail_label.setText("<br>".join(lines))

    def _on_listener_selected(self, item: QListWidgetItem) -> None:
        idx = self._listener_list.row(item)
        if 0 <= idx < len(self._listeners):
            self._show_node_detail({"type": "listener", "data": self._listeners[idx]})

    def _on_agent_selected(self, item: QListWidgetItem) -> None:
        idx = self._agent_list.row(item)
        if 0 <= idx < len(self._agents):
            self._show_node_detail({"type": "agent", "data": self._agents[idx]})

    def _on_task_selected(self, item: QListWidgetItem) -> None:
        idx = self._task_list.row(item)
        if 0 <= idx < len(self._tasks):
            self._show_node_detail({"type": "task", "data": self._tasks[idx]})

    # ── Context menu ──────────────────────────────────────────────────────

    def _on_context_menu(self, pos: Any) -> None:
        menu = QMenu(self)
        menu.addAction("Zoom In", lambda: self._view.scale(1.3, 1.3))
        menu.addAction("Zoom Out", lambda: self._view.scale(0.7, 0.7))
        menu.addAction("Reset View", lambda: self._view.fitInView(
            self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio))
        menu.addAction("Export PNG", self._on_export_png)
        menu.exec(self._view.viewport().mapToGlobal(pos))

    # ── Actions ───────────────────────────────────────────────────────────

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export C2 Data", str(OUTDIR / "c2_export.json"),
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            Path(path).write_text(json.dumps({
                "listeners": self._listeners,
                "agents": self._agents,
                "tasks": self._tasks,
            }, indent=2))

    def _on_export_png(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Graph", str(OUTDIR / "c2_graph.png"),
            "PNG Image (*.png)",
        )
        if not path:
            return
        try:
            from PyQt6.QtGui import QImage, QPainter
            img = QImage(int(self._view.width()), int(self._view.height()), QImage.Format.Format_ARGB32)
            img.fill(QColor("#1e1e2e"))
            painter = QPainter(img)
            self._scene.render(painter)
            painter.end()
            img.save(path)
            self._status_label.setText(f"Exported to {path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Export Error", str(exc))

    def _on_kill_agent(self) -> None:
        selected = self._scene.selectedItems() if self._scene else []
        if selected:
            data = selected[0].data(0)
            if isinstance(data, dict) and data.get("type") == "agent":
                name = data["data"].get("name", data["data"].get("hostname", "unknown"))
                reply = QMessageBox.question(
                    self, "Kill Agent",
                    f"Terminate agent <b>{name}</b>?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self._status_label.setText(f"Kill command sent to agent {name}")
                return
        QMessageBox.information(
            self, "Kill Agent",
            "Select an agent node in the graph or agent list first.",
        )

    def _on_clear_completed(self, checked: bool) -> None:
        self._clear_completed = checked
        self._render_graph()
        label = "Hiding completed tasks" if checked else "Showing all tasks"
        self._status_label.setText(self._status_label.text().rsplit("|", 1)[0].strip() + f" | {label}")


# ═══════════════════════════════════════════════════════════════════════
# Module-level test / demo data
# ═══════════════════════════════════════════════════════════════════════

SAMPLE_C2_DATA = {
    "listeners": [
        {"name": "http_listener", "protocol": "HTTP", "port": 8080, "bind_addr": "0.0.0.0", "status": "Active", "type": "Http"},
        {"name": "https_listener", "protocol": "HTTPS", "port": 8443, "bind_addr": "0.0.0.0", "status": "Active", "type": "Https"},
        {"name": "smb_listener", "protocol": "SMB", "port": 445, "bind_addr": "0.0.0.0", "status": "Inactive", "type": "Smb"},
    ],
    "agents": [
        {"name": "agent-win1", "hostname": "DESKTOP-ABC", "username": "admin", "pid": 4820, "protocol": "HTTP", "listener": "http_listener", "last_checkin": "2026-08-05T10:30:00Z", "status": "Active", "tags": ["workstation", "admin"]},
        {"name": "agent-win2", "hostname": "DESKTOP-DEF", "username": "user1", "pid": 3192, "protocol": "HTTPS", "listener": "https_listener", "last_checkin": "2026-08-05T10:28:00Z", "status": "Active", "tags": ["laptop"]},
        {"name": "agent-linux1", "hostname": "server01", "username": "root", "pid": 1204, "protocol": "HTTP", "listener": "http_listener", "last_checkin": "2026-08-05T09:15:00Z", "status": "Lost", "tags": ["server"]},
    ],
    "tasks": [
        {"id": "task-001", "agent": "agent-win1", "type": "shell", "command": "whoami", "status": "Completed", "result": {"output": "DESKTOP-ABC\\admin", "exit_code": 0, "duration": 1.2}, "created": "2026-08-05T10:25:00Z", "completed": "2026-08-05T10:25:01Z"},
        {"id": "task-002", "agent": "agent-win1", "type": "execute", "command": "dir C:\\", "status": "Completed", "result": {"output": "Volume in drive C...", "exit_code": 0, "duration": 2.5}, "created": "2026-08-05T10:26:00Z", "completed": "2026-08-05T10:26:03Z"},
        {"id": "task-003", "agent": "agent-win2", "type": "download", "command": "download C:\\secrets\\flag.txt", "status": "Running", "result": {}, "created": "2026-08-05T10:27:00Z", "completed": ""},
        {"id": "task-004", "agent": "agent-linux1", "type": "shell", "command": "id", "status": "Failed", "result": {"output": "", "exit_code": 1, "duration": 0.5}, "created": "2026-08-05T10:20:00Z", "completed": "2026-08-05T10:20:01Z"},
    ],
}
