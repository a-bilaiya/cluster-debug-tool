#!/usr/bin/env python3
"""
Standalone VM Hardware Info Report Generator
─────────────────────────────────────────────

Connects to ESXi host(s), collects per-VM hardware info (the same data shown
by `python -m env_validation_tool vminfo`), and bundles JSON + PDF + Excel
into a single ZIP file.

Usage:
    python scripts/vminfo_report.py -c config.yaml
    python scripts/vminfo_report.py --esxi-ips 10.0.0.1 --esxi-pass MYPASS
    python scripts/vminfo_report.py                    # prompts for inputs

Output:
    /tool/out/vminfo_<timestamp>.zip    containing:
        vminfo_<timestamp>.json
        vminfo_<timestamp>.pdf
        vminfo_<timestamp>.xlsx

Requirements: pyVmomi, PyYAML, openpyxl, fpdf2
"""

import os
# Silence fpdf2 deprecation warnings before importing it
os.environ.setdefault("PYTHONWARNINGS", "ignore::DeprecationWarning")

import argparse
import datetime
import getpass
import json
import ssl
import sys
import warnings
import zipfile
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning)

# Make package importable when run from anywhere in the repo
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import yaml
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from fpdf import FPDF

from env_validation_tool import __version__
from env_validation_tool.troubleshoot import (
    _ts_vm_details, _ts_cpu_allocation, _ts_memory_allocation,
)


# ── Argument parsing ──

def _parse_args():
    p = argparse.ArgumentParser(
        prog="vminfo_report",
        description="Collect VM hardware info from ESXi hosts and bundle "
                    "JSON+PDF+Excel into a single ZIP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-c", "--config", default="",
                   help="Path to YAML config (default: prompt for inputs)")
    p.add_argument("--esxi-ips", default="",
                   help="Comma-separated ESXi IPs (overrides config)")
    p.add_argument("--esxi-user", default="",
                   help="ESXi username (default: root)")
    p.add_argument("--esxi-pass", default="",
                   help="ESXi password")
    p.add_argument("--vm-pattern", default="",
                   help="VM name substring filter (default: all VMs)")
    p.add_argument("--output-dir", default="./vminfo_reports",
                   help="Output directory (default: ./vminfo_reports/ in current dir)")
    p.add_argument("--customer", default="",
                   help="Customer/cluster name to embed in reports")
    return p.parse_args()


def _resolve_inputs(args):
    """Load config and fill any missing connection fields by prompting."""
    cfg = {}
    if args.config and os.path.isfile(args.config):
        with open(args.config) as f:
            cfg = yaml.safe_load(f) or {}
        print(f"[*] Loaded config from {args.config}")

    raw_ips = args.esxi_ips or cfg.get("esxi_ips", "")
    esxi_ips = [ip.strip() for ip in str(raw_ips).split(",") if ip.strip()]

    if not esxi_ips:
        raw = input("  ESXi IPs (comma-separated): ").strip()
        esxi_ips = [ip.strip() for ip in raw.split(",") if ip.strip()]
        if not esxi_ips:
            sys.exit("[ERROR] No ESXi IPs provided.")

    user = args.esxi_user or cfg.get("esxi_user", "") \
        or input("  ESXi username [root]: ").strip() or "root"

    password = args.esxi_pass or cfg.get("esxi_pass", "")
    if not password:
        password = getpass.getpass("  ESXi password: ")
        if not password:
            sys.exit("[ERROR] Password required.")

    vm_pattern = args.vm_pattern or cfg.get("vm_pattern", "")
    if not vm_pattern:
        vm_pattern = input(
            "  VM name filter (substring, leave blank for all): "
        ).strip()

    customer = args.customer or cfg.get("customer", "")

    return {
        "esxi_ips":   esxi_ips,
        "user":       user,
        "password":   password,
        "vm_pattern": vm_pattern,
        "customer":   customer,
    }


# ── Connect & collect ──

def _connect(host_ip, user, password):
    context = ssl._create_unverified_context()
    si = SmartConnect(host=host_ip, user=user, pwd=password, sslContext=context)
    content = si.RetrieveContent()
    container = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.HostSystem], True,
    )
    if not container.view:
        raise RuntimeError(f"No host found on {host_ip}")
    host = container.view[0]
    container.Destroy()
    return si, host


def _collect_host(host_ip, user, password, vm_pattern):
    """Connect to host, collect VM data + host info, disconnect, return dict."""
    si = None
    try:
        si, host = _connect(host_ip, user, password)
        hw       = host.summary.hardware
        product  = host.summary.config.product

        host_info = {
            "esxi_ip":     host_ip,
            "esxi_full":   product.fullName,
            "esxi_build":  product.build,
            "vendor":      hw.vendor,
            "model":       hw.model,
            "cpu_model":   hw.cpuModel,
            "cpu_cores":   hw.numCpuCores,
            "cpu_threads": hw.numCpuThreads,
            "cpu_mhz":     hw.cpuMhz,
            "memory_gb":   round(hw.memorySize / (1024 ** 3), 2),
        }

        vm_data   = _ts_vm_details(host)
        cpu_data  = _ts_cpu_allocation(host)
        mem_data  = _ts_memory_allocation(host)

        per_vm_cpu = {v["vm_name"]: v for v in cpu_data.get("per_vm", [])}
        per_vm_mem = {v["vm_name"]: v for v in mem_data.get("per_vm", [])}

        vms = vm_data.get("vms", []) if isinstance(vm_data, dict) else []
        if vm_pattern:
            vms = [v for v in vms if vm_pattern.lower() in v.get("vm_name", "").lower()]

        # Attach per-VM CPU/mem allocation
        for vm in vms:
            n = vm.get("vm_name", "")
            cv = per_vm_cpu.get(n, {})
            mv = per_vm_mem.get(n, {})
            vm["cpu_reservation_mhz"] = cv.get("reservation_mhz", 0)
            vm["cpu_limit_mhz"]       = cv.get("limit_mhz", -1)
            vm["cpu_shares_level"]    = cv.get("shares_level", "")
            vm["mem_reservation_mb"]  = mv.get("reservation_mb", 0)
            vm["mem_limit_mb"]        = mv.get("limit_mb", -1)

        host_info["vms"] = vms
        return host_info
    finally:
        if si:
            try:
                Disconnect(si)
            except Exception:
                pass


# ── Output writers ──

def _write_json(data, path):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _write_excel(data, path):
    wb = Workbook()
    ws = wb.active
    ws.title = "VM Info"

    BOLD       = Font(bold=True)
    HEADER_FILL = PatternFill(fill_type="solid", fgColor="4472C4")
    HEADER_FONT = Font(bold=True, color="FFFFFF")
    SECTION_FILL = PatternFill(fill_type="solid", fgColor="D9E1F2")
    OK_FILL     = PatternFill(fill_type="solid", fgColor="CCFFCC")
    WARN_FILL   = PatternFill(fill_type="solid", fgColor="FFF2CC")

    row = 1

    # Report Info section
    ws.cell(row=row, column=1, value="VM Hardware Info Report").font = Font(bold=True, size=14)
    row += 1
    for label, value in [
        ("Tool",       f"Cluster Debug Tool — vminfo_report v{__version__}"),
        ("Generated",  data.get("generated", "")),
        ("Customer",   data.get("customer", "—") or "—"),
        ("Hosts",      ", ".join(h["esxi_ip"] for h in data["hosts"])),
        ("Total VMs",  sum(len(h.get("vms", [])) for h in data["hosts"])),
    ]:
        ws.cell(row=row, column=1, value=label).font = BOLD
        ws.cell(row=row, column=2, value=value)
        row += 1
    row += 1

    # Per-host VM details
    for host in data["hosts"]:
        # Host header
        ws.cell(row=row, column=1, value=f"Host {host['esxi_ip']}  ({host['model']})").font = Font(bold=True, size=12)
        for c in range(1, 8):
            ws.cell(row=row, column=c).fill = SECTION_FILL
        row += 1
        ws.cell(row=row, column=1, value=f"  ESXi: {host['esxi_full']}")
        row += 1
        ws.cell(row=row, column=1,
                value=f"  CPU: {host['cpu_model']}  ({host['cpu_cores']}C/{host['cpu_threads']}T @ {host['cpu_mhz']} MHz)")
        row += 1
        ws.cell(row=row, column=1, value=f"  Memory: {host['memory_gb']} GB")
        row += 2

        for vm in host.get("vms", []):
            # VM header
            ws.cell(row=row, column=1,
                    value=f"VM: {vm.get('vm_name','?')}  [{vm.get('power_state','?')}]").font = Font(bold=True)
            row += 1
            for label, value in [
                ("VM Hardware Version", vm.get("vm_version", "?")),
                ("Guest OS",           vm.get("guest_os", "?")),
                ("Guest IP",           vm.get("guest_ip", "") or "—"),
                ("Hostname",           vm.get("guest_hostname", "") or "—"),
                ("VMware Tools",       vm.get("tools_status", "?")),
                ("vCPUs",              vm.get("num_cpu", "?")),
                ("Memory MB",          vm.get("memory_mb", "?")),
                ("CPU Reservation",    f"{vm.get('cpu_reservation_mhz',0)} MHz"),
                ("CPU Limit",          "Unlimited" if vm.get("cpu_limit_mhz") == -1 else f"{vm.get('cpu_limit_mhz')} MHz"),
                ("Memory Reservation", f"{vm.get('mem_reservation_mb',0)} MB"),
            ]:
                ws.cell(row=row, column=1, value=f"  {label}").font = BOLD
                ws.cell(row=row, column=2, value=value)
                row += 1

            # Storage Controllers — disks nested under each controller
            disks = vm.get("disks", [])
            ctype_keywords = ("LsiLogic", "BusLogic", "ParaVirtual", "SCSI",
                              "AHCI", "SATA", "NVMe", "NVME", "USB")
            controllers = vm.get("controllers", [])
            storage_ctrls = [c for c in controllers
                             if any(k in c.get("type", "") for k in ctype_keywords)]

            if storage_ctrls:
                row += 1
                ws.cell(row=row, column=1,
                        value=f"  Storage Controllers ({len(storage_ctrls)})").font = BOLD
                row += 1

                for c in storage_ctrls:
                    ctype = c.get("type", "")
                    ctrl_fill = (OK_FILL if "ParaVirtual" in ctype or "NVMe" in ctype or "NVME" in ctype
                                 else WARN_FILL if "LsiLogic" in ctype or "BusLogic" in ctype
                                 else None)

                    # Controller header row
                    ws.cell(row=row, column=1,
                            value=f"    {c.get('label','?')}  [{ctype}]  "
                                  f"bus={c.get('bus_number','?')}  "
                                  f"sharing={c.get('sharing','')}").font = BOLD
                    if ctrl_fill:
                        for ci in range(1, 8):
                            ws.cell(row=row, column=ci).fill = ctrl_fill
                    row += 1

                    # Disks attached to this controller
                    attached = [d for d in disks if d.get("controller_key") == c.get("key")]
                    if attached:
                        headers = ["", "Label", "Unit", "Size GB", "Provisioning", "Disk Mode", "Backing File"]
                        for ci, h in enumerate(headers, start=1):
                            cell = ws.cell(row=row, column=ci, value=h)
                            cell.font = HEADER_FONT
                            if h:
                                cell.fill = HEADER_FILL
                        row += 1
                        for d in sorted(attached, key=lambda x: x.get("unit_number", 0) or 0):
                            prov = d.get("provisioning", "?")
                            prov_fill = OK_FILL if prov == "eagerzeroedthick" else WARN_FILL
                            vals = [
                                "",
                                d.get("label", ""),
                                d.get("unit_number", ""),
                                d.get("capacity_gb", 0),
                                prov,
                                d.get("disk_mode", ""),
                                d.get("backing_file", ""),
                            ]
                            for ci, v in enumerate(vals, start=1):
                                cell = ws.cell(row=row, column=ci, value=v)
                                if ci == 5:
                                    cell.fill = prov_fill
                            row += 1
                    else:
                        ws.cell(row=row, column=2, value="(no disks attached)")
                        row += 1
                    row += 1  # spacer

            # Orphan disks (no matching controller in the storage list)
            attached_keys = {c.get("key") for c in storage_ctrls}
            orphan_disks = [d for d in disks if d.get("controller_key") not in attached_keys]
            if orphan_disks:
                ws.cell(row=row, column=1,
                        value=f"  Other Disks (controller not detected) ({len(orphan_disks)})").font = BOLD
                row += 1
                headers = ["Label", "Size GB", "Provisioning", "Mode", "Backing File"]
                for ci, h in enumerate(headers, start=1):
                    cell = ws.cell(row=row, column=ci, value=h)
                    cell.font = HEADER_FONT
                    cell.fill = HEADER_FILL
                row += 1
                for d in orphan_disks:
                    vals = [d.get("label", ""), d.get("capacity_gb", 0),
                            d.get("provisioning", "?"), d.get("disk_mode", ""),
                            d.get("backing_file", "")]
                    for ci, v in enumerate(vals, start=1):
                        ws.cell(row=row, column=ci, value=v)
                    row += 1

            # NICs
            nics = vm.get("nics", [])
            if nics:
                row += 1
                ws.cell(row=row, column=1, value=f"  Network Adapters ({len(nics)})").font = BOLD
                row += 1
                headers = ["Label", "Type", "Network", "MAC", "Connected"]
                for ci, h in enumerate(headers, start=1):
                    cell = ws.cell(row=row, column=ci, value=h)
                    cell.font = HEADER_FONT
                    cell.fill = HEADER_FILL
                row += 1
                for n in nics:
                    vals = [
                        n.get("label", ""), n.get("type", ""),
                        n.get("network", ""), n.get("mac", ""),
                        "Yes" if n.get("connected") else "No",
                    ]
                    for ci, v in enumerate(vals, start=1):
                        ws.cell(row=row, column=ci, value=v)
                    row += 1

            row += 2  # space between VMs

    # Auto-width columns
    for col_letter in "ABCDEFGH":
        max_len = max(
            (len(str(c.value)) for c in ws[col_letter] if c.value is not None),
            default=10,
        )
        ws.column_dimensions[col_letter].width = min(max_len + 2, 60)

    wb.save(path)


# ── PDF colour palette ──
_PDF_DARK   = (44, 62, 80)        # navy — primary headings
_PDF_HOST   = (52, 73, 94)        # slate — host band
_PDF_VM     = (74, 105, 138)      # blue-grey — VM band
_PDF_HEADER = (68, 114, 196)      # blue — table headers
_PDF_LIGHT  = (235, 241, 250)     # light blue — alt rows
_PDF_OK     = (198, 239, 206)     # green   — good (PVSCSI, NVMe, eagerzeroedthick)
_PDF_WARN   = (255, 235, 156)     # yellow  — warning (LsiLogic, thick)
_PDF_BAD    = (255, 199, 206)     # red     — bad (thin)
_PDF_GREY   = (220, 220, 220)     # grey separator


def _prov_fill(prov):
    p = (prov or "").lower()
    if p == "eagerzeroedthick":
        return _PDF_OK
    if p == "thick":
        return _PDF_WARN
    if p == "thin":
        return _PDF_BAD
    return None


def _ctrl_fill(ctype):
    t = ctype or ""
    if "ParaVirtual" in t or "NVMe" in t or "NVME" in t:
        return _PDF_OK
    if "LsiLogic" in t or "BusLogic" in t:
        return _PDF_WARN
    return None


def _table_row(pdf, widths, values, fills=None, header=False, line_h=5):
    """Draw a fixed-width table row with optional per-cell fills."""
    if header:
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(255, 255, 255)
        pdf.set_fill_color(*_PDF_HEADER)
        for w, v in zip(widths, values):
            pdf.cell(w, line_h, str(v), border=1, align="L", fill=True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(line_h)
        return

    pdf.set_font("Helvetica", size=8)
    for i, (w, v) in enumerate(zip(widths, values)):
        cell_fill = None
        if fills and i < len(fills):
            cell_fill = fills[i]
        if cell_fill:
            pdf.set_fill_color(*cell_fill)
        else:
            pdf.set_fill_color(255, 255, 255)
        pdf.cell(w, line_h, str(v), border=1, align="L", fill=True)
    pdf.ln(line_h)


def _section_band(pdf, text, color, height=7, font_size=11):
    """Coloured band heading."""
    pdf.set_font("Helvetica", "B", font_size)
    pdf.set_text_color(255, 255, 255)
    pdf.set_fill_color(*color)
    pdf.cell(0, height, f"  {text}", ln=1, fill=True)
    pdf.set_text_color(0, 0, 0)


def _kv_box(pdf, items, col_w_label=42, col_w_val=130, line_h=5):
    """Two-column key/value list with light-grey separators."""
    pdf.set_font("Helvetica", size=9)
    for i, (label, val) in enumerate(items):
        if i % 2 == 0:
            pdf.set_fill_color(*_PDF_LIGHT)
        else:
            pdf.set_fill_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(col_w_label, line_h, f" {label}", border=0, fill=True)
        pdf.set_font("Helvetica", size=9)
        pdf.cell(col_w_val, line_h, f" {val}", border=0, ln=1, fill=True)


def _ensure_space(pdf, needed_mm):
    """Add a new page if there's not enough vertical space remaining."""
    if pdf.get_y() + needed_mm > pdf.h - pdf.b_margin:
        pdf.add_page()


def _write_pdf(data, path):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(left=12, top=12, right=12)
    pdf.add_page()

    # ── Title block ──
    pdf.set_text_color(*_PDF_DARK)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, "VM Hardware Info Report", ln=1)
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5,
             f"Generated: {data.get('generated', '')}    "
             f"|    Tool: Cluster Debug Tool v{__version__}",
             ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    # ── Report-level summary box ──
    total_vms     = sum(len(h.get("vms", [])) for h in data["hosts"])
    total_powered = sum(1 for h in data["hosts"] for v in h.get("vms", [])
                        if v.get("power_state") == "poweredOn")
    summary_items = [
        ("Customer",       data.get("customer", "") or "—"),
        ("Hosts Scanned",  len(data["hosts"])),
        ("Total VMs",      total_vms),
        ("Powered On",     f"{total_powered} of {total_vms}"),
        ("VM Filter",      data.get("vm_filter", "all")),
        ("Hosts",          ", ".join(h["esxi_ip"] for h in data["hosts"])),
    ]
    _kv_box(pdf, summary_items)
    pdf.ln(4)

    # ── Per-host section ──
    for host in data["hosts"]:
        _ensure_space(pdf, 50)

        # Host band + spec
        _section_band(pdf, f"Host  {host['esxi_ip']}    {host['model']}",
                      _PDF_HOST, height=8, font_size=12)
        host_kv = [
            ("ESXi",   f"{host['esxi_full']}  (build {host['esxi_build']})"),
            ("Vendor", host['vendor']),
            ("CPU",    f"{host['cpu_model']}  ({host['cpu_cores']}C / "
                       f"{host['cpu_threads']}T  @  {host['cpu_mhz']} MHz)"),
            ("Memory", f"{host['memory_gb']} GB"),
            ("VMs on host", len(host.get("vms", []))),
        ]
        _kv_box(pdf, host_kv)
        pdf.ln(3)

        # Per-VM blocks
        for vm in host.get("vms", []):
            _ensure_space(pdf, 60)

            vm_name  = vm.get("vm_name", "?")
            power    = vm.get("power_state", "?")
            _section_band(pdf, f"VM  {vm_name}    [{power}]",
                          _PDF_VM, height=7, font_size=10)

            vm_kv = [
                ("Hardware Version",  vm.get("vm_version", "?")),
                ("Guest OS",          vm.get("guest_os", "?")),
                ("Guest IP",          vm.get("guest_ip", "") or "—"),
                ("Hostname",          vm.get("guest_hostname", "") or "—"),
                ("VMware Tools",      vm.get("tools_status", "?")),
                ("vCPU",              vm.get("num_cpu", "?")),
                ("Memory",            f"{round(vm.get('memory_mb', 0)/1024, 1)} GB "
                                       f"({vm.get('memory_mb', 0)} MB)"),
                ("CPU Reservation",   f"{vm.get('cpu_reservation_mhz', 0)} MHz "
                                       f"({round(vm.get('cpu_reservation_mhz', 0)/1000, 2)} GHz)"),
                ("CPU Limit",         "Unlimited"
                                       if vm.get("cpu_limit_mhz") == -1
                                       else f"{vm.get('cpu_limit_mhz')} MHz"),
                ("Memory Reservation",
                                      f"{vm.get('mem_reservation_mb', 0)} MB"),
            ]
            _kv_box(pdf, vm_kv, col_w_label=42, col_w_val=130)
            pdf.ln(2)

            # Storage controllers + disks
            disks = vm.get("disks", [])
            controllers = vm.get("controllers", [])
            ctype_keywords = ("LsiLogic", "BusLogic", "ParaVirtual", "SCSI",
                              "AHCI", "SATA", "NVMe", "NVME", "USB")
            storage_ctrls = [c for c in controllers
                             if any(k in c.get("type", "") for k in ctype_keywords)]

            if storage_ctrls:
                _ensure_space(pdf, 25)
                pdf.set_font("Helvetica", "B", 9)
                pdf.set_text_color(*_PDF_DARK)
                pdf.cell(0, 5,
                         f"  Storage Controllers ({len(storage_ctrls)})", ln=1)
                pdf.set_text_color(0, 0, 0)

                for c in storage_ctrls:
                    _ensure_space(pdf, 18)
                    ctype = c.get("type", "")
                    fill  = _ctrl_fill(ctype) or _PDF_GREY

                    pdf.set_font("Helvetica", "B", 9)
                    pdf.set_fill_color(*fill)
                    label = (f"   {c.get('label', '?')}    "
                             f"[{ctype}]    "
                             f"bus={c.get('bus_number', '?')}    "
                             f"sharing={c.get('sharing', 'noSharing')}")
                    pdf.cell(0, 5, label, ln=1, fill=True)

                    attached = [d for d in disks
                                if d.get("controller_key") == c.get("key")]
                    if attached:
                        widths = [12, 30, 12, 22, 32, 22, 42]
                        _table_row(pdf, widths,
                                   ["#", "Label", "Unit", "Size",
                                    "Provisioning", "Mode", "Datastore"],
                                   header=True)
                        for idx, d in enumerate(
                                sorted(attached,
                                       key=lambda x: x.get("unit_number", 0) or 0),
                                start=1):
                            prov = d.get("provisioning", "?")
                            backing = d.get("backing_file", "")
                            ds = ""
                            if backing.startswith("["):
                                ds = backing.split("]")[0].strip("[")
                            row_fills = [None, None, None, None,
                                         _prov_fill(prov), None, None]
                            _table_row(pdf, widths, [
                                idx,
                                (d.get("label", "") or "")[:24],
                                d.get("unit_number", "") if d.get("unit_number") is not None else "",
                                f"{round(d.get('capacity_gb', 0), 1)} GB",
                                prov,
                                d.get("disk_mode", ""),
                                ds[:30],
                            ], fills=row_fills)
                    else:
                        pdf.set_font("Helvetica", "I", 8)
                        pdf.cell(0, 4, "      (no disks attached)", ln=1)
                    pdf.ln(1)

            # Orphan disks (controller wasn't in storage list)
            attached_keys = {c.get("key") for c in storage_ctrls}
            orphan_disks = [d for d in disks
                            if d.get("controller_key") not in attached_keys]
            if orphan_disks:
                _ensure_space(pdf, 15)
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 5,
                         f"  Other Disks  ({len(orphan_disks)})", ln=1)
                widths = [12, 38, 22, 32, 22, 60]
                _table_row(pdf, widths,
                           ["#", "Label", "Size", "Provisioning",
                            "Mode", "Backing"],
                           header=True)
                for idx, d in enumerate(orphan_disks, start=1):
                    prov = d.get("provisioning", "?")
                    _table_row(pdf, widths, [
                        idx,
                        (d.get("label", "") or "")[:30],
                        f"{round(d.get('capacity_gb', 0), 1)} GB",
                        prov,
                        d.get("disk_mode", ""),
                        (d.get("backing_file", "") or "")[:48],
                    ], fills=[None, None, None, _prov_fill(prov), None, None])
                pdf.ln(1)

            # NICs
            nics = vm.get("nics", [])
            if nics:
                _ensure_space(pdf, 15)
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 5, f"  Network Adapters ({len(nics)})", ln=1)
                widths = [12, 38, 38, 50, 30, 18]
                _table_row(pdf, widths,
                           ["#", "Label", "Type", "Network",
                            "MAC", "Connected"],
                           header=True)
                for idx, n in enumerate(nics, start=1):
                    _table_row(pdf, widths, [
                        idx,
                        (n.get("label", "") or "")[:30],
                        (n.get("type", "") or "")[:30],
                        (n.get("network", "") or "")[:38],
                        n.get("mac", ""),
                        "Yes" if n.get("connected") else "No",
                    ])
                pdf.ln(1)

            pdf.ln(3)  # gap between VMs

    # ── Footer note (last page) ──
    _ensure_space(pdf, 10)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(140, 140, 140)
    pdf.cell(0, 4,
             "Provisioning legend: green = eagerzeroedthick, "
             "yellow = thick, red = thin.", ln=1)
    pdf.cell(0, 4,
             "Controller legend: green = ParaVirtual / NVMe, "
             "yellow = LsiLogic / BusLogic.", ln=1)
    pdf.set_text_color(0, 0, 0)

    pdf.output(path)


# ── Console summary ──

def _print_console_summary(data):
    """Print a human-readable VM summary to stdout before files are written."""
    hosts = data.get("hosts", [])
    total_vms     = sum(len(h.get("vms", [])) for h in hosts)
    total_powered = sum(1 for h in hosts for v in h.get("vms", [])
                        if v.get("power_state") == "poweredOn")

    print()
    print("=" * 110)
    print("  VM HARDWARE INFO SUMMARY")
    print("=" * 110)
    print(f"  Generated  : {data.get('generated', '')}")
    print(f"  Customer   : {data.get('customer', '') or '—'}")
    print(f"  VM Filter  : {data.get('vm_filter', 'all')}")
    print(f"  Hosts      : {len(hosts)}    "
          f"VMs: {total_vms}    "
          f"Powered On: {total_powered}/{total_vms}")
    print("=" * 110)

    for host in hosts:
        ip    = host.get("esxi_ip", "?")
        model = host.get("model", "?")
        cpu   = host.get("cpu_model", "?")
        cores = host.get("cpu_cores", "?")
        thr   = host.get("cpu_threads", "?")
        mhz   = host.get("cpu_mhz", "?")
        ram   = host.get("memory_gb", "?")
        vms   = host.get("vms", [])

        print()
        print(f"  Host  {ip}    {model}")
        print("  " + "-" * 108)
        print(f"    ESXi     : {host.get('esxi_full', '?')}")
        print(f"    CPU      : {cpu}  ({cores}C / {thr}T  @  {mhz} MHz)")
        print(f"    Memory   : {ram} GB")
        print(f"    VMs      : {len(vms)}")

        if not vms:
            print("    (no VMs matched)")
            continue

        # Per-VM compact lines
        print()
        print(f"    {'VM Name':<42} {'State':<5} {'vCPU':>4} "
              f"{'RAM(GB)':>8} {'Disks':>6} {'NICs':>5} "
              f"{'CPU Resv':>10} {'IP'}")
        print("    " + "-" * 104)
        for vm in vms:
            name   = (vm.get("vm_name", "?") or "?")[:42]
            power  = vm.get("power_state", "?").replace("poweredOn", "On") \
                                              .replace("poweredOff", "Off") \
                                              .replace("suspended", "Susp")
            vcpu   = vm.get("num_cpu", "?")
            ram_gb = round(vm.get("memory_mb", 0) / 1024, 1) if vm.get("memory_mb") else 0
            disks  = len(vm.get("disks", []))
            nics   = len(vm.get("nics", []))
            cpu_re = vm.get("cpu_reservation_mhz", 0)
            cpu_re_str = (f"{round(cpu_re / 1000, 1)} GHz"
                          if cpu_re else "0")
            ip     = vm.get("guest_ip", "") or "—"
            print(f"    {name:<42} {power:<5} {vcpu:>4} "
                  f"{ram_gb:>8} {disks:>6} {nics:>5} "
                  f"{cpu_re_str:>10} {ip}")

        # Disk-controller breakdown
        ctype_keywords = ("LsiLogic", "BusLogic", "ParaVirtual", "SCSI",
                          "AHCI", "SATA", "NVMe", "NVME", "USB")
        for vm in vms:
            ctrls = [c for c in vm.get("controllers", [])
                     if any(k in c.get("type", "") for k in ctype_keywords)]
            if not ctrls:
                continue
            disks = vm.get("disks", [])
            print()
            print(f"    Storage layout — {vm.get('vm_name', '?')}")
            for c in ctrls:
                ctype = c.get("type", "")
                attached = [d for d in disks
                            if d.get("controller_key") == c.get("key")]
                # Visual flag
                if "ParaVirtual" in ctype or "NVMe" in ctype.upper():
                    marker = "[OK]  "
                elif "LsiLogic" in ctype or "BusLogic" in ctype:
                    marker = "[WARN]"
                else:
                    marker = "      "
                print(f"      {marker} {c.get('label', '?'):<22}  "
                      f"{ctype:<28}  bus={c.get('bus_number', '?')}  "
                      f"sharing={c.get('sharing', 'noSharing')}  "
                      f"disks={len(attached)}")
                for d in sorted(attached,
                                key=lambda x: x.get("unit_number", 0) or 0):
                    prov = d.get("provisioning", "?")
                    prov_marker = ("[OK]  " if prov == "eagerzeroedthick"
                                   else "[WARN]" if prov == "thick"
                                   else "[FAIL]" if prov == "thin"
                                   else "      ")
                    size = round(d.get("capacity_gb", 0), 1)
                    print(f"          {prov_marker} unit={d.get('unit_number', '?'):>2}  "
                          f"{d.get('label', '?'):<14}  "
                          f"{size:>8} GB  {prov:<18}  "
                          f"mode={d.get('disk_mode', '')}")

    print()
    print("=" * 110)
    print(f"  Legend: [OK]=ParaVirtual/NVMe or eagerzeroedthick  "
          f"[WARN]=LsiLogic or thick  [FAIL]=thin")
    print("=" * 110)
    print()


# ── Main ──

def main():
    args   = _parse_args()
    inputs = _resolve_inputs(args)

    print()
    print(f"  Connecting to {len(inputs['esxi_ips'])} host(s)...")
    hosts = []
    for ip in inputs["esxi_ips"]:
        try:
            print(f"    [{ip}] collecting...", end=" ", flush=True)
            host_data = _collect_host(ip, inputs["user"], inputs["password"],
                                      inputs["vm_pattern"])
            hosts.append(host_data)
            print(f"OK ({len(host_data.get('vms', []))} VMs)")
        except Exception as e:
            print(f"FAILED — {e}")

    if not hosts:
        sys.exit("[ERROR] No data collected from any host.")

    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
    data = {
        "generated":  timestamp,
        "tool":       f"vminfo_report v{__version__}",
        "customer":   inputs["customer"],
        "vm_filter":  inputs["vm_pattern"] or "all",
        "hosts":      hosts,
    }

    # ── Show what we collected on the console ──
    _print_console_summary(data)

    out_dir = os.path.abspath(args.output_dir)
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f"vminfo_{timestamp}")
    json_path = base + ".json"
    pdf_path  = base + ".pdf"
    xlsx_path = base + ".xlsx"
    zip_path  = base + ".zip"

    print(f"  Generating report bundle (JSON + Excel + PDF)...")
    _write_json(data, json_path)
    _write_excel(data, xlsx_path)
    _write_pdf(data, pdf_path)

    # Bundle into a single ZIP
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(json_path, os.path.basename(json_path))
        zf.write(pdf_path,  os.path.basename(pdf_path))
        zf.write(xlsx_path, os.path.basename(xlsx_path))

    # Remove the loose files now that they are inside the ZIP
    for p in (json_path, pdf_path, xlsx_path):
        try:
            os.remove(p)
        except OSError:
            pass

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print()
    print(f"  >>> ZIP bundle ready: {zip_path}")
    print(f"      ({size_mb:.2f} MB — contains JSON, PDF, and Excel)")
    print()
    print("  Share this ZIP file with the support team.")


def _should_pause(argv):
    """Pause before exit when running as a frozen exe on Windows."""
    if "--no-pause" in argv:
        return False
    if not sys.platform.startswith("win"):
        return False
    return getattr(sys, "frozen", False)


if __name__ == "__main__":
    import traceback as _tb
    _pause = _should_pause(sys.argv)
    sys.argv = [a for a in sys.argv if a != "--no-pause"]
    _exit_code = 0
    try:
        main()
    except KeyboardInterrupt:
        print("\n[interrupted]")
        _exit_code = 130
    except SystemExit as _e:
        _exit_code = _e.code if isinstance(_e.code, int) else (1 if _e.code else 0)
    except Exception:
        print("\n[ERROR] An unexpected error occurred:\n")
        _tb.print_exc()
        _exit_code = 1
    if _pause:
        try:
            input("\n[ Press Enter to close this window ] ")
        except Exception:
            pass
    sys.exit(_exit_code)
