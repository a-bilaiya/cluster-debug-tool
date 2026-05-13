"""Excel (XLSX) export for troubleshoot mode.

Generates an openpyxl workbook with consolidated sheets per data category,
so support engineers can filter / sort each domain independently.

Usage:
    from env_validation_tool.troubleshoot_excel import generate_troubleshoot_xlsx
    generate_troubleshoot_xlsx(cluster_report, "troubleshoot.xlsx")
"""

import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from . import __version__


# ── Styling constants ────────────────────────────────────────────────────
_HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
_HEADER_FILL = PatternFill(start_color="1E3C72", end_color="1E3C72",
                           fill_type="solid")
_HEADER_ALIGN = Alignment(horizontal="center", vertical="center",
                          wrap_text=True)
_THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin"),
)
_ALT_FILL = PatternFill(start_color="F0F5FF", end_color="F0F5FF",
                        fill_type="solid")
_RED_FILL = PatternFill(start_color="FFD6D6", end_color="FFD6D6",
                        fill_type="solid")
_YELLOW_FILL = PatternFill(start_color="FFF8D6", end_color="FFF8D6",
                           fill_type="solid")
_GREEN_FILL = PatternFill(start_color="D6FFD6", end_color="D6FFD6",
                          fill_type="solid")
_SECTION_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
_SECTION_FILL = PatternFill(start_color="2E5090", end_color="2E5090",
                            fill_type="solid")


def generate_troubleshoot_xlsx(cluster_report, output_path):
    """Generate a multi-sheet Excel workbook from troubleshoot data.

    Args:
        cluster_report: Full cluster report dict (same as JSON output).
        output_path: File path for the .xlsx file.

    Returns:
        output_path on success.
    """
    wb = Workbook()
    # Remove the default sheet — we'll create named ones
    wb.remove(wb.active)

    # ── Executive Summary is the very first sheet ──
    _sheet_executive_summary(wb, cluster_report)

    # ── Cluster-level sheets ──
    _sheet_cluster_summary(wb, cluster_report)

    vc_alarms = cluster_report.get("vcenter_alarms")
    if vc_alarms:
        _sheet_vcenter_alarms(wb, vc_alarms)

    # ── Per-host sheets (9 consolidated sheets per host) ──
    for hr in cluster_report.get("hosts", []):
        if hr.get("status") == "error":
            continue
        ts = hr.get("troubleshoot")
        if not ts:
            continue

        ip = hr.get("esxi_ip", "unknown")
        tag = hr.get("host_identity", {}).get("service_tag", "")
        prefix = f"{tag or ip}"

        _merged_overview(wb, prefix, hr, ts)
        _merged_vms(wb, prefix, ts)
        _merged_resources(wb, prefix, ts)
        _merged_performance(wb, prefix, ts)
        _merged_network(wb, prefix, ts)
        _merged_storage(wb, prefix, ts)
        _merged_hardware(wb, prefix, ts)
        _merged_config(wb, prefix, ts)
        _merged_events(wb, prefix, ts)

    # Ensure at least one sheet exists
    if not wb.sheetnames:
        ws = wb.create_sheet("No Data")
        ws["A1"] = "No troubleshoot data collected."

    wb.save(output_path)
    return output_path


# ── Cluster-level sheets ────────────────────────────────────────────────

def _sheet_executive_summary(wb, cluster_report):
    """Create the first 'Summary' sheet with report info, health dashboard, issues, and support info."""
    ws = wb.create_sheet("Summary")

    hosts = cluster_report.get("hosts", [])
    ok_hosts = [h for h in hosts if h.get("status") != "error"]
    timestamp = cluster_report.get("collection_time", datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"))

    row = 1

    # ── Section 1: Report Info ──
    row = _section_header(ws, row, "Report Info")
    kv1 = [
        ("Tool", f"Cluster Debug Tool v{__version__}"),
        ("Generated", timestamp),
        ("Customer", cluster_report.get("customer_name", "") or "—"),
        ("Cluster", cluster_report.get("cluster_name", "") or cluster_report.get("cluster", "") or "—"),
        ("vCenter", cluster_report.get("vcenter_ip", "") or cluster_report.get("vcenter", "") or "—"),
        ("Hosts Scanned", len(ok_hosts)),
    ]
    row = _write_kv_block(ws, row, kv1)
    row += 1

    # ── Section 2: Health Dashboard ──
    row = _section_header(ws, row, "Health Dashboard")

    total_vms = 0
    total_red = 0
    total_yellow = 0

    for hr in ok_hosts:
        ts = hr.get("troubleshoot", {})
        vm_details = ts.get("vm_details", {})
        if isinstance(vm_details, dict) and not _skip_error(vm_details):
            total_vms += len(vm_details.get("vms", []))

        # Count red/yellow from health_summary checks
        health = ts.get("health_summary", {})
        for chk in health.get("checks", []):
            st = str(chk.get("status", "")).upper()
            if st == "RED":
                total_red += 1
            elif st == "YELLOW":
                total_yellow += 1

        # Count FAILs and WARNs from vm_validation
        for vm_check in hr.get("vm_validation", []):
            for chk in vm_check.get("checks", []):
                st = str(chk.get("status", ""))
                if st == "FAIL":
                    total_red += 1
                elif st == "WARN":
                    total_yellow += 1

    if total_red > 0:
        overall_status = "ISSUES FOUND"
    elif total_yellow > 0:
        overall_status = "ISSUES FOUND"
    else:
        overall_status = "HEALTHY"

    kv2 = [
        ("Total Hosts", len(ok_hosts)),
        ("Total VMs", total_vms),
        ("Critical Issues (RED)", total_red),
        ("Warnings (YELLOW)", total_yellow),
        ("Overall Status", overall_status),
    ]
    row = _write_kv_block(ws, row, kv2)

    # Color the Overall Status cell
    status_row = row - 1
    if total_red > 0:
        status_fill = PatternFill(fill_type="solid", fgColor="FFCCCC")
    elif total_yellow > 0:
        status_fill = PatternFill(fill_type="solid", fgColor="FFF2CC")
    else:
        status_fill = PatternFill(fill_type="solid", fgColor="CCFFCC")
    ws.cell(row=status_row, column=2).fill = status_fill
    row += 1

    # ── Section 3: Issues Found ──
    row = _section_header(ws, row, "Issues Found")
    issue_headers = ["Severity", "Host", "Check", "Required", "Actual"]
    _write_header_row(ws, row, issue_headers)
    row += 1

    issues = []

    for hr in ok_hosts:
        ip = hr.get("esxi_ip", "?")
        ts = hr.get("troubleshoot", {})
        health = ts.get("health_summary", {})
        for chk in health.get("checks", []):
            st = str(chk.get("status", "")).upper()
            if st in ("RED", "YELLOW"):
                issues.append({
                    "severity": st,
                    "host": ip,
                    "check": chk.get("category", chk.get("check", "")),
                    "required": "",
                    "actual": str(chk.get("value", chk.get("detail", ""))),
                })

        for vm_check in hr.get("vm_validation", []):
            vm_name = vm_check.get("vm_name", "")
            for chk in vm_check.get("checks", []):
                st = str(chk.get("status", ""))
                if st == "FAIL":
                    issues.append({
                        "severity": "RED",
                        "host": f"{ip} / {vm_name}",
                        "check": chk.get("check", ""),
                        "required": str(chk.get("required", "")),
                        "actual": str(chk.get("actual", "")),
                    })
                elif st == "WARN":
                    issues.append({
                        "severity": "YELLOW",
                        "host": f"{ip} / {vm_name}",
                        "check": chk.get("check", ""),
                        "required": str(chk.get("required", "")),
                        "actual": str(chk.get("actual", "")),
                    })

    # Sort: red first, then yellow
    issues.sort(key=lambda x: (0 if x["severity"] == "RED" else 1))

    if issues:
        for i, issue in enumerate(issues):
            vals = [
                issue["severity"],
                issue["host"],
                issue["check"],
                issue["required"],
                issue["actual"],
            ]
            _write_data_row(ws, row, vals, i)
            if issue["severity"] == "RED":
                row_fill = PatternFill(fill_type="solid", fgColor="FFCCCC")
            else:
                row_fill = PatternFill(fill_type="solid", fgColor="FFF2CC")
            for col in range(1, 6):
                ws.cell(row=row, column=col).fill = row_fill
            row += 1
    else:
        ok_fill = PatternFill(fill_type="solid", fgColor="CCFFCC")
        ws.cell(row=row, column=1, value="All checks passed").fill = ok_fill
        row += 1

    row += 1

    # ── Section 4: How to Share Report ──
    row = _section_header(ws, row, "How to Share This Report")
    support_lines = [
        ("", "To share this report with the support team:"),
        ("1.", "Attach these files to your support case:"),
        ("", "    report.xlsx   (this file)"),
        ("", "    report.json   (raw data)"),
        ("", "    report.pdf    (summary)"),
        ("2.", "Include your cluster identifier and software version."),
        ("3.", "Describe the symptoms you are experiencing."),
    ]
    for key, val in support_lines:
        cell_k = ws.cell(row=row, column=1, value=key)
        cell_v = ws.cell(row=row, column=2, value=val)
        cell_k.font = Font(name="Calibri", bold=bool(key), size=10)
        cell_v.font = Font(name="Calibri", size=10)
        row += 1

    _auto_width(ws)


def _sheet_cluster_summary(wb, cluster_report):
    """Create a one-row-per-host summary sheet as the first sheet."""
    ws = wb.create_sheet("Cluster Summary")

    cluster = cluster_report.get("cluster", "Unknown")
    vcenter = cluster_report.get("vcenter", "N/A")
    coll_time = cluster_report.get("collection_time", "")

    ws.cell(row=1, column=1, value="Cluster").font = Font(bold=True, size=11)
    ws.cell(row=1, column=2, value=cluster).font = Font(size=11)
    ws.cell(row=2, column=1, value="vCenter").font = Font(bold=True, size=11)
    ws.cell(row=2, column=2, value=vcenter).font = Font(size=11)
    ws.cell(row=3, column=1, value="Collected").font = Font(bold=True, size=11)
    ws.cell(row=3, column=2, value=coll_time).font = Font(size=11)

    headers = [
        "ESXi IP", "Status", "Service Tag", "Model", "Connection",
        "Uptime", "Health", "CPU %", "Mem %", "VMs On", "Alarms",
        "CPU Overcommit", "Mem Overcommit", "ESXi Version",
    ]
    header_row = 5
    _write_header_row(ws, header_row, headers)

    hosts = cluster_report.get("hosts", [])
    for i, hr in enumerate(hosts):
        row = header_row + 1 + i

        if hr.get("status") == "error":
            vals = [hr.get("esxi_ip", ""), "ERROR",
                    hr.get("message", "")[:60]]
            vals.extend([""] * (len(headers) - 3))
            _write_data_row(ws, row, vals, i)
            ws.cell(row=row, column=2).fill = _RED_FILL
            continue

        ts = hr.get("troubleshoot", {})
        state = ts.get("host_state", {})
        cap = ts.get("capacity_usage", {})
        health = ts.get("health_summary", {})
        alarms = ts.get("alarms", {})
        overcommit = ts.get("overcommit_ratios", {})
        sysinfo = ts.get("system_info", {})
        ident = hr.get("host_identity", {})

        overall = health.get("overall_status", "")
        cpu_pct = cap.get("cpu", {}).get("usage_pct", "")
        mem_pct = cap.get("memory", {}).get("usage_pct", "")
        cpu_oc = overcommit.get("cpu", {}).get("vcpu_to_thread_ratio", "")
        mem_oc = overcommit.get("memory", {}).get(
            "configured_to_host_ratio", "")

        vals = [
            hr.get("esxi_ip", ""),
            "OK",
            ident.get("service_tag", ""),
            ident.get("model", ""),
            state.get("connection_state", ""),
            state.get("uptime_human", ""),
            overall,
            cpu_pct,
            mem_pct,
            state.get("vm_count_powered_on", ""),
            alarms.get("active_count", 0),
            cpu_oc,
            mem_oc,
            sysinfo.get("esxi_version", ""),
        ]
        _write_data_row(ws, row, vals, i)

        h_fill = {"GREEN": _GREEN_FILL, "YELLOW": _YELLOW_FILL,
                   "RED": _RED_FILL}.get(str(overall).upper())
        if h_fill:
            ws.cell(row=row, column=7).fill = h_fill
        ws.cell(row=row, column=2).fill = _GREEN_FILL

    _auto_width(ws)


def _sheet_vcenter_alarms(wb, vc_alarms):
    """Create a vCenter-wide alarms sheet (datacenter scope)."""
    ws = wb.create_sheet("vCenter Alarms")

    meta = vc_alarms.get("collection_metadata", {})
    ws.cell(row=1, column=1, value="Scope").font = Font(bold=True)
    ws.cell(row=1, column=2,
            value=meta.get("source", "vCenter (datacenter-wide)"))
    ws.cell(row=2, column=1, value="History Window").font = Font(bold=True)
    ws.cell(row=2, column=2,
            value=f"Last {meta.get('window_days', '?')} days")
    ws.cell(row=3, column=1, value="Active Alarms").font = Font(bold=True)
    ws.cell(row=3, column=2,
            value=f"{vc_alarms.get('active_count', 0)} "
                  f"({vc_alarms.get('critical_count', 0)} critical, "
                  f"{vc_alarms.get('warning_count', 0)} warning)")

    row = 5
    ws.cell(row=row, column=1,
            value=f"Currently Active ({vc_alarms.get('active_count', 0)})").font = Font(bold=True)
    row += 1

    active_headers = ["Severity", "Type", "Object", "Alarm Name",
                      "Triggered Time", "Acknowledged By"]
    _write_header_row(ws, row, active_headers)
    row += 1

    active = vc_alarms.get("active_alarms", [])
    if not active:
        ws.cell(row=row, column=1, value="No currently active alarms")
        row += 1
    else:
        for i, a in enumerate(active):
            status = a.get("status", "")
            severity = "Critical" if status == "red" else (
                "Warning" if status == "yellow" else status)
            vals = [
                severity, a.get("object_type"), a.get("object_name"),
                a.get("alarm_name"), a.get("triggered_time"),
                a.get("acknowledged_by"),
            ]
            _write_data_row(ws, row, vals, i)
            fill = _RED_FILL if status == "red" else (
                _YELLOW_FILL if status == "yellow" else None)
            if fill:
                ws.cell(row=row, column=1).fill = fill
            row += 1

    row += 1
    history = vc_alarms.get("alarm_history", [])
    ws.cell(row=row, column=1,
            value=f"Alarm History ({len(history)} events)").font = Font(bold=True)
    row += 1

    if history:
        hist_headers = ["Time", "Event Type", "Alarm Name",
                        "Entity", "Entity Type", "Message"]
        _write_header_row(ws, row, hist_headers)
        row += 1
        for i, h in enumerate(history):
            vals = [
                h.get("time", ""),
                h.get("event_type", ""),
                h.get("alarm_name", ""),
                h.get("entity_name", ""),
                h.get("entity_type", ""),
                (h.get("message", "") or "")[:200],
            ]
            _write_data_row(ws, row, vals, i)
            row += 1
    else:
        ws.cell(row=row, column=1, value="No alarm events in the time window")

    _auto_width(ws)


# ── Merged per-host sheets ──────────────────────────────────────────────

def _merged_overview(wb, prefix, hr, ts):
    """Host Overview + Health Summary + System Info on one sheet."""
    ws = _add_sheet(wb, prefix, "Overview")
    row = 1

    # ── Section 1: Host Identity ──
    row = _section_header(ws, row, "Host Identity")
    state = ts.get("host_state", {})
    cap = ts.get("capacity_usage", {})
    kv = [
        ("ESXi IP", hr.get("esxi_ip", "")),
        ("Service Tag", hr.get("host_identity", {}).get("service_tag", "")),
        ("Model", hr.get("host_identity", {}).get("model", "")),
        ("Connection State", state.get("connection_state", "")),
        ("Power State", state.get("power_state", "")),
        ("Uptime", state.get("uptime_human", "")),
        ("Uptime (sec)", state.get("uptime_seconds", 0)),
        ("VMs Total", state.get("vm_count_total", 0)),
        ("VMs Powered On", state.get("vm_count_powered_on", 0)),
        ("Collection Time", ts.get("collection_time", "")),
    ]
    row = _write_kv_block(ws, row, kv)
    row += 1

    # ── Section 2: Capacity Usage ──
    row = _section_header(ws, row, "Capacity Usage")
    cpu = cap.get("cpu", {})
    mem = cap.get("memory", {})
    kv2 = [
        ("CPU Used GHz", cpu.get("used_ghz", "")),
        ("CPU Total GHz", cpu.get("total_ghz", "")),
        ("CPU Usage %", cpu.get("usage_pct", "")),
        ("Memory Used GB", mem.get("used_gb", "")),
        ("Memory Total GB", mem.get("total_gb", "")),
        ("Memory Usage %", mem.get("usage_pct", "")),
    ]
    row = _write_kv_block(ws, row, kv2)
    row += 1

    # ── Section 3: Health Summary ──
    data = ts.get("health_summary", {})
    if not _skip_error(data):
        row = _section_header(ws, row, "Health Summary")
        overall = data.get("overall_status", "UNKNOWN")
        ws.cell(row=row, column=1, value="Overall Status").font = Font(bold=True, size=12)
        cell_status = ws.cell(row=row, column=2, value=overall)
        cell_status.font = Font(bold=True, size=12)
        h_fill = {"GREEN": _GREEN_FILL, "YELLOW": _YELLOW_FILL,
                   "RED": _RED_FILL}.get(overall.upper())
        if h_fill:
            cell_status.fill = h_fill
        row += 1
        ws.cell(row=row, column=1, value=data.get("summary_text", ""))
        row += 1

        checks = data.get("checks", [])
        if checks:
            row += 1
            headers = ["Category", "Status", "Value", "Detail"]
            _write_header_row(ws, row, headers)
            row += 1
            for i, c in enumerate(checks):
                st = c.get("status", "GREEN").upper()
                vals = [c.get("category", ""), st,
                        str(c.get("value", "")), c.get("detail", "")]
                _write_data_row(ws, row, vals, i)
                st_fill = {"GREEN": _GREEN_FILL, "YELLOW": _YELLOW_FILL,
                            "RED": _RED_FILL}.get(st)
                if st_fill:
                    ws.cell(row=row, column=2).fill = st_fill
                row += 1
        row += 1

    # ── Section 4: System Info ──
    sysdata = ts.get("system_info", {})
    if not _skip_error(sysdata):
        row = _section_header(ws, row, "System Info")
        kv3 = [
            ("ESXi Version", sysdata.get("esxi_version", "")),
            ("ESXi Build", sysdata.get("esxi_build", "")),
            ("ESXi Full Name", sysdata.get("esxi_full_name", "")),
            ("ESXi Patch Level", sysdata.get("esxi_patch_level", "")),
            ("API Version", sysdata.get("esxi_api_version", "")),
            ("OS Type", sysdata.get("os_type", "")),
            ("Server Model", sysdata.get("model", "")),
            ("Server Vendor", sysdata.get("vendor", "")),
            ("Serial Number", sysdata.get("serial", "")),
            ("UUID", sysdata.get("uuid", "")),
            ("BIOS Version", sysdata.get("bios_version", "")),
            ("BIOS Vendor", sysdata.get("bios_vendor", "")),
            ("BIOS Release Date", sysdata.get("bios_release_date", "")),
            ("NUMA Nodes", sysdata.get("numa_nodes", 0)),
        ]
        for k, v in sysdata.items():
            if k.startswith("id_"):
                kv3.append((k.replace("id_", ""), v))
        row = _write_kv_block(ws, row, kv3)
        row += 1

        # Licenses sub-table
        licenses = sysdata.get("licenses", [])
        if licenses:
            row = _section_header(ws, row, "Licenses")
            lic_headers = ["Name", "Key", "Used", "Total"]
            _write_header_row(ws, row, lic_headers)
            row += 1
            for i, lic in enumerate(licenses):
                vals = [lic.get("name"), lic.get("key"),
                        lic.get("used"), lic.get("total")]
                _write_data_row(ws, row, vals, i)
                row += 1

    _auto_width(ws)


def _merged_vms(wb, prefix, ts):
    """VMs + VM Disks + VM NICs + Guest NICs + Snapshots + Contention + AutoStart."""
    vm_data = ts.get("vm_details", {})
    contention_data = ts.get("vm_contention_stats", {})
    autostart_data = ts.get("vm_autostart")

    has_vms = not _skip_error(vm_data) and vm_data.get("vms")
    has_contention = not _skip_error(contention_data) and contention_data.get("vms")
    has_autostart = not _skip_error(autostart_data)

    if not has_vms and not has_contention and not has_autostart:
        return

    ws = _add_sheet(wb, prefix, "VMs")
    row = 1

    # ── Section 1: VM Summary ──
    vms = vm_data.get("vms", []) if not _skip_error(vm_data) else []
    if vms:
        row = _section_header(ws, row, f"VM Summary ({len(vms)} VMs)")
        headers = ["VM Name", "Power State", "Guest OS", "VM Version", "vCPU",
                    "Memory MB", "Guest State", "Tools Status", "Hostname",
                    "IP Address", "Has Snapshots", "Annotation"]
        _write_header_row(ws, row, headers)
        row += 1
        for i, vm in enumerate(vms):
            vals = [
                vm.get("vm_name"), vm.get("power_state"), vm.get("guest_os"),
                vm.get("vm_version"), vm.get("num_cpu"), vm.get("memory_mb"),
                vm.get("guest_state"), vm.get("tools_status"),
                vm.get("guest_hostname"), vm.get("guest_ip"),
                "Yes" if vm.get("has_snapshots") else "No",
                (vm.get("annotation") or "")[:80],
            ]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 2: VM Disks ──
    all_disks = []
    for vm in vms:
        for d in vm.get("disks", []):
            all_disks.append((vm.get("vm_name", ""), d))
    if all_disks:
        row = _section_header(ws, row, f"VM Disks ({len(all_disks)})")
        headers2 = ["VM Name", "Disk Label", "Capacity GB",
                     "Provisioning", "Disk Mode", "Backing File"]
        _write_header_row(ws, row, headers2)
        row += 1
        for i, (name, d) in enumerate(all_disks):
            vals = [name, d.get("label"), d.get("capacity_gb"),
                    d.get("provisioning", ""), d.get("disk_mode", ""),
                    d.get("backing_file")]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 3: VM NICs ──
    all_nics = []
    for vm in vms:
        for n in vm.get("nics", []):
            all_nics.append((vm.get("vm_name", ""), n))
    if all_nics:
        row = _section_header(ws, row, f"VM NICs ({len(all_nics)})")
        headers3 = ["VM Name", "NIC Label", "Type", "Network", "MAC",
                     "Connected"]
        _write_header_row(ws, row, headers3)
        row += 1
        for i, (name, n) in enumerate(all_nics):
            vals = [name, n.get("label"), n.get("type"), n.get("network"),
                    n.get("mac"), "Yes" if n.get("connected") else "No"]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 4: VM Guest NICs ──
    all_guest_nics = []
    for vm in vms:
        for gn in vm.get("guest_nics", []):
            all_guest_nics.append((vm.get("vm_name", ""), gn))
    if all_guest_nics:
        row = _section_header(ws, row, f"VM Guest NICs ({len(all_guest_nics)})")
        headers4 = ["VM Name", "Network", "IP Addresses", "MAC", "Connected"]
        _write_header_row(ws, row, headers4)
        row += 1
        for i, (name, gn) in enumerate(all_guest_nics):
            ips = ", ".join(gn.get("ip_addresses", []))
            vals = [name, gn.get("network"), ips, gn.get("mac"),
                    "Yes" if gn.get("connected") else "No"]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 5: Snapshots ──
    all_snaps = []
    for vm in vms:
        for s in vm.get("snapshots", []):
            all_snaps.append((vm.get("vm_name", ""), s))
    if all_snaps:
        row = _section_header(ws, row, f"Snapshots ({len(all_snaps)})")
        headers5 = ["VM Name", "Snapshot Name", "Description",
                     "Create Time", "State"]
        _write_header_row(ws, row, headers5)
        row += 1
        for i, (name, s) in enumerate(all_snaps):
            vals = [name, s.get("name"), s.get("description"),
                    s.get("create_time"), s.get("state")]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 6: VM Contention Stats ──
    if has_contention:
        cont_vms = contention_data.get("vms", [])
        row = _section_header(ws, row, f"VM Contention ({len(cont_vms)} VMs)")

        meta = contention_data.get("sampling_metadata", {})
        if meta:
            ws.cell(row=row, column=1, value="Collection Window").font = Font(bold=True)
            ws.cell(row=row, column=2,
                    value=f"{meta.get('collection_window_minutes', '?')} min, "
                          f"{meta.get('interval_id_seconds', 20)}s interval, "
                          f"up to {meta.get('max_samples_requested', '?')} samples")
            row += 1

        headers6 = ["VM Name", "CPU Ready %", "Verdict", "CPU Usage %",
                     "CoStop ms", "Balloon KB", "Swap KB", "Active KB", "Granted KB"]
        _write_header_row(ws, row, headers6)
        row += 1

        def _vm_avg(vm, key):
            v = vm.get(key, 0)
            return v.get("average", 0) if isinstance(v, dict) else v

        for i, vm in enumerate(cont_vms):
            verdict = vm.get("verdict", "OK")
            vals = [
                vm.get("vm_name", ""),
                vm.get("cpu_ready_pct", 0),
                verdict,
                _vm_avg(vm, "cpu_usage_pct"),
                _vm_avg(vm, "cpu_costop_ms"),
                _vm_avg(vm, "mem_balloon_kb"),
                _vm_avg(vm, "mem_swapped_kb"),
                _vm_avg(vm, "mem_active_kb"),
                _vm_avg(vm, "mem_granted_kb"),
            ]
            _write_data_row(ws, row, vals, i)
            vfill = {"CRITICAL": _RED_FILL, "WARNING": _YELLOW_FILL}.get(verdict)
            if vfill:
                ws.cell(row=row, column=3).fill = vfill
            row += 1
        row += 1

    # ── Section 7: VM AutoStart ──
    if has_autostart:
        row = _section_header(ws, row, "VM AutoStart")
        kv = [
            ("AutoStart Enabled", autostart_data.get("enabled", False)),
            ("Default Start Delay", autostart_data.get("default_start_delay", "")),
            ("Default Stop Delay", autostart_data.get("default_stop_delay", "")),
            ("Default Stop Action", autostart_data.get("default_stop_action", "")),
            ("Wait for Heartbeat", autostart_data.get("default_wait_for_heartbeat", "")),
        ]
        auto_vms = autostart_data.get("vms", [])
        for v in auto_vms:
            kv.append(("", ""))
            kv.append((f"VM: {v.get('vm_name', '')}", ""))
            kv.append(("  Start Order", v.get("start_order", "")))
            kv.append(("  Start Delay", v.get("start_delay", "")))
            kv.append(("  Start Action", v.get("start_action", "")))
            kv.append(("  Stop Delay", v.get("stop_delay", "")))
            kv.append(("  Stop Action", v.get("stop_action", "")))
        row = _write_kv_block(ws, row, kv)

    _auto_width(ws)


def _merged_resources(wb, prefix, ts):
    """Datastores + Memory Allocation + CPU Allocation + Overcommit."""
    cap_data = ts.get("capacity_usage", {})
    mem_alloc = ts.get("memory_allocation", {})
    cpu_alloc = ts.get("cpu_allocation", {})
    overcommit = ts.get("overcommit_ratios", {})

    datastores = cap_data.get("datastores", []) if not _skip_error(cap_data) else []
    mem_vms = mem_alloc.get("per_vm", []) if not _skip_error(mem_alloc) else []
    cpu_vms = cpu_alloc.get("per_vm", []) if not _skip_error(cpu_alloc) else []
    has_overcommit = not _skip_error(overcommit)

    if not datastores and not mem_vms and not cpu_vms and not has_overcommit:
        return

    ws = _add_sheet(wb, prefix, "Resources")
    row = 1

    # ── Section 1: Datastores ──
    if datastores:
        row = _section_header(ws, row, f"Datastores ({len(datastores)})")
        headers = ["Name", "Type", "Capacity GB", "Free GB", "Used GB", "Usage %"]
        _write_header_row(ws, row, headers)
        row += 1
        for i, ds in enumerate(datastores):
            vals = [
                ds.get("name"), ds.get("type"),
                ds.get("capacity_gb"), ds.get("free_gb"),
                ds.get("used_gb"), ds.get("usage_pct"),
            ]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 2: Memory Allocation ──
    if mem_vms:
        # Host-level summary
        mem_verdict = mem_alloc.get("reservation_verdict", "")
        mem_kv = [
            ("Host Total", f"{mem_alloc.get('host_total_gb', '?')} GB"),
            ("Total Reservation (all VMs)", f"{mem_alloc.get('total_reservation_gb', '?')} GB"),
            ("Total Reservation (powered-on)", f"{mem_alloc.get('total_reservation_gb_powered_on', '?')} GB"),
            ("Reservation Headroom", f"{mem_alloc.get('reservation_headroom_gb', '?')} GB"),
            ("Reservation Verdict", mem_verdict if mem_verdict else "N/A"),
        ]
        row = _section_header(ws, row, f"Memory Allocation ({len(mem_vms)} VMs)")
        row = _write_kv_block(ws, row, mem_kv)
        # Color verdict
        verdict_row = row - 1
        vfill = {"OK": _GREEN_FILL, "OVERCOMMITTED": _RED_FILL}.get(mem_verdict)
        if vfill:
            ws.cell(row=verdict_row, column=2).fill = vfill
        row += 1
        headers2 = ["VM Name", "Power State", "Config MB",
                     "Reservation MB", "Limit MB", "Effective Limit MB",
                     "Shares", "Level", "Reservation Met"]
        _write_header_row(ws, row, headers2)
        row += 1
        for i, v in enumerate(mem_vms):
            limit = v.get("limit_mb", -1)
            vals = [
                v.get("vm_name"), v.get("power_state"),
                v.get("configured_mb"), v.get("reservation_mb"),
                "Unlimited" if limit == -1 else limit,
                v.get("effective_limit_mb", ""),
                v.get("shares_value"), v.get("shares_level"),
                v.get("reservation_met", ""),
            ]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 3: CPU Allocation ──
    if cpu_vms:
        # Host-level summary
        cpu_verdict = cpu_alloc.get("reservation_verdict", "")
        cpu_kv = [
            ("Host Total", f"{cpu_alloc.get('host_total_mhz', '?')} MHz ({cpu_alloc.get('host_cores', '?')} cores × {cpu_alloc.get('host_mhz_per_core', '?')} MHz)"),
            ("Host Cores / Threads", f"{cpu_alloc.get('host_cores', '?')} / {cpu_alloc.get('host_threads', '?')}"),
            ("Total Reservation (all VMs)", f"{cpu_alloc.get('total_reservation_mhz', '?')} MHz"),
            ("Total Reservation (powered-on)", f"{cpu_alloc.get('total_reservation_mhz_powered_on', '?')} MHz"),
            ("Reservation Headroom", f"{cpu_alloc.get('reservation_headroom_mhz', '?')} MHz"),
            ("Reservation Verdict", cpu_verdict if cpu_verdict else "N/A"),
        ]
        row = _section_header(ws, row, f"CPU Allocation ({len(cpu_vms)} VMs)")
        row = _write_kv_block(ws, row, cpu_kv)
        # Color verdict
        verdict_row = row - 1
        vfill = {"OK": _GREEN_FILL, "OVERCOMMITTED": _RED_FILL}.get(cpu_verdict)
        if vfill:
            ws.cell(row=verdict_row, column=2).fill = vfill
        row += 1
        headers3 = ["VM Name", "Power State", "vCPU",
                     "Reservation MHz", "Limit MHz", "Effective Limit MHz",
                     "VM Max MHz", "Shares", "Level", "Reservation Met"]
        _write_header_row(ws, row, headers3)
        row += 1
        for i, v in enumerate(cpu_vms):
            limit = v.get("limit_mhz", -1)
            vals = [
                v.get("vm_name"), v.get("power_state"),
                v.get("num_cpu"), v.get("reservation_mhz"),
                "Unlimited" if limit == -1 else limit,
                v.get("effective_limit_mhz", ""),
                v.get("vm_max_mhz", ""),
                v.get("shares_value"), v.get("shares_level"),
                v.get("reservation_met", ""),
            ]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 4: Overcommit Ratios ──
    if has_overcommit:
        row = _section_header(ws, row, "Overcommit Ratios")
        cpu_oc = overcommit.get("cpu", {})
        mem_oc = overcommit.get("memory", {})
        kv = []
        if cpu_oc:
            kv.extend([
                ("CPU vCPU:pCPU Ratio", f"{cpu_oc.get('vcpu_per_pcpu', 0):.2f}:1"),
                ("CPU Verdict", cpu_oc.get("verdict", "OK")),
                ("Total VM vCPUs", cpu_oc.get("total_vm_vcpus", 0)),
                ("Host Threads", cpu_oc.get("host_threads", 0)),
            ])
        if mem_oc:
            if kv:
                kv.append(("", ""))
            kv.extend([
                ("Memory Overcommit Ratio", f"{mem_oc.get('ratio', 0):.2f}:1"),
                ("Memory Verdict", mem_oc.get("verdict", "OK")),
                ("Total VM Configured MB", mem_oc.get("total_vm_configured_mb", 0)),
                ("Host Total MB", mem_oc.get("host_total_mb", 0)),
            ])
        row = _write_kv_block(ws, row, kv)
        # Color verdict cells
        for i, (key, val) in enumerate(kv):
            if "Verdict" in key:
                r = row - len(kv) + i
                vfill = {"CRITICAL": _RED_FILL, "WARNING": _YELLOW_FILL,
                          "OK": _GREEN_FILL}.get(str(val))
                if vfill:
                    ws.cell(row=r, column=2).fill = vfill

    _auto_width(ws)


def _merged_performance(wb, prefix, ts):
    """Performance Stats + IO Stats (incl per-disk, per-NIC) + Datastore IO."""
    perf_data = ts.get("performance_stats", {})
    io_data = ts.get("io_stats", {})
    ds_io_data = ts.get("datastore_io_stats", {})

    has_perf = not _skip_error(perf_data)
    has_io = not _skip_error(io_data)
    has_ds = not _skip_error(ds_io_data) and ds_io_data.get("datastores")

    if not has_perf and not has_io and not has_ds:
        return

    ws = _add_sheet(wb, prefix, "Performance")
    row = 1

    # ── Section 1: Performance Stats ──
    if has_perf:
        row = _section_header(ws, row, "Performance Stats")
        interval = perf_data.get("interval_minutes", "?")
        sampling = perf_data.get("sampling_interval_seconds", 20)
        max_samp = perf_data.get("total_samples_requested", "?")
        ws.cell(row=row, column=1, value="Collection Window").font = Font(bold=True)
        ws.cell(row=row, column=2,
                value=f"{interval} min, {sampling}s sampling, up to {max_samp} samples")
        row += 1

        headers = ["Metric", "Latest", "Average", "Minimum", "Maximum", "Samples"]
        _write_header_row(ws, row, headers)
        row += 1

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
            stats = perf_data.get(key, {})
            if isinstance(stats, dict) and "latest" in stats:
                vals = [
                    label, stats["latest"], stats["average"],
                    stats["minimum"], stats["maximum"], stats.get("samples", 0),
                ]
                _write_data_row(ws, row, vals, ri)
                row += 1
                ri += 1
        row += 1

    # ── Section 2: IO Stats ──
    if has_io:
        row = _section_header(ws, row, "IO Stats")
        interval = io_data.get("interval_minutes", "?")
        sampling = io_data.get("sampling_interval_seconds", 20)
        max_samp = io_data.get("total_samples_requested", "?")
        ws.cell(row=row, column=1, value="Collection Window").font = Font(bold=True)
        ws.cell(row=row, column=2,
                value=f"{interval} min, {sampling}s sampling, up to {max_samp} samples")
        row += 1

        io_headers = ["Metric", "Latest", "Average", "Minimum", "Maximum", "Samples"]
        _write_header_row(ws, row, io_headers)
        row += 1

        io_metrics = [
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
        for label, key in io_metrics:
            stats = io_data.get(key, {})
            if isinstance(stats, dict) and "latest" in stats:
                vals = [
                    label, stats["latest"], stats["average"],
                    stats["minimum"], stats["maximum"], stats.get("samples", 0),
                ]
                _write_data_row(ws, row, vals, ri)
                row += 1
                ri += 1
        row += 1

        # ── Section 3: Per-Disk IO ──
        per_disk = io_data.get("per_disk", [])
        if per_disk:
            row = _section_header(ws, row, f"Per-Disk IO ({len(per_disk)} disks)")
            pd_headers = ["Device", "Rd Lat Avg", "Wr Lat Avg",
                           "Rd IOPS Avg", "Wr IOPS Avg", "Rd KBps Avg",
                           "Wr KBps Avg", "Cmds Aborted Max", "Bus Resets Max"]
            _write_header_row(ws, row, pd_headers)
            row += 1
            for di, dd in enumerate(per_disk):
                def _avg_val(k, _dd=dd):
                    v = _dd.get(k, {})
                    return v.get("average", 0) if v else 0
                def _max_val(k, _dd=dd):
                    v = _dd.get(k, {})
                    return v.get("maximum", 0) if v else 0
                vals = [
                    dd.get("device", ""),
                    _avg_val("read_latency_ms"), _avg_val("write_latency_ms"),
                    _avg_val("read_iops"), _avg_val("write_iops"),
                    _avg_val("read_kbps"), _avg_val("write_kbps"),
                    _max_val("commands_aborted"), _max_val("bus_resets"),
                ]
                _write_data_row(ws, row, vals, di)
                row += 1
            row += 1

        # ── Section 4: Per-NIC IO ──
        per_nic = io_data.get("per_nic", [])
        if per_nic:
            row = _section_header(ws, row, f"Per-NIC IO ({len(per_nic)} NICs)")
            pn_headers = ["Interface", "RX KBps Avg", "TX KBps Avg",
                           "Pkts RX Avg", "Pkts TX Avg", "Drop RX Max",
                           "Drop TX Max", "Err RX Max", "Err TX Max"]
            _write_header_row(ws, row, pn_headers)
            row += 1
            for ni, nd in enumerate(per_nic):
                def _avg_n(k, _nd=nd):
                    v = _nd.get(k, {})
                    return v.get("average", 0) if v else 0
                def _max_n(k, _nd=nd):
                    v = _nd.get(k, {})
                    return v.get("maximum", 0) if v else 0
                vals = [
                    nd.get("interface", ""),
                    _avg_n("rx_kbps"), _avg_n("tx_kbps"),
                    _avg_n("packets_rx"), _avg_n("packets_tx"),
                    _max_n("dropped_rx"), _max_n("dropped_tx"),
                    _max_n("errors_rx"), _max_n("errors_tx"),
                ]
                _write_data_row(ws, row, vals, ni)
                row += 1
            row += 1

        # Bottleneck warnings
        bottlenecks = io_data.get("bottlenecks", [])
        if bottlenecks:
            row = _section_header(ws, row, "Bottleneck Warnings")
            for bi, b in enumerate(bottlenecks):
                ws.cell(row=row, column=1, value=b).fill = _RED_FILL
                row += 1
            row += 1

    # ── Section 5: Datastore IO Stats ──
    if has_ds:
        datastores = ds_io_data.get("datastores", [])
        row = _section_header(ws, row, f"Datastore IO ({len(datastores)} datastores)")

        meta = ds_io_data.get("sampling_metadata", {})
        if meta:
            ws.cell(row=row, column=1, value="Collection Window").font = Font(bold=True)
            ws.cell(row=row, column=2,
                    value=f"{meta.get('collection_window_minutes', '?')} min, "
                          f"{meta.get('interval_id_seconds', 20)}s interval")
            row += 1

        ds_headers = ["Datastore", "Rd Lat Avg ms", "Wr Lat Avg ms",
                       "Rd IOPS Avg", "Wr IOPS Avg", "Rd KBps Avg", "Wr KBps Avg"]
        _write_header_row(ws, row, ds_headers)
        row += 1

        for i, ds in enumerate(datastores):
            def _avg(k, _ds=ds):
                v = _ds.get(k, {})
                return v.get("average", 0) if isinstance(v, dict) else 0
            vals = [
                ds.get("datastore_name", ""),
                _avg("read_latency_ms"), _avg("write_latency_ms"),
                _avg("read_iops"), _avg("write_iops"),
                _avg("read_kbps"), _avg("write_kbps"),
            ]
            _write_data_row(ws, row, vals, i)
            row += 1

    _auto_width(ws)


def _merged_network(wb, prefix, ts):
    """pNICs + vSwitches + PortGroups + VMkernel + DNS/NTP + CDP/LLDP + TCP/IP + DVS."""
    net_data = ts.get("network_config", {})
    tcpip_data = ts.get("tcpip_stacks")
    dvs_data = ts.get("dvs_config")

    has_net = not _skip_error(net_data)
    has_tcp = not _skip_error(tcpip_data) and tcpip_data.get("stacks")
    has_dvs = not _skip_error(dvs_data) and dvs_data.get("proxy_switches")

    if not has_net and not has_tcp and not has_dvs:
        return

    ws = _add_sheet(wb, prefix, "Network")
    row = 1

    if has_net:
        # ── Section 1: Physical NICs ──
        pnics = net_data.get("pnics", [])
        if pnics:
            row = _section_header(ws, row, f"Physical NICs ({len(pnics)})")
            headers = ["Device", "MAC", "Driver", "Link Speed Mb", "Link Up",
                        "TSO", "CSO", "Wake-on-LAN"]
            _write_header_row(ws, row, headers)
            row += 1
            for i, p in enumerate(pnics):
                off = p.get("offload", {})
                vals = [p.get("device"), p.get("mac"), p.get("driver"),
                        p.get("link_speed_mb"),
                        "Yes" if p.get("link_up") else "No",
                        "Yes" if off.get("tso_enabled") else "No",
                        "Yes" if off.get("cso_enabled") else "No",
                        "Yes" if off.get("wake_on_lan") else "No"]
                _write_data_row(ws, row, vals, i)
                row += 1
            row += 1

        # ── Section 2: vSwitches ──
        vswitches = net_data.get("vswitches", [])
        if vswitches:
            row = _section_header(ws, row, f"vSwitches ({len(vswitches)})")
            headers2 = ["Name", "Num Ports", "MTU", "pNICs",
                         "Promiscuous", "MAC Changes", "Forged Transmits",
                         "Teaming Policy", "Active NICs", "Standby NICs"]
            _write_header_row(ws, row, headers2)
            row += 1
            for i, vs in enumerate(vswitches):
                pol = vs.get("policy", {})
                sec = pol.get("security", {})
                team = pol.get("nic_teaming", {})
                vals = [vs.get("name"), vs.get("num_ports"), vs.get("mtu"),
                        ", ".join(vs.get("pnics", [])),
                        str(sec.get("allow_promiscuous", "")),
                        str(sec.get("mac_changes", "")),
                        str(sec.get("forged_transmits", "")),
                        team.get("policy", ""),
                        ", ".join(team.get("active_nics", [])) if team.get("active_nics") else "",
                        ", ".join(team.get("standby_nics", [])) if team.get("standby_nics") else ""]
                _write_data_row(ws, row, vals, i)
                row += 1
            row += 1

        # ── Section 3: Port Groups ──
        portgroups = net_data.get("portgroups", [])
        if portgroups:
            row = _section_header(ws, row, f"Port Groups ({len(portgroups)})")
            headers3 = ["Name", "VLAN ID", "vSwitch",
                         "Promiscuous", "MAC Changes", "Forged Transmits"]
            _write_header_row(ws, row, headers3)
            row += 1
            for i, pg in enumerate(portgroups):
                pol = pg.get("policy_override", {})
                sec = pol.get("security", {}) if pol else {}
                vals = [pg.get("name"), pg.get("vlan_id"), pg.get("vswitch"),
                        str(sec.get("allow_promiscuous", "")),
                        str(sec.get("mac_changes", "")),
                        str(sec.get("forged_transmits", ""))]
                _write_data_row(ws, row, vals, i)
                row += 1
            row += 1

        # ── Section 4: VMkernel Adapters ──
        vkernel = net_data.get("vmkernel_adapters", [])
        if vkernel:
            row = _section_header(ws, row, f"VMkernel Adapters ({len(vkernel)})")
            headers4 = ["Device", "Portgroup", "MAC", "IP", "Subnet", "DHCP",
                         "MTU", "NetStack", "vMotion"]
            _write_header_row(ws, row, headers4)
            row += 1
            for i, vk in enumerate(vkernel):
                vals = [vk.get("device"), vk.get("portgroup"), vk.get("mac"),
                        vk.get("ip"), vk.get("subnet"),
                        "Yes" if vk.get("dhcp") else "No",
                        vk.get("mtu", ""),
                        vk.get("netstack", ""),
                        "Yes" if vk.get("vmotion_enabled") else "No"]
                _write_data_row(ws, row, vals, i)
                row += 1
            # IPv6 rows
            for vk in vkernel:
                ipv6 = vk.get("ipv6", {})
                for a in ipv6.get("addresses", []):
                    vals = [vk.get("device"), "IPv6",
                            "", a.get("address", ""),
                            str(a.get("prefix_length", "")),
                            a.get("origin", ""),
                            "", "", ""]
                    _write_data_row(ws, row, vals, row - 2)
                    row += 1
            row += 1

        # ── Section 5: DNS / NTP ──
        dns = net_data.get("dns", {})
        if dns:
            row = _section_header(ws, row, "DNS / NTP")
            ntp = net_data.get("ntp", {})
            kv = [
                ("Hostname", dns.get("hostname", "")),
                ("Domain", dns.get("domain", "")),
                ("DNS Servers", ", ".join(dns.get("servers", []))),
                ("Search Domains", ", ".join(dns.get("search_domains", []))),
                ("", ""),
                ("NTP Servers", ", ".join(ntp.get("servers", []))),
                ("Timezone", ntp.get("timezone", "")),
            ]
            row = _write_kv_block(ws, row, kv)
            row += 1

        # ── Section 6: CDP / LLDP ──
        cdp_lldp = net_data.get("cdp_lldp", [])
        if cdp_lldp:
            row = _section_header(ws, row, f"CDP / LLDP ({len(cdp_lldp)})")
            headers6 = ["Device", "Switch ID", "Port ID", "Switch Address",
                         "LLDP Chassis", "LLDP Port"]
            _write_header_row(ws, row, headers6)
            row += 1
            for i, c in enumerate(cdp_lldp):
                vals = [c.get("device"), c.get("switch_id"), c.get("port_id"),
                        c.get("switch_address"), c.get("lldp_chassis"),
                        c.get("lldp_port")]
                _write_data_row(ws, row, vals, i)
                row += 1
            row += 1

    # ── Section 7: TCP/IP Stacks ──
    if has_tcp:
        stacks = tcpip_data.get("stacks", [])
        row = _section_header(ws, row, f"TCP/IP Stacks ({len(stacks)})")
        headers7 = ["Key", "Name", "DNS Servers", "DNS Search", "Hostname",
                     "Domain", "Default GW", "IPv6 GW", "IPv6 Enabled"]
        _write_header_row(ws, row, headers7)
        row += 1
        for i, s in enumerate(stacks):
            vals = [
                s.get("key", ""), s.get("name", ""),
                ", ".join(s.get("dns_servers", [])),
                ", ".join(s.get("dns_search", [])),
                s.get("dns_hostname", ""), s.get("dns_domain", ""),
                s.get("default_gateway", ""), s.get("ipv6_default_gateway", ""),
                s.get("ip_v6_enabled", ""),
            ]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 8: DVS Config ──
    if has_dvs:
        switches = dvs_data.get("proxy_switches", [])
        row = _section_header(ws, row, f"DVS Config ({len(switches)})")
        headers8 = ["DVS Name", "UUID", "Num Ports", "Configured Ports",
                     "Available Ports", "MTU", "Uplink pNICs"]
        _write_header_row(ws, row, headers8)
        row += 1
        for i, s in enumerate(switches):
            vals = [
                s.get("dvs_name", ""), s.get("dvs_uuid", ""),
                s.get("num_ports", ""), s.get("configured_num_ports", ""),
                s.get("num_ports_available", ""), s.get("mtu", ""),
                ", ".join(s.get("uplink_pnics", [])),
            ]
            _write_data_row(ws, row, vals, i)
            row += 1

    _auto_width(ws)


def _merged_storage(wb, prefix, ts):
    """iSCSI + HBAs + SCSI LUNs + Multipath + FS Volumes + VMFS Extents."""
    data = ts.get("storage_config", {})
    if _skip_error(data):
        return

    ws = _add_sheet(wb, prefix, "Storage")
    row = 1

    # ── Section 1: iSCSI ──
    if data.get("iscsi_enabled"):
        row = _section_header(ws, row, "iSCSI Config")
        ws.cell(row=row, column=1, value="Software iSCSI").font = Font(bold=True)
        ws.cell(row=row, column=2, value="ENABLED")
        row += 1
        targets = data.get("iscsi_targets", [])
        if targets:
            t_headers = ["Type", "Address", "Port", "HBA Device", "IQN"]
            _write_header_row(ws, row, t_headers)
            row += 1
            for i, t in enumerate(targets):
                vals = [t.get("type"), t.get("address"), t.get("port"),
                        t.get("hba_device"), t.get("iscsi_name", "")]
                _write_data_row(ws, row, vals, i)
                row += 1
        row += 1

    # ── Section 2: HBAs ──
    hbas = data.get("hbas", [])
    if hbas:
        row = _section_header(ws, row, f"HBAs ({len(hbas)})")
        headers = ["Device", "Type", "Model", "Driver", "Status", "PCI",
                    "iSCSI Name", "iSCSI Alias"]
        _write_header_row(ws, row, headers)
        row += 1
        for i, h in enumerate(hbas):
            vals = [h.get("device"), h.get("type"), h.get("model"),
                    h.get("driver"), h.get("status"), h.get("pci"),
                    h.get("iscsi_name", ""), h.get("iscsi_alias", "")]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 3: SCSI LUNs ──
    luns = data.get("scsi_luns", [])
    if luns:
        row = _section_header(ws, row, f"SCSI LUNs ({len(luns)})")
        headers2 = ["Canonical Name", "Display Name", "Model", "Vendor",
                     "Capacity GB", "LUN Type", "State", "Revision",
                     "UUID", "Serial Number", "Queue Depth", "SSD"]
        _write_header_row(ws, row, headers2)
        row += 1
        for i, l in enumerate(luns):
            ssd = "Yes" if l.get("ssd") is True else ("No" if l.get("ssd") is False else "")
            vals = [l.get("canonical_name"), l.get("display_name"),
                    l.get("model"), l.get("vendor"), l.get("capacity_gb"),
                    l.get("lun_type"), l.get("operational_state"),
                    l.get("revision"), l.get("uuid", ""),
                    l.get("serial_number", ""),
                    l.get("queue_depth") if l.get("queue_depth") is not None else "",
                    ssd]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 4: Multipath ──
    multipath = data.get("multipath", [])
    if multipath:
        row = _section_header(ws, row, f"Multipath ({len(multipath)})")
        headers3 = ["LUN ID", "Policy", "Path Count", "Active Paths",
                     "Path Names", "Path States"]
        _write_header_row(ws, row, headers3)
        row += 1
        for i, mp in enumerate(multipath):
            paths = mp.get("paths", [])
            names = ", ".join(p.get("name", "") for p in paths)
            states = ", ".join(p.get("state", "") for p in paths)
            active = sum(1 for p in paths if p.get("is_working"))
            vals = [mp.get("lun_id"), mp.get("policy"),
                    mp.get("path_count"), active, names, states]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 5: File System Volumes ──
    volumes = data.get("file_system_volumes", [])
    if volumes:
        row = _section_header(ws, row, f"File System Volumes ({len(volumes)})")
        headers4 = ["Name", "Type", "Capacity GB", "VMFS Version",
                     "SSD", "Local", "Path", "Accessible", "Mounted",
                     "Access Mode", "UUID", "NFS Host", "NFS Path"]
        _write_header_row(ws, row, headers4)
        row += 1
        for i, v in enumerate(volumes):
            vals = [v.get("name"), v.get("type"), v.get("capacity_gb"),
                    v.get("vmfs_version", ""), v.get("ssd", ""),
                    v.get("local", ""), v.get("path", ""),
                    "Yes" if v.get("accessible") else "No",
                    "Yes" if v.get("mounted") else "No",
                    v.get("access_mode", ""),
                    v.get("uuid", ""),
                    v.get("nfs_remote_host", ""),
                    v.get("nfs_remote_path", "")]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

        # ── Section 6: VMFS Extents ──
        ext_vols = [v for v in volumes if v.get("extents")]
        if ext_vols:
            row = _section_header(ws, row, "VMFS Extents")
            _write_header_row(ws, row, ["Volume", "Disk Name", "Partition"])
            row += 1
            idx = 0
            for v in ext_vols:
                for ext in v["extents"]:
                    vals = [v.get("name"), ext.get("disk_name"),
                            ext.get("partition")]
                    _write_data_row(ws, row, vals, idx)
                    row += 1
                    idx += 1

    _auto_width(ws)


def _merged_hardware(wb, prefix, ts):
    """Sensors + PCI + CPU Topology + GPU + IPMI/BMC + Power + Coredump/Swap."""
    hw_data = ts.get("hardware_health", {})
    pci_data = ts.get("pci_devices", {})
    cpu_data = ts.get("cpu_topology")
    gpu_data = ts.get("graphics_gpu")
    ipmi_data = ts.get("ipmi_bmc")
    power_data = ts.get("power_policy", {})
    cd_data = ts.get("coredump_swap")

    has_hw = not _skip_error(hw_data) and hw_data.get("sensors")
    has_pci = not _skip_error(pci_data) and pci_data.get("devices")
    has_cpu = not _skip_error(cpu_data)
    has_gpu = not _skip_error(gpu_data)
    has_ipmi = not _skip_error(ipmi_data)
    has_power = not _skip_error(power_data) and power_data
    has_cd = not _skip_error(cd_data)

    if not any([has_hw, has_pci, has_cpu, has_gpu, has_ipmi, has_power, has_cd]):
        return

    ws = _add_sheet(wb, prefix, "Hardware")
    row = 1

    # ── Section 1: Sensors ──
    if has_hw:
        sensors = hw_data.get("sensors", [])
        row = _section_header(ws, row, f"Sensors ({len(sensors)})")
        headers = ["ID", "Sensor Name", "Type", "Status", "Reading", "Units"]
        _write_header_row(ws, row, headers)
        row += 1
        for i, s in enumerate(sensors):
            status = s.get("status", "green")
            vals = [
                s.get("id"), s.get("name"), s.get("sensor_type"),
                status, s.get("reading"), s.get("units"),
            ]
            _write_data_row(ws, row, vals, i)
            fill = _RED_FILL if status == "red" else (
                _YELLOW_FILL if status == "yellow" else (
                    _GREEN_FILL if status == "green" else None))
            if fill:
                ws.cell(row=row, column=4).fill = fill
            row += 1
        row += 1

    # ── Section 2: PCI Devices ──
    if has_pci:
        devices = pci_data.get("devices", [])
        row = _section_header(ws, row, f"PCI Devices ({len(devices)})")
        headers2 = ["ID", "Device Name", "Vendor Name", "Class ID",
                     "Vendor ID", "Device ID"]
        _write_header_row(ws, row, headers2)
        row += 1
        for i, d in enumerate(devices):
            vals = [d.get("id"), d.get("device_name"), d.get("vendor_name"),
                    d.get("class_id"), d.get("vendor_id"), d.get("device_id")]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 3: CPU Topology ──
    if has_cpu:
        row = _section_header(ws, row, "CPU Topology")
        kv = [
            ("CPU Packages (Sockets)", cpu_data.get("num_cpu_pkgs", "")),
            ("CPU Cores", cpu_data.get("num_cpu_cores", "")),
            ("CPU Threads", cpu_data.get("num_cpu_threads", "")),
            ("Cores per Socket", cpu_data.get("cores_per_socket", "")),
            ("Threads per Core", cpu_data.get("threads_per_core", "")),
        ]
        numa = cpu_data.get("numa", {})
        if numa:
            kv.append(("", ""))
            kv.append(("NUMA Nodes", numa.get("num_nodes", "")))
            kv.append(("NUMA Type", numa.get("type", "")))
            for ni, node in enumerate(numa.get("nodes", [])):
                kv.append((f"  Node {ni} Memory GB", node.get("memory_size_gb", "")))
                kv.append((f"  Node {ni} CPUs",
                            ", ".join(str(c) for c in node.get("cpu_ids", []))))
        row = _write_kv_block(ws, row, kv)
        row += 1

        # CPU Packages table
        pkgs = cpu_data.get("packages", [])
        if pkgs:
            row = _section_header(ws, row, f"CPU Packages ({len(pkgs)})")
            pkg_headers = ["Index", "Vendor", "Hz", "Bus Hz", "Description", "Threads"]
            _write_header_row(ws, row, pkg_headers)
            row += 1
            for i, p in enumerate(pkgs):
                vals = [
                    p.get("index", ""), p.get("vendor", ""), p.get("hz", ""),
                    p.get("bus_hz", ""), p.get("description", ""),
                    p.get("thread_count", ""),
                ]
                _write_data_row(ws, row, vals, i)
                row += 1
            row += 1

    # ── Section 4: GPU / Graphics ──
    if has_gpu:
        row = _section_header(ws, row, "GPU / Graphics")
        config = gpu_data.get("config", {})
        devices = gpu_data.get("devices", [])
        kv2 = [
            ("Default Graphics Type", config.get("host_default_graphics_type", "")),
            ("Passthru Policy", config.get("shared_passthru_assignment_policy", "")),
        ]
        if devices:
            for d in devices:
                kv2.append(("", ""))
                kv2.append(("Device", d.get("device_name", "")))
                kv2.append(("  Vendor", d.get("vendor_name", "")))
                kv2.append(("  PCI ID", d.get("pci_id", "")))
                kv2.append(("  Memory MB", d.get("gpu_memory_mb", "")))
                kv2.append(("  Type", d.get("graphics_type", "")))
                kv2.append(("  VMs", d.get("vm_count", 0)))
        else:
            kv2.append(("GPU Devices", "None detected"))
        row = _write_kv_block(ws, row, kv2)
        row += 1

    # ── Section 5: IPMI / BMC ──
    if has_ipmi:
        row = _section_header(ws, row, "IPMI / BMC")
        kv3 = [
            ("BMC Present", ipmi_data.get("present", "")),
            ("BMC IP", ipmi_data.get("bmc_ip", "")),
            ("BMC MAC", ipmi_data.get("bmc_mac", "")),
            ("Login", ipmi_data.get("login", "")),
        ]
        row = _write_kv_block(ws, row, kv3)
        row += 1

    # ── Section 6: Power Policy ──
    if has_power:
        row = _section_header(ws, row, "Power Policy")
        kv4 = [
            ("Power Policy Key", power_data.get("current_policy_key", "")),
            ("Power Policy Name", power_data.get("current_policy_name", "")),
            ("Power Policy Desc", power_data.get("current_policy_desc", "")),
            ("CPU Policy", power_data.get("cpu_policy", "")),
            ("HW Support", power_data.get("hw_support", "")),
            ("Hyperthreading Active", power_data.get("hyperthreading_active", "")),
            ("Hyperthreading Available", power_data.get("hyperthreading_available", "")),
        ]
        row = _write_kv_block(ws, row, kv4)
        row += 1

    # ── Section 7: Coredump / Swap ──
    if has_cd:
        row = _section_header(ws, row, "Coredump / Swap")
        kv5 = []
        cd = cd_data.get("coredump")
        if cd and not isinstance(cd, str):
            kv5.append(("Coredump Disk", cd.get("disk_name", "")))
            kv5.append(("Coredump Partition", cd.get("partition", "")))
            kv5.append(("Coredump Storage Type", cd.get("storage_type", "")))
            kv5.append(("Coredump Diagnostic Type", cd.get("diagnostic_type", "")))
        else:
            kv5.append(("Coredump", "Not configured"))
        kv5.append(("", ""))
        kv5.append(("Swap Datastore", cd_data.get("swap_datastore", "None")))
        kv5.append(("Scratch Configured", cd_data.get("scratch_configured", "")))
        kv5.append(("Scratch Current", cd_data.get("scratch_current", "")))
        for opt in cd_data.get("system_swap_options", []):
            kv5.append(("System Swap Option", opt.get("key", "")))
        row = _write_kv_block(ws, row, kv5)

    _auto_width(ws)


def _merged_config(wb, prefix, ts):
    """Services + Firewall + Security + Advanced Settings + VIBs + SNMP + vSAN."""
    svc_data = ts.get("services", {})
    fw_data = ts.get("firewall", {})
    sec_data = ts.get("security_config")
    adv_data = ts.get("advanced_settings", {})
    vib_data = ts.get("installed_vibs")
    snmp_data = ts.get("snmp_config")
    vsan_data = ts.get("vsan_config")

    has_svc = not _skip_error(svc_data) and svc_data.get("services")
    has_fw = not _skip_error(fw_data) and fw_data.get("rulesets")
    has_sec = not _skip_error(sec_data)
    has_adv = not _skip_error(adv_data)
    has_vib = not _skip_error(vib_data)
    has_snmp = not _skip_error(snmp_data)
    has_vsan = not _skip_error(vsan_data)

    if not any([has_svc, has_fw, has_sec, has_adv, has_vib, has_snmp, has_vsan]):
        return

    ws = _add_sheet(wb, prefix, "Config")
    row = 1

    # ── Section 1: Services ──
    if has_svc:
        services = svc_data.get("services", [])
        row = _section_header(ws, row, f"Services ({len(services)})")
        headers = ["Key", "Label", "Running", "Policy", "Required"]
        _write_header_row(ws, row, headers)
        row += 1
        for i, s in enumerate(services):
            running = s.get("running", False)
            vals = [s.get("key"), s.get("label"),
                    "Yes" if running else "No",
                    s.get("policy"), "Yes" if s.get("required") else "No"]
            _write_data_row(ws, row, vals, i)
            if running:
                ws.cell(row=row, column=3).fill = _GREEN_FILL
            row += 1
        row += 1

    # ── Section 2: Firewall ──
    if has_fw:
        rulesets = fw_data.get("rulesets", [])
        row = _section_header(ws, row, f"Firewall Rulesets ({len(rulesets)})")
        headers2 = ["Key", "Label", "Enabled", "Rules Count",
                     "Ports/Direction/Protocol"]
        _write_header_row(ws, row, headers2)
        row += 1
        for i, rs in enumerate(rulesets):
            rules = rs.get("rules", [])
            rule_summary = "; ".join(
                f"{r.get('port_start')}-{r.get('port_end')}/{r.get('protocol')}"
                f"/{r.get('direction')}"
                for r in rules[:5]
            )
            if len(rules) > 5:
                rule_summary += f"... +{len(rules) - 5} more"
            vals = [rs.get("key"), rs.get("label"),
                    "Yes" if rs.get("enabled") else "No",
                    len(rules), rule_summary]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 3: Security Config ──
    if has_sec:
        row = _section_header(ws, row, "Security Config")
        kv = [
            ("Lockdown Mode", sec_data.get("lockdown_mode", "")),
            ("Admin Disabled", sec_data.get("admin_disabled", "")),
            ("SSL Thumbprint", sec_data.get("ssl_thumbprint", "")),
            ("Certificate Present", sec_data.get("certificate_present", "")),
            ("Certificate Bytes", sec_data.get("certificate_bytes", "")),
            ("TPM Present", sec_data.get("tpm_present", "")),
            ("TPM Version", sec_data.get("tpm_version", "")),
            ("Crypto Enabled", sec_data.get("crypto_enabled", "")),
            ("Crypto Key ID", sec_data.get("crypto_key_id", "")),
        ]
        for i, ac in enumerate(sec_data.get("auth_configs", [])):
            kv.append((f"Auth Config [{i}] Type", ac.get("type", "")))
            kv.append((f"Auth Config [{i}] Enabled", ac.get("enabled", "")))
            if ac.get("joined_domain"):
                kv.append((f"Auth Config [{i}] Domain", ac.get("joined_domain", "")))
                kv.append((f"Auth Config [{i}] Trusted",
                             ", ".join(ac.get("trusted_domains", []))))
        row = _write_kv_block(ws, row, kv)
        row += 1

    # ── Section 4: Key Advanced Settings ──
    if has_adv:
        categorized = adv_data.get("categorized", {})
        if categorized:
            total_keys = sum(len(v) for v in categorized.values())
            row = _section_header(ws, row, f"Key Advanced Settings ({total_keys})")
            headers3 = ["Category", "Setting", "Value"]
            _write_header_row(ws, row, headers3)
            row += 1
            idx = 0
            for cat, settings in categorized.items():
                for key, val in settings.items():
                    vals = [cat, key, str(val)]
                    _write_data_row(ws, row, vals, idx)
                    row += 1
                    idx += 1
            row += 1

        # ── Section 5: All Advanced Settings ──
        all_settings = adv_data.get("all_settings", {})
        if all_settings:
            row = _section_header(ws, row, f"All Advanced Settings ({len(all_settings)})")
            headers4 = ["Setting Key", "Value"]
            _write_header_row(ws, row, headers4)
            row += 1
            for i, (k, v) in enumerate(sorted(all_settings.items())):
                vals = [k, str(v)]
                _write_data_row(ws, row, vals, i)
                row += 1
            row += 1

    # ── Section 6: Installed VIBs ──
    if has_vib:
        vibs = vib_data.get("vibs", [])
        if vibs:
            row = _section_header(ws, row, f"Installed VIBs ({len(vibs)})")
            headers5 = ["Name", "Version", "Vendor", "Creation Date",
                         "Acceptance Level"]
            _write_header_row(ws, row, headers5)
            row += 1
            for i, v in enumerate(vibs):
                vals = [
                    v.get("name", ""), v.get("version", ""),
                    v.get("vendor", ""), v.get("creation_date", ""),
                    v.get("acceptance_level", ""),
                ]
                _write_data_row(ws, row, vals, i)
                row += 1
        else:
            row = _section_header(ws, row, "Installed VIBs")
            kv2 = [
                ("Image Profile", vib_data.get("image_profile", "")),
                ("Acceptance Level", vib_data.get("acceptance_level", "")),
                ("Note", vib_data.get("note", "VIB listing may not be available")),
            ]
            row = _write_kv_block(ws, row, kv2)
        row += 1

    # ── Section 7: SNMP Config ──
    if has_snmp:
        row = _section_header(ws, row, "SNMP Config")
        kv3 = [
            ("SNMP Enabled", snmp_data.get("enabled", "")),
            ("Port", snmp_data.get("port", "")),
            ("Read-Only Communities", ", ".join(snmp_data.get("read_only_communities", []))),
            ("Engine ID", snmp_data.get("engine_id", "")),
        ]
        for i, t in enumerate(snmp_data.get("trap_targets", [])):
            kv3.append((f"Trap Target {i} Host", t.get("hostname", "")))
            kv3.append((f"Trap Target {i} Port", t.get("port", "")))
            kv3.append((f"Trap Target {i} Community", t.get("community", "")))
        row = _write_kv_block(ws, row, kv3)
        row += 1

    # ── Section 8: vSAN Config ──
    if has_vsan:
        row = _section_header(ws, row, "vSAN Config")
        kv4 = [
            ("vSAN Enabled", vsan_data.get("enabled", False)),
            ("Cluster UUID", vsan_data.get("cluster_uuid", "")),
            ("Node UUID", vsan_data.get("node_uuid", "")),
            ("Auto Claim Storage", vsan_data.get("auto_claim", "")),
            ("Fault Domain", vsan_data.get("fault_domain", "")),
        ]
        for i, dm in enumerate(vsan_data.get("disk_mappings", [])):
            kv4.append((f"Disk Group {i} SSD", dm.get("ssd", "")))
            kv4.append((f"Disk Group {i} HDDs", ", ".join(dm.get("hdds", []))))
        for i, p in enumerate(vsan_data.get("network_ports", [])):
            kv4.append((f"vSAN Port {i}", p.get("device", "")))
        row = _write_kv_block(ws, row, kv4)

    _auto_width(ws)


def _merged_events(wb, prefix, ts):
    """Alarms + Events + Recent Tasks."""
    alarm_data = ts.get("alarms", {})
    event_data = ts.get("events", {})
    task_data = ts.get("recent_tasks", {})

    has_alarms = not _skip_error(alarm_data)
    has_events = not _skip_error(event_data) and event_data.get("events")
    has_tasks = not _skip_error(task_data) and task_data.get("tasks")

    if not has_alarms and not has_events and not has_tasks:
        return

    ws = _add_sheet(wb, prefix, "Events")
    row = 1

    # ── Section 1: Active Alarms ──
    if has_alarms:
        meta = alarm_data.get("collection_metadata", {})
        if meta:
            ws.cell(row=row, column=1, value="History Window").font = Font(bold=True)
            ws.cell(row=row, column=2,
                    value=f"Last {meta.get('window_days', '?')} days")
            row += 1

        active = alarm_data.get("active_alarms", [])
        row = _section_header(ws, row,
                              f"Active Alarms ({alarm_data.get('active_count', 0)})")
        active_headers = ["Severity", "Type", "Object", "Alarm Name",
                          "Triggered Time", "Acknowledged By"]
        _write_header_row(ws, row, active_headers)
        row += 1

        if not active:
            ws.cell(row=row, column=1, value="No currently active alarms")
            row += 1
        else:
            for i, a in enumerate(active):
                status = a.get("status", "")
                severity = "Critical" if status == "red" else (
                    "Warning" if status == "yellow" else status)
                vals = [
                    severity, a.get("object_type"), a.get("object_name"),
                    a.get("alarm_name"), a.get("triggered_time"),
                    a.get("acknowledged_by"),
                ]
                _write_data_row(ws, row, vals, i)
                fill = _RED_FILL if status == "red" else (
                    _YELLOW_FILL if status == "yellow" else None)
                if fill:
                    ws.cell(row=row, column=1).fill = fill
                row += 1
        row += 1

        # ── Section 2: Alarm History ──
        history = alarm_data.get("alarm_history", [])
        row = _section_header(ws, row,
                              f"Alarm History ({len(history)} events)")
        if history:
            hist_headers = ["Time", "Event Type", "Alarm Name",
                            "Entity", "Message"]
            _write_header_row(ws, row, hist_headers)
            row += 1
            for i, h in enumerate(history):
                vals = [
                    h.get("time", ""),
                    h.get("event_type", ""),
                    h.get("alarm_name", ""),
                    h.get("entity_name", ""),
                    (h.get("message", "") or "")[:200],
                ]
                _write_data_row(ws, row, vals, i)
                row += 1
        else:
            ws.cell(row=row, column=1, value="No alarm events in the time window")
            row += 1
        row += 1

    # ── Section 3: Events ──
    if has_events:
        events = event_data.get("events", [])
        row = _section_header(ws, row, f"Events ({len(events)})")
        ev_headers = ["Time", "Type", "User", "Message"]
        _write_header_row(ws, row, ev_headers)
        row += 1
        for i, e in enumerate(events):
            vals = [e.get("time"), e.get("type"), e.get("user"),
                    e.get("message")]
            _write_data_row(ws, row, vals, i)
            row += 1
        row += 1

    # ── Section 4: Recent Tasks ──
    if has_tasks:
        tasks = task_data.get("tasks", [])
        row = _section_header(ws, row, f"Recent Tasks ({len(tasks)})")
        task_headers = ["State", "Task Name", "Description ID", "Target",
                        "Target Type", "Start Time", "Complete Time",
                        "User", "Progress", "Error"]
        _write_header_row(ws, row, task_headers)
        row += 1
        for i, t in enumerate(tasks):
            state = t.get("state", "")
            vals = [
                state,
                t.get("task_name") or t.get("description", ""),
                t.get("description", ""),
                t.get("entity_name"), t.get("entity_type"),
                t.get("start_time"), t.get("complete_time"),
                t.get("user"), t.get("progress", ""),
                t.get("error"),
            ]
            _write_data_row(ws, row, vals, i)
            if state == "error":
                ws.cell(row=row, column=1).fill = _RED_FILL
            elif state == "running":
                ws.cell(row=row, column=1).fill = _GREEN_FILL
            row += 1

    _auto_width(ws)


# ── Helper functions ─────────────────────────────────────────────────────

def _section_header(ws, row, title, num_cols=14):
    """Write a bold section header spanning multiple columns. Returns next row."""
    cell = ws.cell(row=row, column=1, value=title)
    cell.font = _SECTION_FONT
    cell.fill = _SECTION_FILL
    cell.alignment = Alignment(vertical="center")
    for c in range(2, num_cols + 1):
        ws.cell(row=row, column=c).fill = _SECTION_FILL
    return row + 1


def _add_sheet(wb, prefix, name):
    """Create a sheet with a safe title (max 31 chars)."""
    title = f"{prefix} {name}"[:31]
    existing = set(wb.sheetnames)
    if title in existing:
        for n in range(2, 100):
            alt = f"{title[:28]}_{n}"
            if alt not in existing:
                title = alt
                break
    return wb.create_sheet(title)


def _write_header_row(ws, row, headers):
    """Write a styled header row."""
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=row, column=col, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = _HEADER_ALIGN
        cell.border = _THIN_BORDER


def _write_data_row(ws, row, values, idx):
    """Write a data row with alternating fill."""
    fill = _ALT_FILL if idx % 2 == 1 else None
    for col, val in enumerate(values, 1):
        cell = ws.cell(row=row, column=col, value=val)
        cell.border = _THIN_BORDER
        cell.alignment = Alignment(vertical="center", wrap_text=False)
        cell.font = Font(name="Calibri", size=9)
        if fill:
            cell.fill = fill


def _write_kv_block(ws, start_row, rows):
    """Write key-value pairs starting at a given row. Returns next row."""
    for i, (key, val) in enumerate(rows):
        r = start_row + i
        cell_k = ws.cell(row=r, column=1, value=key)
        cell_v = ws.cell(row=r, column=2, value=str(val) if val else "")
        cell_k.font = Font(name="Calibri", bold=True, size=10)
        cell_v.font = Font(name="Calibri", size=10)
        if i % 2 == 1 and key:
            cell_k.fill = _ALT_FILL
            cell_v.fill = _ALT_FILL
    return start_row + len(rows)


def _write_kv_sheet(ws, rows):
    """Write key-value pairs to a sheet (legacy, used by cluster-level sheets)."""
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 60
    for i, (key, val) in enumerate(rows):
        r = i + 1
        cell_k = ws.cell(row=r, column=1, value=key)
        cell_v = ws.cell(row=r, column=2, value=str(val) if val else "")
        cell_k.font = Font(name="Calibri", bold=True, size=10)
        cell_v.font = Font(name="Calibri", size=10)
        if i % 2 == 1 and key:
            cell_k.fill = _ALT_FILL
            cell_v.fill = _ALT_FILL


def _auto_width(ws, min_width=8, max_width=55):
    """Auto-fit column widths based on content."""
    for col_cells in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col_cells[0].column)
        for cell in col_cells:
            try:
                cell_len = len(str(cell.value or ""))
                if cell_len > max_len:
                    max_len = cell_len
            except Exception:
                pass
        width = min(max(max_len + 2, min_width), max_width)
        ws.column_dimensions[col_letter].width = width


def _skip_error(data):
    """Return True if data indicates an error or is empty."""
    if not data:
        return True
    if isinstance(data, dict) and data.get("status") == "error":
        return True
    return False
