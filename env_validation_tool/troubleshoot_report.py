"""Console output formatting for troubleshoot mode."""


def print_troubleshoot_summary(esxi_ip, service_tag, ts):
    """Print formatted troubleshoot report for one host.

    Args:
        esxi_ip: ESXi host IP address.
        service_tag: Host service tag.
        ts: Troubleshoot data dict from collect_troubleshoot_report().
    """
    w = 70
    print("\n" + "=" * w)
    print(f"  TROUBLESHOOT REPORT: {esxi_ip}  [{service_tag}]")
    print("=" * w)

    # Health summary first — the executive overview
    _section_health_summary(ts.get("health_summary", {}), w)
    _section_host_state(ts.get("host_state", {}), w)
    _section_system_info(ts.get("system_info", {}), w)
    _section_capacity(ts.get("capacity_usage", {}), w)
    _section_alarms(ts.get("alarms", {}), w)
    _section_vm_details(ts.get("vm_details", {}), w)
    _section_hardware_health(ts.get("hardware_health", {}), w)
    _section_performance(ts.get("performance_stats", {}), w)
    _section_io_stats(ts.get("io_stats", {}), w)
    _section_vm_contention(ts.get("vm_contention_stats", {}), w)
    _section_datastore_io(ts.get("datastore_io_stats", {}), w)
    _section_overcommit(ts.get("overcommit_ratios", {}), w)
    _section_memory_alloc(ts.get("memory_allocation", {}), w)
    _section_cpu_alloc(ts.get("cpu_allocation", {}), w)
    _section_network_config(ts.get("network_config", {}), w)
    _section_storage_config(ts.get("storage_config", {}), w)
    _section_services(ts.get("services", {}), w)
    _section_events(ts.get("events", {}), w)
    _section_firewall(ts.get("firewall", {}), w)
    _section_power_policy(ts.get("power_policy", {}), w)
    _section_recent_tasks(ts.get("recent_tasks", {}), w)
    _section_security(ts.get("security_config", {}), w)
    _section_cpu_topology(ts.get("cpu_topology", {}), w)
    _section_coredump_swap(ts.get("coredump_swap", {}), w)
    _section_vm_autostart(ts.get("vm_autostart", {}), w)
    _section_graphics_gpu(ts.get("graphics_gpu", {}), w)
    _section_ipmi_bmc(ts.get("ipmi_bmc", {}), w)
    _section_tcpip_stacks(ts.get("tcpip_stacks", {}), w)
    _section_dvs(ts.get("dvs_config", {}), w)
    _section_vsan(ts.get("vsan_config", {}), w)
    _section_vibs(ts.get("installed_vibs", {}), w)
    _section_snmp(ts.get("snmp_config", {}), w)
    print()


# ── Section renderers ─────────────────────────────────────────────────


def _section_health_summary(data, w):
    overall = data.get("overall_status", "?")
    _header(f"Health Summary — {overall}", w)
    if _is_error(data):
        return

    print(f"  {data.get('summary_text', '')}")

    good = data.get("good", [])
    warnings = data.get("warnings", [])
    critical = data.get("critical", [])

    if critical:
        print()
        for name in critical:
            # Find check details
            detail = ""
            for c in data.get("checks", []):
                if c.get("category") == name:
                    detail = c.get("detail", "")
                    break
            print(f"  [RED]    {name}: {detail}")

    if warnings:
        print()
        for name in warnings:
            detail = ""
            for c in data.get("checks", []):
                if c.get("category") == name:
                    detail = c.get("detail", "")
                    break
            print(f"  [YELLOW] {name}: {detail}")

    if good:
        print(f"\n  [GREEN]  {', '.join(good)}")


def _section_vm_contention(data, w):
    _header("VM Contention Stats", w)
    if _is_error(data):
        return

    vms = data.get("vms", [])
    if not vms:
        print("  No powered-on VMs or no contention data.")
        return

    meta = data.get("sampling_metadata", {})
    if meta:
        print(f"  Collection: {meta.get('description', '')}")

    fmt = "  {name:40s} {ready:>10s} {verdict:>10s} {cpu:>8s} {balloon:>10s} {swap:>10s}"
    print(fmt.format(name="VM Name", ready="Ready%", verdict="Verdict",
                     cpu="CPU%", balloon="Balloon(KB)", swap="Swap(KB)"))
    print("  " + "-" * 82)
    for v in vms:
        ready = v.get("cpu_ready_pct", 0)
        verdict = v.get("verdict", "?")
        cpu = v.get("cpu_usage_pct", {})
        balloon = v.get("mem_balloon_kb", {})
        swap = v.get("mem_swapped_kb", {})
        cpu_avg = cpu.get("average", 0) if isinstance(cpu, dict) else 0
        balloon_avg = balloon.get("average", 0) if isinstance(balloon, dict) else 0
        swap_avg = swap.get("average", 0) if isinstance(swap, dict) else 0
        icon = "[CRIT]" if verdict == "CRITICAL" else (
            "[WARN]" if verdict == "WARNING" else "      ")
        print(f"  {icon}{v.get('vm_name', '?'):34s} {ready:>10.2f} {verdict:>10s} "
              f"{cpu_avg:>8.1f} {balloon_avg:>10.0f} {swap_avg:>10.0f}")


def _section_datastore_io(data, w):
    _header("Datastore I/O Stats", w)
    if _is_error(data):
        return

    datastores = data.get("datastores", [])
    if not datastores:
        print("  No datastore I/O data available.")
        return

    meta = data.get("sampling_metadata", {})
    if meta:
        print(f"  Collection: {meta.get('description', '')}")

    for ds in datastores:
        print(f"\n  --- {ds.get('name', '?')} ---")
        for label, key in [("Read Latency (ms)", "read_latency_ms"),
                           ("Write Latency (ms)", "write_latency_ms"),
                           ("Read IOPS", "read_iops"),
                           ("Write IOPS", "write_iops"),
                           ("Read KBps", "read_kbps"),
                           ("Write KBps", "write_kbps")]:
            stats = ds.get(key, {})
            if stats:
                print(f"    {label:25s} avg={stats.get('average',0):>8.1f}  "
                      f"max={stats.get('maximum',0):>8.1f}")


def _section_overcommit(data, w):
    _header("Resource Overcommit Ratios", w)
    if _is_error(data):
        return

    cpu = data.get("cpu", {})
    mem = data.get("memory", {})
    vm_count = data.get("powered_on_vm_count", 0)

    if cpu:
        ratio = cpu.get("vcpu_to_pcpu_ratio", 0)
        verdict = cpu.get("verdict", "?")
        icon = "[CRIT]" if verdict == "CRITICAL" else (
            "[WARN]" if verdict == "WARNING" else "[OK]  ")
        print(f"  {icon} CPU:    {cpu.get('total_vm_vcpus',0)} vCPUs / "
              f"{cpu.get('host_logical_threads',0)} threads = "
              f"{ratio:.2f}:1  ({verdict})")

    if mem:
        ratio = mem.get("overcommit_ratio", 0)
        verdict = mem.get("verdict", "?")
        icon = "[CRIT]" if verdict == "CRITICAL" else (
            "[WARN]" if verdict == "WARNING" else "[OK]  ")
        print(f"  {icon} Memory: {mem.get('total_vm_configured_mb',0):.0f} MB / "
              f"{mem.get('host_total_mb',0):.0f} MB = "
              f"{ratio:.2f}:1  ({verdict})")
        gap = mem.get("unreserved_gap_mb", 0)
        if gap > 0:
            print(f"         Unreserved gap: {gap:.0f} MB")

    print(f"  Powered-on VMs: {vm_count}")


def _section_host_state(data, w):
    _header("Host State", w)
    if _is_error(data):
        return
    print(f"  Connection State: {data.get('connection_state', '?')}")
    print(f"  Power State:      {data.get('power_state', '?')}")
    print(f"  Uptime:           {data.get('uptime_human', '?')} "
          f"({data.get('uptime_seconds', 0):,} seconds)")
    if data.get("boot_time"):
        print(f"  Boot Time:        {data['boot_time']}")
    print(f"  VMs:              {data.get('vm_count_powered_on', 0)} running "
          f"/ {data.get('vm_count_total', 0)} total")
    if data.get("in_maintenance_mode"):
        print(f"  Maintenance Mode: YES")
    if data.get("reboot_required"):
        print(f"  Reboot Required:  YES")
    if data.get("standby_mode") and data["standby_mode"] != "none":
        print(f"  Standby Mode:     {data['standby_mode']}")


def _section_capacity(data, w):
    _header("Capacity & Usage", w)
    if _is_error(data):
        return

    cpu = data.get("cpu", {})
    mem = data.get("memory", {})
    print(f"  CPU:     {cpu.get('used_ghz', 0)} GHz / "
          f"{cpu.get('total_ghz', 0)} GHz  ({cpu.get('usage_pct', 0)}%)")
    print(f"  Memory:  {mem.get('used_gb', 0)} GB / "
          f"{mem.get('total_gb', 0)} GB  ({mem.get('usage_pct', 0)}%)")

    datastores = data.get("datastores", [])
    if datastores:
        print()
        print("  Datastores:")
        for ds in datastores:
            name = ds.get("name", "?")
            free = ds.get("free_gb", 0)
            cap = ds.get("capacity_gb", 0)
            pct = ds.get("usage_pct", 0)
            cap_tb = round(cap / 1024, 2) if cap >= 1024 else None
            cap_str = f"{cap_tb} TB" if cap_tb else f"{cap} GB"
            print(f"    {name:20s}  {free:>10.1f} GB free / {cap_str}  "
                  f"({pct}% used)")


def _section_alarms(data, w):
    active_count = data.get("active_count", 0)
    history_count = data.get("history_count", 0)
    crit = data.get("critical_count", 0)
    warn = data.get("warning_count", 0)
    _header(f"Alarms — {active_count} active ({crit} critical, {warn} warning), "
            f"{history_count} historical", w)
    if _is_error(data):
        return

    meta = data.get("collection_metadata", {})
    if meta:
        print(f"  History window: last {meta.get('window_days', '?')} days")

    # Active alarms
    active = data.get("active_alarms", [])
    if active:
        print(f"\n  --- Currently Active ({len(active)}) ---")
        for a in active:
            status = a.get("status", "")
            icon = "[CRIT]" if status == "red" else "[WARN]" if status == "yellow" else "[INFO]"
            obj_type = a.get("object_type", "?")
            obj_name = a.get("object_name", "?")
            alarm_name = a.get("alarm_name", "?")
            triggered = a.get("triggered_time", "?")
            ack = a.get("acknowledged_by", "")
            ack_str = f"  (ack: {ack})" if ack else ""
            prefix = f"{obj_type} alarm on {obj_name}" if obj_type == "vm" else "Host alarm"
            print(f"  {icon:6s} {prefix}: \"{alarm_name}\" — {triggered}{ack_str}")
    else:
        print("  No currently active alarms.")

    # Historical alarm events
    history = data.get("alarm_history", [])
    if history:
        print(f"\n  --- Alarm History ({len(history)} events) ---")
        for h in history:
            ts = h.get("time", "?")
            etype = h.get("event_type", "?")
            msg = h.get("message", "")
            # Truncate long messages
            if len(msg) > 120:
                msg = msg[:117] + "..."
            print(f"  {ts}  {etype:35s}  {msg}")


def _section_hardware_health(data, w):
    summary = data.get("summary", {})
    total = summary.get("total", 0)
    warn = summary.get("warning", 0)
    crit = summary.get("critical", 0)
    normal = summary.get("normal", 0)
    _header(f"Hardware Health ({total} sensors: {warn} warning, {crit} critical)",
            w)
    if _is_error(data):
        return

    note = data.get("note")
    if note:
        print(f"  Note: {note}")
        return

    sensors = data.get("sensors", [])
    if not sensors:
        print("  No sensors available.")
        return

    # Show non-green sensors first
    non_green = [s for s in sensors if s.get("status") != "green"]
    if non_green:
        fmt = "  {icon:6s} {name:40s}  Status={status:8s}  Reading={reading} {units}"
        for s in non_green:
            icon = "[CRIT]" if s["status"] == "red" else "[WARN]"
            print(fmt.format(
                icon=icon,
                name=s.get("name", "?"),
                status=s["status"],
                reading=s.get("reading", "?"),
                units=s.get("units", ""),
            ))
    else:
        print(f"  All {total} sensors report normal status.")

    if normal and non_green:
        print(f"  ({normal} normal sensors omitted)")


def _section_performance(data, w):
    interval = data.get("interval_minutes", "?")
    _header(f"Performance Statistics (last {interval} minutes)", w)
    if _is_error(data):
        return

    sampling = data.get("sampling_interval_seconds", "?")
    window = data.get("collection_window", "")
    if window:
        print(f"  Collection: {window}")
    else:
        print(f"  Sampling interval: {sampling}s")

    perf_counters = [
        ("CPU Usage %",        "cpu_usage_pct"),
        ("CPU Ready (ms)",     "cpu_ready_ms"),
        ("CPU CoStop (ms)",    "cpu_costop_ms"),
        ("CPU Latency %",      "cpu_latency_pct"),
        ("Memory Usage %",     "memory_usage_pct"),
        ("Mem Balloon (KB)",   "mem_balloon_kb"),
        ("Mem Swap Used (KB)", "mem_swapused_kb"),
        ("Mem Swap In (KBps)", "mem_swapin_kbps"),
        ("Mem Swap Out (KBps)","mem_swapout_kbps"),
        ("Mem Active (KB)",    "mem_active_kb"),
    ]
    for label, key in perf_counters:
        stats = data.get(key)
        if not stats:
            continue
        print(f"  {label:20s}  Latest={stats['latest']:>8.1f}  "
              f"Avg={stats['average']:>8.1f}  "
              f"Min={stats['minimum']:>8.1f}  "
              f"Max={stats['maximum']:>8.1f}  "
              f"({stats['samples']} samples @ {sampling}s intervals)")


def _section_memory_alloc(data, w):
    _header("Resource Allocation — Memory", w)
    if _is_error(data):
        return

    host_gb = data.get("host_total_gb", 0)
    res_gb = data.get("total_reservation_gb", 0)
    avail_gb = data.get("available_reservation_gb", 0)
    print(f"  Host Total: {host_gb} GB  |  "
          f"Reserved: {res_gb} GB  |  "
          f"Available: {avail_gb} GB")

    per_vm = data.get("per_vm", [])
    if not per_vm:
        print("  No VMs.")
        return

    print()
    fmt = "  {name:40s} {res:>10s}  {limit:>10s}  {shares:>8s}  {level:>8s}"
    print(fmt.format(name="VM Name", res="Reserv(MB)",
                     limit="Limit(MB)", shares="Shares", level="Level"))
    print("  " + "-" * 80)
    for v in per_vm:
        limit = v.get("limit_mb", -1)
        limit_str = "Unlimited" if limit == -1 else str(limit)
        print(fmt.format(
            name=v.get("vm_name", "?")[:40],
            res=str(v.get("reservation_mb", 0)),
            limit=limit_str,
            shares=str(v.get("shares_value", 0)),
            level=str(v.get("shares_level", "N/A")),
        ))


def _section_cpu_alloc(data, w):
    _header("Resource Allocation — CPU", w)
    if _is_error(data):
        return

    per_vm = data.get("per_vm", [])
    if not per_vm:
        print("  No VMs.")
        return

    fmt = "  {name:40s} {cpus:>5s} {res:>12s}  {limit:>10s}  {shares:>8s}  {level:>8s}"
    print(fmt.format(name="VM Name", cpus="vCPU", res="Reserv(MHz)",
                     limit="Limit(MHz)", shares="Shares", level="Level"))
    print("  " + "-" * 88)
    for v in per_vm:
        limit = v.get("limit_mhz", -1)
        limit_str = "Unlimited" if limit == -1 else str(limit)
        print(fmt.format(
            name=v.get("vm_name", "?")[:40],
            cpus=str(v.get("num_cpu", 0)),
            res=str(v.get("reservation_mhz", 0)),
            limit=limit_str,
            shares=str(v.get("shares_value", 0)),
            level=str(v.get("shares_level", "N/A")),
        ))


def _section_recent_tasks(data, w):
    total = data.get("total_count", 0)
    meta = data.get("collection_metadata", {})
    days = meta.get("window_days", "?")
    _header(f"Tasks ({total} in last {days} days)", w)
    if _is_error(data):
        return

    if meta:
        method = meta.get("method", "")
        print(f"  Window: {meta.get('window_start', '?')[:19]} → "
              f"{meta.get('window_end', '?')[:19]}  (via {method})")

    note = data.get("note")
    if note:
        print(f"  Note: {note}")
        return

    tasks = data.get("tasks", [])
    if not tasks:
        print("  No tasks in this window.")
        return

    fmt = "  {state:10s} {desc:45s} {entity:25s} {start:22s} {err}"
    print(fmt.format(state="State", desc="Description", entity="Entity",
                     start="Start Time", err="Error"))
    print("  " + "-" * 110)
    for t in tasks[:25]:
        state = t.get("state", "?")
        icon = "[RUN] " if state == "running" else (
            "[FAIL]" if state == "error" else "      ")
        desc = t.get("description", "") or t.get("name", "?")
        entity = t.get("entity_name", "")[:25]
        start = t.get("start_time", "")[:22]
        err = t.get("error", "")
        err_str = f"  ERR: {err[:40]}" if err else ""
        print(f"  {icon}{state:10s} {desc:45s} {entity:25s} {start:22s}{err_str}")

    if total > 25:
        print(f"  ({total - 25} more tasks — see JSON)")


def _section_io_stats(data, w):
    interval = data.get("interval_minutes", "?")
    _header(f"I/O Statistics (last {interval} minutes)", w)
    if _is_error(data):
        return

    sampling = data.get("sampling_interval_seconds", "?")
    window = data.get("collection_window", "")
    if window:
        print(f"  Collection: {window}")
    else:
        print(f"  Sampling interval: {sampling}s")

    def _print_metric(label, key):
        stats = data.get(key)
        if not stats:
            return
        print(f"    {label:28s}  Latest={stats['latest']:>8.1f}  "
              f"Avg={stats['average']:>8.1f}  "
              f"Min={stats['minimum']:>8.1f}  "
              f"Max={stats['maximum']:>8.1f}  "
              f"({stats['samples']} samples @ {sampling}s intervals)")

    # Disk I/O (aggregate)
    disk_metrics = [
        ("Read Latency (ms)",          "read_latency_ms"),
        ("Write Latency (ms)",         "write_latency_ms"),
        ("Device Read Latency (ms)",   "device_read_latency_ms"),
        ("Device Write Latency (ms)",  "device_write_latency_ms"),
        ("Kernel Read Latency (ms)",   "kernel_read_latency_ms"),
        ("Kernel Write Latency (ms)",  "kernel_write_latency_ms"),
        ("Queue Read Latency (ms)",    "queue_read_latency_ms"),
        ("Queue Write Latency (ms)",   "queue_write_latency_ms"),
        ("Read IOPS",                  "read_iops"),
        ("Write IOPS",                 "write_iops"),
        ("Read KBps",                  "read_kbps"),
        ("Write KBps",                 "write_kbps"),
        ("Max Queue Depth",            "max_queue_depth"),
        ("Commands Aborted",           "commands_aborted"),
        ("Bus Resets",                 "bus_resets"),
    ]

    has_disk = any(data.get(key) for _, key in disk_metrics)
    if has_disk:
        print("  Disk I/O (aggregate):")
        for label, key in disk_metrics:
            _print_metric(label, key)

    # Per-disk breakdown
    per_disk = data.get("per_disk", [])
    if per_disk:
        print(f"\n  Per-Disk Breakdown ({len(per_disk)} devices):")
        for dd in per_disk:
            dev = dd.get("device", "?")
            print(f"    --- {dev} ---")
            rl = dd.get("read_latency_ms", {})
            wl = dd.get("write_latency_ms", {})
            ri = dd.get("read_iops", {})
            wi = dd.get("write_iops", {})
            if rl:
                print(f"      Read Lat:  avg={rl.get('average',0):.1f}ms  max={rl.get('maximum',0):.1f}ms")
            if wl:
                print(f"      Write Lat: avg={wl.get('average',0):.1f}ms  max={wl.get('maximum',0):.1f}ms")
            if ri:
                print(f"      Read IOPS: avg={ri.get('average',0):.1f}  max={ri.get('maximum',0):.1f}")
            if wi:
                print(f"      Write IOPS: avg={wi.get('average',0):.1f}  max={wi.get('maximum',0):.1f}")
            ca = dd.get("commands_aborted", {})
            br = dd.get("bus_resets", {})
            if ca and ca.get("maximum", 0) > 0:
                print(f"      Cmds Aborted: {ca['maximum']}")
            if br and br.get("maximum", 0) > 0:
                print(f"      Bus Resets: {br['maximum']}")

    # Network I/O (aggregate)
    net_metrics = [
        ("Net RX (KBps)",     "net_rx_kbps"),
        ("Net TX (KBps)",     "net_tx_kbps"),
        ("Packets RX",        "net_packets_rx"),
        ("Packets TX",        "net_packets_tx"),
        ("Dropped RX",        "net_dropped_rx"),
        ("Dropped TX",        "net_dropped_tx"),
        ("Errors RX",         "net_errors_rx"),
        ("Errors TX",         "net_errors_tx"),
    ]

    has_net = any(data.get(key) for _, key in net_metrics)
    if has_net:
        print("\n  Network I/O (aggregate):")
        for label, key in net_metrics:
            _print_metric(label, key)

    # Per-NIC breakdown
    per_nic = data.get("per_nic", [])
    if per_nic:
        print(f"\n  Per-NIC Breakdown ({len(per_nic)} interfaces):")
        for nd in per_nic:
            iface = nd.get("interface", "?")
            rx = nd.get("rx_kbps", {})
            tx = nd.get("tx_kbps", {})
            dr = nd.get("dropped_rx", {})
            dt = nd.get("dropped_tx", {})
            er = nd.get("errors_rx", {})
            et = nd.get("errors_tx", {})
            print(f"    --- {iface} ---")
            if rx:
                print(f"      RX: avg={rx.get('average',0):.1f} KBps  max={rx.get('maximum',0):.1f} KBps")
            if tx:
                print(f"      TX: avg={tx.get('average',0):.1f} KBps  max={tx.get('maximum',0):.1f} KBps")
            if dr and dr.get("maximum", 0) > 0:
                print(f"      Dropped RX: {dr['maximum']}")
            if dt and dt.get("maximum", 0) > 0:
                print(f"      Dropped TX: {dt['maximum']}")
            if er and er.get("maximum", 0) > 0:
                print(f"      Errors RX: {er['maximum']}")
            if et and et.get("maximum", 0) > 0:
                print(f"      Errors TX: {et['maximum']}")

    if not has_disk and not has_net:
        print("  No I/O statistics available.")
        return

    # Bottleneck warnings
    bottlenecks = data.get("bottlenecks", [])
    if bottlenecks:
        print()
        for b in bottlenecks:
            print(f"  [WARN] {b}")


def _section_system_info(data, w):
    _header("System Information", w)
    if _is_error(data):
        return
    print(f"  ESXi: {data.get('esxi_full_name', 'N/A')}")
    print(f"  Build: {data.get('esxi_build', '')}  "
          f"Patch: {data.get('esxi_patch_level', '')}")
    print(f"  Server: {data.get('vendor', '')} {data.get('model', '')}")
    print(f"  Serial: {data.get('serial', '')}  UUID: {data.get('uuid', '')}")
    print(f"  BIOS: {data.get('bios_version', '')} "
          f"({data.get('bios_vendor', '')}) "
          f"Date: {data.get('bios_release_date', '')}")
    print(f"  NUMA: {data.get('numa_nodes', 0)} nodes")

    licenses = data.get("licenses", [])
    if licenses:
        for lic in licenses:
            print(f"  License: {lic.get('name')} — "
                  f"used={lic.get('used')}/{lic.get('total')}")


def _section_vm_details(data, w):
    vms = data.get("vms", [])
    total = data.get("total_count", 0)
    _header(f"Virtual Machines ({total} total)", w)
    if _is_error(data):
        return
    if not vms:
        print("  No VMs on this host.")
        return

    for vm in vms:
        state = vm.get("power_state", "?").replace("powered", "")
        print(f"\n  VM: {vm.get('vm_name')}  [{state}]")
        print(f"    OS: {vm.get('guest_os', 'N/A')}  "
              f"Ver: {vm.get('vm_version', '')}  "
              f"CPU: {vm.get('num_cpu', 0)}  "
              f"RAM: {vm.get('memory_mb', 0)} MB")
        if vm.get("guest_ip"):
            print(f"    IP: {vm.get('guest_ip')}  "
                  f"Host: {vm.get('guest_hostname', '')}")
        print(f"    Tools: {vm.get('tools_status', 'N/A')}")
        disks = vm.get("disks", [])
        if disks:
            for d in disks:
                print(f"    Disk: {d.get('label')} — "
                      f"{d.get('capacity_gb', 0)} GB")
        nics = vm.get("nics", [])
        if nics:
            for n in nics:
                print(f"    NIC: {n.get('label')} "
                      f"({n.get('type', '')}) "
                      f"net={n.get('network', '')} "
                      f"mac={n.get('mac', '')}")
        if vm.get("has_snapshots"):
            snaps = vm.get("snapshots", [])
            for s in snaps:
                print(f"    Snap: {s.get('name')} — {s.get('create_time')}")


def _section_network_config(data, w):
    _header("Network Configuration", w)
    if _is_error(data):
        return

    pnics = data.get("pnics", [])
    if pnics:
        print("  Physical NICs:")
        for p in pnics:
            up = "UP" if p.get("link_up") else "DOWN"
            print(f"    {p.get('device'):8s} mac={p.get('mac')}  "
                  f"drv={p.get('driver')}  "
                  f"{p.get('link_speed_mb', 0)}Mb [{up}]")
            offload = p.get("offload", {})
            if offload:
                parts = []
                if offload.get("tso_enabled"):
                    parts.append("TSO")
                if offload.get("cso_enabled"):
                    parts.append("CSO")
                if offload.get("wake_on_lan"):
                    parts.append("WoL")
                if parts:
                    print(f"             offload: {', '.join(parts)}")

    vswitches = data.get("vswitches", [])
    if vswitches:
        print("  vSwitches:")
        for vs in vswitches:
            pnics_str = ", ".join(vs.get("pnics", []))
            print(f"    {vs.get('name'):12s} ports={vs.get('num_ports')}  "
                  f"mtu={vs.get('mtu')}  pnics=[{pnics_str}]")
            pol = vs.get("policy", {})
            if pol:
                sec = pol.get("security", {})
                team = pol.get("nic_teaming", {})
                if sec:
                    print(f"      Security: promisc={sec.get('allow_promiscuous')}  "
                          f"mac_chg={sec.get('mac_changes')}  "
                          f"forged={sec.get('forged_transmits')}")
                if team:
                    print(f"      Teaming: policy={team.get('policy')}  "
                          f"active={team.get('active_nics')}  "
                          f"standby={team.get('standby_nics')}")

    portgroups = data.get("portgroups", [])
    if portgroups:
        print("  Port Groups:")
        for pg in portgroups:
            print(f"    {pg.get('name'):20s} vlan={pg.get('vlan_id')}  "
                  f"vswitch={pg.get('vswitch')}")
            pol = pg.get("policy_override", {})
            if pol:
                sec = pol.get("security", {})
                if sec and any(v is not None for v in sec.values()):
                    print(f"      Policy override: promisc={sec.get('allow_promiscuous')}  "
                          f"mac_chg={sec.get('mac_changes')}  "
                          f"forged={sec.get('forged_transmits')}")

    vkernel = data.get("vmkernel_adapters", [])
    if vkernel:
        print("  VMkernel:")
        for vk in vkernel:
            extra = ""
            if vk.get("mtu"):
                extra += f"  mtu={vk['mtu']}"
            if vk.get("netstack"):
                extra += f"  stack={vk['netstack']}"
            if vk.get("vmotion_enabled"):
                extra += "  [vMotion]"
            print(f"    {vk.get('device'):8s} pg={vk.get('portgroup')}  "
                  f"ip={vk.get('ip', '')}/{vk.get('subnet', '')}{extra}")
            ipv6 = vk.get("ipv6", {})
            if ipv6 and ipv6.get("addresses"):
                for addr in ipv6["addresses"]:
                    print(f"             IPv6: {addr.get('address')}/{addr.get('prefix_length')}  "
                          f"origin={addr.get('origin', '')}")

    dns = data.get("dns", {})
    if dns:
        print(f"  DNS: {', '.join(dns.get('servers', []))}")
        print(f"  Domain: {dns.get('domain', '')}")

    ntp = data.get("ntp", {})
    if ntp and ntp.get("servers"):
        print(f"  NTP: {', '.join(ntp['servers'])}  "
              f"TZ={ntp.get('timezone', '')}")

    cdp_lldp = data.get("cdp_lldp", [])
    if cdp_lldp:
        print("  CDP/LLDP:")
        for c in cdp_lldp:
            parts = [f"{c.get('device')}"]
            if c.get("switch_id"):
                parts.append(f"switch={c['switch_id']}")
            if c.get("port_id"):
                parts.append(f"port={c['port_id']}")
            print(f"    {' '.join(parts)}")


def _section_storage_config(data, w):
    _header("Storage Configuration", w)
    if _is_error(data):
        return

    if data.get("iscsi_enabled"):
        print("  iSCSI: ENABLED (software)")

    hbas = data.get("hbas", [])
    if hbas:
        print(f"  HBAs ({len(hbas)}):")
        for h in hbas:
            extra = ""
            if h.get("iscsi_name"):
                extra = f"  iqn={h['iscsi_name']}"
            print(f"    {h.get('device'):12s} {h.get('type')}  "
                  f"model={h.get('model', '')[:30]}  "
                  f"drv={h.get('driver')}  "
                  f"status={h.get('status')}{extra}")

    iscsi_targets = data.get("iscsi_targets", [])
    if iscsi_targets:
        print(f"  iSCSI Targets ({len(iscsi_targets)}):")
        for t in iscsi_targets:
            name = t.get("iscsi_name", "")
            name_str = f"  iqn={name}" if name else ""
            print(f"    [{t.get('type')}] {t.get('address')}:{t.get('port')}"
                  f"  hba={t.get('hba_device')}{name_str}")

    luns = data.get("scsi_luns", [])
    if luns:
        print(f"  SCSI LUNs ({len(luns)}):")
        for l in luns:
            ssd_str = ""
            if l.get("ssd") is True:
                ssd_str = " [SSD]"
            elif l.get("ssd") is False:
                ssd_str = " [HDD]"
            qd = l.get("queue_depth")
            qd_str = f"  qd={qd}" if qd is not None else ""
            print(f"    {l.get('canonical_name', ''):30s}  "
                  f"{l.get('model', ''):18s}  "
                  f"{l.get('capacity_gb', 0):>8.1f} GB  "
                  f"{l.get('operational_state', '')}{ssd_str}{qd_str}")

    mp = data.get("multipath", [])
    if mp:
        print(f"  Multipath ({len(mp)} LUNs):")
        for m in mp:
            active = sum(1 for p in m.get("paths", []) if p.get("is_working"))
            print(f"    {m.get('lun_id', ''):30s}  "
                  f"policy={m.get('policy', '')}  "
                  f"paths={m.get('path_count')} ({active} active)")

    volumes = data.get("file_system_volumes", [])
    if volumes:
        print(f"  Volumes ({len(volumes)}):")
        for v in volumes:
            extra_parts = []
            if v.get("ssd"):
                extra_parts.append("SSD")
            if v.get("vmfs_version"):
                extra_parts.append(f"VMFS {v['vmfs_version']}")
            if v.get("nfs_remote_host"):
                extra_parts.append(f"NFS:{v['nfs_remote_host']}:{v.get('nfs_remote_path', '')}")
            extra = f"  [{', '.join(extra_parts)}]" if extra_parts else ""
            print(f"    {v.get('name', ''):20s} type={v.get('type', '')}  "
                  f"{v.get('capacity_gb', 0)} GB  "
                  f"path={v.get('path', '')}{extra}")
            exts = v.get("extents", [])
            if exts:
                for ext in exts:
                    print(f"      extent: {ext.get('disk_name')}:{ext.get('partition')}")


def _section_services(data, w):
    total = data.get("total_count", 0)
    running = data.get("running_count", 0)
    _header(f"Services ({total} total, {running} running)", w)
    if _is_error(data):
        return

    services = data.get("services", [])
    if not services:
        print("  No services.")
        return

    # Show running services
    running_svcs = [s for s in services if s.get("running")]
    stopped_svcs = [s for s in services if not s.get("running")]

    if running_svcs:
        print("  Running:")
        for s in running_svcs:
            print(f"    {s.get('key'):30s} policy={s.get('policy')}")

    if stopped_svcs:
        print(f"  Stopped ({len(stopped_svcs)}):")
        for s in stopped_svcs[:10]:
            print(f"    {s.get('key'):30s} policy={s.get('policy')}")
        if len(stopped_svcs) > 10:
            print(f"    ... +{len(stopped_svcs) - 10} more stopped services")


def _section_events(data, w):
    total = data.get("total_count", 0)
    meta = data.get("collection_metadata", {})
    days = meta.get("window_days", "?")
    _header(f"Events ({total} in last {days} days)", w)
    if _is_error(data):
        return

    if meta:
        print(f"  Window: {meta.get('window_start', '?')[:19]} → "
              f"{meta.get('window_end', '?')[:19]}")

    events = data.get("events", [])
    if not events:
        print("  No events in this window.")
        return

    for e in events[:30]:
        time_str = e.get("time", "")[:19]
        etype = e.get("type", "")[:25]
        msg = e.get("message", "")[:60]
        print(f"  {time_str}  [{etype:25s}]  {msg}")
    if total > 30:
        print(f"  ... +{total - 30} more events (see JSON)")


def _section_firewall(data, w):
    total = data.get("total_count", 0)
    enabled = data.get("enabled_count", 0)
    _header(f"Firewall ({total} rulesets, {enabled} enabled)", w)
    if _is_error(data):
        return

    rulesets = data.get("rulesets", [])
    if not rulesets:
        print("  No firewall rulesets.")
        return

    enabled_rs = [r for r in rulesets if r.get("enabled")]
    if enabled_rs:
        print("  Enabled rulesets:")
        for rs in enabled_rs[:15]:
            rules = rs.get("rules", [])
            rule_str = ", ".join(
                f"{r.get('port_start')}/{r.get('protocol')}"
                for r in rules[:3]
            )
            if len(rules) > 3:
                rule_str += f"... +{len(rules) - 3}"
            print(f"    {rs.get('key'):30s} rules=[{rule_str}]")
        if len(enabled_rs) > 15:
            print(f"    ... +{len(enabled_rs) - 15} more")


def _section_power_policy(data, w):
    _header("Power Policy", w)
    if _is_error(data) or not data:
        return

    print(f"  Policy: {data.get('current_policy_name', 'N/A')} "
          f"(key={data.get('current_policy_key', '')})")
    if data.get("current_policy_desc"):
        print(f"  Desc: {data['current_policy_desc']}")
    print(f"  CPU Policy: {data.get('cpu_policy', 'N/A')}  "
          f"HW Support: {data.get('hw_support', 'N/A')}")
    ht_active = data.get("hyperthreading_active")
    if ht_active is not None:
        print(f"  Hyperthreading: "
              f"{'Active' if ht_active else 'Inactive'}  "
              f"(available={data.get('hyperthreading_available', 'N/A')})")


def _section_security(data, w):
    _header("Security Configuration", w)
    if _is_error(data) or not data:
        return
    print(f"  Lockdown Mode:  {data.get('lockdown_mode', 'N/A')}")
    print(f"  Admin Disabled: {data.get('admin_disabled', 'N/A')}")
    print(f"  SSL Thumbprint: {data.get('ssl_thumbprint', 'N/A')}")
    print(f"  Certificate:    {'Present' if data.get('certificate_present') else 'None'}"
          f"  ({data.get('certificate_bytes', 0)} bytes)")
    print(f"  TPM:            {'Present' if data.get('tpm_present') else 'None'}"
          f"  ver={data.get('tpm_version', 'N/A')}")
    print(f"  Crypto:         {'Enabled' if data.get('crypto_enabled') else 'Disabled'}")
    for ac in data.get("auth_configs", []):
        en = "enabled" if ac.get("enabled") else "disabled"
        domain = f"  domain={ac['joined_domain']}" if ac.get("joined_domain") else ""
        print(f"  Auth: {ac.get('type', '?')} ({en}){domain}")


def _section_cpu_topology(data, w):
    _header("CPU Topology", w)
    if _is_error(data) or not data:
        return
    print(f"  Sockets: {data.get('num_cpu_pkgs', '?')}  "
          f"Cores: {data.get('num_cpu_cores', '?')}  "
          f"Threads: {data.get('num_cpu_threads', '?')}")
    print(f"  Cores/Socket: {data.get('cores_per_socket', '?')}  "
          f"Threads/Core: {data.get('threads_per_core', '?')}")
    numa = data.get("numa", {})
    if numa:
        print(f"  NUMA: {numa.get('num_nodes', '?')} node(s)")
        for ni, node in enumerate(numa.get("nodes", [])):
            print(f"    Node {ni}: {node.get('memory_size_gb', '?')} GB  "
                  f"CPUs={len(node.get('cpu_ids', []))}")


def _section_coredump_swap(data, w):
    _header("Coredump / Swap / Scratch", w)
    if _is_error(data) or not data:
        return
    cd = data.get("coredump")
    if cd and isinstance(cd, dict) and not cd.get("status"):
        print(f"  Coredump Disk:    {cd.get('disk_name', 'N/A')}  "
              f"partition={cd.get('partition', 'N/A')}")
    else:
        print(f"  Coredump:         Not configured")
    print(f"  Swap Datastore:   {data.get('swap_datastore') or 'None'}")
    print(f"  Scratch Config:   {data.get('scratch_configured', 'N/A')}")
    print(f"  Scratch Current:  {data.get('scratch_current', 'N/A')}")


def _section_vm_autostart(data, w):
    _header("VM AutoStart", w)
    if _is_error(data) or not data:
        return
    print(f"  Enabled: {data.get('enabled', False)}")
    if data.get("enabled"):
        print(f"  Default Start Delay: {data.get('default_start_delay', '?')}s  "
              f"Stop Action: {data.get('default_stop_action', '?')}")
    for v in data.get("vms", []):
        print(f"    {v.get('vm_name', '?')}  order={v.get('start_order', '?')}  "
              f"action={v.get('start_action', '?')}")


def _section_graphics_gpu(data, w):
    _header("Graphics / GPU", w)
    if _is_error(data) or not data:
        return
    devices = data.get("devices", [])
    if devices:
        for d in devices:
            print(f"  {d.get('device_name', '?')}  "
                  f"vendor={d.get('vendor_name', '?')}  "
                  f"mem={d.get('gpu_memory_mb', 0)}MB  "
                  f"type={d.get('graphics_type', '?')}")
    else:
        print(f"  No GPU devices detected.")
    cfg = data.get("config", {})
    if cfg:
        print(f"  Default type: {cfg.get('host_default_graphics_type', 'N/A')}")


def _section_ipmi_bmc(data, w):
    _header("IPMI / BMC (iDRAC)", w)
    if _is_error(data) or not data:
        return
    if data.get("present"):
        print(f"  BMC IP:  {data.get('bmc_ip', 'N/A')}")
        print(f"  BMC MAC: {data.get('bmc_mac', 'N/A')}")
    else:
        print(f"  BMC/IPMI: Not available via API")


def _section_tcpip_stacks(data, w):
    _header("TCP/IP Stacks", w)
    if _is_error(data) or not data:
        return
    stacks = data.get("stacks", [])
    if not stacks:
        print(f"  No TCP/IP stacks found.")
        return
    for s in stacks:
        gw = s.get("default_gateway", "")
        dns = ", ".join(s.get("dns_servers", []))
        print(f"  {s.get('key', '?'):20s}  gw={gw}  dns=[{dns}]")


def _section_dvs(data, w):
    _header("Distributed Virtual Switches", w)
    if _is_error(data) or not data:
        return
    switches = data.get("proxy_switches", [])
    if not switches:
        print(f"  No DVS proxy switches on this host.")
        return
    for s in switches:
        uplinks = ", ".join(s.get("uplink_pnics", []))
        print(f"  {s.get('dvs_name', '?')}  ports={s.get('num_ports', 0)}  "
              f"mtu={s.get('mtu', 0)}  uplinks=[{uplinks}]")


def _section_vsan(data, w):
    _header("vSAN Configuration", w)
    if _is_error(data) or not data:
        return
    if not data.get("enabled"):
        print(f"  vSAN: Not enabled on this host.")
        return
    print(f"  Cluster UUID: {data.get('cluster_uuid', 'N/A')}")
    print(f"  Node UUID:    {data.get('node_uuid', 'N/A')}")
    for i, dm in enumerate(data.get("disk_mappings", [])):
        print(f"  Disk Group {i}: SSD={dm.get('ssd', '')}  "
              f"HDDs={dm.get('hdds', [])}")


def _section_vibs(data, w):
    _header("Installed VIBs / Packages", w)
    if _is_error(data) or not data:
        return
    vibs = data.get("vibs", [])
    if vibs:
        print(f"  {len(vibs)} packages installed:")
        for v in vibs[:20]:
            print(f"    {v.get('name', '?'):40s} {v.get('version', '')}")
        if len(vibs) > 20:
            print(f"    ... +{len(vibs) - 20} more (see Excel/JSON)")
    else:
        print(f"  Image Profile: {data.get('image_profile', 'N/A')}")
        if data.get("note"):
            print(f"  Note: {data['note']}")


def _section_snmp(data, w):
    _header("SNMP Configuration", w)
    if _is_error(data) or not data:
        return
    if data.get("present") is False:
        print(f"  SNMP: Not available")
        return
    print(f"  Enabled: {data.get('enabled', 'N/A')}  "
          f"Port: {data.get('port', 161)}")
    communities = data.get("read_only_communities", [])
    if communities:
        print(f"  Communities: {', '.join(communities)}")
    for t in data.get("trap_targets", []):
        print(f"  Trap: {t.get('hostname', '?')}:{t.get('port', 0)}")


# ── Helpers ───────────────────────────────────────────────────────────


def print_vcenter_alarms(vc_alarms):
    """Print vCenter-wide alarms (datacenter scope)."""
    w = 70
    print("\n" + "=" * w)
    print("  vCenter Alarms (Datacenter-Wide)")
    print("=" * w)

    active_count = vc_alarms.get("active_count", 0)
    history_count = vc_alarms.get("history_count", 0)
    crit = vc_alarms.get("critical_count", 0)
    warn = vc_alarms.get("warning_count", 0)

    print(f"  Active: {active_count} ({crit} critical, {warn} warning)")
    print(f"  Historical events: {history_count}")

    meta = vc_alarms.get("collection_metadata", {})
    if meta:
        print(f"  Window: last {meta.get('window_days', '?')} days")

    active = vc_alarms.get("active_alarms", [])
    if active:
        print(f"\n  --- Currently Active ({len(active)}) ---")
        for a in active:
            status = a.get("status", "")
            icon = "[CRIT]" if status == "red" else (
                "[WARN]" if status == "yellow" else "[INFO]")
            obj_type = a.get("object_type", "?")
            obj_name = a.get("object_name", "?")
            alarm_name = a.get("alarm_name", "?")
            triggered = a.get("triggered_time", "?")
            ack = a.get("acknowledged_by", "")
            ack_str = f"  (ack: {ack})" if ack else ""
            print(f"  {icon:6s} {obj_type} {obj_name}: "
                  f"\"{alarm_name}\" - {triggered}{ack_str}")
    else:
        print("  No currently active alarms.")

    history = vc_alarms.get("alarm_history", [])
    if history:
        print(f"\n  --- Alarm History ({len(history)} events) ---")
        for h in history[:50]:  # Cap console output
            ts_str = h.get("time", "?")
            etype = h.get("event_type", "?")
            msg = h.get("message", "")
            if len(msg) > 120:
                msg = msg[:117] + "..."
            print(f"  {ts_str}  {etype:35s}  {msg}")
        if len(history) > 50:
            print(f"  ... and {len(history) - 50} more events "
                  "(see Excel/PDF for full list)")


def _header(title, width=70):
    print("\n" + "-" * width)
    print(f"  {title}")
    print("-" * width)


def _is_error(data):
    if isinstance(data, dict) and data.get("status") == "error":
        print(f"  [ERROR] {data.get('error', 'unknown error')}")
        return True
    return False
