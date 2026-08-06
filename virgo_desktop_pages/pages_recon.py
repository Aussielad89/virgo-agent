"""Recon Graph Explorer — force-directed topology of nmap/amass/subfinder output."""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .base import *  # noqa: F401,F403
from .base import HERE, OUTDIR  # noqa: F401

from PyQt6.QtCore import QPointF, QTimer, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QTransform
from PyQt6.QtWidgets import (
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
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
    QVBoxLayout,
    QWidget,
)


# ═══════════════════════════════════════════════════════════════════════
# Data parsers
# ═══════════════════════════════════════════════════════════════════════

def _parse_nmap_xml(path: Path) -> dict[str, Any]:
    """Parse nmap -oX XML into our internal graph format."""
    tree = ET.parse(path)
    root = tree.getroot()
    hosts: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for host in root.findall(".//host"):
        status_el = host.find("status")
        if status_el is not None and status_el.get("state") != "up":
            continue

        addr = host.find("address")
        ip = addr.get("addr", "") if addr is not None else ""

        hostnames_el = host.find("hostnames")
        hostnames = [
            h.get("name", "")
            for h in (hostnames_el.findall("hostname") if hostnames_el is not None else [])
            if h.get("name")
        ]

        ports_el = host.find("ports")
        open_ports: list[dict[str, Any]] = []
        if ports_el is not None:
            for port in ports_el.findall("port"):
                if port.find("state") is not None and port.find("state").get("state") == "open":
                    svc = port.find("service")
                    open_ports.append({
                        "port": int(port.get("portid", "0")),
                        "protocol": port.get("protocol", "tcp"),
                        "service": svc.get("name", "") if svc is not None else "",
                        "product": svc.get("product", "") if svc is not None else "",
                        "version": svc.get("version", "") if svc is not None else "",
                        "vuln": svc.get("vuln", "") if svc is not None else "",
                    })

        os_el = host.find("os")
        os_info = ""
        if os_el is not None:
            osmatch = os_el.find("osmatch")
            if osmatch is not None:
                os_info = osmatch.get("name", "")

        hosts.append({
            "type": "host",
            "ip": ip,
            "hostnames": hostnames,
            "label": hostnames[0] if hostnames else ip,
            "ports": open_ports,
            "os": os_info,
            "status": "up",
        })

    # Build edges: host → its open ports (service edges)
    for h in hosts:
        for p in h["ports"]:
            edges.append({
                "type": "service",
                "source": h["ip"],
                "target": f"{h['ip']}:{p['port']}",
                "label": f"{p['service'] or 'open'}/{p['port']}",
                "vuln": p.get("vuln", ""),
            })

    # Build inter-host edges for common service relationships
    for i, h1 in enumerate(hosts):
        for h2 in hosts[i + 1:]:
            h1_services = {p["port"] for p in h1["ports"]}
            h2_services = {p["port"] for p in h2["ports"]}
            common = h1_services & h2_services
            if common:
                edges.append({
                    "type": "edge",
                    "source": h1["ip"],
                    "target": h2["ip"],
                    "label": f"shared ports: {', '.join(str(p) for p in sorted(common)[:3])}",
                })

    return {"nodes": hosts, "edges": edges}


def _parse_json(path: Path) -> dict[str, Any]:
    """Parse JSON files with host/subdomain objects (amass/subfinder/nmap JSON)."""
    raw = json.loads(path.read_text())

    # Handle amass/subfinder JSON arrays
    if isinstance(raw, list):
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name", item.get("domain", item.get("host", "")))
            ip = item.get("ip", item.get("resolved", item.get("addr", "")))
            if not name:
                continue
            node_type = "subdomain" if item.get("type") == "name" or not ip else "host"
            nodes.append({
                "type": node_type,
                "ip": ip or name,
                "label": name,
                "hostnames": [name],
                "ports": [],
                "os": "",
                "status": "resolved" if node_type == "subdomain" else "up",
                "vuln": "",
            })
        return {"nodes": nodes, "edges": edges}

    # Handle nmap JSON-style objects
    if isinstance(raw, dict):
        if "nodes" in raw and "edges" in raw:
            return raw
        # Single host object
        if "ip" in raw or "addr" in raw:
            ip = raw.get("ip") or raw.get("addr", "")
            return {
                "nodes": [{
                    "type": "host",
                    "ip": ip,
                    "label": raw.get("hostname", ip),
                    "hostnames": [raw.get("hostname", "")],
                    "ports": raw.get("ports", []),
                    "os": raw.get("os", ""),
                    "status": "up",
                    "vuln": "",
                }],
                "edges": [],
            }
    return {"nodes": [], "edges": []}


# ═══════════════════════════════════════════════════════════════════════
# Force-directed layout (static, used as initial positions + animation target)
# ═══════════════════════════════════════════════════════════════════════

def _force_directed_layout(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    iterations: int = 200,
) -> dict[str, QPointF]:
    """Simple spring-electrical force-directed layout."""
    positions: dict[str, QPointF] = {}
    velocities: dict[str, QPointF] = {}

    for i, node in enumerate(nodes):
        angle = 2 * math.pi * i / max(len(nodes), 1)
        r = 200 + 50 * (i % 5)
        positions[node["ip"]] = QPointF(
            400 + r * math.cos(angle),
            300 + r * math.sin(angle),
        )
        velocities[node["ip"]] = QPointF(0, 0)

    if not nodes:
        return positions

    for _ in range(iterations):
        # Repulsion between all pairs
        for i, n1 in enumerate(nodes):
            for j, n2 in enumerate(nodes):
                if i >= j:
                    continue
                key1, key2 = n1["ip"], n2["ip"]
                if key1 not in positions or key2 not in positions:
                    continue
                diff = positions[key1] - positions[key2]
                dist = diff.manhattanLength()
                if dist < 1:
                    dist = 1
                force = 5000 / (dist * dist)
                direction = diff / dist
                velocities[key1] = velocities[key1] + direction * force
                velocities[key2] = velocities[key2] - direction * force

        # Attraction along edges
        for edge in edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            tgt_node = tgt.split(":")[0] if ":" in tgt else tgt
            if src not in positions or tgt_node not in positions:
                continue
            diff = positions[tgt_node] - positions[src]
            dist = diff.manhattanLength()
            if dist < 1:
                dist = 1
            force = dist * 0.01
            direction = diff / dist
            velocities[src] = velocities[src] + direction * force
            velocities[tgt_node] = velocities[tgt_node] - direction * force

        # Center gravity
        for key in positions:
            center = QPointF(400, 300)
            diff = center - positions[key]
            velocities[key] = velocities[key] + diff * 0.001

        # Damping + apply
        for key in velocities:
            velocities[key] = velocities[key] * 0.9
            positions[key] = positions[key] + velocities[key]

    return positions


# ═══════════════════════════════════════════════════════════════════════
# Graphics items
# ═══════════════════════════════════════════════════════════════════════

class _HostNode(QGraphicsEllipseItem):
    """Host node: larger circle with accent color."""

    def __init__(self, x: float, y: float, radius: float, color: QColor, label: str) -> None:
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.setPos(QPointF(x, y))
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor("#45475a"), 2))
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self._label = label
        self._radius = radius
        self._base_color = color

    def hoverEnterEvent(self, event: Any) -> None:  # noqa: N802
        self.setPen(QPen(QColor("#cdd6f4"), 3))

    def hoverLeaveEvent(self, event: Any) -> None:  # noqa: N802
        self.setPen(QPen(QColor("#45475a"), 2))


class _ServiceNode(QGraphicsEllipseItem):
    """Service node: smaller circle on the edge endpoint."""

    def __init__(self, x: float, y: float, radius: float, color: QColor, label: str) -> None:
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.setPos(QPointF(x, y))
        self.setBrush(QBrush(color))
        self.setPen(QPen(QColor("#45475a"), 1))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self._label = label
        self._radius = radius


class _EdgeLine(QGraphicsLineItem):
    """Edge line connecting two nodes."""

    def __init__(self, x1: float, y1: float, x2: float, y2: float, label: str = "") -> None:
        super().__init__(x1, y1, x2, y2)
        self.setPen(QPen(QColor("#45475a"), 1, Qt.PenStyle.DashLine))
        self._label = label


class _VulnRing(QGraphicsEllipseItem):
    """Red ring around nodes with critical vulnerabilities."""

    def __init__(self, x: float, y: float, radius: float) -> None:
        super().__init__(-radius - 4, -radius - 4, (radius + 4) * 2, (radius + 4) * 2)
        self.setPos(QPointF(x, y))
        self.setBrush(QBrush(QColor("#f38ba8")))
        self.setPen(QPen(QColor("#f38ba8"), 2, Qt.PenStyle.DashLine))
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)


# ═══════════════════════════════════════════════════════════════════════
# Page
# ═══════════════════════════════════════════════════════════════════════

class ReconGraphPage(PageWidget):
    """Interactive force-directed graph of recon data (nmap XML, amass/subfinder JSON)."""

    def __init__(self) -> None:
        super().__init__(
            "Recon Graph Explorer",
            "Network topology from nmap / amass / subfinder output",
        )
        self._scene: QGraphicsScene | None = None
        self._view: QGraphicsView | None = None
        self._nodes: list[dict[str, Any]] = []
        self._edges: list[dict[str, Any]] = []
        self._positions: dict[str, QPointF] = {}
        self._detail_label: QLabel | None = None
        self._status_label: QLabel | None = None
        self._layout_timer: QTimer | None = None
        self._data_file: Path | None = None
        self._built = False
        self._anim_iterations = 0
        self._selected_node: dict[str, Any] | None = None
        self._host_items: list[_HostNode] = []
        self._service_items: list[_ServiceNode] = []
        self._edge_items: list[_EdgeLine] = []
        self._vuln_items: list[_VulnRing] = []

        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Build the page UI in __init__ (called once)."""
        if self._built:
            return
        self._built = True

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # ── Left panel: import + file list ──────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(4)

        import_grp = QGroupBox("Import")
        import_lay = QVBoxLayout(import_grp)
        import_lay.setSpacing(4)

        btn_import = QPushButton("📂 Import nmap XML / JSON")
        btn_import.clicked.connect(self._on_import)
        import_lay.addWidget(btn_import)

        btn_sample = QPushButton("📋 Load sample data")
        btn_sample.clicked.connect(self._on_load_sample)
        import_lay.addWidget(btn_sample)

        left.addWidget(import_grp)

        # File list
        self._file_list = QListWidget()
        self._file_list.itemClicked.connect(self._on_file_selected)
        left.addWidget(self._file_list, 1)

        root.addLayout(left, 1)

        # ── Center: graph view ──────────────────────────────────────────
        center = QVBoxLayout()
        center.setSpacing(2)

        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(-600, -400, 1200, 800)
        self._scene.setBackgroundBrush(QBrush(QColor("#1e1e2e")))

        self._view = QGraphicsView(self._scene)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._view.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.setStyleSheet(
            "QGraphicsView { border: 1px solid #313244; border-radius: 6px; background: #1e1e2e; }"
        )
        self._view.customContextMenuRequested.connect(self._on_context_menu)
        center.addWidget(self._view, 1)

        # Install wheel-event zoom handler
        self._view.wheelEvent = self._on_wheel  # type: ignore[method-assign]

        # Install click handler for node selection
        self._view.mousePressEvent = self._on_view_clicked  # type: ignore[method-assign]

        # Detail panel
        detail_grp = QGroupBox("Node Detail")
        detail_lay = QVBoxLayout(detail_grp)
        self._detail_label = QLabel("Click a node to inspect")
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._detail_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        detail_lay.addWidget(self._detail_label)
        center.addWidget(detail_grp, 0)

        root.addLayout(center, 3)

        # ── Bottom status bar ──────────────────────────────────────────
        self._status_label = QLabel("No data loaded — import a file or load sample data")
        self._status_label.setStyleSheet(
            "color: #6c7086; font-size: 12px; padding: 4px 2px; "
            "border-top: 1px solid #313244; background: #181825;"
        )
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self._status_label, 0)

    # ── Data loading ──────────────────────────────────────────────────

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Recon Data",
            str(OUTDIR),
            "Supported Files (*.xml *.json);;Nmap XML (*.xml);;JSON (*.json);;All Files (*)",
        )
        if not path:
            return
        self._load_file(Path(path))

    def _on_load_sample(self) -> None:
        self._load_sample()

    def _load_sample(self) -> None:
        """Load built-in sample data so the page isn't empty on first open."""
        self._nodes = [
            {"type": "host", "ip": "10.0.0.1", "label": "target.local",
             "hostnames": ["target.local"],
             "ports": [{"port": 22, "protocol": "tcp", "service": "ssh", "product": "OpenSSH",
                        "version": "8.9p1", "vuln": ""},
                       {"port": 80, "protocol": "tcp", "service": "http", "product": "nginx",
                        "version": "1.24", "vuln": "CVE-2024-1234"}],
             "os": "Linux 5.15", "status": "up", "vuln": ""},
            {"type": "host", "ip": "10.0.0.2", "label": "web01.internal",
             "hostnames": ["web01.internal"],
             "ports": [{"port": 443, "protocol": "tcp", "service": "https", "product": "nginx",
                        "version": "1.24", "vuln": ""}],
             "os": "Linux 5.15", "status": "up", "vuln": ""},
            {"type": "host", "ip": "10.0.0.3", "label": "db01.internal",
             "hostnames": ["db01.internal"],
             "ports": [{"port": 3306, "protocol": "tcp", "service": "mysql", "product": "MySQL",
                        "version": "8.0", "vuln": ""}],
             "os": "Linux 5.15", "status": "up", "vuln": ""},
            {"type": "host", "ip": "10.0.0.4", "label": "10.0.0.4", "hostnames": [],
             "ports": [{"port": 445, "protocol": "tcp", "service": "microsoft-ds", "product": "",
                        "version": "", "vuln": "critical"}],
             "os": "Windows 10", "status": "up", "vuln": "critical"},
            {"type": "subdomain", "ip": "203.0.113.5", "label": "api.target.local",
             "hostnames": ["api.target.local"], "ports": [], "os": "", "status": "resolved",
             "vuln": ""},
            {"type": "subdomain", "ip": "203.0.113.6", "label": "dev.target.local",
             "hostnames": ["dev.target.local"], "ports": [], "os": "", "status": "resolved",
             "vuln": ""},
        ]
        self._edges = [
            {"type": "service", "source": "10.0.0.1", "target": "10.0.0.1:22", "label": "ssh/22", "vuln": ""},
            {"type": "service", "source": "10.0.0.1", "target": "10.0.0.1:80", "label": "http/80", "vuln": "critical"},
            {"type": "edge", "source": "10.0.0.1", "target": "10.0.0.2", "label": "HTTP", "vuln": ""},
            {"type": "edge", "source": "10.0.0.2", "target": "10.0.0.3", "label": "MySQL", "vuln": ""},
            {"type": "edge", "source": "10.0.0.1", "target": "10.0.0.4", "label": "SMB", "vuln": ""},
            {"type": "edge", "source": "10.0.0.1", "target": "203.0.113.5", "label": "DNS", "vuln": ""},
            {"type": "edge", "source": "10.0.0.1", "target": "203.0.113.6", "label": "DNS", "vuln": ""},
        ]
        self._data_file = None
        self._file_list.addItem("sample (built-in)")
        self._render_graph()

    def _load_file(self, path: Path) -> None:
        try:
            if path.suffix == ".xml":
                data = _parse_nmap_xml(path)
            else:
                data = _parse_json(path)
            self._nodes = data.get("nodes", [])
            self._edges = data.get("edges", [])
            self._data_file = path
            self._file_list.addItem(path.name)
            self._render_graph()
        except Exception as exc:
            QMessageBox.warning(self, "Import Error", f"Failed to parse {path.name}:\n{exc}")

    def _on_file_selected(self, item: QListWidgetItem) -> None:
        if item.text() == "sample (built-in)":
            self._load_sample()

    # ── Graph rendering ───────────────────────────────────────────────

    def _render_graph(self) -> None:
        """Draw the force-directed graph in the scene."""
        if self._scene is None:
            return
        self._scene.clear()
        self._host_items.clear()
        self._service_items.clear()
        self._edge_items.clear()
        self._vuln_items.clear()
        self._positions.clear()

        if not self._nodes:
            self._status_label.setText("No nodes to display — import a file or load sample data")
            txt = self._scene.addText("No data loaded — import a file or load sample data")
            txt.setDefaultTextColor(QColor("#6c7086"))
            txt.setFont(QFont("Segoe UI", 12))
            return

        # Compute initial circular positions (animation will settle them)
        self._positions.clear()
        for i, node in enumerate(self._nodes):
            angle = 2 * math.pi * i / max(len(self._nodes), 1)
            r = 200 + 50 * (i % 5)
            self._positions[node["ip"]] = QPointF(
                400 + r * math.cos(angle),
                300 + r * math.sin(angle),
            )

        # Draw edges first (behind nodes)
        for edge in self._edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            tgt_node = tgt.split(":")[0] if ":" in tgt else tgt
            if src in self._positions and tgt_node in self._positions:
                p1 = self._positions[src]
                p2 = self._positions[tgt_node]
                line = _EdgeLine(p1.x(), p1.y(), p2.x(), p2.y(), edge.get("label", ""))
                self._scene.addItem(line)
                self._edge_items.append(line)

        # Draw nodes
        for node in self._nodes:
            ip = node["ip"]
            if ip not in self._positions:
                continue
            pos = self._positions[ip]
            node_type = node.get("type", "host")

            if node_type == "host":
                radius = 22
                color = QColor("#89b4fa")  # accent blue for hosts
                if node.get("os", "").startswith("Windows"):
                    color = QColor("#f9e2af")  # yellow for Windows hosts
                elif node.get("os", "").startswith("Linux"):
                    color = QColor("#a6e3a1")  # green for Linux hosts

                item = _HostNode(pos.x(), pos.y(), radius, color, node.get("label", ip))
                item.setData(0, node)
                self._scene.addItem(item)
                self._host_items.append(item)

                # Label below host node
                label = QGraphicsTextItem(node.get("label", ip), item)
                label.setPos(-label.boundingRect().width() / 2, radius + 2)
                label.setDefaultTextColor(QColor("#cdd6f4"))
                label.setFont(QFont("Segoe UI", 8))

                # Port labels for hosts
                if node.get("ports"):
                    port_text = ", ".join(f"{p['port']}/{p['protocol']}" for p in node["ports"][:3])
                    if len(node["ports"]) > 3:
                        port_text += f" +{len(node['ports']) - 3}"
                    pt = QGraphicsTextItem(port_text, item)
                    pt.setPos(-pt.boundingRect().width() / 2, radius + 14)
                    pt.setDefaultTextColor(QColor("#6c7086"))
                    pt.setFont(QFont("Segoe UI", 7))

                # Critical vuln ring
                if node.get("vuln") == "critical" or any(
                    p.get("vuln") == "critical" for p in node.get("ports", [])
                ):
                    ring = _VulnRing(pos.x(), pos.y(), radius)
                    self._scene.addItem(ring)
                    self._vuln_items.append(ring)

            else:
                # Service / subdomain node: smaller circle
                radius = 14
                color = QColor("#cba6f7")  # purple for subdomains
                if node_type == "service":
                    color = QColor("#1e1e2e")  # surface color for services

                item = _ServiceNode(pos.x(), pos.y(), radius, color, node.get("label", ip))
                item.setData(0, node)
                self._scene.addItem(item)
                self._service_items.append(item)

                # Label below service node
                label = QGraphicsTextItem(node.get("label", ip), item)
                label.setPos(-label.boundingRect().width() / 2, radius + 2)
                label.setDefaultTextColor(QColor("#cdd6f4"))
                label.setFont(QFont("Segoe UI", 7))

        # Update status bar
        host_count = sum(1 for n in self._nodes if n.get("type") == "host")
        svc_count = sum(1 for n in self._nodes if n.get("type") == "service")
        sub_count = sum(1 for n in self._nodes if n.get("type") == "subdomain")
        vuln_count = sum(1 for n in self._nodes if n.get("vuln") == "critical")
        vuln_count += sum(1 for e in self._edges if e.get("vuln") == "critical")
        status_parts = [f"Nodes: {len(self._nodes)} (hosts: {host_count}, svc: {svc_count}, sub: {sub_count})"]
        status_parts.append(f"Edges: {len(self._edges)}")
        if vuln_count > 0:
            status_parts.append(f"Vulns: {vuln_count} critical")
        status_parts.append(f"Source: {self._data_file.name if self._data_file else 'sample'}")
        self._status_label.setText("  |  ".join(status_parts))

        # Fit view to scene
        self._view.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    # ── Force-directed animation ──────────────────────────────────────

    def _start_animation(self) -> None:
        """Start the force-directed layout animation with a QTimer."""
        self._anim_iterations = 0
        if self._layout_timer is not None:
            self._layout_timer.stop()

        self._layout_timer = QTimer(self)
        self._layout_timer.setInterval(50)
        self._layout_timer.timeout.connect(self._animation_tick)
        self._layout_timer.start()

    def _animation_tick(self) -> None:
        """Run a few iterations of the force simulation per timer tick."""
        if not self._nodes or not self._edges:
            if self._layout_timer is not None:
                self._layout_timer.stop()
            return

        iterations_per_tick = 5
        self._anim_iterations += iterations_per_tick

        # Run force simulation iterations
        positions = self._positions
        velocities: dict[str, QPointF] = {k: QPointF(0, 0) for k in positions}

        for _ in range(iterations_per_tick):
            # Repulsion
            for i, n1 in enumerate(self._nodes):
                for j, n2 in enumerate(self._nodes):
                    if i >= j:
                        continue
                    key1, key2 = n1["ip"], n2["ip"]
                    if key1 not in positions or key2 not in positions:
                        continue
                    diff = positions[key1] - positions[key2]
                    dist = diff.manhattanLength()
                    if dist < 1:
                        dist = 1
                    force = 5000 / (dist * dist)
                    direction = diff / dist
                    velocities[key1] = velocities[key1] + direction * force
                    velocities[key2] = velocities[key2] - direction * force

            # Attraction along edges
            for edge in self._edges:
                src = edge.get("source", "")
                tgt = edge.get("target", "")
                tgt_node = tgt.split(":")[0] if ":" in tgt else tgt
                if src not in positions or tgt_node not in positions:
                    continue
                diff = positions[tgt_node] - positions[src]
                dist = diff.manhattanLength()
                if dist < 1:
                    dist = 1
                force = dist * 0.01
                direction = diff / dist
                velocities[src] = velocities[src] + direction * force
                velocities[tgt_node] = velocities[tgt_node] - direction * force

            # Center gravity + damping + apply
            for key in positions:
                center = QPointF(400, 300)
                diff = center - positions[key]
                velocities[key] = velocities[key] + diff * 0.001
                velocities[key] = velocities[key] * 0.9
                positions[key] = positions[key] + velocities[key]

        # Update node positions in the scene
        for item in self._host_items + self._service_items:
            node_data = item.data(0)
            if node_data is not None:
                ip = node_data.get("ip", "")
                if ip in positions:
                    item.setPos(positions[ip])

        # Update vuln ring positions too
        for ring in self._vuln_items:
            ring.setPos(ring.pos())  # keep in sync

        # Stop after ~200 iterations
        if self._anim_iterations >= 200:
            self._layout_timer.stop()
            self._layout_timer = None

    # ── Interaction ────────────────────────────────────────────────────

    def _on_view_clicked(self, event: Any) -> None:  # noqa: N802
        """Handle mouse clicks on the graph view for node selection."""
        item = self._view.itemAt(event.pos())
        if item is not None and isinstance(item, (_HostNode, _ServiceNode)):
            node_data = item.data(0)
            if node_data is not None:
                self._selected_node = node_data
                self._update_detail_panel(node_data)
                # Highlight selected node
                self._clear_selection_highlights()
                item.setPen(QPen(QColor("#f9e2af"), 3))
        else:
            self._selected_node = None
            self._update_detail_panel(None)
            self._clear_selection_highlights()

        # Pass through to default handling
        QGraphicsView.mousePressEvent(self._view, event)

    def _clear_selection_highlights(self) -> None:
        """Remove highlight borders from all nodes."""
        for item in self._host_items + self._service_items:
            node_data = item.data(0)
            if node_data is not None and node_data.get("type") == "host":
                item.setPen(QPen(QColor("#45475a"), 2))
            elif node_data is not None and node_data.get("type") == "service":
                item.setPen(QPen(QColor("#45475a"), 1))

    def _update_detail_panel(self, node: dict[str, Any] | None) -> None:
        """Update the detail panel with the selected node's information."""
        if self._detail_label is None:
            return
        if node is None:
            self._detail_label.setText("Click a node to inspect")
            return

        node_type = node.get("type", "host")
        ip = node.get("ip", "N/A")
        label = node.get("label", ip)
        hostnames = node.get("hostnames", [])
        ports = node.get("ports", [])
        os_info = node.get("os", "")
        status = node.get("status", "unknown")
        vuln = node.get("vuln", "")

        # Build HTML detail
        html = f'<h3 style="color:#89b4fa;margin:0 0 4px 0;">{label}</h3>'
        html += f'<p style="margin:2px 0;color:#cdd6f4;"><b>Type:</b> {node_type}<br>'
        html += f'<b>IP:</b> {ip}<br>'
        if hostnames and hostnames != [label]:
            html += f'<b>Hostnames:</b> {", ".join(hostnames)}<br>'
        if os_info:
            html += f'<b>OS:</b> {os_info}<br>'
        html += f'<b>Status:</b> {status}'
        if vuln:
            html += f' <span style="color:#f38ba8;">⚠ CRITICAL</span>'
        html += '</p>'

        if ports:
            html += '<h4 style="color:#a6adc8;margin:6px 0 2px 0;">Ports</h4>'
            html += '<table style="color:#cdd6f4;font-size:11px;border-collapse:collapse;">'
            html += '<tr><th style="padding:2px 6px;text-align:left;color:#89b4fa;">Port</th>'
            html += '<th style="padding:2px 6px;text-align:left;color:#89b4fa;">Proto</th>'
            html += '<th style="padding:2px 6px;text-align:left;color:#89b4fa;">Service</th>'
            html += '<th style="padding:2px 6px;text-align:left;color:#89b4fa;">Product</th>'
            html += '<th style="padding:2px 6px;text-align:left;color:#89b4fa;">Vuln</th></tr>'
            for p in ports:
                vuln_flag = f' <span style="color:#f38ba8;">⚠ {p.get("vuln", "")}</span>' if p.get("vuln") else ""
                html += f'<tr><td style="padding:1px 6px;">{p.get("port", "")}</td>'
                html += f'<td style="padding:1px 6px;">{p.get("protocol", "")}</td>'
                html += f'<td style="padding:1px 6px;">{p.get("service", "")}</td>'
                html += f'<td style="padding:1px 6px;">{p.get("product", "")} {p.get("version", "")}</td>'
                html += f'<td style="padding:1px 6px;">{vuln_flag}</td></tr>'
            html += '</table>'

        self._detail_label.setText(html)

    def _on_wheel(self, event: Any) -> None:  # noqa: N802
        """Handle mouse wheel for zoom in/out."""
        zoom_factor = 1.15
        if event.angleDelta().y() > 0:
            self._view.scale(zoom_factor, zoom_factor)  # type: ignore[union-attr]
        else:
            self._view.scale(1 / zoom_factor, 1 / zoom_factor)  # type: ignore[union-attr]

    def _on_context_menu(self, pos: Any) -> None:
        """Right-click context menu for zoom and export."""
        menu = QMenu(self)
        menu.addAction("🔍 Zoom In", lambda: self._view.scale(1.3, 1.3))
        menu.addAction("🔍 Zoom Out", lambda: self._view.scale(0.7, 0.7))
        menu.addAction("📐 Reset View", lambda: self._view.fitInView(
            self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio))
        menu.addSeparator()
        menu.addAction("💾 Export PNG", self._on_export_png)
        menu.exec(self._view.viewport().mapToGlobal(pos))

    def _on_export_png(self) -> None:
        """Export the current graph view as a PNG image."""
        if self._scene is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Graph", str(OUTDIR / "recon_graph.png"), "PNG Image (*.png)",
        )
        if not path:
            return
        try:
            img = QImage(
                int(self._scene.sceneRect().width()),
                int(self._scene.sceneRect().height()),
                QImage.Format.Format_ARGB32,
            )
            img.fill(QColor("#1e1e2e"))
            painter = QPainter(img)
            self._scene.render(painter)
            painter.end()
            img.save(path)
            self._status_label.setText(f"Exported to {path}")
        except Exception as exc:
            QMessageBox.warning(self, "Export Error", str(exc))

    # ── Activation ─────────────────────────────────────────────────────

    def on_activate(self) -> None:
        """Refresh the graph when the page becomes visible."""
        if self._nodes and self._scene is not None:
            self._render_graph()
            self._start_animation()