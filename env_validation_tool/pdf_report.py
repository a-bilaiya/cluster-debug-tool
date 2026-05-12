"""PDF report generation using fpdf2.

Usage as library:
    from env_validation_tool.pdf_report import generate_pdf_report
    generate_pdf_report(cluster_report, "output.pdf",
                        net_results=[], iperf_results=None)
"""

import time
from fpdf import FPDF

# Colours (R, G, B)
_GREEN = (34, 139, 34)
_RED = (200, 30, 30)
_ORANGE = (210, 130, 0)
_DARK = (40, 40, 40)


def _yn(val):
    """Convert bool/None to Y/N/- for compact table display."""
    if val is True:
        return "Y"
    if val is False:
        return "N"
    return "-"
_HEADER_BG = (30, 60, 114)
_HEADER_FG = (255, 255, 255)
_ROW_ALT = (240, 245, 255)
_WHITE = (255, 255, 255)


def _status_color(status):
    return {"PASS": _GREEN, "FAIL": _RED, "WARN": _ORANGE}.get(status, _DARK)


def _sanitize_text(text):
    """Replace non-latin-1 characters for fpdf2 core fonts."""
    if not isinstance(text, str):
        return str(text)
    replacements = {
        '\u2014': '-', '\u2013': '-', '\u2018': "'", '\u2019': "'",
        '\u201c': '"', '\u201d': '"', '\u2026': '...', '\u2022': '*',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode('latin-1', errors='replace').decode('latin-1')


class _ReportPDF(FPDF):
    """Custom FPDF subclass with header/footer."""

    def __init__(self, cluster_name=""):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.cluster_name = _sanitize_text(cluster_name)
        self.set_auto_page_break(auto=True, margin=18)

    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_DARK)
        self.cell(0, 6, "RVC Environment Validation Report", ln=True)
        self.set_font("Helvetica", "", 8)
        self.cell(0, 4, f"Cluster: {self.cluster_name}", ln=True)
        self.line(self.l_margin, self.get_y() + 1,
                  self.w - self.r_margin, self.get_y() + 1)
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(130, 130, 130)
        self.cell(0, 10,
                  f"Page {self.page_no()}/{{nb}}  |  "
                  f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
                  align="C")

    # ── helpers ──

    def section_title(self, text):
        self.ln(3)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(*_DARK)
        self.cell(0, 8, text, ln=True)
        self.ln(1)

    def table_header(self, cols):
        """cols: list of (label, width)"""
        self.set_fill_color(*_HEADER_BG)
        self.set_text_color(*_HEADER_FG)
        self.set_font("Helvetica", "B", 7)
        for label, w in cols:
            self.cell(w, 6, label, border=1, fill=True, align="C")
        self.ln()
        self.set_text_color(*_DARK)
        self.set_font("Helvetica", "", 7)

    def table_row(self, cols, values, row_idx):
        """Print one row; alternate shading."""
        if row_idx % 2 == 1:
            self.set_fill_color(*_ROW_ALT)
        else:
            self.set_fill_color(*_WHITE)
        for (_, w), val in zip(cols, values):
            self.cell(w, 5, _sanitize_text(str(val)), border=1, fill=True,
                      align="C")
        self.ln()


def generate_pdf_report(cluster_report, output_path,
                        net_results=None, iperf_results=None):
    """Generate a PDF report and write it to *output_path*.

    Parameters match the data structures produced by cli.py.
    """
    cluster_name = cluster_report.get("cluster", "Unknown")
    pdf = _ReportPDF(cluster_name=cluster_name)
    pdf.alias_nb_pages()
    pdf.add_page()

    # ── 1. Cluster Overview ──
    pdf.section_title("1. Cluster Overview")
    pdf.set_font("Helvetica", "", 9)
    vcenter = cluster_report.get("vcenter", "N/A")
    ts = cluster_report.get("collection_time", "N/A")
    host_count = len(cluster_report.get("hosts", []))
    pdf.cell(0, 5, f"vCenter: {vcenter}    |    Hosts: {host_count}    |    "
                    f"Collected: {ts}", ln=True)

    # ── 2. Host Hardware Summary ──
    pdf.section_title("2. Host Hardware Summary")
    hw_cols = [
        ("ESXi IP", 28), ("Service Tag", 22), ("Model", 38),
        ("CPU", 25), ("Cores/Threads", 24), ("Clock GHz", 18),
        ("RAM GB", 16), ("Data Disks", 18), ("OS Disk GB", 18),
        ("AES", 10), ("SSE4.2", 12), ("AVX2", 10), ("uArch", 30),
        ("Result", 16),
    ]
    pdf.table_header(hw_cols)

    for idx, hr in enumerate(cluster_report.get("hosts", [])):
        if hr.get("status") == "error":
            vals = [hr.get("esxi_ip", "?")] + ["ERROR"] * (len(hw_cols) - 1)
            pdf.table_row(hw_cols, vals, idx)
            continue

        ident = hr["host_identity"]
        cpu = hr["cpu_details"]
        feat = hr.get("cpu_features", {})
        data_disks = [d for d in hr["storage"] if d.get("role") == "data"]
        os_disks = [d for d in hr["storage"] if d.get("role") == "os"]
        os_gb = f"{os_disks[0]['capacity_gb']:.0f}" if os_disks else "?"

        checks = hr.get("validation", [])
        fails = sum(1 for c in checks if c["status"] == "FAIL")
        warns = sum(1 for c in checks if c["status"] == "WARN")
        result = f"FAIL({fails})" if fails else (
            f"PASS({warns}w)" if warns else "PASS")

        vals = [
            hr.get("esxi_ip", "?"),
            ident.get("service_tag", "?"),
            ident.get("model", "?")[:22],
            cpu.get("model", "?")[:16],
            f"{cpu.get('cores', '?')}/{cpu.get('threads', '?')}",
            f"{cpu.get('clock_ghz', '?')}",
            f"{int(hr.get('memory_gb', 0))}",
            str(len(data_disks)),
            os_gb,
            "Y" if feat.get("aes") else "N",
            "Y" if feat.get("sse4_2") else "N",
            "Y" if feat.get("avx2") else "N",
            cpu.get("microarchitecture", "?"),
            result,
        ]
        pdf.table_row(hw_cols, vals, idx)

    # ── 3. Per-Host Validation Details ──
    pdf.section_title("3. Validation Details")
    val_cols = [
        ("Check", 70), ("Status", 16),
        ("Actual", 80), ("Expected", 70),
    ]

    for hr in cluster_report.get("hosts", []):
        if hr.get("status") == "error":
            continue
        ip = hr.get("esxi_ip", "?")
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, f"Host: {ip}  [{hr['host_identity']['service_tag']}]",
                 ln=True)
        pdf.table_header(val_cols)
        for ci, c in enumerate(hr.get("validation", [])):
            pdf.set_text_color(*_status_color(c["status"]))
            vals = [
                c.get("check", ""),
                c["status"],
                str(c.get("actual", "")),
                str(c.get("expected", "")),
            ]
            pdf.table_row(val_cols, vals, ci)
            pdf.set_text_color(*_DARK)
        pdf.ln(2)

    # ── 4. Network Performance (if available) ──
    if net_results:
        pdf.section_title("4. Network Performance (Phase 2)")
        net_cols = [
            ("VM Name", 35), ("VM IP", 28), ("Tag", 18),
            ("Ping Avg ms", 20), ("Ping Loss %", 20),
            ("TCP Mbps", 22), ("HTTPS Avg ms", 22),
            ("HTTPS OK", 16),
        ]
        pdf.table_header(net_cols)
        for ni, nr in enumerate(net_results):
            ping = nr.get("ping", {})
            tcp = nr.get("tcp_throughput", {})
            https = nr.get("https_response", {})
            vals = [
                nr.get("node_name", "?")[:22],
                nr.get("node_ip", "?"),
                nr.get("server_tag", "?"),
                f"{ping['rtt_avg_ms']:.2f}" if ping.get("status") == "ok" else "N/A",
                f"{ping.get('packet_loss_pct', 'N/A')}",
                f"{tcp['throughput_mbps']:.1f}" if tcp.get("status") == "ok" else "N/A",
                f"{https['response_avg_ms']:.1f}" if https.get("status") == "ok" else "N/A",
                f"{https.get('successful', 0)}/{https.get('requests', 0)}"
                if https.get("status") == "ok" else "N/A",
            ]
            pdf.table_row(net_cols, vals, ni)

    # ── 5. iperf3 Bandwidth (if available) ──
    if iperf_results and iperf_results.get("status") == "ok":
        pdf.section_title("5. iperf3 Bandwidth Tests (Phase 3)")

        # DevVM → Node
        devvm = iperf_results.get("devvm_node", [])
        if devvm:
            iperf_cols = [
                ("Node", 30), ("IP", 25),
                ("TCP Upload Gbps", 28), ("TCP Download Gbps", 30),
                ("UDP Gbps", 22), ("UDP Jitter ms", 24), ("UDP Loss %", 20),
            ]
            pdf.table_header(iperf_cols)
            for ii, ir in enumerate(devvm):
                tu = ir.get("tcp_upload", {})
                td = ir.get("tcp_download", {})
                udp = ir.get("udp", {})
                vals = [
                    ir.get("node_name", "?")[:20],
                    ir.get("node_ip", "?"),
                    f"{tu['gbps']:.2f}" if tu.get("status") == "ok" else "N/A",
                    f"{td['gbps']:.2f}" if td.get("status") == "ok" else "N/A",
                    f"{udp['gbps']:.2f}" if udp.get("status") == "ok" else "N/A",
                    f"{udp.get('jitter_ms', 0):.3f}" if udp.get("status") == "ok" else "N/A",
                    f"{udp.get('loss_pct', 0):.2f}" if udp.get("status") == "ok" else "N/A",
                ]
                pdf.table_row(iperf_cols, vals, ii)

        # Node-to-Node
        n2n = iperf_results.get("node_to_node", [])
        if n2n:
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(0, 5, "Node-to-Node Bandwidth", ln=True)
            n2n_cols = [
                ("Source", 30), ("Destination", 30),
                ("Gbps", 22), ("Retransmits", 22), ("Status", 16),
            ]
            pdf.table_header(n2n_cols)
            for ti, t in enumerate(n2n):
                vals = [
                    t.get("src", "?"),
                    t.get("dst", "?"),
                    f"{t['gbps']:.2f}" if t.get("status") == "ok" else "N/A",
                    str(t.get("retransmits", 0)),
                    t.get("status", "?"),
                ]
                pdf.table_row(n2n_cols, vals, ti)

    # ── 6. Overall Result ──
    pdf.section_title("6. Overall Result")
    total_fail = 0
    total_warn = 0
    for hr in cluster_report.get("hosts", []):
        for c in hr.get("validation", []):
            if c["status"] == "FAIL":
                total_fail += 1
            elif c["status"] == "WARN":
                total_warn += 1

    pdf.set_font("Helvetica", "B", 14)
    if total_fail == 0 and total_warn == 0:
        pdf.set_text_color(*_GREEN)
        pdf.cell(0, 10, "ALL CHECKS PASSED", ln=True, align="C")
    elif total_fail == 0:
        pdf.set_text_color(*_ORANGE)
        pdf.cell(0, 10, f"PASSED with {total_warn} warning(s)", ln=True,
                 align="C")
    else:
        pdf.set_text_color(*_RED)
        pdf.cell(0, 10, f"{total_fail} FAILED  |  {total_warn} warning(s)",
                 ln=True, align="C")
    pdf.set_text_color(*_DARK)

    # Write file
    pdf.output(output_path)
    return output_path


def generate_troubleshoot_pdf(cluster_report, output_path):
    """Generate a standalone troubleshoot PDF report.

    Separate from the environment validation PDF — contains only
    runtime diagnostics (host state, alarms, I/O, sensors, etc.).
    """
    cluster_name = cluster_report.get("cluster", "Unknown")
    pdf = _ReportPDF(cluster_name=cluster_name)
    pdf.alias_nb_pages()
    pdf.add_page()

    # Title
    pdf.section_title("RVC Troubleshoot Report")
    pdf.set_font("Helvetica", "", 9)
    vcenter = cluster_report.get("vcenter", "N/A")
    ts = cluster_report.get("collection_time", "N/A")
    host_count = sum(
        1 for hr in cluster_report.get("hosts", [])
        if hr.get("status") != "error"
    )
    pdf.cell(0, 5, f"vCenter: {vcenter}    |    Hosts: {host_count}    |    "
                    f"Collected: {ts}", ln=True)

    # Render troubleshoot sections for each host
    for hr in cluster_report.get("hosts", []):
        if hr.get("status") == "error":
            continue
        ts_data = hr.get("troubleshoot")
        if not ts_data:
            continue

        ip = hr.get("esxi_ip", "?")
        tag = hr.get("host_identity", {}).get("service_tag", "?")

        pdf.add_page()
        pdf.section_title(f"Host: {ip}  [{tag}]")

        _ts_pdf_health_summary(pdf, ts_data)
        _ts_pdf_state_capacity(pdf, ts_data)
        _ts_pdf_system_info(pdf, ts_data)
        _ts_pdf_alarms(pdf, ts_data)
        _ts_pdf_vm_details(pdf, ts_data)
        _ts_pdf_resource_alloc(pdf, ts_data)
        _ts_pdf_overcommit(pdf, ts_data)
        _ts_pdf_hardware_health(pdf, ts_data)
        _ts_pdf_performance(pdf, ts_data)
        _ts_pdf_vm_contention(pdf, ts_data)
        _ts_pdf_io_stats(pdf, ts_data)
        _ts_pdf_datastore_io(pdf, ts_data)
        _ts_pdf_network_config(pdf, ts_data)
        _ts_pdf_storage_config(pdf, ts_data)
        _ts_pdf_services(pdf, ts_data)
        _ts_pdf_events(pdf, ts_data)
        _ts_pdf_pci_devices(pdf, ts_data)
        _ts_pdf_firewall(pdf, ts_data)
        _ts_pdf_advanced_settings(pdf, ts_data)
        _ts_pdf_power_policy(pdf, ts_data)
        _ts_pdf_recent_tasks(pdf, ts_data)
        _ts_pdf_security(pdf, ts_data)
        _ts_pdf_cpu_topology(pdf, ts_data)
        _ts_pdf_coredump_swap(pdf, ts_data)
        _ts_pdf_vm_autostart(pdf, ts_data)
        _ts_pdf_graphics_gpu(pdf, ts_data)
        _ts_pdf_ipmi_bmc(pdf, ts_data)
        _ts_pdf_tcpip_stacks(pdf, ts_data)
        _ts_pdf_dvs(pdf, ts_data)
        _ts_pdf_vsan(pdf, ts_data)
        _ts_pdf_vibs(pdf, ts_data)
        _ts_pdf_snmp(pdf, ts_data)

    # vCenter-wide alarms (datacenter scope, not per-host)
    vc_alarms = cluster_report.get("vcenter_alarms")
    if vc_alarms:
        pdf.add_page()
        _ts_pdf_vcenter_alarms(pdf, vc_alarms)

    pdf.output(output_path)
    return output_path


# ── Troubleshoot PDF rendering ─────────────────────────────────────────

_YELLOW = (210, 170, 0)


def _health_color(status):
    return {
        "green": _GREEN,
        "yellow": _YELLOW,
        "red": _RED,
    }.get(str(status).lower(), _DARK)



def _ts_pdf_state_capacity(pdf, ts):
    state = ts.get("host_state", {})
    cap = ts.get("capacity_usage", {})
    if _ts_is_error(state) and _ts_is_error(cap):
        return

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Host State & Capacity", ln=True)
    pdf.set_font("Helvetica", "", 8)

    if not _ts_is_error(state):
        conn = state.get("connection_state", "?")
        uptime = state.get("uptime_human", "?")
        vms_on = state.get("vm_count_powered_on", 0)
        vms_total = state.get("vm_count_total", 0)
        pdf.cell(0, 5, f"State: {conn}  |  Uptime: {uptime}  |  "
                        f"VMs: {vms_on} running / {vms_total} total",
                 ln=True)

    if not _ts_is_error(cap):
        cpu = cap.get("cpu", {})
        mem = cap.get("memory", {})
        pdf.cell(0, 5, f"CPU: {cpu.get('used_ghz', 0)} / "
                        f"{cpu.get('total_ghz', 0)} GHz "
                        f"({cpu.get('usage_pct', 0)}%)  |  "
                        f"Memory: {mem.get('used_gb', 0)} / "
                        f"{mem.get('total_gb', 0)} GB "
                        f"({mem.get('usage_pct', 0)}%)",
                 ln=True)

        datastores = cap.get("datastores", [])
        if datastores:
            ds_cols = [
                ("Datastore", 50), ("Type", 20), ("Capacity GB", 28),
                ("Free GB", 28), ("Used GB", 28), ("Usage %", 20),
            ]
            pdf.table_header(ds_cols)
            for di, ds in enumerate(datastores):
                vals = [
                    ds.get("name", "?"),
                    ds.get("type", "?"),
                    f"{ds.get('capacity_gb', 0):.1f}",
                    f"{ds.get('free_gb', 0):.1f}",
                    f"{ds.get('used_gb', 0):.1f}",
                    f"{ds.get('usage_pct', 0):.1f}",
                ]
                pdf.table_row(ds_cols, vals, di)
    pdf.ln(3)


def _ts_pdf_alarms(pdf, ts):
    data = ts.get("alarms", {})
    if _ts_is_error(data):
        return

    active_count = data.get("active_count", 0)
    history_count = data.get("history_count", 0)
    crit = data.get("critical_count", 0)
    warn = data.get("warning_count", 0)

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"Alarms - {active_count} active ({crit} critical, "
                    f"{warn} warning), {history_count} historical", ln=True)

    meta = data.get("collection_metadata", {})
    if meta:
        pdf.set_font("Helvetica", "", 7)
        pdf.cell(0, 4,
                 f"History window: last {meta.get('window_days', '?')} days  |  "
                 f"{meta.get('window_start', '?')[:19]} to "
                 f"{meta.get('window_end', '?')[:19]}",
                 ln=True)

    # --- Active alarms ---
    active = data.get("active_alarms", [])
    if active:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, f"Currently Active ({len(active)})", ln=True)

        alarm_cols = [
            ("Severity", 18), ("Type", 14), ("Object", 40),
            ("Alarm Name", 70), ("Triggered", 50), ("Ack By", 30),
        ]
        pdf.table_header(alarm_cols)

        for ai, a in enumerate(active):
            status = a.get("status", "")
            severity = "Critical" if status == "red" else (
                "Warning" if status == "yellow" else status)
            pdf.set_text_color(*_health_color(status))
            vals = [
                severity,
                a.get("object_type", "?"),
                a.get("object_name", "?")[:30],
                a.get("alarm_name", "?")[:45],
                a.get("triggered_time", "?")[:30],
                a.get("acknowledged_by", "")[:20],
            ]
            pdf.table_row(alarm_cols, vals, ai)
            pdf.set_text_color(*_DARK)
        pdf.ln(2)
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 5, "No currently active alarms.", ln=True)

    # --- Historical alarm events ---
    history = data.get("alarm_history", [])
    if history:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, f"Alarm History ({len(history)} events)", ln=True)

        hist_cols = [("Time", 45), ("Event Type", 50),
                     ("Message", 120)]
        pdf.table_header(hist_cols)

        for hi, h in enumerate(history):
            vals = [
                h.get("time", "?")[:19],
                h.get("event_type", "?"),
                (h.get("message", "") or "")[:80],
            ]
            pdf.table_row(hist_cols, vals, hi)
        pdf.ln(2)

    pdf.ln(3)


def _ts_pdf_vcenter_alarms(pdf, vc_alarms):
    """Render vCenter-wide alarms (datacenter scope) in PDF."""
    active_count = vc_alarms.get("active_count", 0)
    history_count = vc_alarms.get("history_count", 0)
    crit = vc_alarms.get("critical_count", 0)
    warn = vc_alarms.get("warning_count", 0)

    pdf.section_title("vCenter Alarms (Datacenter-Wide)")
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6,
             f"{active_count} active ({crit} critical, {warn} warning), "
             f"{history_count} historical events", ln=True)

    meta = vc_alarms.get("collection_metadata", {})
    if meta:
        pdf.set_font("Helvetica", "", 7)
        pdf.cell(0, 4,
                 f"Scope: {meta.get('source', 'vCenter')}  |  "
                 f"History: last {meta.get('window_days', '?')} days  |  "
                 f"{meta.get('window_start', '?')[:19]} to "
                 f"{meta.get('window_end', '?')[:19]}",
                 ln=True)

    # --- Active alarms ---
    active = vc_alarms.get("active_alarms", [])
    if active:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, f"Currently Active ({len(active)})", ln=True)

        alarm_cols = [
            ("Severity", 18), ("Type", 14), ("Object", 40),
            ("Alarm Name", 70), ("Triggered", 50), ("Ack By", 30),
        ]
        pdf.table_header(alarm_cols)

        for ai, a in enumerate(active):
            status = a.get("status", "")
            severity = "Critical" if status == "red" else (
                "Warning" if status == "yellow" else status)
            pdf.set_text_color(*_health_color(status))
            vals = [
                severity,
                a.get("object_type", "?"),
                a.get("object_name", "?")[:30],
                a.get("alarm_name", "?")[:45],
                a.get("triggered_time", "?")[:30],
                a.get("acknowledged_by", "")[:20],
            ]
            pdf.table_row(alarm_cols, vals, ai)
            pdf.set_text_color(*_DARK)
        pdf.ln(2)
    else:
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 5, "No currently active alarms.", ln=True)

    # --- Historical alarm events ---
    history = vc_alarms.get("alarm_history", [])
    if history:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, f"Alarm History ({len(history)} events)", ln=True)

        hist_cols = [("Time", 40), ("Event Type", 45), ("Entity", 35),
                     ("Message", 95)]
        pdf.table_header(hist_cols)

        for hi, h in enumerate(history):
            vals = [
                h.get("time", "?")[:19],
                h.get("event_type", "?"),
                h.get("entity_name", "?")[:25] if h.get("entity_name") else "",
                (h.get("message", "") or "")[:65],
            ]
            pdf.table_row(hist_cols, vals, hi)
        pdf.ln(2)

    pdf.ln(3)


def _ts_pdf_resource_alloc(pdf, ts):
    # Memory
    mem_data = ts.get("memory_allocation", {})
    if not _ts_is_error(mem_data):
        pdf.set_font("Helvetica", "B", 9)
        host_gb = mem_data.get("host_total_gb", 0)
        res_gb = mem_data.get("total_reservation_gb", 0)
        avail_gb = mem_data.get("available_reservation_gb", 0)
        pdf.cell(0, 6, f"Memory Allocation  (Host: {host_gb} GB  |  "
                        f"Reserved: {res_gb} GB  |  "
                        f"Available: {avail_gb} GB)", ln=True)

        per_vm = mem_data.get("per_vm", [])
        if per_vm:
            mem_cols = [
                ("VM Name", 70), ("State", 20), ("Config MB", 22),
                ("Reserv MB", 22), ("Limit MB", 22),
                ("Shares", 20), ("Level", 18),
            ]
            pdf.table_header(mem_cols)
            for mi, v in enumerate(per_vm):
                limit = v.get("limit_mb", -1)
                vals = [
                    v.get("vm_name", "?")[:45],
                    v.get("power_state", "?").replace("powered", ""),
                    str(v.get("configured_mb", 0)),
                    str(v.get("reservation_mb", 0)),
                    "Unlim" if limit == -1 else str(limit),
                    str(v.get("shares_value", 0)),
                    str(v.get("shares_level", "N/A")),
                ]
                pdf.table_row(mem_cols, vals, mi)
        pdf.ln(2)

    # CPU
    cpu_data = ts.get("cpu_allocation", {})
    if not _ts_is_error(cpu_data):
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, "CPU Allocation", ln=True)

        per_vm = cpu_data.get("per_vm", [])
        if per_vm:
            cpu_cols = [
                ("VM Name", 70), ("State", 20), ("vCPU", 14),
                ("Reserv MHz", 24), ("Limit MHz", 24),
                ("Shares", 20), ("Level", 18),
            ]
            pdf.table_header(cpu_cols)
            for ci, v in enumerate(per_vm):
                limit = v.get("limit_mhz", -1)
                vals = [
                    v.get("vm_name", "?")[:45],
                    v.get("power_state", "?").replace("powered", ""),
                    str(v.get("num_cpu", 0)),
                    str(v.get("reservation_mhz", 0)),
                    "Unlim" if limit == -1 else str(limit),
                    str(v.get("shares_value", 0)),
                    str(v.get("shares_level", "N/A")),
                ]
                pdf.table_row(cpu_cols, vals, ci)
        pdf.ln(3)


def _ts_pdf_hardware_health(pdf, ts):
    data = ts.get("hardware_health", {})
    if _ts_is_error(data):
        return

    summary = data.get("summary", {})
    total = summary.get("total", 0)
    warn = summary.get("warning", 0)
    crit = summary.get("critical", 0)
    normal = summary.get("normal", 0)

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"Hardware Health Sensors ({total} total: "
                    f"{normal} normal, {warn} warning, {crit} critical)",
             ln=True)

    sensors = data.get("sensors", [])
    if not sensors:
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 5, data.get("note", "No sensors available."), ln=True)
        pdf.ln(3)
        return

    sensor_cols = [
        ("ID", 20), ("Sensor Name", 70), ("Type", 24),
        ("Status", 16), ("Reading", 22), ("Units", 22),
    ]
    pdf.table_header(sensor_cols)

    for si, s in enumerate(sensors):
        status = s.get("status", "green")
        if status != "green":
            pdf.set_text_color(*_health_color(status))
        vals = [
            str(s.get("id", ""))[:14],
            s.get("name", "?")[:45],
            str(s.get("sensor_type", ""))[:16],
            status,
            str(s.get("reading", "")),
            str(s.get("units", "")),
        ]
        pdf.table_row(sensor_cols, vals, si)
        pdf.set_text_color(*_DARK)

    pdf.ln(3)


def _ts_pdf_performance(pdf, ts):
    data = ts.get("performance_stats", {})
    if _ts_is_error(data):
        return

    interval = data.get("interval_minutes", "?")
    sampling = data.get("sampling_interval_seconds", 20)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"Performance Statistics (last {interval} minutes)",
             ln=True)
    pdf.set_font("Helvetica", "", 7)
    pdf.cell(0, 4,
             f"Sampling interval: {sampling}s  |  "
             f"Collection window: {interval} min  |  "
             f"Max samples: {data.get('total_samples_requested', '?')}",
             ln=True)

    perf_cols = [
        ("Metric", 40), ("Latest", 22), ("Average", 22),
        ("Minimum", 22), ("Maximum", 22), ("Samples", 18),
    ]
    pdf.table_header(perf_cols)

    perf_metrics = [
        ("CPU Usage %", "cpu_usage_pct"),
        ("CPU Ready (ms)", "cpu_ready_ms"),
        ("CPU CoStop (ms)", "cpu_costop_ms"),
        ("CPU Latency %", "cpu_latency_pct"),
        ("CPU Wait (ms)", "cpu_wait_ms"),
        ("CPU Used (ms)", "cpu_used_ms"),
        ("Memory Usage %", "memory_usage_pct"),
        ("Mem Balloon (KB)", "mem_balloon_kb"),
        ("Mem Swap Used (KB)", "mem_swap_used_kb"),
        ("Mem Swap In (KBps)", "mem_swapin_kbps"),
        ("Mem Swap Out (KBps)", "mem_swapout_kbps"),
        ("Mem Compressed (KB)", "mem_compressed_kb"),
        ("Mem Active (KB)", "mem_active_kb"),
        ("Mem Granted (KB)", "mem_granted_kb"),
    ]
    ri = 0
    for label, key in perf_metrics:
        stats = data.get(key)
        if not stats:
            continue
        vals = [
            label,
            f"{stats['latest']:.1f}",
            f"{stats['average']:.1f}",
            f"{stats['minimum']:.1f}",
            f"{stats['maximum']:.1f}",
            str(stats.get("samples", 0)),
        ]
        pdf.table_row(perf_cols, vals, ri)
        ri += 1

    pdf.ln(3)


def _ts_pdf_io_stats(pdf, ts):
    data = ts.get("io_stats", {})
    if _ts_is_error(data):
        return

    interval = data.get("interval_minutes", "?")
    sampling = data.get("sampling_interval_seconds", 20)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"I/O Statistics (last {interval} minutes)", ln=True)
    pdf.set_font("Helvetica", "", 7)
    pdf.cell(0, 4,
             f"Sampling interval: {sampling}s  |  "
             f"Collection window: {interval} min  |  "
             f"Max samples: {data.get('total_samples_requested', '?')}",
             ln=True)

    io_cols = [
        ("Metric", 40), ("Latest", 22), ("Average", 22),
        ("Minimum", 22), ("Maximum", 22), ("Samples", 18),
    ]
    pdf.table_header(io_cols)

    metrics = [
        ("Read Latency (ms)", "read_latency_ms"),
        ("Write Latency (ms)", "write_latency_ms"),
        ("Dev Read Lat (ms)", "device_read_latency_ms"),
        ("Dev Write Lat (ms)", "device_write_latency_ms"),
        ("Kern Read Lat (ms)", "kernel_read_latency_ms"),
        ("Kern Write Lat (ms)", "kernel_write_latency_ms"),
        ("Queue Read Lat (ms)", "queue_read_latency_ms"),
        ("Queue Write Lat (ms)", "queue_write_latency_ms"),
        ("Read IOPS", "read_iops"),
        ("Write IOPS", "write_iops"),
        ("Read KBps", "read_kbps"),
        ("Write KBps", "write_kbps"),
        ("Max Queue Depth", "max_queue_depth"),
        ("Commands Aborted", "commands_aborted"),
        ("Bus Resets", "bus_resets"),
        ("Net RX KBps", "net_rx_kbps"),
        ("Net TX KBps", "net_tx_kbps"),
        ("Packets RX", "net_packets_rx"),
        ("Packets TX", "net_packets_tx"),
        ("Dropped RX", "net_dropped_rx"),
        ("Dropped TX", "net_dropped_tx"),
        ("Errors RX", "net_errors_rx"),
        ("Errors TX", "net_errors_tx"),
    ]

    ri = 0
    for label, key in metrics:
        stats = data.get(key)
        if not stats:
            continue
        vals = [
            label,
            f"{stats['latest']:.1f}",
            f"{stats['average']:.1f}",
            f"{stats['minimum']:.1f}",
            f"{stats['maximum']:.1f}",
            str(stats.get("samples", 0)),
        ]
        pdf.table_row(io_cols, vals, ri)
        ri += 1

    # Per-disk table
    per_disk = data.get("per_disk", [])
    if per_disk:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, f"Per-Disk Breakdown ({len(per_disk)} devices)", ln=True)
        pd_cols = [
            ("Device", 30), ("RdLat ms", 18), ("WrLat ms", 18),
            ("Rd IOPS", 18), ("Wr IOPS", 18), ("Rd KBps", 18),
            ("Wr KBps", 18), ("CmdAbrt", 16), ("BusRst", 16),
        ]
        pdf.table_header(pd_cols)
        for di, dd in enumerate(per_disk):
            def _avg(k):
                v = dd.get(k, {})
                return f"{v.get('average', 0):.1f}" if v else "N/A"
            def _mx(k):
                v = dd.get(k, {})
                return f"{v.get('maximum', 0):.0f}" if v else "0"
            vals = [
                dd.get("device", ""),
                _avg("read_latency_ms"), _avg("write_latency_ms"),
                _avg("read_iops"), _avg("write_iops"),
                _avg("read_kbps"), _avg("write_kbps"),
                _mx("commands_aborted"), _mx("bus_resets"),
            ]
            pdf.table_row(pd_cols, vals, di)

    # Per-NIC table
    per_nic = data.get("per_nic", [])
    if per_nic:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, f"Per-NIC Breakdown ({len(per_nic)} interfaces)", ln=True)
        pn_cols = [
            ("Interface", 30), ("RX KBps", 22), ("TX KBps", 22),
            ("PktsRX", 20), ("PktsTX", 20), ("DrpRX", 16),
            ("DrpTX", 16), ("ErrRX", 16), ("ErrTX", 16),
        ]
        pdf.table_header(pn_cols)
        for ni, nd in enumerate(per_nic):
            def _avg_n(k):
                v = nd.get(k, {})
                return f"{v.get('average', 0):.1f}" if v else "N/A"
            def _mx_n(k):
                v = nd.get(k, {})
                return f"{v.get('maximum', 0):.0f}" if v else "0"
            vals = [
                nd.get("interface", ""),
                _avg_n("rx_kbps"), _avg_n("tx_kbps"),
                _avg_n("packets_rx"), _avg_n("packets_tx"),
                _mx_n("dropped_rx"), _mx_n("dropped_tx"),
                _mx_n("errors_rx"), _mx_n("errors_tx"),
            ]
            pdf.table_row(pn_cols, vals, ni)

    # Bottleneck warnings
    bottlenecks = data.get("bottlenecks", [])
    if bottlenecks:
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*_RED)
        for b in bottlenecks:
            pdf.cell(0, 5, f"WARNING: {b}", ln=True)
        pdf.set_text_color(*_DARK)

    pdf.ln(3)


def _ts_pdf_recent_tasks(pdf, ts):
    data = ts.get("recent_tasks", {})
    if _ts_is_error(data):
        return

    total = data.get("total_count", 0)
    pdf.set_font("Helvetica", "B", 9)
    meta = data.get("collection_metadata", {})
    window = meta.get("window_days", "?")
    pdf.cell(0, 6, f"Recent Tasks ({total} total, last {window} days)", ln=True)
    if meta:
        pdf.set_font("Helvetica", "", 7)
        pdf.cell(0, 4,
                 f"Window: {meta.get('window_start', '?')}  |  "
                 f"Method: {meta.get('method', '?')}", ln=True)

    tasks = data.get("tasks", [])
    if not tasks:
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 5, data.get("note", "No recent tasks."), ln=True)
        pdf.ln(3)
        return

    task_cols = [
        ("State", 18), ("Description", 70), ("Entity", 40),
        ("Start Time", 40), ("Error", 60),
    ]
    pdf.table_header(task_cols)

    for ti, t in enumerate(tasks[:30]):
        state = t.get("state", "?")
        if state == "error":
            pdf.set_text_color(*_RED)
        elif state == "running":
            pdf.set_text_color(*_GREEN)

        desc = t.get("description", "") or t.get("name", "?")
        vals = [
            state,
            desc[:45],
            t.get("entity_name", "")[:28],
            t.get("start_time", "")[:28],
            t.get("error", "")[:38],
        ]
        pdf.table_row(task_cols, vals, ti)
        pdf.set_text_color(*_DARK)

    pdf.ln(3)


def _ts_pdf_system_info(pdf, ts):
    data = ts.get("system_info", {})
    if _ts_is_error(data):
        return

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "System Information", ln=True)
    pdf.set_font("Helvetica", "", 8)

    pdf.cell(0, 5, f"ESXi: {data.get('esxi_full_name', '')}  |  "
                    f"Build: {data.get('esxi_build', '')}  |  "
                    f"Patch: {data.get('esxi_patch_level', '')}", ln=True)
    pdf.cell(0, 5, f"Server: {data.get('vendor', '')} {data.get('model', '')}  |  "
                    f"Serial: {data.get('serial', '')}  |  "
                    f"NUMA: {data.get('numa_nodes', 0)} nodes", ln=True)
    pdf.cell(0, 5, f"BIOS: {data.get('bios_version', '')}  |  "
                    f"Vendor: {data.get('bios_vendor', '')}  |  "
                    f"Date: {data.get('bios_release_date', '')}", ln=True)

    licenses = data.get("licenses", [])
    if licenses:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, "Licenses:", ln=True)
        lic_cols = [("Name", 60), ("Key", 30), ("Used", 20), ("Total", 20)]
        pdf.table_header(lic_cols)
        for li, lic in enumerate(licenses):
            vals = [lic.get("name"), lic.get("key"),
                    str(lic.get("used", 0)), str(lic.get("total", 0))]
            pdf.table_row(lic_cols, vals, li)
    pdf.ln(3)


def _ts_pdf_vm_details(pdf, ts):
    data = ts.get("vm_details", {})
    if _ts_is_error(data):
        return
    vms = data.get("vms", [])
    if not vms:
        return

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"Virtual Machines ({data.get('total_count', 0)} total)",
             ln=True)

    vm_cols = [
        ("VM Name", 55), ("Power", 16), ("Guest OS", 45), ("Ver", 14),
        ("vCPU", 12), ("RAM MB", 16), ("Tools", 20),
        ("IP", 28), ("Snaps", 14),
    ]
    pdf.table_header(vm_cols)
    for vi, vm in enumerate(vms):
        vals = [
            vm.get("vm_name", "")[:35],
            vm.get("power_state", "").replace("powered", ""),
            vm.get("guest_os", "")[:30],
            vm.get("vm_version", ""),
            str(vm.get("num_cpu", 0)),
            str(vm.get("memory_mb", 0)),
            vm.get("tools_status", "")[:14],
            vm.get("guest_ip", ""),
            "Yes" if vm.get("has_snapshots") else "No",
        ]
        pdf.table_row(vm_cols, vals, vi)

    # VM Disks sub-table
    all_disks = []
    for vm in vms:
        for d in vm.get("disks", []):
            all_disks.append((vm.get("vm_name", ""), d))
    if all_disks:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, "VM Disks", ln=True)
        disk_cols = [("VM", 45), ("Label", 30), ("GB", 18), ("Backing", 120)]
        pdf.table_header(disk_cols)
        for di, (name, d) in enumerate(all_disks):
            vals = [name[:30], d.get("label", ""),
                    str(d.get("capacity_gb", 0)),
                    d.get("backing_file", "")[:75]]
            pdf.table_row(disk_cols, vals, di)
    pdf.ln(3)


def _ts_pdf_network_config(pdf, ts):
    data = ts.get("network_config", {})
    if _ts_is_error(data):
        return

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Network Configuration", ln=True)

    # pNICs
    pnics = data.get("pnics", [])
    if pnics:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, "Physical NICs", ln=True)
        cols = [("Device", 18), ("MAC", 36), ("Driver", 18),
                ("Speed Mb", 18), ("Link", 12), ("TSO", 10),
                ("CSO", 10), ("WoL", 10)]
        pdf.table_header(cols)
        for i, p in enumerate(pnics):
            off = p.get("offload", {})
            vals = [p.get("device"), p.get("mac"), p.get("driver"),
                    str(p.get("link_speed_mb", 0)),
                    "UP" if p.get("link_up") else "DN",
                    "Y" if off.get("tso_enabled") else "N",
                    "Y" if off.get("cso_enabled") else "N",
                    "Y" if off.get("wake_on_lan") else "N"]
            pdf.table_row(cols, vals, i)
        pdf.ln(2)

    # vSwitches
    vswitches = data.get("vswitches", [])
    if vswitches:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, "vSwitches", ln=True)
        cols = [("Name", 24), ("Ports", 14), ("MTU", 14),
                ("pNICs", 40), ("Promisc", 14), ("MAC Chg", 14),
                ("Forged", 14), ("Teaming", 28)]
        pdf.table_header(cols)
        for i, vs in enumerate(vswitches):
            pol = vs.get("policy", {})
            sec = pol.get("security", {})
            team = pol.get("nic_teaming", {})
            vals = [vs.get("name"), str(vs.get("num_ports", 0)),
                    str(vs.get("mtu", 0)),
                    ", ".join(vs.get("pnics", [])),
                    _yn(sec.get("allow_promiscuous")),
                    _yn(sec.get("mac_changes")),
                    _yn(sec.get("forged_transmits")),
                    str(team.get("policy", ""))[:18]]
            pdf.table_row(cols, vals, i)
        pdf.ln(2)

    # Port groups
    portgroups = data.get("portgroups", [])
    if portgroups:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, "Port Groups", ln=True)
        cols = [("Name", 40), ("VLAN", 16), ("vSwitch", 24),
                ("Promisc", 16), ("MAC Chg", 16), ("Forged", 16)]
        pdf.table_header(cols)
        for i, pg in enumerate(portgroups):
            pol = pg.get("policy_override", {})
            sec = pol.get("security", {}) if pol else {}
            vals = [pg.get("name", "")[:28], str(pg.get("vlan_id", 0)),
                    pg.get("vswitch", ""),
                    _yn(sec.get("allow_promiscuous")),
                    _yn(sec.get("mac_changes")),
                    _yn(sec.get("forged_transmits"))]
            pdf.table_row(cols, vals, i)
        pdf.ln(2)

    # VMkernel
    vkernel = data.get("vmkernel_adapters", [])
    if vkernel:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, "VMkernel Adapters", ln=True)
        cols = [("Device", 16), ("Portgroup", 28), ("IP", 28),
                ("Subnet", 28), ("MTU", 14), ("Stack", 18),
                ("vMot", 12)]
        pdf.table_header(cols)
        for i, vk in enumerate(vkernel):
            vals = [vk.get("device"), vk.get("portgroup"),
                    vk.get("ip", ""), vk.get("subnet", ""),
                    str(vk.get("mtu", "")),
                    vk.get("netstack", ""),
                    "Y" if vk.get("vmotion_enabled") else "N"]
            pdf.table_row(cols, vals, i)
        # IPv6 sub-rows
        for vk in vkernel:
            ipv6 = vk.get("ipv6", {})
            addrs = ipv6.get("addresses", [])
            if addrs:
                pdf.set_font("Helvetica", "", 7)
                for a in addrs:
                    pdf.cell(0, 4,
                             f"  {vk.get('device')} IPv6: "
                             f"{a.get('address')}/{a.get('prefix_length')}  "
                             f"origin={a.get('origin', '')}",
                             ln=True)
        pdf.ln(2)

    # DNS
    dns = data.get("dns", {})
    if dns:
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 5, f"DNS: {', '.join(dns.get('servers', []))}  |  "
                        f"Domain: {dns.get('domain', '')}", ln=True)

    # NTP
    ntp = data.get("ntp", {})
    if ntp and ntp.get("servers"):
        pdf.cell(0, 5, f"NTP: {', '.join(ntp['servers'])}  |  "
                        f"TZ: {ntp.get('timezone', '')}", ln=True)

    # CDP/LLDP
    cdp_lldp = data.get("cdp_lldp", [])
    if cdp_lldp:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, "CDP/LLDP", ln=True)
        cols = [("Device", 18), ("Switch", 40), ("Port", 30),
                ("Address", 30)]
        pdf.table_header(cols)
        for i, c in enumerate(cdp_lldp):
            vals = [c.get("device"), c.get("switch_id", ""),
                    c.get("port_id", ""), c.get("switch_address", "")]
            pdf.table_row(cols, vals, i)

    pdf.ln(3)


def _ts_pdf_storage_config(pdf, ts):
    data = ts.get("storage_config", {})
    if _ts_is_error(data):
        return

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Storage Configuration", ln=True)

    if data.get("iscsi_enabled"):
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 4, "Software iSCSI: ENABLED", ln=True)

    # HBAs
    hbas = data.get("hbas", [])
    if hbas:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, "Host Bus Adapters", ln=True)
        cols = [("Device", 20), ("Type", 28), ("Model", 40),
                ("Driver", 20), ("Status", 16), ("iSCSI Name", 40)]
        pdf.table_header(cols)
        for i, h in enumerate(hbas):
            vals = [h.get("device"), h.get("type"), h.get("model", "")[:28],
                    h.get("driver"), h.get("status"),
                    h.get("iscsi_name", "")[:28]]
            pdf.table_row(cols, vals, i)
        pdf.ln(2)

    # iSCSI targets
    iscsi_targets = data.get("iscsi_targets", [])
    if iscsi_targets:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, f"iSCSI Targets ({len(iscsi_targets)})", ln=True)
        cols = [("Type", 24), ("Address", 40), ("Port", 16),
                ("HBA", 20), ("IQN", 60)]
        pdf.table_header(cols)
        for i, t in enumerate(iscsi_targets):
            vals = [t.get("type", ""), t.get("address", ""),
                    str(t.get("port", 3260)), t.get("hba_device", ""),
                    t.get("iscsi_name", "")[:40]]
            pdf.table_row(cols, vals, i)
        pdf.ln(2)

    # SCSI LUNs
    luns = data.get("scsi_luns", [])
    if luns:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, f"SCSI LUNs ({len(luns)})", ln=True)
        cols = [("Display Name", 46), ("Model", 28), ("Cap GB", 18),
                ("Type", 14), ("State", 16), ("SSD", 10),
                ("QD", 10), ("Serial", 28)]
        pdf.table_header(cols)
        for i, l in enumerate(luns):
            ssd = "Y" if l.get("ssd") is True else ("N" if l.get("ssd") is False else "-")
            qd = str(l.get("queue_depth", "")) if l.get("queue_depth") is not None else "-"
            vals = [l.get("display_name", "")[:32], l.get("model", "")[:18],
                    str(l.get("capacity_gb", 0)),
                    l.get("lun_type", ""), l.get("operational_state", ""),
                    ssd, qd, l.get("serial_number", "")[:18]]
            pdf.table_row(cols, vals, i)
        pdf.ln(2)

    # Multipath
    mp = data.get("multipath", [])
    if mp:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, f"Multipath ({len(mp)} LUNs)", ln=True)
        cols = [("LUN ID", 50), ("Policy", 30), ("Paths", 16),
                ("Active", 16)]
        pdf.table_header(cols)
        for i, m in enumerate(mp):
            active = sum(1 for p in m.get("paths", []) if p.get("is_working"))
            vals = [m.get("lun_id", "")[:36], m.get("policy", ""),
                    str(m.get("path_count", 0)), str(active)]
            pdf.table_row(cols, vals, i)
        pdf.ln(2)

    # File system volumes
    volumes = data.get("file_system_volumes", [])
    if volumes:
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(0, 5, "File System Volumes", ln=True)
        cols = [("Name", 36), ("Type", 14), ("Cap GB", 18),
                ("VMFS", 12), ("SSD", 10), ("Mount", 10),
                ("Path", 50)]
        pdf.table_header(cols)
        for i, v in enumerate(volumes):
            vals = [v.get("name", "")[:24], v.get("type", ""),
                    str(v.get("capacity_gb", 0)),
                    str(v.get("vmfs_version", "")),
                    "Y" if v.get("ssd") else "-",
                    "Y" if v.get("mounted") else "N",
                    v.get("path", "")[:34]]
            pdf.table_row(cols, vals, i)
        # NFS detail sub-rows
        nfs_vols = [v for v in volumes if v.get("nfs_remote_host")]
        if nfs_vols:
            pdf.set_font("Helvetica", "", 7)
            for v in nfs_vols:
                pdf.cell(0, 4,
                         f"  NFS: {v.get('name', '')} -> "
                         f"{v.get('nfs_remote_host')}:{v.get('nfs_remote_path', '')}",
                         ln=True)
        # VMFS extent sub-rows
        ext_vols = [v for v in volumes if v.get("extents")]
        if ext_vols:
            pdf.set_font("Helvetica", "", 7)
            for v in ext_vols:
                for ext in v["extents"]:
                    pdf.cell(0, 4,
                             f"  Extent: {v.get('name', '')} -> "
                             f"{ext.get('disk_name')}:{ext.get('partition')}",
                             ln=True)

    pdf.ln(3)


def _ts_pdf_services(pdf, ts):
    data = ts.get("services", {})
    if _ts_is_error(data):
        return
    services = data.get("services", [])
    if not services:
        return

    total = data.get("total_count", 0)
    running = data.get("running_count", 0)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"Services ({total} total, {running} running)", ln=True)

    cols = [("Key", 50), ("Label", 50), ("Running", 16),
            ("Policy", 22), ("Required", 16)]
    pdf.table_header(cols)
    for i, s in enumerate(services):
        is_running = s.get("running", False)
        if is_running:
            pdf.set_text_color(*_GREEN)
        vals = [s.get("key", "")[:32], s.get("label", "")[:32],
                "Yes" if is_running else "No",
                s.get("policy", ""),
                "Yes" if s.get("required") else "No"]
        pdf.table_row(cols, vals, i)
        pdf.set_text_color(*_DARK)
    pdf.ln(3)


def _ts_pdf_events(pdf, ts):
    data = ts.get("events", {})
    if _ts_is_error(data):
        return
    events = data.get("events", [])
    if not events:
        return

    pdf.set_font("Helvetica", "B", 9)
    meta = data.get("collection_metadata", {})
    window = meta.get("window_days", "?")
    pdf.cell(0, 6, f"Events ({data.get('total_count', 0)} total, "
                    f"last {window} days)", ln=True)
    if meta:
        pdf.set_font("Helvetica", "", 7)
        pdf.cell(0, 4,
                 f"Window: {meta.get('window_start', '?')} -> "
                 f"{meta.get('window_end', '?')}", ln=True)

    cols = [("Time", 45), ("Type", 35), ("User", 20), ("Message", 130)]
    pdf.table_header(cols)
    for i, e in enumerate(events[:30]):
        vals = [e.get("time", "")[:30],
                e.get("type", "")[:22],
                e.get("user", "")[:14],
                e.get("message", "")[:85]]
        pdf.table_row(cols, vals, i)
    pdf.ln(3)


def _ts_pdf_pci_devices(pdf, ts):
    data = ts.get("pci_devices", {})
    if _ts_is_error(data):
        return
    devices = data.get("devices", [])
    if not devices:
        return

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"PCI Devices ({data.get('total_count', 0)} total)", ln=True)

    cols = [("ID", 22), ("Device Name", 80), ("Vendor", 50),
            ("Class", 18), ("DevID", 18)]
    pdf.table_header(cols)
    for i, d in enumerate(devices):
        vals = [d.get("id", "")[:14], d.get("device_name", "")[:52],
                d.get("vendor_name", "")[:32],
                str(d.get("class_id", "")),
                str(d.get("device_id", ""))]
        pdf.table_row(cols, vals, i)
    pdf.ln(3)


def _ts_pdf_firewall(pdf, ts):
    data = ts.get("firewall", {})
    if _ts_is_error(data):
        return
    rulesets = data.get("rulesets", [])
    if not rulesets:
        return

    total = data.get("total_count", 0)
    enabled = data.get("enabled_count", 0)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"Firewall Rulesets ({total} total, {enabled} enabled)",
             ln=True)

    cols = [("Key", 50), ("Label", 50), ("Enabled", 16),
            ("Rules", 14), ("Ports/Proto", 60)]
    pdf.table_header(cols)
    for i, rs in enumerate(rulesets):
        rules = rs.get("rules", [])
        rule_str = "; ".join(
            f"{r.get('port_start')}/{r.get('protocol')}"
            for r in rules[:3]
        )
        if len(rules) > 3:
            rule_str += f"... +{len(rules) - 3}"
        vals = [rs.get("key", "")[:32], rs.get("label", "")[:32],
                "Yes" if rs.get("enabled") else "No",
                str(len(rules)), rule_str[:38]]
        pdf.table_row(cols, vals, i)
    pdf.ln(3)


def _ts_pdf_advanced_settings(pdf, ts):
    data = ts.get("advanced_settings", {})
    if _ts_is_error(data):
        return

    total = data.get("total_count", 0)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"Advanced Settings ({total} total - key settings shown)",
             ln=True)

    categorized = data.get("categorized", {})
    if not categorized:
        return

    cols = [("Category", 24), ("Setting", 70), ("Value", 80)]
    pdf.table_header(cols)
    row_idx = 0
    for cat, settings in categorized.items():
        for key, val in settings.items():
            vals = [cat, key, str(val)[:52]]
            pdf.table_row(cols, vals, row_idx)
            row_idx += 1
    pdf.ln(3)


def _ts_pdf_power_policy(pdf, ts):
    data = ts.get("power_policy", {})
    if _ts_is_error(data) or not data:
        return

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Power Policy & CPU Management", ln=True)
    pdf.set_font("Helvetica", "", 8)

    pdf.cell(0, 5, f"Policy: {data.get('current_policy_name', 'N/A')} "
                    f"({data.get('current_policy_key', '')})  |  "
                    f"{data.get('current_policy_desc', '')}", ln=True)
    pdf.cell(0, 5, f"CPU Policy: {data.get('cpu_policy', 'N/A')}  |  "
                    f"HW Support: {data.get('hw_support', 'N/A')}  |  "
                    f"HyperThreading: "
                    f"{'Active' if data.get('hyperthreading_active') else 'Inactive'}",
             ln=True)
    pdf.ln(3)


def _ts_pdf_security(pdf, ts):
    data = ts.get("security_config", {})
    if _ts_is_error(data) or not data:
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Security Configuration", ln=True)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, f"Lockdown: {data.get('lockdown_mode', 'N/A')}  |  "
                    f"TPM: {'Yes' if data.get('tpm_present') else 'No'}  |  "
                    f"Crypto: {'On' if data.get('crypto_enabled') else 'Off'}",
             ln=True)
    pdf.cell(0, 5, f"SSL Thumbprint: {data.get('ssl_thumbprint', 'N/A')}",
             ln=True)
    for ac in data.get("auth_configs", []):
        en = "enabled" if ac.get("enabled") else "disabled"
        domain = ac.get("joined_domain", "")
        pdf.cell(0, 5, f"  Auth: {ac.get('type', '?')} ({en})"
                        f"{'  domain=' + domain if domain else ''}", ln=True)
    pdf.ln(3)


def _ts_pdf_cpu_topology(pdf, ts):
    data = ts.get("cpu_topology", {})
    if _ts_is_error(data) or not data:
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "CPU Topology", ln=True)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, f"Sockets: {data.get('num_cpu_pkgs', '?')}  |  "
                    f"Cores: {data.get('num_cpu_cores', '?')}  |  "
                    f"Threads: {data.get('num_cpu_threads', '?')}  |  "
                    f"Cores/Socket: {data.get('cores_per_socket', '?')}  |  "
                    f"Threads/Core: {data.get('threads_per_core', '?')}", ln=True)
    numa = data.get("numa", {})
    if numa and numa.get("num_nodes"):
        pdf.cell(0, 5, f"NUMA: {numa['num_nodes']} node(s)", ln=True)
        for ni, node in enumerate(numa.get("nodes", [])):
            pdf.cell(0, 5, f"  Node {ni}: {node.get('memory_size_gb', '?')} GB  "
                            f"CPUs={len(node.get('cpu_ids', []))}", ln=True)
    pdf.ln(3)


def _ts_pdf_coredump_swap(pdf, ts):
    data = ts.get("coredump_swap", {})
    if _ts_is_error(data) or not data:
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Coredump / Swap / Scratch", ln=True)
    pdf.set_font("Helvetica", "", 8)
    cd = data.get("coredump")
    if cd and isinstance(cd, dict) and not cd.get("status"):
        pdf.cell(0, 5, f"Coredump: {cd.get('disk_name', 'N/A')}  "
                        f"partition={cd.get('partition', '')}", ln=True)
    else:
        pdf.cell(0, 5, "Coredump: Not configured", ln=True)
    pdf.cell(0, 5, f"Swap DS: {data.get('swap_datastore') or 'None'}  |  "
                    f"Scratch: {data.get('scratch_current', 'N/A')}", ln=True)
    pdf.ln(3)


def _ts_pdf_vm_autostart(pdf, ts):
    data = ts.get("vm_autostart", {})
    if _ts_is_error(data) or not data:
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "VM AutoStart", ln=True)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, f"Enabled: {data.get('enabled', False)}", ln=True)
    for v in data.get("vms", []):
        pdf.cell(0, 5, f"  {v.get('vm_name', '?')}  "
                        f"order={v.get('start_order', '?')}  "
                        f"action={v.get('start_action', '?')}", ln=True)
    pdf.ln(3)


def _ts_pdf_graphics_gpu(pdf, ts):
    data = ts.get("graphics_gpu", {})
    if _ts_is_error(data) or not data:
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Graphics / GPU", ln=True)
    pdf.set_font("Helvetica", "", 8)
    devices = data.get("devices", [])
    if devices:
        for d in devices:
            pdf.cell(0, 5, f"{d.get('device_name', '?')}  "
                            f"vendor={d.get('vendor_name', '?')}  "
                            f"mem={d.get('gpu_memory_mb', 0)}MB", ln=True)
    else:
        pdf.cell(0, 5, "No GPU devices detected.", ln=True)
    pdf.ln(3)


def _ts_pdf_ipmi_bmc(pdf, ts):
    data = ts.get("ipmi_bmc", {})
    if _ts_is_error(data) or not data:
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "IPMI / BMC (iDRAC)", ln=True)
    pdf.set_font("Helvetica", "", 8)
    if data.get("present"):
        pdf.cell(0, 5, f"BMC IP: {data.get('bmc_ip', 'N/A')}  "
                        f"MAC: {data.get('bmc_mac', 'N/A')}", ln=True)
    else:
        pdf.cell(0, 5, "BMC/IPMI: Not available via API", ln=True)
    pdf.ln(3)


def _ts_pdf_tcpip_stacks(pdf, ts):
    data = ts.get("tcpip_stacks", {})
    if _ts_is_error(data) or not data:
        return
    stacks = data.get("stacks", [])
    if not stacks:
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"TCP/IP Stacks ({len(stacks)})", ln=True)
    pdf.set_font("Helvetica", "", 8)
    for s in stacks:
        dns = ", ".join(s.get("dns_servers", []))
        pdf.cell(0, 5, f"{s.get('key', '?')}  gw={s.get('default_gateway', '')}  "
                        f"dns=[{dns}]", ln=True)
    pdf.ln(3)


def _ts_pdf_dvs(pdf, ts):
    data = ts.get("dvs_config", {})
    if _ts_is_error(data) or not data:
        return
    switches = data.get("proxy_switches", [])
    if not switches:
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Distributed Virtual Switches", ln=True)
    pdf.set_font("Helvetica", "", 8)
    for s in switches:
        uplinks = ", ".join(s.get("uplink_pnics", []))
        pdf.cell(0, 5, f"{s.get('dvs_name', '?')}  ports={s.get('num_ports', 0)}  "
                        f"mtu={s.get('mtu', 0)}  uplinks=[{uplinks}]", ln=True)
    pdf.ln(3)


def _ts_pdf_vsan(pdf, ts):
    data = ts.get("vsan_config", {})
    if _ts_is_error(data) or not data:
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "vSAN Configuration", ln=True)
    pdf.set_font("Helvetica", "", 8)
    if not data.get("enabled"):
        pdf.cell(0, 5, "vSAN: Not enabled", ln=True)
    else:
        pdf.cell(0, 5, f"Cluster: {data.get('cluster_uuid', 'N/A')}  "
                        f"Node: {data.get('node_uuid', 'N/A')}", ln=True)
    pdf.ln(3)


def _ts_pdf_vibs(pdf, ts):
    data = ts.get("installed_vibs", {})
    if _ts_is_error(data) or not data:
        return
    vibs = data.get("vibs", [])
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"Installed VIBs ({len(vibs)} packages)", ln=True)
    pdf.set_font("Helvetica", "", 8)
    if vibs:
        cols = [("Name", 70), ("Version", 60), ("Vendor", 60)]
        pdf.table_header(cols)
        for i, v in enumerate(vibs[:30]):
            pdf.table_row(cols, [
                v.get("name", ""), v.get("version", ""), v.get("vendor", ""),
            ], i)
        if len(vibs) > 30:
            pdf.cell(0, 5, f"  ... +{len(vibs) - 30} more (see Excel/JSON)", ln=True)
    else:
        pdf.cell(0, 5, f"Image Profile: {data.get('image_profile', 'N/A')}", ln=True)
    pdf.ln(3)


def _ts_pdf_snmp(pdf, ts):
    data = ts.get("snmp_config", {})
    if _ts_is_error(data) or not data:
        return
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "SNMP Configuration", ln=True)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, f"Enabled: {data.get('enabled', 'N/A')}  "
                    f"Port: {data.get('port', 161)}", ln=True)
    communities = data.get("read_only_communities", [])
    if communities:
        pdf.cell(0, 5, f"Communities: {', '.join(communities)}", ln=True)
    for t in data.get("trap_targets", []):
        pdf.cell(0, 5, f"Trap: {t.get('hostname', '?')}:{t.get('port', 0)}",
                 ln=True)
    pdf.ln(3)


def _ts_pdf_health_summary(pdf, ts):
    data = ts.get("health_summary", {})
    if _ts_is_error(data) or not data:
        return

    overall = data.get("overall_status", "UNKNOWN")
    color = {"GREEN": _GREEN, "YELLOW": _YELLOW, "RED": _RED}.get(
        overall.upper(), _DARK)

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*color)
    pdf.cell(0, 8, f"Health Summary: {overall}", ln=True)
    pdf.set_text_color(*_DARK)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, data.get("summary_text", ""), ln=True)

    checks = data.get("checks", [])
    if checks:
        cols = [("Category", 50), ("Status", 18), ("Value", 40),
                ("Detail", 120)]
        pdf.table_header(cols)
        for ci, c in enumerate(checks):
            st = c.get("status", "GREEN").upper()
            st_color = {"GREEN": _GREEN, "YELLOW": _YELLOW,
                        "RED": _RED}.get(st, _DARK)
            pdf.set_text_color(*st_color)
            vals = [c.get("category", ""), st,
                    str(c.get("value", "")), c.get("detail", "")[:75]]
            pdf.table_row(cols, vals, ci)
            pdf.set_text_color(*_DARK)
    pdf.ln(3)


def _ts_pdf_vm_contention(pdf, ts):
    data = ts.get("vm_contention_stats", {})
    if _ts_is_error(data) or not data:
        return
    vms = data.get("vms", [])
    if not vms:
        return

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"VM Contention Stats ({len(vms)} VMs)", ln=True)

    meta = data.get("sampling_metadata", {})
    if meta:
        pdf.set_font("Helvetica", "", 7)
        pdf.cell(0, 4,
                 f"Interval: {meta.get('interval_id_seconds', 20)}s  |  "
                 f"Window: {meta.get('collection_window_minutes', '?')} min  |  "
                 f"Max samples: {meta.get('max_samples_requested', '?')}",
                 ln=True)

    cols = [("VM Name", 55), ("Ready %", 18), ("Verdict", 18),
            ("CPU %", 16), ("CoStop ms", 20),
            ("Balloon KB", 22), ("Swap KB", 20),
            ("Active KB", 22), ("Granted KB", 22)]
    pdf.table_header(cols)
    def _vm_avg(vm, key, fmt=".1f"):
        """Extract average from a dict-valued metric, or scalar directly."""
        v = vm.get(key, 0)
        if isinstance(v, dict):
            v = v.get("average", 0)
        return f"{v:{fmt}}"

    for vi, vm in enumerate(vms):
        verdict = vm.get("verdict", "OK")
        if verdict == "CRITICAL":
            pdf.set_text_color(*_RED)
        elif verdict == "WARNING":
            pdf.set_text_color(*_ORANGE)
        vals = [
            vm.get("vm_name", "")[:35],
            f"{vm.get('cpu_ready_pct', 0):.2f}",
            verdict,
            _vm_avg(vm, "cpu_usage_pct", ".1f"),
            _vm_avg(vm, "cpu_costop_ms", ".0f"),
            _vm_avg(vm, "mem_balloon_kb", ".0f"),
            _vm_avg(vm, "mem_swapped_kb", ".0f"),
            _vm_avg(vm, "mem_active_kb", ".0f"),
            _vm_avg(vm, "mem_granted_kb", ".0f"),
        ]
        pdf.table_row(cols, vals, vi)
        pdf.set_text_color(*_DARK)
    pdf.ln(3)


def _ts_pdf_datastore_io(pdf, ts):
    data = ts.get("datastore_io_stats", {})
    if _ts_is_error(data) or not data:
        return
    datastores = data.get("datastores", [])
    if not datastores:
        return

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"Datastore I/O ({len(datastores)} datastores)", ln=True)

    meta = data.get("sampling_metadata", {})
    if meta:
        pdf.set_font("Helvetica", "", 7)
        pdf.cell(0, 4,
                 f"Interval: {meta.get('interval_id_seconds', 20)}s  |  "
                 f"Window: {meta.get('collection_window_minutes', '?')} min",
                 ln=True)

    cols = [("Datastore", 50), ("RdLat ms", 22), ("WrLat ms", 22),
            ("Rd IOPS", 22), ("Wr IOPS", 22),
            ("Rd KBps", 22), ("Wr KBps", 22)]
    pdf.table_header(cols)

    for di, ds in enumerate(datastores):
        def _avg(k):
            v = ds.get(k, {})
            return f"{v.get('average', 0):.1f}" if isinstance(v, dict) else "N/A"
        vals = [
            ds.get("datastore_name", "")[:32],
            _avg("read_latency_ms"), _avg("write_latency_ms"),
            _avg("read_iops"), _avg("write_iops"),
            _avg("read_kbps"), _avg("write_kbps"),
        ]
        pdf.table_row(cols, vals, di)
    pdf.ln(3)


def _ts_pdf_overcommit(pdf, ts):
    data = ts.get("overcommit_ratios", {})
    if _ts_is_error(data) or not data:
        return

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Overcommit Ratios", ln=True)

    cpu = data.get("cpu", {})
    mem = data.get("memory", {})
    cols = [("Category", 40), ("Metric", 60), ("Value", 30), ("Verdict", 24)]
    pdf.table_header(cols)

    rows = []
    if cpu:
        verdict = cpu.get("verdict", "OK")
        rows.append(("CPU", "vCPU:pCPU ratio",
                      f"{cpu.get('vcpu_per_pcpu', 0):.2f}:1", verdict))
        rows.append(("CPU", f"Total vCPUs / Threads",
                      f"{cpu.get('total_vm_vcpus', 0)} / {cpu.get('host_threads', 0)}",
                      ""))
    if mem:
        verdict = mem.get("verdict", "OK")
        rows.append(("Memory", "Configured / Physical",
                      f"{mem.get('ratio', 0):.2f}:1", verdict))
        rows.append(("Memory", f"VM Configured / Host Total MB",
                      f"{mem.get('total_vm_configured_mb', 0)} / {mem.get('host_total_mb', 0)}",
                      ""))

    for ri, (cat, metric, val, verdict) in enumerate(rows):
        if verdict in ("CRITICAL", "FAIL"):
            pdf.set_text_color(*_RED)
        elif verdict == "WARNING":
            pdf.set_text_color(*_ORANGE)
        pdf.table_row(cols, [cat, metric, val, verdict], ri)
        pdf.set_text_color(*_DARK)
    pdf.ln(3)


def _ts_is_error(data):
    return isinstance(data, dict) and data.get("status") == "error"
