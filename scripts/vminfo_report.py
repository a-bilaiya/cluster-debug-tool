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
    p.add_argument("--output-dir", default="/tool/out",
                   help="Output directory (default: /tool/out)")
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
            "  VM name filter (e.g. rvc-ls, leave blank for all): "
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
        ("Tool",       f"RVC Cluster Debug Tool — vminfo_report v{__version__}"),
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

            # Disks
            disks = vm.get("disks", [])
            if disks:
                row += 1
                ws.cell(row=row, column=1, value=f"  Disks ({len(disks)})").font = BOLD
                row += 1
                headers = ["Label", "Size GB", "Provisioning", "Disk Mode", "Controller Key", "Unit", "Backing File"]
                for ci, h in enumerate(headers, start=1):
                    cell = ws.cell(row=row, column=ci, value=h)
                    cell.font = HEADER_FONT
                    cell.fill = HEADER_FILL
                row += 1
                for d in disks:
                    prov = d.get("provisioning", "?")
                    fill = OK_FILL if prov == "eagerzeroedthick" else WARN_FILL
                    vals = [
                        d.get("label", ""), d.get("capacity_gb", 0),
                        prov, d.get("disk_mode", ""),
                        d.get("controller_key", ""),
                        d.get("unit_number", ""),
                        d.get("backing_file", ""),
                    ]
                    for ci, v in enumerate(vals, start=1):
                        cell = ws.cell(row=row, column=ci, value=v)
                        if ci == 3:
                            cell.fill = fill
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

            # Storage Controllers
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
                headers = ["Label", "Type", "Bus #", "Sharing", "Hot-Add", "Key"]
                for ci, h in enumerate(headers, start=1):
                    cell = ws.cell(row=row, column=ci, value=h)
                    cell.font = HEADER_FONT
                    cell.fill = HEADER_FILL
                row += 1
                for c in storage_ctrls:
                    ctype = c.get("type", "")
                    fill = (OK_FILL if "ParaVirtual" in ctype or "NVMe" in ctype or "NVME" in ctype
                            else WARN_FILL if "LsiLogic" in ctype or "BusLogic" in ctype
                            else None)
                    vals = [
                        c.get("label", ""), ctype,
                        c.get("bus_number", ""),
                        c.get("sharing", ""),
                        "Yes" if c.get("hot_add_remove") else "No",
                        c.get("key", ""),
                    ]
                    for ci, v in enumerate(vals, start=1):
                        cell = ws.cell(row=row, column=ci, value=v)
                        if ci == 2 and fill:
                            cell.fill = fill
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


def _write_pdf(data, path):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "VM Hardware Info Report", ln=1)

    # Report metadata
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 6, f"Tool       : RVC Cluster Debug Tool v{__version__}", ln=1)
    pdf.cell(0, 6, f"Generated  : {data.get('generated', '')}", ln=1)
    pdf.cell(0, 6, f"Customer   : {data.get('customer','') or '-'}", ln=1)
    pdf.cell(0, 6, f"Hosts      : {', '.join(h['esxi_ip'] for h in data['hosts'])}", ln=1)
    pdf.cell(0, 6, f"Total VMs  : {sum(len(h.get('vms', [])) for h in data['hosts'])}", ln=1)
    pdf.ln(4)

    for host in data["hosts"]:
        if pdf.get_y() > 250:
            pdf.add_page()
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_fill_color(217, 225, 242)
        pdf.cell(0, 8, f"Host {host['esxi_ip']}  ({host['model']})", ln=1, fill=True)
        pdf.set_font("Helvetica", size=9)
        pdf.cell(0, 5, f"  ESXi: {host['esxi_full']}", ln=1)
        pdf.cell(0, 5, f"  CPU : {host['cpu_model']}  ({host['cpu_cores']}C/{host['cpu_threads']}T @ {host['cpu_mhz']} MHz)", ln=1)
        pdf.cell(0, 5, f"  RAM : {host['memory_gb']} GB", ln=1)
        pdf.ln(2)

        for vm in host.get("vms", []):
            if pdf.get_y() > 250:
                pdf.add_page()
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 6, f"VM: {vm.get('vm_name','?')}  [{vm.get('power_state','?')}]", ln=1)
            pdf.set_font("Helvetica", size=9)
            for label, value in [
                ("VM Version",         vm.get("vm_version", "?")),
                ("Guest OS",           vm.get("guest_os", "?")),
                ("Guest IP",           vm.get("guest_ip", "") or "-"),
                ("VMware Tools",       vm.get("tools_status", "?")),
                ("vCPUs",              vm.get("num_cpu", "?")),
                ("Memory",             f"{round(vm.get('memory_mb', 0)/1024, 1)} GB"),
                ("CPU Reservation",    f"{vm.get('cpu_reservation_mhz', 0)} MHz"),
                ("Memory Reservation", f"{vm.get('mem_reservation_mb', 0)} MB"),
            ]:
                pdf.cell(0, 5, f"   {label:<22} : {value}", ln=1)

            disks = vm.get("disks", [])
            if disks:
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 5, f"   Disks ({len(disks)})", ln=1)
                pdf.set_font("Helvetica", size=8)
                for d in disks:
                    pdf.cell(0, 4,
                             f"      {d.get('label','?'):<20}  "
                             f"{round(d.get('capacity_gb',0),1)} GB   "
                             f"{d.get('provisioning','?'):<18}  "
                             f"{d.get('disk_mode','')}", ln=1)

            nics = vm.get("nics", [])
            if nics:
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 5, f"   NICs ({len(nics)})", ln=1)
                pdf.set_font("Helvetica", size=8)
                for n in nics:
                    pdf.cell(0, 4,
                             f"      {n.get('label','?'):<22}  "
                             f"{n.get('type',''):<22}  "
                             f"{n.get('network','')}  "
                             f"({n.get('mac','')})", ln=1)

            controllers = vm.get("controllers", [])
            ctype_keywords = ("LsiLogic", "BusLogic", "ParaVirtual", "SCSI",
                              "AHCI", "SATA", "NVMe", "NVME", "USB")
            storage_ctrls = [c for c in controllers
                             if any(k in c.get("type", "") for k in ctype_keywords)]
            if storage_ctrls:
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 5, f"   Storage Controllers ({len(storage_ctrls)})", ln=1)
                pdf.set_font("Helvetica", size=8)
                for c in storage_ctrls:
                    pdf.cell(0, 4,
                             f"      {c.get('label','?'):<22}  "
                             f"{c.get('type',''):<32}  "
                             f"bus={c.get('bus_number','?')}  "
                             f"sharing={c.get('sharing','')}", ln=1)
            pdf.ln(2)

    pdf.output(path)


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

    out_dir  = args.output_dir
    os.makedirs(out_dir, exist_ok=True)
    base     = os.path.join(out_dir, f"vminfo_{timestamp}")
    json_path = base + ".json"
    pdf_path  = base + ".pdf"
    xlsx_path = base + ".xlsx"
    zip_path  = base + ".zip"

    print()
    print(f"  Writing reports...")
    _write_json(data, json_path);   print(f"    JSON  : {json_path}")
    _write_excel(data, xlsx_path);  print(f"    Excel : {xlsx_path}")
    _write_pdf(data, pdf_path);     print(f"    PDF   : {pdf_path}")

    # Bundle into a single ZIP
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(json_path, os.path.basename(json_path))
        zf.write(pdf_path,  os.path.basename(pdf_path))
        zf.write(xlsx_path, os.path.basename(xlsx_path))

    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print()
    print(f"  ZIP bundle: {zip_path}  ({size_mb:.2f} MB)")
    print()
    print("  Share the ZIP with Rubrik Support — it contains JSON, PDF, and Excel.")


if __name__ == "__main__":
    main()
