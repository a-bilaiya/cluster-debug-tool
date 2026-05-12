"""Interactive menu-driven console for the RVC env_validation_tool."""

import getpass
import json
import os
import ssl
import sys

from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim

from .troubleshoot import (
    _ts_alarms, _ts_recent_tasks, _ts_cpu_allocation, _ts_memory_allocation,
    _ts_hardware_health, _ts_performance_stats, _ts_vm_details,
    _ts_capacity_usage,
)
from .validator import validate_rvc_vm, validate_requirements, validate_cluster_size


# ── ANSI Colors ──

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_RED    = "\033[31m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_CYAN   = "\033[36m"
_WHITE  = "\033[97m"
_BLUE   = "\033[34m"


def _c(color, text):
    return f"{color}{text}{_RESET}"


def _header(title):
    width = 70
    print()
    print(_c(_BOLD + _CYAN, "═" * width))
    print(_c(_BOLD + _CYAN, f"  {title}"))
    print(_c(_BOLD + _CYAN, "═" * width))


def _section(title):
    print()
    print(_c(_BOLD + _BLUE, f"── {title} " + "─" * max(0, 60 - len(title))))


def _ask(prompt, default=None, secret=False):
    """Prompt user for input."""
    if default:
        display_prompt = f"  {prompt} [{default}]: "
    else:
        display_prompt = f"  {prompt}: "
    if secret:
        val = getpass.getpass(display_prompt)
    else:
        val = input(display_prompt).strip()
    return val if val else (default or "")


def _menu(title, options, allow_back=True):
    """Display a numbered menu and return the chosen index (0-based) or -1 for back."""
    print()
    print(_c(_BOLD, f"  {title}"))
    print()
    for i, opt in enumerate(options, 1):
        print(f"    {_c(_CYAN, str(i)+'.')} {opt}")
    if allow_back:
        print(f"    {_c(_YELLOW, '0.')} Back")
    print()

    while True:
        raw = input("  Choice: ").strip()
        if raw == "0" and allow_back:
            return -1
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print(f"  {_c(_RED, 'Invalid choice. Enter 1-' + str(len(options)) + ' or 0 to go back.')}")


def _status(color, label, msg):
    print(f"  {_c(color, label):<25} {msg}")


# ── Connection ──

def _connect_esxi(host_ip, user, password):
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
    return si, content, host


def _setup_connections(session):
    """Prompt for credentials and connect to all ESXi hosts."""
    _header("Connect to ESXi Hosts")

    raw_ips = _ask("ESXi IPs (comma-separated)")
    if not raw_ips:
        print(_c(_RED, "  No IPs provided."))
        return False

    user = _ask("ESXi username", default="root")
    password = _ask("ESXi password", secret=True)

    session["esxi_ips"] = [ip.strip() for ip in raw_ips.split(",") if ip.strip()]
    session["esxi_user"] = user
    session["esxi_pass"] = password
    session["hosts"] = {}

    print()
    print("  Connecting...")
    for ip in session["esxi_ips"]:
        try:
            si, content, host = _connect_esxi(ip, user, password)
            session["hosts"][ip] = {"si": si, "content": content, "host": host}
            model = host.summary.hardware.model
            ver = host.summary.config.product.version
            print(f"  {_c(_GREEN, '✓')} {ip:<18} {model}  ESXi {ver}")
        except Exception as e:
            print(f"  {_c(_RED, '✗')} {ip:<18} FAILED — {e}")

    connected = [ip for ip in session["esxi_ips"] if ip in session["hosts"]]
    if not connected:
        print(_c(_RED, "\n  No hosts connected. Check IPs and credentials."))
        return False

    # Optional VM pattern
    vm_pat = _ask("VM name pattern to match (e.g. rvc-ls, leave blank for all)", default="")
    session["vm_pattern"] = vm_pat

    print(f"\n  {_c(_GREEN, str(len(connected)) + ' host(s) connected.')}")
    return True


def _load_config_interactive(session):
    """Load credentials from an existing config file."""
    import yaml
    path = _ask("Config file path", default="config_r7k_silver.yaml")
    if not os.path.isfile(path):
        # Try relative to tool directory
        alt = os.path.join(os.path.dirname(__file__), "..", path)
        if os.path.isfile(alt):
            path = alt
        else:
            print(_c(_RED, f"  File not found: {path}"))
            return False

    with open(path) as f:
        cfg = yaml.safe_load(f)

    raw_ips = cfg.get("esxi_ips", "")
    user = cfg.get("esxi_user", "root")
    password = cfg.get("esxi_pass", "")
    vm_pattern = cfg.get("vm_pattern", "")
    session["esxi_ips"] = [ip.strip() for ip in str(raw_ips).split(",") if ip.strip()]
    session["esxi_user"] = user
    session["esxi_pass"] = password
    session["hosts"] = {}

    print()
    print("  Connecting...")
    for ip in session["esxi_ips"]:
        try:
            si, content, host = _connect_esxi(ip, user, password)
            session["hosts"][ip] = {"si": si, "content": content, "host": host}
            model = host.summary.hardware.model
            ver = host.summary.config.product.version
            print(f"  {_c(_GREEN, '✓')} {ip:<18} {model}  ESXi {ver}")
        except Exception as e:
            print(f"  {_c(_RED, '✗')} {ip:<18} FAILED — {e}")

    connected = [ip for ip in session["esxi_ips"] if ip in session["hosts"]]
    if not connected:
        print(_c(_RED, "\n  No hosts connected."))
        return False

    if not vm_pattern:
        vm_pattern = _ask("VM name filter (e.g. rvc-ls, leave blank for all)", default="")
    session["vm_pattern"] = vm_pattern

    print(f"\n  {_c(_GREEN, str(len(connected)) + ' host(s) connected.')}")
    return True


def _pick_host(session):
    """Let user pick one host or all."""
    ips = [ip for ip in session["esxi_ips"] if ip in session["hosts"]]
    if len(ips) == 1:
        return ips

    options = ["All hosts"] + ips
    idx = _menu("Select host", options)
    if idx == -1:
        return None
    if idx == 0:
        return ips
    return [ips[idx - 1]]


# ── Menu Actions ──

def _check_vm_info(session):
    _header("VM Hardware Info")
    targets = _pick_host(session)
    if not targets:
        return

    for ip in targets:
        h = session["hosts"][ip]
        _section(f"Host {ip}")
        try:
            host = h["host"]
            hw_host = host.summary.hardware
            esxi_ver = host.summary.config.product.fullName

            # Host-level summary
            print(f"  ESXi     : {esxi_ver}")
            print(f"  CPU      : {hw_host.cpuModel}")
            print(f"             {hw_host.numCpuCores} cores / {hw_host.numCpuThreads} threads  "
                  f"@ {hw_host.cpuMhz} MHz per core")
            print(f"  Memory   : {round(hw_host.memorySize / (1024**3), 1)} GB")

            data = _ts_vm_details(host)
            vms = data.get("vms", []) if isinstance(data, dict) else []

            # Filter by vm_pattern if set
            vm_pat = session.get("vm_pattern", "").lower()
            if vm_pat:
                vms = [v for v in vms if vm_pat in v.get("vm_name", "").lower()]

            if not vms:
                print(_c(_YELLOW, "\n  No matching VMs found."))
                continue

            for vm in vms:
                name     = vm.get("vm_name", "?")
                power    = vm.get("power_state", "?")
                pcolor   = _GREEN if "On" in power else _YELLOW
                mem_gb   = round(vm.get("memory_mb", 0) / 1024, 1)
                vcpus    = vm.get("num_cpu", "?")
                vm_ver   = vm.get("vm_version", "?")
                guest_os = vm.get("guest_os", "?")
                guest_ip = vm.get("guest_ip", "") or "—"
                hostname = vm.get("guest_hostname", "") or "—"
                tools    = vm.get("tools_status", "?")

                print()
                print(f"  {_c(_BOLD, name)}  [{_c(pcolor, power)}]")
                print(f"    VM Version  : {vm_ver}")
                print(f"    Guest OS    : {guest_os}")
                print(f"    Guest IP    : {guest_ip}   Hostname: {hostname}")
                print(f"    VMware Tools: {tools}")
                print()

                # CPU
                print(f"    {_c(_BOLD, 'CPU')}")
                print(f"      vCPUs     : {vcpus}")
                cpu_alloc = _ts_cpu_allocation(host)
                per_vm_cpu = {v["vm_name"]: v for v in cpu_alloc.get("per_vm", [])}
                cv = per_vm_cpu.get(name, {})
                resv_mhz  = cv.get("reservation_mhz", 0)
                limit_mhz = cv.get("limit_mhz", -1)
                shares    = cv.get("shares_level", "?")
                resv_color = _GREEN if resv_mhz > 0 else _YELLOW
                print(f"      Reservation: {_c(resv_color, str(resv_mhz) + ' MHz')}  "
                      f"({round(resv_mhz/1000, 1)} GHz)")
                print(f"      Limit      : {'Unlimited' if limit_mhz == -1 else str(limit_mhz) + ' MHz'}")
                print(f"      Shares     : {shares}")

                # Memory
                print()
                print(f"    {_c(_BOLD, 'Memory')}")
                print(f"      Configured : {mem_gb} GB ({vm.get('memory_mb', 0)} MB)")
                mem_alloc = _ts_memory_allocation(host)
                per_vm_mem = {v["vm_name"]: v for v in mem_alloc.get("per_vm", [])}
                mv = per_vm_mem.get(name, {})
                mem_resv = mv.get("reservation_mb", 0)
                mem_lim  = mv.get("limit_mb", -1)
                resv_color = _GREEN if mem_resv >= vm.get("memory_mb", 0) else _YELLOW
                print(f"      Reservation: {_c(resv_color, str(mem_resv) + ' MB')}")
                print(f"      Limit      : {'Unlimited' if mem_lim == -1 else str(mem_lim) + ' MB'}")

                # Disks
                disks = vm.get("disks", [])
                print()
                print(f"    {_c(_BOLD, 'Disks')}  ({len(disks)})")
                print(f"      {'Label':<25} {'Size':>10} {'Provisioning':<20} {'Mode'}")
                print("      " + "─" * 75)
                for d in disks:
                    prov = d.get("provisioning", "?")
                    prov_color = _GREEN if prov == "eagerzeroedthick" else _YELLOW
                    print(f"      {d.get('label','?'):<25} "
                          f"{str(round(d.get('capacity_gb', 0), 1)) + ' GB':>10}  "
                          f"{_c(prov_color, prov):<28}  "
                          f"{d.get('disk_mode','?')}")

                # NICs
                nics = vm.get("nics", [])
                controllers = vm.get("controllers", [])
                print()
                print(f"    {_c(_BOLD, 'Network Adapters')}  ({len(nics)})")
                print(f"      {'Label':<20} {'Type':<25} {'Network':<25} {'MAC':<20} {'Connected'}")
                print("      " + "─" * 100)
                for n in nics:
                    conn_color = _GREEN if n.get("connected") else _YELLOW
                    print(f"      {n.get('label','?'):<20} "
                          f"{n.get('type','?'):<25} "
                          f"{n.get('network','?'):<25} "
                          f"{n.get('mac','?'):<20} "
                          f"{_c(conn_color, 'Yes' if n.get('connected') else 'No')}")

                # SCSI Controllers
                scsi = [c for c in controllers if "SCSI" in c.get("type", "") or "Scsi" in c.get("type", "")]
                if scsi:
                    print()
                    print(f"    {_c(_BOLD, 'SCSI Controllers')}  ({len(scsi)})")
                    for c in scsi:
                        ctype = c.get("type", "?")
                        pvscsi_color = _GREEN if "ParaVirtual" in ctype else _YELLOW
                        print(f"      {c.get('label','?'):<30} {_c(pvscsi_color, ctype)}")

        except Exception as e:
            print(_c(_RED, f"  Error: {e}"))
            import traceback; traceback.print_exc()


def _check_alarms(session):
    _header("Check Alarms")
    targets = _pick_host(session)
    if not targets:
        return

    for ip in targets:
        h = session["hosts"][ip]
        _section(f"Host {ip}")
        try:
            data = _ts_alarms(h["si"], h["host"])
            active = data.get("active_alarms", [])
            hist = data.get("alarm_history", [])
            print(f"  Active alarms : {data.get('active_count', 0)}  "
                  f"(critical: {data.get('critical_count',0)}, "
                  f"warning: {data.get('warning_count',0)})")
            print(f"  History (7d)  : {data.get('history_count', 0)} events")
            if active:
                print()
                for a in active:
                    color = _RED if a.get("status") == "red" else _YELLOW
                    print(f"    {_c(color, '●')} {a.get('alarm_name','?'):<50} "
                          f"{a.get('object_name','?')} ({a.get('object_type','?')})")
            else:
                print(f"  {_c(_GREEN, '  No active alarms.')}")
        except Exception as e:
            print(_c(_RED, f"  Error: {e}"))


def _check_reservations(session):
    _header("Check VM CPU / Memory Reservations")
    targets = _pick_host(session)
    if not targets:
        return

    for ip in targets:
        h = session["hosts"][ip]
        _section(f"Host {ip}")
        try:
            hw = h["host"].summary.hardware
            host_total_mhz = hw.cpuMhz * hw.numCpuCores
            host_mem_mb = round(hw.memorySize / (1024**2))

            cpu_data = _ts_cpu_allocation(h["host"])
            mem_data = _ts_memory_allocation(h["host"])

            cpu_host = cpu_data.get("host_summary", {})
            mem_host = mem_data.get("host_summary", {})

            print(f"  Host CPU total : {host_total_mhz} MHz "
                  f"({round(host_total_mhz/1000,1)} GHz)")
            print(f"  Total resv     : {cpu_host.get('total_reservation_mhz',0)} MHz  "
                  f"Verdict: {_c(_GREEN if cpu_host.get('reservation_verdict')=='OK' else _RED, cpu_host.get('reservation_verdict','?'))}")
            print(f"  Host MEM total : {host_mem_mb} MB ({round(host_mem_mb/1024,1)} GB)")
            print(f"  Total mem resv : {mem_host.get('total_reservation_mb',0)} MB  "
                  f"Verdict: {_c(_GREEN if mem_host.get('reservation_verdict')=='OK' else _RED, mem_host.get('reservation_verdict','?'))}")

            per_vm_cpu = {v["vm_name"]: v for v in cpu_data.get("per_vm", [])}
            per_vm_mem = {v["vm_name"]: v for v in mem_data.get("per_vm", [])}

            print()
            print(f"  {'VM Name':<45} {'CPU Resv':>12} {'CPU Limit':>12} {'Mem Resv':>12} {'Mem Limit':>12}")
            print("  " + "─" * 100)
            all_vms = sorted(set(list(per_vm_cpu.keys()) + list(per_vm_mem.keys())))
            for vm_name in all_vms:
                cv = per_vm_cpu.get(vm_name, {})
                mv = per_vm_mem.get(vm_name, {})
                cpu_resv = cv.get("reservation_mhz", 0)
                cpu_lim  = cv.get("limit_mhz", -1)
                mem_resv = mv.get("reservation_mb", 0)
                mem_lim  = mv.get("limit_mb", -1)
                cpu_str  = f"{cpu_resv} MHz"
                cpu_lim_str = "Unlimited" if cpu_lim == -1 else f"{cpu_lim} MHz"
                mem_str  = f"{mem_resv} MB"
                mem_lim_str = "Unlimited" if mem_lim == -1 else f"{mem_lim} MB"
                # Color-code reservation
                resv_color = _GREEN if cpu_resv > 0 else _YELLOW
                print(f"  {vm_name:<45} "
                      f"{_c(resv_color, cpu_str):>20} "
                      f"{cpu_lim_str:>12} "
                      f"{mem_str:>12} "
                      f"{mem_lim_str:>12}")
        except Exception as e:
            print(_c(_RED, f"  Error: {e}"))


def _check_tasks(session):
    _header("Recent Tasks (last 7 days)")
    targets = _pick_host(session)
    if not targets:
        return

    for ip in targets:
        h = session["hosts"][ip]
        _section(f"Host {ip}")
        try:
            data = _ts_recent_tasks(h["si"], h["host"], task_days=7)
            tasks = data.get("tasks", [])
            meta = data.get("collection_metadata", {})
            print(f"  Tasks found: {len(tasks)}  "
                  f"(method: {meta.get('method','?')}, "
                  f"event-mgr supplement: {meta.get('event_manager_supplement',0)})")
            if not tasks:
                print(f"  {_c(_YELLOW, '  No tasks in window.')}")
                continue
            print()
            print(f"  {'#':<4} {'Task Name':<42} {'Target':<22} {'Status':<10} {'Time':<28} {'Error'}")
            print("  " + "─" * 140)
            for i, t in enumerate(tasks, 1):
                name = t.get("task_name") or t.get("description", "?")
                target = t.get("entity_name", "")
                state = t.get("state", "")
                start = (t.get("start_time") or "")[:26]
                error = t.get("error", "")
                color = (_RED if state == "error" else
                         _GREEN if state == "success" else
                         _YELLOW)
                err_short = f"  → {error[:60]}" if error else ""
                print(f"  {i:<4} {name:<42} {target:<22} "
                      f"{_c(color, state):<18} {start:<28}{err_short}")
        except Exception as e:
            print(_c(_RED, f"  Error: {e}"))


def _check_hardware(session):
    _header("Hardware Health")
    targets = _pick_host(session)
    if not targets:
        return

    for ip in targets:
        h = session["hosts"][ip]
        _section(f"Host {ip}")
        try:
            data = _ts_hardware_health(h["host"])
            sensors = data.get("sensors", [])
            total = len(sensors)
            by_status = {}
            for s in sensors:
                st = s.get("status", "unknown")
                by_status.setdefault(st, []).append(s)

            print(f"  Total sensors: {total}")
            for status, items in sorted(by_status.items()):
                color = (_RED if status in ("red","critical","alert") else
                         _YELLOW if status in ("yellow","warning") else _GREEN)
                print(f"  {_c(color, status.upper()):<20} {len(items)} sensors")
                if status not in ("green", "unknown", "normal"):
                    for s in items:
                        print(f"      ● {s.get('name','?'):<40} "
                              f"{s.get('reading','?')} {s.get('units','')}  "
                              f"base={s.get('base_reading','?')}")
        except Exception as e:
            print(_c(_RED, f"  Error: {e}"))


def _check_performance(session):
    _header("Performance Stats")
    targets = _pick_host(session)
    if not targets:
        return

    interval = input("  Lookback minutes [60]: ").strip()
    interval = int(interval) if interval.isdigit() else 60

    for ip in targets:
        h = session["hosts"][ip]
        _section(f"Host {ip}  (last {interval} min)")
        try:
            data = _ts_performance_stats(h["si"], h["host"], interval)
            metrics = data.get("metrics", {})
            if not metrics:
                print(_c(_YELLOW, "  No metrics available."))
                continue
            print(f"  {'Metric':<35} {'Latest':>10} {'Avg':>10} {'Min':>10} {'Max':>10}")
            print("  " + "─" * 80)
            for name, vals in sorted(metrics.items()):
                if not isinstance(vals, dict):
                    continue
                print(f"  {name:<35} "
                      f"{str(vals.get('latest',''))[:8]:>10} "
                      f"{str(vals.get('avg',''))[:8]:>10} "
                      f"{str(vals.get('min',''))[:8]:>10} "
                      f"{str(vals.get('max',''))[:8]:>10}")
        except Exception as e:
            print(_c(_RED, f"  Error: {e}"))


def _check_vm_validation(session):
    _header("VM Validation (RVCLS Spec)")
    targets = _pick_host(session)
    if not targets:
        return

    vm_pat = session.get("vm_pattern", "")

    for ip in targets:
        h = session["hosts"][ip]
        _section(f"Host {ip}")
        try:
            vm_details = _ts_vm_details(h["host"])
            cpu_data = _ts_cpu_allocation(h["host"])
            mem_data = _ts_memory_allocation(h["host"])

            per_vm_cpu = {v["vm_name"]: v for v in cpu_data.get("per_vm", [])}
            per_vm_mem = {v["vm_name"]: v for v in mem_data.get("per_vm", [])}

            vms = vm_details.get("vms", []) if isinstance(vm_details, dict) else vm_details

            if not vms:
                print(_c(_YELLOW, "  No matching VMs found."))
                continue

            for vm in vms:
                vm_name = vm.get("vm_name", vm.get("name", "?"))
                result = validate_rvc_vm(
                    vm,
                    cpu_alloc_vm=per_vm_cpu.get(vm_name),
                    mem_alloc_vm=per_vm_mem.get(vm_name),
                )
                print(f"\n  VM: {_c(_BOLD, vm_name)}")
                for chk in result.get("checks", []):
                    status = chk.get("status", "?")
                    color = (_GREEN if status == "PASS" else
                             _RED if status == "FAIL" else _YELLOW)
                    print(f"    [{_c(color, status):<13}] "
                          f"{chk.get('check','?'):<40} "
                          f"required={chk.get('required','')}  "
                          f"actual={chk.get('actual','')}")
        except Exception as e:
            print(_c(_RED, f"  Error: {e}"))
            import traceback; traceback.print_exc()


def _check_capacity(session):
    _header("Datastore Capacity")
    targets = _pick_host(session)
    if not targets:
        return

    for ip in targets:
        h = session["hosts"][ip]
        _section(f"Host {ip}")
        try:
            data = _ts_capacity_usage(h["host"])
            print(f"  {'Datastore':<30} {'Free':>12} {'Total':>12} {'Used %':>8}")
            print("  " + "─" * 70)
            for ds in data.get("datastores", []):
                pct = ds.get("used_pct", 0)
                color = _RED if pct >= 90 else _YELLOW if pct >= 75 else _GREEN
                print(f"  {ds.get('name','?'):<30} "
                      f"{str(round(ds.get('free_gb',0),1))+' GB':>12} "
                      f"{str(round(ds.get('capacity_gb',0),1))+' GB':>12} "
                      f"{_c(color, str(round(pct,1))+'%'):>16}")
        except Exception as e:
            print(_c(_RED, f"  Error: {e}"))


def _full_troubleshoot(session):
    _header("Full Troubleshoot Run")
    targets = _pick_host(session)
    if not targets:
        return

    # Default output paths
    _DEFAULT_OUT  = "/tool/out/interactive_report"
    print(f"\n  Default output: {_DEFAULT_OUT}.{{json,pdf,xlsx}}")
    custom = input("  Custom base path (Enter to use default): ").strip()
    base = custom if custom else _DEFAULT_OUT

    out_json  = base + ".json"
    out_pdf   = base + ".pdf"
    out_xlsx  = base + ".xlsx"

    print(f"\n  Will generate:")
    print(f"    JSON  → {out_json}")
    print(f"    PDF   → {out_pdf}")
    print(f"    Excel → {out_xlsx}")

    from .troubleshoot import collect_troubleshoot_report
    from .troubleshoot_report import print_troubleshoot_summary
    from .troubleshoot_excel import generate_troubleshoot_xlsx
    from .pdf_report import generate_troubleshoot_pdf
    from .discovery.esxi import ESXiDiscovery
    from .validator import validate_requirements

    reports = []
    for ip in targets:
        h = session["hosts"][ip]
        print(f"\n  [{ip}] Collecting data...")
        try:
            discovery = ESXiDiscovery()
            discovery._si = h["si"]
            discovery._host = h["host"]

            # Build the same full report structure that the CLI produces:
            # host_identity + cpu_details + memory_gb + storage + network +
            # rvc_vms + validation + troubleshoot (nested)
            vm_pat = session.get("vm_pattern", "")
            host_report = discovery.collect_host_report(
                vm_pattern=vm_pat or None,
                vm_exclude=[],
            )
            host_report["esxi_ip"] = ip
            host_report["validation"] = validate_requirements(host_report)
            host_report["troubleshoot"] = collect_troubleshoot_report(
                discovery,
                perf_interval_minutes=60,
                event_days=7,
            )

            tag = host_report.get("host_identity", {}).get("service_tag", "?")
            ts = host_report["troubleshoot"]
            state = ts.get("host_state", {})
            alarms = ts.get("alarms", {})
            print(f"  {_c(_GREEN, '✓')} {ip} — tag={tag}  "
                  f"uptime={state.get('uptime_human','?')}  "
                  f"alarms={alarms.get('total_count', 0)}")
            reports.append(host_report)
        except Exception as e:
            import traceback
            print(_c(_RED, f"  ✗ Error on {ip}: {e}"))
            traceback.print_exc()

    if not reports:
        print(_c(_RED, "\n  No data collected."))
        return

    result = {"hosts": reports, "cluster_name": "Interactive", "vcenter_ip": "?"}
    result["customer_name"] = session.get("customer_name", "")

    # Ensure output directory exists
    out_dir = os.path.dirname(out_json)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # JSON
    with open(out_json, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n  {_c(_GREEN, '✓ JSON  saved:')} {out_json}")

    # Excel
    try:
        generate_troubleshoot_xlsx(result, out_xlsx)
        print(f"  {_c(_GREEN, '✓ Excel saved:')} {out_xlsx}")
    except Exception as e:
        print(_c(_RED, f"  ✗ Excel failed: {e}"))

    # PDF
    try:
        generate_troubleshoot_pdf(result, out_pdf)
        print(f"  {_c(_GREEN, '✓ PDF   saved:')} {out_pdf}")
    except Exception as e:
        print(_c(_RED, f"  ✗ PDF failed: {e}"))

    # Console summary
    print()
    for rep in reports:
        ip  = rep.get("esxi_ip", "?")
        tag = rep.get("host_identity", {}).get("service_tag", "?")
        ts  = rep.get("troubleshoot", {})
        print_troubleshoot_summary(ip, tag, ts)
        print()


_MAIN_MENU_ITEMS = [
    # (key, label, description, action_or_sentinel)
    ("1", "Alarms",         "Check active & historical alarms (7-day window)",              _check_alarms),
    ("2", "Reservations",   "CPU / memory reservation per VM vs RVCLS spec",                _check_reservations),
    ("3", "Tasks",          "Recent tasks + failed operations (7-day window)",               _check_tasks),
    ("4", "Hardware",       "Sensor health — temps, fans, voltage, power",                  _check_hardware),
    ("5", "Performance",    "CPU, memory, disk & network metrics (last 60 min)",            _check_performance),
    ("6", "VM Info",        "VM hardware: disks, CPU/mem, NICs, controllers, ESXi version", _check_vm_info),
    ("7", "Validate VMs",   "Check VMs against RVCLS spec (vCPU, disk, NIC, resv)",        _check_vm_validation),
    ("8", "Capacity",       "Datastore free space and usage %",                             _check_capacity),
    ("9", "Full Report",    "All data → JSON + PDF + Excel",                                _full_troubleshoot),
    ("0", "Reconnect",      "Change hosts or credentials",                                   "reconnect"),
]

_MAIN_MENU_HELP = """\

  HELP — Menu Options
  ───────────────────
  1  Alarms       → active_alarms (red/yellow), alarm_history
                    Source: ESXi EventManager + triggeredAlarmState

  2  Reservations → per-VM CPU reservation_mhz, limit_mhz, shares
                    host-level headroom, RVCLS verdict (need ≥48 GHz)

  3  Tasks        → recentTask buffer + EventManager (7-day)
                    Catches: powerOn/Off, reconfigure, create, errors

  4  Hardware     → hardware sensors (temp/fan/voltage/power)
                    flags any RED/YELLOW sensor readings

  5  Performance  → cpu.usage, mem.active, disk latency, net throughput
                    latest/avg/min/max over the lookback window

  6  VM Info      → per-VM: vCPU, memory (configured + reservation + limit)
                    disks (size, provisioning, mode), NICs (type, network, MAC)
                    SCSI controllers, VM hardware version, ESXi version
                    color-coded: PVSCSI=green, LSI=yellow; eagerzeroedthick=green

  7  Validate VMs → vCPU≥24, RAM≥128GB, NICs≥4, OS disk≥400GB
                    eagerzeroedthick, data disks 3-4, CPU resv≥48GHz

  8  Capacity     → datastore free/used GB and %, flags >75% yellow >90% red

  9  Full Report  → runs all of the above, saves JSON+PDF+Excel

  Press Enter to return to menu."""


def _main_menu(session):
    """Display the improved main menu and return an action callable, 'reconnect', or 'quit'."""
    print()
    print(_c(_BOLD, "  What would you like to do?"))
    print()
    for key, label, desc, _ in _MAIN_MENU_ITEMS:
        print(f"    {_c(_CYAN, key):<12}  {_c(_BOLD, label):<18} {desc}")
    print()
    print(f"    {_c(_YELLOW, 'h'):<12}  {'Help':<18} Show what each option collects")
    print(f"    {_c(_YELLOW, 'q'):<12}  {'Quit'}")
    print()

    while True:
        raw = input("  Choice: ").strip().lower()
        if raw in ("q", "quit"):
            return "quit"
        if raw in ("h", "?", "help"):
            print(_MAIN_MENU_HELP)
            input()
            return _main_menu(session)
        for key, _label, _desc, action in _MAIN_MENU_ITEMS:
            if raw == key:
                return action
        print(_c(_RED, "  Invalid choice. Enter 1-9, 0 to reconnect, h for help, or q to quit."))


def _disconnect_all(session):
    for ip, h in session.get("hosts", {}).items():
        try:
            Disconnect(h["si"])
        except Exception:
            pass
    session["hosts"] = {}


# ── Main interactive loop ──

def _build_session_from_cfg(cfg):
    """Build and connect a session dict from a preloaded config dict."""
    import yaml
    session = {
        "esxi_ips": [],
        "esxi_user": cfg.get("esxi_user", "root"),
        "esxi_pass": cfg.get("esxi_pass", ""),
        "hosts": {},
        "vm_pattern": cfg.get("vm_pattern", ""),
    }
    raw_ips = cfg.get("esxi_ips", "")
    session["esxi_ips"] = [ip.strip() for ip in str(raw_ips).split(",") if ip.strip()]

    print()
    print("  Connecting...")
    for ip in session["esxi_ips"]:
        try:
            si, content, host = _connect_esxi(ip, session["esxi_user"], session["esxi_pass"])
            session["hosts"][ip] = {"si": si, "content": content, "host": host}
            model = host.summary.hardware.model
            ver = host.summary.config.product.version
            print(f"  {_c(_GREEN, '✓')} {ip:<18} {model}  ESXi {ver}")
        except Exception as e:
            print(f"  {_c(_RED, '✗')} {ip:<18} FAILED — {e}")

    connected = [ip for ip in session["esxi_ips"] if ip in session["hosts"]]
    if connected:
        print(f"\n  {_c(_GREEN, str(len(connected)) + ' host(s) connected.')}")
    return session, bool(connected)


def run_interactive(preload_cfg=None):
    """Entry point for interactive console mode."""
    _header("RVC Environment Validation Tool — Interactive Mode")

    session = {
        "esxi_ips": [],
        "esxi_user": "root",
        "esxi_pass": "",
        "hosts": {},
        "vm_pattern": "",
    }

    # If a config was preloaded (from -c flag), auto-connect without prompting
    if preload_cfg:
        session, connected = _build_session_from_cfg(preload_cfg)
    else:
        conn_options = [
            "Enter ESXi credentials manually",
            "Load from config file",
        ]
        idx = _menu("How to connect?", conn_options, allow_back=False)
        if idx == 0:
            connected = _setup_connections(session)
        else:
            connected = _load_config_interactive(session)

    if not connected:
        print(_c(_RED, "\n  Could not connect to any hosts. Exiting."))
        return

    # Main menu loop
    while True:
        connected_ips = [ip for ip in session["esxi_ips"] if ip in session["hosts"]]
        conn_str = ", ".join(connected_ips) if connected_ips else "none"
        _header(f"Main Menu  [{conn_str}]")

        action = _main_menu(session)

        if action == "quit":
            break
        elif action == "reconnect":
            _disconnect_all(session)
            reconnect_options = [
                "Enter ESXi credentials manually",
                "Load from config file",
            ]
            ci = _menu("How to connect?", reconnect_options, allow_back=False)
            if ci == 0:
                _setup_connections(session)
            else:
                _load_config_interactive(session)
        elif callable(action):
            try:
                action(session)
            except KeyboardInterrupt:
                print(_c(_YELLOW, "\n  Interrupted."))

        # Prompt to continue or quit
        print()
        again = input("  Press Enter to continue, or 'q' to quit: ").strip().lower()
        if again == "q":
            break

    _disconnect_all(session)
    print(_c(_GREEN, "\n  Goodbye.\n"))
