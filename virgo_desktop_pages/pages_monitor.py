"""Virgo Desktop pages — monitor (split from the monolith)."""
from __future__ import annotations

from .base import *  # noqa: F401,F403 — shared Qt imports + helpers
from .base import HERE, OUTDIR, icon, _beep, _set_layout_visible
from .base import _StopStream, _GuiStream  # noqa: F401



# ═══════════════════════════════════════════════════════════════════════
# Network Scanner page
# ═══════════════════════════════════════════════════════════════════════


class NetworkPage(PageWidget):
    """Recon Dashboard + Attack Surface Map — device discovery, port scan, topology."""

    def __init__(self) -> None:
        super().__init__(
            "Recon",
            "Device discovery, port scanning & attack surface visualization.",
        )

        # ── Controls ──
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("Target:"))
        self.subnet_input = QLineEdit("192.168.1.0/24")
        self.subnet_input.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; padding: 5px 8px; color: #cdd6f4; }"
        )
        self.subnet_input.setFixedWidth(150)
        ctrl_row.addWidget(self.subnet_input)
        self.scan_btn = QPushButton("🔍  Scan")
        self.scan_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 5px 14px; color: #cdd6f4; }"
            "QPushButton:hover { border-color: #89b4fa; }"
        )
        self.scan_btn.clicked.connect(self._scan)
        ctrl_row.addWidget(self.scan_btn)
        self.auto_cb = QCheckBox("Auto (30s)")
        self.auto_cb.setStyleSheet("color: #a6adc8;")
        self.auto_cb.toggled.connect(self._toggle_auto)
        ctrl_row.addWidget(self.auto_cb)
        self.export_btn = QPushButton("💾  Export")
        self.export_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 5px 10px; color: #cdd6f4; font-size: 11px; }"
        )
        self.export_btn.clicked.connect(self._export)
        ctrl_row.addWidget(self.export_btn)
        ctrl_row.addStretch()
        self.content.addLayout(ctrl_row)

        # ── Tab widget: Devices | Topology | Port Scanner ──
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #313244; border-radius: 6px; "
            "background: #1e1e2e; }"
            "QTabBar::tab { background: #181825; border: 1px solid #313244; "
            "border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; "
            "padding: 6px 14px; margin-right: 2px; color: #6c7086; }"
            "QTabBar::tab:selected { background: #313244; color: #89b4fa; font-weight: bold; }"
            "QTabBar::tab:hover { color: #cdd6f4; }"
        )

        # ── Tab 1: Recon Dashboard (device cards / table) ──
        dev_tab = QWidget()
        dev_lo = QVBoxLayout(dev_tab)
        dev_lo.setContentsMargins(8, 8, 8, 8)

        self._device_table = QTableWidget(0, 5)
        self._device_table.setHorizontalHeaderLabels(["IP", "Hostname", "MAC", "Vendor", "Status"])
        self._device_table.setAlternatingRowColors(True)
        self._device_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._device_table.verticalHeader().setVisible(False)
        self._device_table.horizontalHeader().setStretchLastSection(True)
        self._device_table.setColumnWidth(0, 130)
        self._device_table.setColumnWidth(1, 150)
        self._device_table.setColumnWidth(2, 140)
        self._device_table.setStyleSheet(
            "QTableWidget { background: #1e1e2e; border: none; border-radius: 6px; "
            "color: #cdd6f4; gridline-color: #313244; font-size: 12px; }"
            "QTableWidget::item { padding: 4px 8px; }"
            "QHeaderView::section { background: #181825; border: 1px solid #313244; "
            "padding: 6px; color: #a6adc8; font-weight: bold; }"
        )
        dev_lo.addWidget(self._device_table)

        self._device_count = QLabel("0 devices")
        self._device_count.setStyleSheet("color: #a6adc8; font-size: 12px; padding: 2px;")
        dev_lo.addWidget(self._device_count)
        self._tabs.addTab(dev_tab, "📋  Devices")

        # ── Tab 2: Attack Surface Map (topology graph) ──
        topo_tab = QWidget()
        topo_lo = QVBoxLayout(topo_tab)
        topo_lo.setContentsMargins(8, 8, 8, 8)

        self._topo_scene = QGraphicsScene()
        self._topo_view = QGraphicsView(self._topo_scene)
        self._topo_view.setMinimumHeight(300)
        self._topo_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._topo_view.setStyleSheet("background: #11111b; border: none; border-radius: 6px;")
        topo_lo.addWidget(self._topo_view)

        topo_info = QLabel("Devices discovered by scan appear as nodes. Edges show connectivity.")
        topo_info.setStyleSheet("color: #6c7086; font-size: 11px; padding: 2px;")
        topo_lo.addWidget(topo_info)
        self._tabs.addTab(topo_tab, "🗺️  Topology")

        # ── Tab 3: Port Scanner ──
        port_tab = QWidget()
        port_lo = QVBoxLayout(port_tab)
        port_lo.setContentsMargins(8, 8, 8, 8)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Host:"))
        self.port_host = QLineEdit("localhost")
        self.port_host.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; padding: 5px 8px; color: #cdd6f4; }"
        )
        self.port_host.setFixedWidth(150)
        port_row.addWidget(self.port_host)
        port_row.addWidget(QLabel("Ports:"))
        self.port_range = QLineEdit("80,443,22,8080,11434,5432,3306")
        self.port_range.setStyleSheet(
            "QLineEdit { background: #181825; border: 1px solid #313244; "
            "border-radius: 6px; padding: 5px 8px; color: #cdd6f4; }"
        )
        port_row.addWidget(self.port_range, 1)

        self.port_scan_btn = QPushButton("🔍  Scan ports")
        self.port_scan_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 5px 14px; color: #cdd6f4; }"
            "QPushButton:hover { border-color: #f38ba8; }"
        )
        self.port_scan_btn.clicked.connect(self._scan_ports)
        port_row.addWidget(self.port_scan_btn)
        port_lo.addLayout(port_row)

        self.port_results = QListWidget()
        self.port_results.setStyleSheet(
            "QListWidget { background: #1e1e2e; border: 1px solid #313244; "
            "border-radius: 6px; color: #cdd6f4; }"
            "QListWidget::item { padding: 4px 8px; }"
        )
        port_lo.addWidget(self.port_results, 1)
        self._tabs.addTab(port_tab, "🔌  Ports")

        self._add(self._tabs)

        # ── Status bar ──
        self._status = QLabel("Ready. Enter a subnet and scan.")
        self._status.setStyleSheet("color: #6c7086; font-size: 12px;")
        self.content.addWidget(self._status)

        # ── State ──
        self._devices: list[dict] = []
        self._timer = QTimer()
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self._scan)

    # ── Recon scan ──────────────────────────────────────────────────────

    def _toggle_auto(self, on: bool) -> None:
        if on:
            self._scan()
            self._timer.start()
        else:
            self._timer.stop()

    def _scan(self) -> None:
        self._status.setText("Scanning...")
        self.scan_btn.setEnabled(False)

        def _run() -> None:
            devices = []
            try:
                from virgo_network_scanner import scan_subnet
                raw = scan_subnet(self.subnet_input.text())
                for d in (raw or []):
                    if hasattr(d, "_asdict"):
                        devices.append(d._asdict())
                    elif isinstance(d, dict):
                        devices.append(d)
                    else:
                        devices.append({"ip": str(d), "hostname": "", "mac": "", "vendor": "", "status": "up"})
            except Exception as exc:
                devices = [{"ip": f"Error: {exc}", "hostname": "", "mac": "", "vendor": "", "status": "error"}]
            QMetaObject.invokeMethod(
                self, "_show_results", Qt.ConnectionType.QueuedConnection,
                Q_ARG(list, devices),
            )

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot(list)
    def _show_results(self, devices: list[dict]) -> None:
        self._devices = devices
        self._device_table.setRowCount(len(devices))
        for row, d in enumerate(devices):
            ip = d.get("ip", "?")
            host = d.get("hostname", "") or d.get("host", "")
            mac = d.get("mac", "")
            vendor = d.get("vendor", "")
            status = d.get("status", "up")

            ip_item = QTableWidgetItem(ip)
            ip_item.setForeground(QColor("#89b4fa"))
            self._device_table.setItem(row, 0, ip_item)
            self._device_table.setItem(row, 1, QTableWidgetItem(host))
            self._device_table.setItem(row, 2, QTableWidgetItem(mac))
            self._device_table.setItem(row, 3, QTableWidgetItem(vendor))

            st_item = QTableWidgetItem(status)
            st_item.setForeground(QColor("#a6e3a1" if status == "up" else "#f38ba8"))
            self._device_table.setItem(row, 4, st_item)

        self._device_count.setText(f"{len(devices)} device(s)")
        self._status.setText(f"Found {len(devices)} device(s)")
        self.scan_btn.setEnabled(True)
        self._build_topology()

    # ── Attack Surface Map (topology) ──────────────────────────────────

    def _build_topology(self) -> None:
        """Render discovered devices as a visual network graph."""
        self._topo_scene.clear()
        if not self._devices:
            txt = self._topo_scene.addText("No devices — run a scan first")
            txt.setDefaultTextColor(QColor("#6c7086"))
            return

        import math
        n = len(self._devices)
        cx, cy, radius = 250, 180, 140
        node_w, node_h = 100, 36

        self._topo_nodes: list[dict] = []
        for i, d in enumerate(self._devices):
            angle = (2 * math.pi * i) / n - math.pi / 2
            x = cx + radius * math.cos(angle) - node_w // 2
            y = cy + radius * math.sin(angle) - node_h // 2

            # Node rect
            ip = d.get("ip", f"device_{i}")
            rect = QGraphicsRectItem(x, y, node_w, node_h)
            rect.setBrush(QBrush(QColor("#181825")))
            rect.setPen(QPen(QColor("#89b4fa"), 1.5))
            rect.setFlags(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable)
            self._topo_scene.addItem(rect)

            # IP label
            label = QGraphicsTextItem(ip, rect)
            label.setPos(x + 6, y + 8)
            label.setDefaultTextColor(QColor("#cdd6f4"))
            f = QFont("Segoe UI", 8, QFont.Weight.Bold)
            label.setFont(f)

            self._topo_nodes.append({"rect": rect, "ip": ip})

        # Draw edges between consecutive devices (star topology)
        for i in range(n - 1):
            n1 = self._topo_nodes[i]
            n2 = self._topo_nodes[i + 1]
            r1 = n1["rect"]
            r2 = n2["rect"]
            x1 = r1.rect().center().x() + r1.pos().x()
            y1 = r1.rect().center().y() + r1.pos().y()
            x2 = r2.rect().center().x() + r2.pos().x()
            y2 = r2.rect().center().y() + r2.pos().y()
            self._topo_scene.addLine(x1, y1, x2, y2, QPen(QColor("#45475a"), 1, Qt.PenStyle.DashLine))

        self._topo_scene.setSceneRect(0, 0, 500, 400)

    # ── Port scanner ────────────────────────────────────────────────────

    def _scan_ports(self) -> None:
        host = self.port_host.text().strip()
        ports: list[int] = []
        for part in self.port_range.text().split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-")
                ports.extend(range(int(a), int(b) + 1))
            elif part.isdigit():
                ports.append(int(part))
        if not host or not ports:
            return
        self.port_scan_btn.setEnabled(False)
        self.port_results.clear()

        def _run() -> None:
            import socket
            open_ports: list[int] = []
            for port in ports:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(0.5)
                        if s.connect_ex((host, port)) == 0:
                            open_ports.append(port)
                except Exception:
                    pass
            QMetaObject.invokeMethod(
                self, "_show_ports", Qt.ConnectionType.QueuedConnection,
                Q_ARG(list, open_ports), Q_ARG(list, ports),
            )

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot(list, list)
    def _show_ports(self, open_ports: list, all_ports: list) -> None:
        self.port_results.clear()
        for port in all_ports:
            is_open = int(port) in open_ports
            item = QListWidgetItem(f"  {'🔓' if is_open else '🔒'}  Port {port}  {'OPEN' if is_open else 'closed'}")
            if is_open:
                item.setForeground(QColor("#a6e3a1"))
            else:
                item.setForeground(QColor("#6c7086"))
            self.port_results.addItem(item)
        self.port_scan_btn.setEnabled(True)
        self._status.setText(f"Port scan: {len(open_ports)}/{len(all_ports)} open")

    def _export(self) -> None:
        if not self._devices:
            self._status.setText("Nothing to export yet.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export devices", "network-scan.csv", "CSV (*.csv)"
        )
        if not path:
            return
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["ip", "hostname", "mac", "vendor", "status"])
            w.writeheader()
            w.writerows(self._devices)
        self._status.setText(f"Exported {len(self._devices)} device(s)")


# ═══════════════════════════════════════════════════════════════════════
# Diagnostics page
# ═══════════════════════════════════════════════════════════════════════


class DiagnosticsPage(PageWidget):
    """Live system health — CPU, RAM, disk, network, services, processes."""

    def __init__(self) -> None:
        super().__init__(
            "System Health",
            "Live CPU, memory, disk, network & service monitoring.",
        )

        self._timer = QTimer()
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self._refresh)

        # ── Controls ──
        ctrl_row = QHBoxLayout()
        refresh_btn = QPushButton("🔄  Refresh")
        refresh_btn.setStyleSheet(
            "QPushButton { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 6px 14px; color: #cdd6f4; }"
            "QPushButton:hover { border-color: #89b4fa; }"
        )
        refresh_btn.clicked.connect(self._refresh)
        ctrl_row.addWidget(refresh_btn)
        self._auto_cb = QCheckBox("Auto (5s)")
        self._auto_cb.setStyleSheet("color: #a6adc8;")
        self._auto_cb.toggled.connect(self._toggle_auto)
        ctrl_row.addWidget(self._auto_cb)
        ctrl_row.addStretch()
        self.content.addLayout(ctrl_row)

        # ── Stats grid: CPU, RAM, DISK ──
        gauges = QHBoxLayout()
        gauges.setSpacing(16)
        self._gauges: dict[str, QProgressBar] = {}
        for name, icon, color in [
            ("CPU", "⚡", "#89b4fa"),
            ("RAM", "🅂", "#a6e3a1"),
            ("DISK C:", "💾", "#f9e2af"),
        ]:
            box = QWidget()
            box.setStyleSheet(
                "background: #181825; border: 1px solid #313244; "
                "border-radius: 8px; padding: 12px;"
            )
            bl = QVBoxLayout(box)
            bl.setSpacing(6)
            bl.addWidget(QLabel(f"{icon}  {name}"))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            bar.setFixedHeight(22)
            bar.setStyleSheet(f"""
                QProgressBar {{ background: #11111b; border: none; border-radius: 4px;
                    text-align: center; color: #cdd6f4; font-size: 11px; }}
                QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}
            """)
            bl.addWidget(bar)
            gauges.addWidget(box, 1)
            self._gauges[name] = bar
        self.content.addLayout(gauges)

        # ── Network + Services row ──
        info_row = QHBoxLayout()
        info_row.setSpacing(16)

        # Network panel
        net_group = self._section("Network")
        self._net_labels: list[QLabel] = []
        self._net_container = QVBoxLayout()
        net_group.layout().addLayout(self._net_container)  # type: ignore
        info_row.addWidget(net_group, 1)

        # Services panel
        svc_group = self._section("Services")
        self._svc_labels: dict[str, QLabel] = {}
        for svc in ["Ollama", "Ollama Models"]:
            row = QHBoxLayout()
            lbl = QLabel(f"  ○  {svc}")
            lbl.setStyleSheet("color: #a6adc8; font-size: 12px;")
            row.addWidget(lbl)
            self._svc_labels[svc] = lbl
            svc_group.layout().addLayout(row)  # type: ignore
        info_row.addWidget(svc_group, 1)
        self.content.addLayout(info_row)

        # ── Process table ──
        proc_group = self._section("Top Processes")
        self._proc_table = QTableWidget(0, 4)
        self._proc_table.setHorizontalHeaderLabels(["PID", "Name", "Mem %", "CPU %"])
        self._proc_table.setAlternatingRowColors(True)
        self._proc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._proc_table.verticalHeader().setVisible(False)
        self._proc_table.horizontalHeader().setStretchLastSection(True)
        self._proc_table.setStyleSheet(
            "QTableWidget { background: #1e1e2e; border: none; border-radius: 6px; "
            "color: #cdd6f4; gridline-color: #313244; font-size: 11px; }"
            "QTableWidget::item { padding: 2px 6px; }"
            "QHeaderView::section { background: #181825; border: 1px solid #313244; "
            "padding: 4px; color: #a6adc8; font-weight: bold; }"
        )
        self._proc_table.setMinimumHeight(200)
        proc_group.layout().addWidget(self._proc_table)  # type: ignore
        self._add(proc_group)

        # ── Last update timestamp ──
        self._ts_label = QLabel("")
        self._ts_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        self.content.addWidget(self._ts_label)

        self._refresh()

    def on_activate(self) -> None:
        if self._auto_cb.isChecked():
            self._timer.start()

    def _toggle_auto(self, on: bool) -> None:
        if on:
            self._refresh()
            self._timer.start()
        else:
            self._timer.stop()

    def _refresh(self) -> None:
        """Fetch latest stats and update all widgets."""
        try:
            from virgo_diagnostics import get_system_stats
            stats = get_system_stats()

            # CPU gauge
            cpu_pct = stats.get("cpu", {}).get("percent", 0) or 0
            self._gauges["CPU"].setValue(int(cpu_pct))
            freq = stats.get("cpu", {}).get("freq_mhz")
            freq_str = f" @ {freq}MHz" if freq else ""
            self._gauges["CPU"].setFormat(f"CPU  {cpu_pct:.0f}%  ({stats['cpu'].get('count', '?')} cores{freq_str})")

            # RAM gauge
            mem = stats.get("memory", {})
            if mem:
                self._gauges["RAM"].setValue(int(mem["percent"]))
                self._gauges["RAM"].setFormat(f"RAM  {mem['percent']:.0f}%  ({mem['used_gb']}/{mem['total_gb']} GB)")

            # Disk gauge
            disks = stats.get("disk", [])
            if disks:
                d = disks[0]
                self._gauges["DISK C:"].setValue(int(d["percent"]))
                self._gauges["DISK C:"].setFormat(f"{d['mount']}  {d['percent']:.0f}%  ({d['used_gb']}/{d['total_gb']} GB)")

            # Network
            for i in reversed(range(self._net_container.count())):
                w = self._net_container.itemAt(i)
                if w and w.widget():
                    w.widget().deleteLater()
            for iface in stats.get("network", [])[:5]:
                lbl = QLabel(f"  🌐  {iface['interface']}:  {iface['ip']}")
                lbl.setStyleSheet("color: #a6adc8; font-size: 12px;")
                self._net_container.addWidget(lbl)
            if not stats.get("network"):
                self._net_container.addWidget(QLabel("  (no network info)"))

            # Services
            services = stats.get("services", {})
            for svc, lbl in self._svc_labels.items():
                if svc == "Ollama":
                    status = services.get("Ollama", "unknown")
                    icon = "🟢" if status == "running" else ("🟡" if status == "checking" else "🔴")
                    lbl.setText(f"  {icon}  Ollama: {status}")
                elif svc == "Ollama Models":
                    models = stats.get("ollama", {}).get("models", [])
                    count = stats.get("ollama", {}).get("model_count", 0)
                    lbl.setText(f"  🧠  {count} model(s): {', '.join(models[:3])}{'...' if count > 3 else ''}")

            # Processes
            self._proc_table.setRowCount(0)
            for proc in stats.get("processes", [])[:10]:
                r = self._proc_table.rowCount()
                self._proc_table.insertRow(r)
                self._proc_table.setItem(r, 0, QTableWidgetItem(str(proc["pid"])))
                self._proc_table.setItem(r, 1, QTableWidgetItem(proc["name"]))
                mt = QTableWidgetItem(f"{proc['mem_pct']:.1f}")
                mt.setForeground(QColor("#a6e3a1"))
                self._proc_table.setItem(r, 2, mt)
                ct = QTableWidgetItem(f"{proc['cpu_pct']:.1f}")
                ct.setForeground(QColor("#89b4fa"))
                self._proc_table.setItem(r, 3, ct)

            self._ts_label.setText(f"Last updated: {stats['timestamp']}")

        except Exception as exc:
            self._ts_label.setText(f"Error: {exc}")


# ═══════════════════════════════════════════════════════════════════════
# Alerts page
# ═══════════════════════════════════════════════════════════════════════


class AlertsPage(PageWidget):
    """Alert evaluation and history."""

    def __init__(self) -> None:
        super().__init__(
            "Alerts",
            "Threshold-based alert evaluation from diagnostics & network data.",
        )

        self._add_row(
            QPushButton(f"{icon('run')}  Evaluate Alerts", clicked=self._evaluate),
            QPushButton(f"{icon('fix')}  Run Fixer", clicked=self._run_fixer),
            QPushButton(f"{icon('delete')}  Clear Alerts", clicked=self._clear),
        )
        self.auto_cb = QCheckBox("Auto (30s)")
        self.auto_cb.toggled.connect(self._toggle_auto)
        self._add_row(self.auto_cb)

        self.alerts_list = QListWidget()
        self._add(self.alerts_list)
        self.status = QLabel("No alerts evaluated yet.")

        self._timer = QTimer()
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self._evaluate)

        self._last_alerts = ""
        self._add(self.status)

    def _toggle_auto(self, on: bool) -> None:
        if on:
            self._evaluate()
            self._timer.start()
        else:
            self._timer.stop()

    def _run_fixer(self) -> None:
        self.status.setText("Running fixer...")
        try:
            from virgo_fixer import fix_all

            fix_all()
            self.status.setText(f"{icon('ok')} Fixer finished")
        except Exception as exc:
            self.status.setText(f"Fixer error: {exc}")
        self._evaluate()

    def _evaluate(self) -> None:
        self.alerts_list.clear()
        self.status.setText("Evaluating...")

        def _run() -> None:
            try:
                from virgo_alerts import check_thresholds

                check_thresholds()
            except Exception as exc:
                lines = [f"Error: {exc}"]
            else:
                lines = []
                alert_path = OUTDIR / "ALERTS_TRIGGERED.txt"
                if alert_path.exists():
                    lines = alert_path.read_text().strip().split("\n")
                if not lines:
                    lines = ["System clear — no alerts triggered."]
            QMetaObject.invokeMethod(
                self,
                "_show_alerts",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, "\n".join(lines)),
            )

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot(str)
    def _show_alerts(self, text: str) -> None:
        self.alerts_list.clear()
        for line in text.split("\n"):
            self.alerts_list.addItem(line)
        self.status.setText(
            f"{self.alerts_list.count()} alert(s)" if self.alerts_list.count() else "No alerts"
        )
        # Live alert: tray-notify only when the alert set CHANGES and is non-empty
        is_clear = "no alerts triggered" in text.lower()
        changed = text != self._last_alerts
        self._last_alerts = text
        if changed and not is_clear and self.alerts_list.count():
            first = next((l for l in text.split("\n") if l.strip()), "alerts triggered")
            w = self.window()
            if w is not None and hasattr(w, "_notify_tray"):
                w._notify_tray(
                    f"⚠ {self.alerts_list.count()} Virgo alert(s)",
                    first[:140],
                    critical="critical" in first.lower() or "critical" in text.lower(),
                )

    def _clear(self) -> None:
        self.alerts_list.clear()
        self.status.setText("Cleared")
        alert_path = OUTDIR / "ALERTS_TRIGGERED.txt"
        if alert_path.exists():
            alert_path.unlink()


# ═══════════════════════════════════════════════════════════════════════
# Notifications centre
# ═══════════════════════════════════════════════════════════════════════

_SEV_COLORS = {
    "critical": "#f38ba8",
    "warning": "#f9e2af",
    "info": "#a6adc8",
}


class NotificationsPage(PageWidget):
    """Aggregated alerts / diagnostics / network / activity feed with toasts."""

    def __init__(self) -> None:
        super().__init__(
            "Notifications",
            "Alerts, diagnostics findings, network scans and activity events — "
            "aggregated into one feed with desktop toasts.",
        )

        self._add_row(
            QPushButton(f"{icon('refresh')}  Scan now", clicked=self.scan),
            QPushButton("✓  Mark all read", clicked=self._mark_all_read),
            QPushButton(f"{icon('delete')}  Clear feed", clicked=self._clear_feed),
        )
        self.auto_cb = QCheckBox("Auto-scan (30s)")
        self.auto_cb.toggled.connect(self._toggle_auto)
        self._add_row(self.auto_cb)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._mark_one_read)
        self._add(self.list)

        self.status = QLabel("No notifications yet — run a scan to collect events.")
        self._add(self.status)

        self._timer = QTimer()
        self._timer.setInterval(30000)
        self._timer.timeout.connect(self.scan)

        # Guard against stale background scans re-adding cleared items.
        self._scan_token = 0

        try:
            from virgo_notifications import store
        except Exception:
            store = None
        self._store = store

    def _toggle_auto(self, on: bool) -> None:
        if on:
            self.scan()
            self._timer.start()
        else:
            self._timer.stop()

    def on_activate(self) -> None:
        self.scan()

    def scan(self) -> None:
        """Scan all sources in a worker thread, then refresh the list."""
        if self._store is None:
            self.status.setText("Notification store unavailable.")
            return
        self._scan_token += 1
        token = self._scan_token

        def _run() -> None:
            err = ""
            try:
                new = self._store.scan_all()
                items = self._store.all()
            except Exception as exc:
                new, items, err = [], [], str(exc)
            QMetaObject.invokeMethod(
                self,
                "_finish_scan",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(int, token),
                Q_ARG(str, json.dumps(new)),
                Q_ARG(str, json.dumps(items)),
                Q_ARG(str, err),
            )

        threading.Thread(target=_run, daemon=True).start()

    @pyqtSlot(int, str, str, str)
    def _finish_scan(self, token: int, new_json: str, items_json: str, err: str) -> None:
        # A newer scan or a clear has since started — drop this stale result.
        if token != self._scan_token:
            return
        if err:
            self.status.setText(f"Scan error: {err}")
            return
        try:
            new = json.loads(new_json)
            items = json.loads(items_json)
        except Exception:
            new, items = [], []
        # Toast the newest warning/critical items (cap to avoid spam).
        win = self.window()
        for n in reversed(new[-3:]):
            if n.get("severity") not in ("warning", "critical"):
                continue
            title = f"Virgo · {n.get('source', 'event')}: {n.get('title', '')}"
            msg = str(n.get("message", ""))[:160]
            if hasattr(win, "notify"):
                try:
                    win.notify(title, msg)
                except Exception:
                    pass
            if n.get("severity") == "critical":
                _beep("error")
        self._render(items)
        unread = sum(1 for n in items if not n.get("read"))
        self.status.setText(
            f"{len(items)} notification(s) · {unread} unread"
            + (f" · +{len(new)} new" if new else "")
        )

    def _render(self, items: list[dict]) -> None:
        self.list.clear()
        for n in reversed(items):
            sev = n.get("severity", "info")
            color = _SEV_COLORS.get(sev, "#a6adc8")
            read_mark = "" if n.get("read") else "● "
            ts = str(n.get("ts", ""))[:19]
            label = (
                f"{read_mark}[{sev.upper()}] {ts}  {n.get('source', '?')} — "
                f"{n.get('title', '')}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, n.get("id"))
            item.setToolTip(str(n.get("message", "")))
            f = item.font()
            f.setBold(not n.get("read"))
            item.setFont(f)
            item.setForeground(QBrush(QColor(color)))
            self.list.addItem(item)

    def _mark_one_read(self, item: QListWidgetItem) -> None:
        if self._store is None:
            return
        nid = item.data(Qt.ItemDataRole.UserRole)
        if nid:
            self._store.mark_read(int(nid))
            self.scan()

    def _mark_all_read(self) -> None:
        if self._store is None:
            return
        self._store.mark_all_read()
        self.scan()

    def _clear_feed(self) -> None:
        if self._store is None:
            return
        self._scan_token += 1  # invalidate any in-flight scan
        self._store.clear()
        self.list.clear()
        self.status.setText("Feed cleared.")


# ═══════════════════════════════════════════════════════════════════════
# Scaffold page
# ═══════════════════════════════════════════════════════════════════════


