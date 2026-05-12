"""RVC Troubleshoot data collection — runtime diagnostics via pyVmomi.

Collects the same information visible in the vSphere UI:
  1. Host state & uptime
  2. Capacity & usage (CPU / Memory / Storage)
  3. Active alarms (host + VM)
  4. Memory reservation per VM
  5. CPU allocation per VM
  6. Hardware health sensors
  7. Performance statistics (CPU / Memory usage %)
"""

import datetime
import time

from pyVmomi import vim


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def collect_troubleshoot_report(discovery, perf_interval_minutes=60,
                                event_days=7):
    """Collect all troubleshoot data from an already-connected ESXiDiscovery.

    Each section is collected independently — a failure in one does not
    block the others.

    Args:
        discovery: ESXiDiscovery instance (already connected).
        perf_interval_minutes: How far back to query perf stats (default 60).
        event_days: How many days back for events/tasks (default 7).

    Returns:
        dict with all diagnostic sections plus health_summary.
    """
    host = discovery.host
    si = discovery.service_instance

    report = {
        "collection_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    sections = [
        ("host_state",          _ts_host_state,            (host,)),
        ("capacity_usage",      _ts_capacity_usage,        (host,)),
        ("alarms",              _ts_alarms,                (si, host, event_days)),
        ("memory_allocation",   _ts_memory_allocation,     (host,)),
        ("cpu_allocation",      _ts_cpu_allocation,        (host,)),
        ("hardware_health",     _ts_hardware_health,       (host,)),
        ("performance_stats",   _ts_performance_stats,     (si, host, perf_interval_minutes)),
        ("recent_tasks",        _ts_recent_tasks,          (si, host, event_days)),
        ("io_stats",            _ts_io_stats,              (si, host, perf_interval_minutes)),
        ("system_info",         _ts_system_info,           (si, host)),
        ("vm_details",          _ts_vm_details,            (host,)),
        ("network_config",      _ts_network_config,        (host,)),
        ("storage_config",      _ts_storage_config,        (host,)),
        ("services",            _ts_services,              (host,)),
        ("events",              _ts_events,                (si, host, event_days)),
        ("pci_devices",         _ts_pci_devices,           (host,)),
        ("advanced_settings",   _ts_advanced_settings,     (host,)),
        ("firewall",            _ts_firewall,              (host,)),
        ("power_policy",        _ts_power_policy,          (host,)),
        ("security_config",     _ts_security_config,       (host,)),
        ("cpu_topology",        _ts_cpu_topology,          (host,)),
        ("coredump_swap",       _ts_coredump_swap,         (host,)),
        ("vm_autostart",        _ts_vm_autostart,          (host,)),
        ("graphics_gpu",        _ts_graphics_gpu,          (host,)),
        ("ipmi_bmc",            _ts_ipmi_bmc,              (host,)),
        ("tcpip_stacks",        _ts_tcpip_stacks,          (host,)),
        ("dvs_config",          _ts_dvs_config,            (host,)),
        ("vsan_config",         _ts_vsan_config,           (host,)),
        ("installed_vibs",      _ts_installed_vibs,        (host,)),
        ("snmp_config",         _ts_snmp_config,           (host,)),
        # --- new Phase 2 sections ---
        ("vm_contention_stats", _ts_vm_contention_stats,   (si, host, perf_interval_minutes)),
        ("datastore_io_stats",  _ts_datastore_io_stats,    (si, host, perf_interval_minutes)),
        ("overcommit_ratios",   _ts_overcommit_ratios,     (host,)),
    ]

    for key, func, args in sections:
        try:
            report[key] = func(*args)
        except Exception as e:
            report[key] = {"status": "error", "error": str(e)}

    # Health summary runs last — it reads from the collected report
    try:
        report["health_summary"] = _ts_health_summary(report)
    except Exception as e:
        report["health_summary"] = {"status": "error", "error": str(e)}

    return report


# ---------------------------------------------------------------------------
# 1. Host State
# ---------------------------------------------------------------------------

def _ts_host_state(host):
    qs = host.summary.quickStats
    uptime_sec = getattr(qs, "uptime", 0) or 0

    total_vms = 0
    powered_on = 0
    for v in (host.vm or []):
        total_vms += 1
        if str(v.runtime.powerState) == "poweredOn":
            powered_on += 1

    # Boot time
    boot_time = ""
    try:
        bt = host.runtime.bootTime
        if bt:
            boot_time = str(bt)
    except Exception:
        pass

    # Maintenance / standby
    in_maint = getattr(host.runtime, "inMaintenanceMode", False)
    standby = str(getattr(host.runtime, "standbyMode", "none") or "none")
    reboot_req = getattr(host.summary, "rebootRequired", False)

    # Quarantine
    quarantine = ""
    try:
        qi = getattr(host.summary, "quarantineInfo", None)
        if qi:
            quarantine = str(qi)
    except Exception:
        pass

    return {
        "connection_state": str(host.runtime.connectionState),
        "power_state": str(host.runtime.powerState),
        "uptime_seconds": uptime_sec,
        "uptime_human": _fmt_uptime(uptime_sec),
        "boot_time": boot_time,
        "in_maintenance_mode": in_maint,
        "standby_mode": standby,
        "reboot_required": reboot_req,
        "quarantine_info": quarantine,
        "vm_count_total": total_vms,
        "vm_count_powered_on": powered_on,
        "host_name": host.name,
    }


# ---------------------------------------------------------------------------
# 2. Capacity & Usage
# ---------------------------------------------------------------------------

def _ts_capacity_usage(host):
    qs = host.summary.quickStats
    hw = host.summary.hardware

    # CPU
    cpu_used_mhz = getattr(qs, "overallCpuUsage", 0) or 0
    cpu_total_mhz = (hw.cpuMhz or 0) * (hw.numCpuCores or 1)
    cpu_used_ghz = round(cpu_used_mhz / 1000.0, 3)
    cpu_total_ghz = round(cpu_total_mhz / 1000.0, 2)
    cpu_pct = round(cpu_used_mhz / cpu_total_mhz * 100, 1) if cpu_total_mhz else 0

    # Memory
    mem_used_mb = getattr(qs, "overallMemoryUsage", 0) or 0
    mem_total_bytes = host.hardware.memorySize or 0
    mem_total_gb = round(mem_total_bytes / (1024 ** 3), 2)
    mem_used_gb = round(mem_used_mb / 1024.0, 2)
    mem_pct = round(mem_used_mb / (mem_total_bytes / (1024 ** 2)) * 100, 1) if mem_total_bytes else 0

    # Datastores
    datastores = []
    for ds in (host.datastore or []):
        s = ds.summary
        cap_gb = round(s.capacity / (1024 ** 3), 2)
        free_gb = round(s.freeSpace / (1024 ** 3), 2)
        used_gb = round(cap_gb - free_gb, 2)
        usage_pct = round(used_gb / cap_gb * 100, 1) if cap_gb else 0
        ds_info = {
            "name": s.name,
            "type": s.type,
            "capacity_gb": cap_gb,
            "free_gb": free_gb,
            "used_gb": used_gb,
            "usage_pct": usage_pct,
            "url": getattr(s, "url", ""),
            "maintenance_mode": getattr(s, "maintenanceMode", ""),
            "accessible": getattr(s, "accessible", True),
            "multiple_host_access": getattr(s, "multipleHostAccess", None),
        }
        # SIOC (Storage I/O Control)
        try:
            iorm = getattr(ds, "iormConfiguration", None)
            if iorm:
                ds_info["sioc_enabled"] = getattr(iorm, "enabled", False)
                ds_info["sioc_congestion_threshold"] = getattr(
                    iorm, "congestionThresholdMode", "")
                ds_info["sioc_stats_enabled"] = getattr(
                    iorm, "statsCollectionEnabled", None)
        except Exception:
            pass
        datastores.append(ds_info)

    return {
        "cpu": {
            "used_mhz": cpu_used_mhz,
            "total_mhz": cpu_total_mhz,
            "used_ghz": cpu_used_ghz,
            "total_ghz": cpu_total_ghz,
            "usage_pct": cpu_pct,
        },
        "memory": {
            "used_mb": mem_used_mb,
            "total_mb": round(mem_total_bytes / (1024 ** 2)),
            "used_gb": mem_used_gb,
            "total_gb": mem_total_gb,
            "usage_pct": mem_pct,
        },
        "datastores": datastores,
    }


# ---------------------------------------------------------------------------
# 3. Active Alarms
# ---------------------------------------------------------------------------

def _ts_alarms(si, host, event_days=7):
    # --- Active (currently triggered) alarms ---
    host_alarms = _collect_active_alarms(host, "host")
    vm_alarms = []
    for v in (host.vm or []):
        vm_alarms.extend(_collect_active_alarms(v, "vm"))

    active_all = host_alarms + vm_alarms
    critical = sum(1 for a in active_all if a["status"] == "red")
    warning = sum(1 for a in active_all if a["status"] == "yellow")

    # --- Historical alarm events (active + cleared) from last N days ---
    historical = _collect_alarm_history(si, host, event_days)

    now = datetime.datetime.now(datetime.timezone.utc)
    window_start = now - datetime.timedelta(days=event_days)

    return {
        "active_alarms": active_all,
        "active_count": len(active_all),
        "critical_count": critical,
        "warning_count": warning,
        "alarm_history": historical,
        "history_count": len(historical),
        "total_count": len(active_all) + len(historical),
        "collection_metadata": {
            "window_days": event_days,
            "window_start": str(window_start),
            "window_end": str(now),
            "active_source": "triggeredAlarmState",
            "history_source": "EventManager (AlarmEvent filter)",
        },
    }


def _collect_active_alarms(entity, entity_type):
    """Collect currently triggered alarms from an entity."""
    alarms = []
    for alarm_state in (entity.triggeredAlarmState or []):
        alarm_name = "Unknown"
        try:
            alarm_name = alarm_state.alarm.info.name
        except Exception:
            pass

        triggered = ""
        try:
            triggered = str(alarm_state.time)
        except Exception:
            pass

        ack_by = ""
        try:
            ack_by = alarm_state.acknowledgedByUser or ""
        except Exception:
            pass

        alarms.append({
            "object_name": entity.name,
            "object_type": entity_type,
            "alarm_name": alarm_name,
            "status": str(alarm_state.overallStatus),
            "triggered_time": triggered,
            "acknowledged_by": ack_by,
            "state": "active",
        })
    return alarms


def _collect_alarm_history(si, host, event_days):
    """Query EventManager for alarm events (triggered, cleared, acknowledged)
    from the last N days. Returns both active and resolved alarm history."""
    content = si.RetrieveContent()
    event_manager = content.eventManager
    if not event_manager:
        return []

    now = datetime.datetime.now(datetime.timezone.utc)
    start_time = now - datetime.timedelta(days=event_days)

    # Filter for alarm events on this host
    filter_spec = vim.event.EventFilterSpec(
        entity=vim.event.EventFilterSpec.ByEntity(
            entity=host,
            recursion=vim.event.EventFilterSpec.RecursionOption.children,
        ),
        time=vim.event.EventFilterSpec.ByTime(
            beginTime=start_time,
            endTime=now,
        ),
        eventTypeId=[
            "AlarmStatusChangedEvent",
            "AlarmActionTriggeredEvent",
            "AlarmAcknowledgedEvent",
            "AlarmClearedEvent",
            "AlarmCreatedEvent",
            "AlarmReconfiguredEvent",
        ],
    )

    try:
        collector = event_manager.CreateCollectorForEvents(filter=filter_spec)
    except Exception:
        return []

    historical = []
    try:
        collector.RewindCollector()
        while True:
            page = collector.ReadNextEvents(maxCount=500)
            if not page:
                break
            for ev in page:
                entry = {
                    "event_type": type(ev).__name__,
                    "time": str(getattr(ev, "createdTime", "")),
                    "message": getattr(ev, "fullFormattedMessage", "")
                              or getattr(ev, "message", ""),
                    "user": getattr(ev, "userName", ""),
                }
                # AlarmStatusChangedEvent has from/to status
                if hasattr(ev, "alarm") and ev.alarm:
                    try:
                        entry["alarm_name"] = ev.alarm.name
                    except Exception:
                        entry["alarm_name"] = "Unknown"
                if hasattr(ev, "entity") and ev.entity:
                    try:
                        entry["entity_name"] = ev.entity.name
                        entry["entity_type"] = type(ev.entity.entity).__name__
                    except Exception:
                        pass
                if hasattr(ev, "from"):
                    entry["from_status"] = str(getattr(ev, "from", ""))
                if hasattr(ev, "to"):
                    entry["to_status"] = str(getattr(ev, "to", ""))

                historical.append(entry)
            if len(historical) >= 1000:
                break
    except Exception:
        pass
    finally:
        try:
            collector.DestroyCollector()
        except Exception:
            pass

    return historical


# ---------------------------------------------------------------------------
# 4. Memory Reservation
# ---------------------------------------------------------------------------

def _ts_memory_allocation(host):
    mem_total_mb = round(host.hardware.memorySize / (1024 ** 2), 2)
    mem_total_gb = round(mem_total_mb / 1024.0, 2)

    per_vm = []
    total_reservation_mb = 0
    total_reservation_mb_on = 0  # powered-on VMs only
    for v in (host.vm or []):
        mem_alloc = _safe_resource_alloc(v, "memoryAllocation")
        res_mb = mem_alloc.get("reservation", 0)
        limit_mb = mem_alloc.get("limit", -1)
        configured_mb = v.config.hardware.memoryMB if v.config else 0
        total_reservation_mb += res_mb
        is_on = str(v.runtime.powerState) == "poweredOn"
        if is_on:
            total_reservation_mb_on += res_mb

        # Effective limit (unlimited = -1 means configured_mb)
        effective_limit_mb = configured_mb if limit_mb == -1 else min(limit_mb, configured_mb)

        per_vm.append({
            "vm_name": v.name,
            "power_state": str(v.runtime.powerState),
            "configured_mb": configured_mb,
            "reservation_mb": res_mb,
            "limit_mb": limit_mb,
            "effective_limit_mb": effective_limit_mb,
            "shares_level": mem_alloc.get("shares_level", "N/A"),
            "shares_value": mem_alloc.get("shares_value", 0),
            "reservation_met": "YES" if res_mb <= mem_total_mb else "NO",
        })

    total_reservation_gb = round(total_reservation_mb / 1024.0, 2)
    total_reservation_gb_on = round(total_reservation_mb_on / 1024.0, 2)
    reservation_satisfied = total_reservation_mb_on <= mem_total_mb
    headroom_gb = round((mem_total_mb - total_reservation_mb_on) / 1024.0, 2)

    return {
        "host_total_mb": mem_total_mb,
        "host_total_gb": mem_total_gb,
        "total_reservation_gb": total_reservation_gb,
        "total_reservation_gb_powered_on": total_reservation_gb_on,
        "reservation_headroom_gb": headroom_gb,
        "reservation_verdict": "OK" if reservation_satisfied else "OVERCOMMITTED",
        "available_reservation_gb": round(mem_total_gb - total_reservation_gb, 2),
        "per_vm": per_vm,
    }


# ---------------------------------------------------------------------------
# 5. CPU Allocation
# ---------------------------------------------------------------------------

def _ts_cpu_allocation(host):
    hw = host.summary.hardware
    mhz_per_core = hw.cpuMhz or 0
    host_total_mhz = mhz_per_core * hw.numCpuCores
    host_cores = hw.numCpuCores
    host_threads = hw.numCpuThreads

    per_vm = []
    total_reservation_mhz = 0
    total_reservation_mhz_on = 0  # powered-on VMs only
    for v in (host.vm or []):
        cpu_alloc = _safe_resource_alloc(v, "cpuAllocation")
        num_cpu = v.config.hardware.numCPU if v.config else 0
        res_mhz = cpu_alloc.get("reservation", 0)
        limit_mhz = cpu_alloc.get("limit", -1)
        total_reservation_mhz += res_mhz
        is_on = str(v.runtime.powerState) == "poweredOn"
        if is_on:
            total_reservation_mhz_on += res_mhz

        # Per-VM MHz capacity: vcpus * mhz_per_core
        vm_max_mhz = num_cpu * mhz_per_core
        # Effective limit (unlimited = -1 means vm_max_mhz)
        effective_limit = vm_max_mhz if limit_mhz == -1 else min(limit_mhz, vm_max_mhz)

        per_vm.append({
            "vm_name": v.name,
            "power_state": str(v.runtime.powerState),
            "num_cpu": num_cpu,
            "reservation_mhz": res_mhz,
            "limit_mhz": limit_mhz,
            "effective_limit_mhz": effective_limit,
            "vm_max_mhz": vm_max_mhz,
            "shares_level": cpu_alloc.get("shares_level", "N/A"),
            "shares_value": cpu_alloc.get("shares_value", 0),
            "reservation_met": "YES" if res_mhz <= host_total_mhz else "NO",
        })

    # Reservation verdict — can the host satisfy all powered-on reservations?
    reservation_satisfied = total_reservation_mhz_on <= host_total_mhz
    reservation_headroom_mhz = host_total_mhz - total_reservation_mhz_on

    return {
        "host_total_mhz": host_total_mhz,
        "host_mhz_per_core": mhz_per_core,
        "host_cores": host_cores,
        "host_threads": host_threads,
        "total_reservation_mhz": total_reservation_mhz,
        "total_reservation_mhz_powered_on": total_reservation_mhz_on,
        "reservation_headroom_mhz": reservation_headroom_mhz,
        "reservation_verdict": "OK" if reservation_satisfied else "OVERCOMMITTED",
        "per_vm": per_vm,
    }


def _safe_resource_alloc(vm, attr_name):
    """Safely read vm.resourceConfig.memoryAllocation or .cpuAllocation."""
    result = {"reservation": 0, "limit": -1, "shares_level": "N/A", "shares_value": 0}
    try:
        rc = vm.resourceConfig
        if rc is None:
            return result
        alloc = getattr(rc, attr_name, None)
        if alloc is None:
            return result
        result["reservation"] = getattr(alloc, "reservation", 0) or 0
        result["limit"] = getattr(alloc, "limit", -1)
        shares = getattr(alloc, "shares", None)
        if shares:
            result["shares_level"] = str(getattr(shares, "level", "N/A"))
            result["shares_value"] = getattr(shares, "shares", 0) or 0
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# 6. Hardware Health Sensors
# ---------------------------------------------------------------------------

def _ts_hardware_health(host):
    sensors_out = []
    health_rt = getattr(host.runtime, "healthSystemRuntime", None)
    if health_rt is None:
        return {
            "sensors": [],
            "summary": {"total": 0, "normal": 0, "warning": 0, "critical": 0},
            "note": "healthSystemRuntime not available on this host",
        }

    sys_health = getattr(health_rt, "systemHealthInfo", None)
    if sys_health is None:
        return {
            "sensors": [],
            "summary": {"total": 0, "normal": 0, "warning": 0, "critical": 0},
            "note": "systemHealthInfo not available",
        }

    normal = warning = critical = 0
    for sensor in (sys_health.numericSensorInfo or []):
        status = "green"
        health_state = getattr(sensor, "healthState", None)
        if health_state:
            status = str(getattr(health_state, "key", "green")).lower()

        # Reading adjusted by unitModifier (power-of-10 exponent)
        raw_reading = getattr(sensor, "currentReading", 0) or 0
        modifier = getattr(sensor, "unitModifier", 0) or 0
        reading = round(raw_reading * (10 ** modifier), 2)

        base_units = getattr(sensor, "baseUnits", "")
        sensor_type = getattr(sensor, "sensorType", "")

        sensors_out.append({
            "id": getattr(sensor, "id", ""),
            "name": getattr(sensor, "name", "Unknown"),
            "sensor_type": str(sensor_type),
            "status": status,
            "reading": reading,
            "units": str(base_units),
        })

        if status == "green":
            normal += 1
        elif status == "yellow":
            warning += 1
        else:
            critical += 1

    return {
        "sensors": sensors_out,
        "summary": {
            "total": len(sensors_out),
            "normal": normal,
            "warning": warning,
            "critical": critical,
        },
    }


# ---------------------------------------------------------------------------
# 7. Performance Statistics (CPU & Memory usage %)
# ---------------------------------------------------------------------------

def _ts_performance_stats(si, host, interval_minutes):
    content = si.RetrieveContent()
    perf_manager = content.perfManager

    # Build counter name → ID map
    counter_map = {}
    for counter in perf_manager.perfCounter:
        full_name = "{}.{}.{}".format(
            counter.groupInfo.key,
            counter.nameInfo.key,
            counter.rollupType,
        )
        counter_map[full_name] = counter.key

    # ---- counters to collect ----
    # Format: (counter_full_name, output_label, unit_type)
    #   unit_type: "hundredths_pct" = divide by 100 → %
    #              "raw"            = use as-is (ms, KB, etc.)
    _COUNTERS = [
        # CPU utilization
        ("cpu.usage.average",       "cpu_usage_pct",            "hundredths_pct"),
        # CPU contention
        ("cpu.ready.summation",     "cpu_ready_ms",             "raw"),
        ("cpu.costop.summation",    "cpu_costop_ms",            "raw"),
        ("cpu.swapwait.summation",  "cpu_swapwait_ms",          "raw"),
        ("cpu.latency.average",     "cpu_latency_pct",          "hundredths_pct"),
        ("cpu.wait.summation",      "cpu_wait_ms",              "raw"),
        ("cpu.used.summation",      "cpu_used_ms",              "raw"),
        # Memory utilization
        ("mem.usage.average",       "memory_usage_pct",         "hundredths_pct"),
        # Memory pressure
        ("mem.vmmemctl.average",    "mem_balloon_kb",           "raw"),
        ("mem.swapused.average",    "mem_swapused_kb",          "raw"),
        ("mem.swapin.average",      "mem_swapin_kbps",          "raw"),
        ("mem.swapout.average",     "mem_swapout_kbps",         "raw"),
        ("mem.compressed.average",  "mem_compressed_kb",        "raw"),
        ("mem.active.average",      "mem_active_kb",            "raw"),
        ("mem.granted.average",     "mem_granted_kb",           "raw"),
    ]

    # Resolve counter IDs — skip any that don't exist on this host
    metric_ids = []
    id_to_info = {}  # counterId → (label, unit_type)
    for cname, label, utype in _COUNTERS:
        cid = counter_map.get(cname)
        if cid is not None:
            metric_ids.append(
                vim.PerformanceManager.MetricId(counterId=cid, instance="")
            )
            id_to_info[cid] = (label, utype)

    if not metric_ids:
        return {"status": "error", "error": "No performance counters resolved"}

    # Real-time interval = 20 seconds; max samples for requested window
    max_samples = max(1, interval_minutes * 3)

    query_spec = vim.PerformanceManager.QuerySpec(
        entity=host,
        metricId=metric_ids,
        intervalId=20,
        maxSample=max_samples,
    )

    results = perf_manager.QueryPerf(querySpec=[query_spec])

    stats = {}
    if results:
        for metric_series in results[0].value:
            cid = metric_series.id.counterId
            info = id_to_info.get(cid)
            if not info:
                continue
            label, utype = info

            values = [v for v in metric_series.value if v >= 0]
            if not values:
                continue

            if utype == "hundredths_pct":
                values = [v / 100.0 for v in values]

            stats[label] = {
                "latest": round(values[-1], 2),
                "average": round(sum(values) / len(values), 2),
                "minimum": round(min(values), 2),
                "maximum": round(max(values), 2),
                "samples": len(values),
            }

    stats["sampling_metadata"] = {
        "interval_id_seconds": 20,
        "collection_window_minutes": interval_minutes,
        "max_samples_requested": max_samples,
        "description": (
            f"{interval_minutes} min window, "
            f"20-sec real-time interval, "
            f"up to {max_samples} samples"
        ),
    }
    # Keep legacy flat keys for backward compat with existing renderers
    stats["interval_minutes"] = interval_minutes
    stats["sampling_interval_seconds"] = 20
    stats["total_samples_requested"] = max_samples
    stats["collection_window"] = stats["sampling_metadata"]["description"]
    return stats


# ---------------------------------------------------------------------------
# 8. Recent Tasks
# ---------------------------------------------------------------------------

def _ts_recent_tasks(si, host, task_days=7):
    content = si.RetrieveContent()
    task_mgr = content.taskManager
    if task_mgr is None:
        return {"tasks": [], "note": "TaskManager not available"}

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=task_days)
    host_name = host.name

    # Try time-filtered collector first, fall back to recentTask
    tasks_out = []
    used_collector = False
    max_collector = getattr(task_mgr, "maxCollector", 0)
    if max_collector and max_collector > 0:
        try:
            time_spec = vim.TaskFilterSpec.ByTime(
                timeType=vim.TaskFilterSpec.ByTime.TimeType.startedTime,
                beginTime=cutoff,
            )
            entity_spec = vim.TaskFilterSpec.ByEntity(
                entity=host,
                recursion=vim.TaskFilterSpec.RecursionOption.all,
            )
            task_filter = vim.TaskFilterSpec(
                time=time_spec,
                entity=entity_spec,
            )
            collector = task_mgr.CreateCollectorForTasks(task_filter)
            try:
                collector.ResetCollector()
                while True:
                    batch = collector.ReadNextTasks(maxCount=500)
                    if not batch:
                        break
                    for info in batch:
                        tasks_out.append(_format_task_info(info, host_name))
                    if len(tasks_out) >= 2000:
                        break
                used_collector = True
            finally:
                try:
                    collector.DestroyCollector()
                except Exception:
                    pass
        except Exception:
            pass

    if not used_collector:
        # Fall back to recentTask list (ESXi standalone mode)
        recent = getattr(task_mgr, "recentTask", None) or []
        for task_ref in recent:
            try:
                info = task_ref.info
            except Exception:
                # Skip internal tasks (vslmCatalogChangeResult, etc.)
                continue
            tasks_out.append(_format_task_info(info, host_name))

    # Supplement with EventManager VM events (captures power-on failures,
    # reconfigs, etc. that recentTask may miss due to VSLM buffer flooding)
    event_tasks = _collect_task_events_from_eventmanager(
        si, content, cutoff, now)
    if event_tasks:
        # Deduplicate: skip events that already have a matching task entry
        # (same entity + same second)
        existing_keys = set()
        for t in tasks_out:
            key = (t.get("entity_name", ""), t.get("start_time", "")[:19])
            existing_keys.add(key)
        for et in event_tasks:
            key = (et.get("entity_name", ""), et.get("start_time", "")[:19])
            if key not in existing_keys:
                tasks_out.append(et)
                existing_keys.add(key)

    # Sort: errors first, then running, then by start_time descending
    state_order = {"error": 0, "running": 1, "queued": 2, "success": 3}
    tasks_out.sort(key=lambda t: (state_order.get(t["state"], 9), t["start_time"]),
                   reverse=True)

    return {
        "tasks": tasks_out[:500],
        "total_count": len(tasks_out),
        "collection_metadata": {
            "window_days": task_days,
            "window_start": str(cutoff),
            "window_end": str(now),
            "method": "TaskFilterSpec" if used_collector else "recentTask_fallback",
            "event_manager_supplement": len(event_tasks),
        },
    }


def _collect_task_events_from_eventmanager(si, content, cutoff, now):
    """Collect VM task events from EventManager as supplementary task data.

    On standalone ESXi, the TaskManager recentTask buffer is small and gets
    flooded by internal VSLM tasks. EventManager has time-filtered collectors
    and captures power-on failures, reconfigs, and other VM operations that
    TaskManager may miss.
    """
    event_mgr = content.eventManager
    if not event_mgr:
        return []

    task_events = []
    try:
        filter_spec = vim.event.EventFilterSpec(
            time=vim.event.EventFilterSpec.ByTime(
                beginTime=cutoff,
                endTime=now,
            ),
        )
        collector = event_mgr.CreateCollectorForEvents(filter=filter_spec)
        collector.RewindCollector()

        all_events = []
        while True:
            page = collector.ReadNextEvents(maxCount=500)
            if not page:
                break
            all_events.extend(page)
            if len(all_events) >= 5000:
                break
        collector.DestroyCollector()

        # Map event types to task-like entries
        vm_event_types = {
            "VmPoweredOnEvent": ("Power On virtual machine", "success"),
            "VmPoweredOffEvent": ("Power Off virtual machine", "success"),
            "VmStartingEvent": ("Power On virtual machine", "running"),
            "VmStoppingEvent": ("Power Off virtual machine", "running"),
            "VmReconfiguredEvent": ("Reconfigure virtual machine", "success"),
            "VmCreatedEvent": ("Create virtual machine", "success"),
            "VmRemovedEvent": ("Delete virtual machine", "success"),
            "VmClonedEvent": ("Clone virtual machine", "success"),
            "VmMigratedEvent": ("Migrate virtual machine", "success"),
            "VmSuspendedEvent": ("Suspend virtual machine", "success"),
            "VmResettingEvent": ("Reset virtual machine", "running"),
            "VmBeingCreatedEvent": ("Create virtual machine", "running"),
            "VmFailedStartingEvent": ("Power On virtual machine", "error"),
            "VmFailedToPowerOffEvent": ("Power Off virtual machine", "error"),
            "VmMessageWarningEvent": ("VM Warning", "warning"),
            "VmMessageErrorEvent": ("VM Error", "error"),
        }
        # Starting/stopping are intermediate — skip them to avoid duplicates
        # with their completed counterparts
        skip_intermediate = {
            "VmStartingEvent", "VmStoppingEvent", "VmBeingCreatedEvent",
            "VmResettingEvent",
        }

        seen = set()
        for ev in all_events:
            ev_type_name = type(ev).__name__
            short_type = ev_type_name.replace("vim.event.", "")

            if short_type in skip_intermediate:
                continue
            if short_type not in vm_event_types:
                continue

            task_name, default_state = vm_event_types[short_type]
            time_str = str(getattr(ev, "createdTime", "") or "")

            vm_name = ""
            try:
                if hasattr(ev, "vm") and ev.vm:
                    vm_name = str(ev.vm.name or "")
            except Exception:
                pass

            msg = str(getattr(ev, "fullFormattedMessage", "") or "")
            user = str(getattr(ev, "userName", "") or "")

            # Extract error from message for failure events
            error = ""
            state = default_state
            if "fail" in short_type.lower() or "error" in short_type.lower():
                error = msg
                state = "error"
            # Check message for failure indicators
            if "insufficient" in msg.lower() or "cannot" in msg.lower():
                state = "error"
                error = msg

            dedup_key = (vm_name, short_type, time_str[:19])
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            task_events.append({
                "task_name": task_name,
                "description": short_type,
                "name": short_type,
                "state": state,
                "progress": None,
                "entity_name": vm_name,
                "entity_type": "VirtualMachine",
                "queued_time": "",
                "start_time": time_str,
                "complete_time": time_str,
                "user": user,
                "error": error,
                "source": "EventManager",
            })

    except Exception:
        pass

    return task_events


def _format_task_info(info, host_name):
    """Format a single TaskInfo into a serializable dict."""
    entity_name = ""
    entity_type = ""
    try:
        entity = info.entity
        if entity:
            entity_name = getattr(entity, "name", "")
            entity_type = type(entity).__name__
    except Exception:
        pass

    start_time = ""
    complete_time = ""
    try:
        if info.startTime:
            start_time = str(info.startTime)
    except Exception:
        pass
    try:
        if info.completeTime:
            complete_time = str(info.completeTime)
    except Exception:
        pass

    error_msg = ""
    if info.error:
        try:
            error_msg = str(info.error.localizedMessage or info.error.msg or "")
        except Exception:
            error_msg = str(info.error)

    # Human-readable task name from description.message or descriptionId
    task_name = ""
    try:
        desc_obj = getattr(info, "description", None)
        if desc_obj and hasattr(desc_obj, "message"):
            task_name = str(desc_obj.message or "")
    except Exception:
        pass
    if not task_name:
        task_name = str(getattr(info, "descriptionId", "") or "")

    # Extract username from reason object
    user_name = ""
    reason = getattr(info, "reason", None)
    if reason:
        try:
            user_name = str(getattr(reason, "userName", "") or "")
        except Exception:
            user_name = str(reason)

    return {
        "task_name": task_name,
        "description": str(getattr(info, "descriptionId", "") or ""),
        "name": str(getattr(info, "name", "") or ""),
        "state": str(getattr(info, "state", "")),
        "progress": getattr(info, "progress", None),
        "entity_name": str(entity_name),
        "entity_type": str(entity_type).replace("vim.", ""),
        "queued_time": "",
        "start_time": start_time,
        "complete_time": complete_time,
        "user": user_name,
        "error": str(error_msg),
    }


# ---------------------------------------------------------------------------
# 9. I/O Statistics (Disk Latency, IOPS, Throughput)
# ---------------------------------------------------------------------------

def _ts_io_stats(si, host, interval_minutes):
    content = si.RetrieveContent()
    perf_manager = content.perfManager

    # Build counter name → ID map
    counter_map = {}
    for counter in perf_manager.perfCounter:
        full_name = "{}.{}.{}".format(
            counter.groupInfo.key,
            counter.nameInfo.key,
            counter.rollupType,
        )
        counter_map[full_name] = counter.key

    # Aggregate disk I/O counters (instance="")
    io_counters = {
        "disk.totalReadLatency.average": "read_latency_ms",
        "disk.totalWriteLatency.average": "write_latency_ms",
        "disk.numberReadAveraged.average": "read_iops",
        "disk.numberWriteAveraged.average": "write_iops",
        "disk.read.average": "read_kbps",
        "disk.write.average": "write_kbps",
        "disk.commandsAborted.summation": "commands_aborted",
        "disk.busResets.summation": "bus_resets",
        "disk.maxQueueDepth.average": "max_queue_depth",
        "disk.deviceReadLatency.average": "device_read_latency_ms",
        "disk.deviceWriteLatency.average": "device_write_latency_ms",
        "disk.kernelReadLatency.average": "kernel_read_latency_ms",
        "disk.kernelWriteLatency.average": "kernel_write_latency_ms",
        "disk.queueReadLatency.average": "queue_read_latency_ms",
        "disk.queueWriteLatency.average": "queue_write_latency_ms",
    }

    # Network I/O counters (aggregate)
    net_counters = {
        "net.bytesRx.average": "net_rx_kbps",
        "net.bytesTx.average": "net_tx_kbps",
        "net.packetsRx.summation": "net_packets_rx",
        "net.packetsTx.summation": "net_packets_tx",
        "net.droppedRx.summation": "net_dropped_rx",
        "net.droppedTx.summation": "net_dropped_tx",
        "net.errorsRx.summation": "net_errors_rx",
        "net.errorsTx.summation": "net_errors_tx",
    }

    all_counters = {}
    all_counters.update(io_counters)
    all_counters.update(net_counters)

    # --- Aggregate stats (instance="") ---
    metric_ids = []
    id_to_label = {}
    for counter_name, label in all_counters.items():
        cid = counter_map.get(counter_name)
        if cid is not None:
            metric_ids.append(
                vim.PerformanceManager.MetricId(counterId=cid, instance="")
            )
            id_to_label[cid] = label

    if not metric_ids:
        return {
            "status": "error",
            "error": "No disk/network I/O counters found on this host",
        }

    max_samples = max(1, interval_minutes * 3)

    query_spec = vim.PerformanceManager.QuerySpec(
        entity=host,
        metricId=metric_ids,
        intervalId=20,
        maxSample=max_samples,
    )

    results = perf_manager.QueryPerf(querySpec=[query_spec])

    def _summarize(values):
        return {
            "latest": round(values[-1], 2),
            "average": round(sum(values) / len(values), 2),
            "minimum": round(min(values), 2),
            "maximum": round(max(values), 2),
            "samples": len(values),
        }

    stats = {}
    if results:
        for metric_series in results[0].value:
            cid = metric_series.id.counterId
            label = id_to_label.get(cid)
            if not label:
                continue
            values = [v for v in metric_series.value if v >= 0]
            if not values:
                continue
            stats[label] = _summarize(values)

    # --- Per-disk instance stats (instance="*") ---
    per_disk_counters = {
        "disk.totalReadLatency.average": "read_latency_ms",
        "disk.totalWriteLatency.average": "write_latency_ms",
        "disk.numberReadAveraged.average": "read_iops",
        "disk.numberWriteAveraged.average": "write_iops",
        "disk.read.average": "read_kbps",
        "disk.write.average": "write_kbps",
        "disk.deviceReadLatency.average": "device_read_latency_ms",
        "disk.deviceWriteLatency.average": "device_write_latency_ms",
        "disk.commandsAborted.summation": "commands_aborted",
        "disk.busResets.summation": "bus_resets",
    }
    pd_metric_ids = []
    pd_id_to_label = {}
    for counter_name, label in per_disk_counters.items():
        cid = counter_map.get(counter_name)
        if cid is not None:
            pd_metric_ids.append(
                vim.PerformanceManager.MetricId(counterId=cid, instance="*")
            )
            pd_id_to_label[cid] = label

    per_disk = {}
    if pd_metric_ids:
        pd_query = vim.PerformanceManager.QuerySpec(
            entity=host,
            metricId=pd_metric_ids,
            intervalId=20,
            maxSample=max_samples,
        )
        try:
            pd_results = perf_manager.QueryPerf(querySpec=[pd_query])
            if pd_results:
                for metric_series in pd_results[0].value:
                    inst = metric_series.id.instance
                    if not inst:
                        continue
                    cid = metric_series.id.counterId
                    label = pd_id_to_label.get(cid)
                    if not label:
                        continue
                    values = [v for v in metric_series.value if v >= 0]
                    if not values:
                        continue
                    if inst not in per_disk:
                        per_disk[inst] = {"device": inst}
                    per_disk[inst][label] = _summarize(values)
        except Exception:
            pass

    # --- Per-NIC instance stats (instance="*") ---
    per_nic_counters = {
        "net.bytesRx.average": "rx_kbps",
        "net.bytesTx.average": "tx_kbps",
        "net.packetsRx.summation": "packets_rx",
        "net.packetsTx.summation": "packets_tx",
        "net.droppedRx.summation": "dropped_rx",
        "net.droppedTx.summation": "dropped_tx",
        "net.errorsRx.summation": "errors_rx",
        "net.errorsTx.summation": "errors_tx",
    }
    pn_metric_ids = []
    pn_id_to_label = {}
    for counter_name, label in per_nic_counters.items():
        cid = counter_map.get(counter_name)
        if cid is not None:
            pn_metric_ids.append(
                vim.PerformanceManager.MetricId(counterId=cid, instance="*")
            )
            pn_id_to_label[cid] = label

    per_nic = {}
    if pn_metric_ids:
        pn_query = vim.PerformanceManager.QuerySpec(
            entity=host,
            metricId=pn_metric_ids,
            intervalId=20,
            maxSample=max_samples,
        )
        try:
            pn_results = perf_manager.QueryPerf(querySpec=[pn_query])
            if pn_results:
                for metric_series in pn_results[0].value:
                    inst = metric_series.id.instance
                    if not inst:
                        continue
                    cid = metric_series.id.counterId
                    label = pn_id_to_label.get(cid)
                    if not label:
                        continue
                    values = [v for v in metric_series.value if v >= 0]
                    if not values:
                        continue
                    if inst not in per_nic:
                        per_nic[inst] = {"interface": inst}
                    per_nic[inst][label] = _summarize(values)
        except Exception:
            pass

    # Flag potential bottlenecks
    bottlenecks = []
    read_lat = stats.get("read_latency_ms", {})
    write_lat = stats.get("write_latency_ms", {})
    if read_lat and read_lat.get("average", 0) > 20:
        bottlenecks.append(
            f"High read latency: avg {read_lat['average']}ms "
            f"(max {read_lat['maximum']}ms)"
        )
    if write_lat and write_lat.get("average", 0) > 20:
        bottlenecks.append(
            f"High write latency: avg {write_lat['average']}ms "
            f"(max {write_lat['maximum']}ms)"
        )
    cmd_abort = stats.get("commands_aborted", {})
    if cmd_abort and cmd_abort.get("maximum", 0) > 0:
        bottlenecks.append(
            f"Disk commands aborted: total {cmd_abort['maximum']} "
            f"(avg {cmd_abort['average']})"
        )
    bus_rst = stats.get("bus_resets", {})
    if bus_rst and bus_rst.get("maximum", 0) > 0:
        bottlenecks.append(
            f"Disk bus resets: total {bus_rst['maximum']} "
            f"(avg {bus_rst['average']})"
        )
    net_drop_rx = stats.get("net_dropped_rx", {})
    net_drop_tx = stats.get("net_dropped_tx", {})
    if net_drop_rx and net_drop_rx.get("maximum", 0) > 0:
        bottlenecks.append(f"Network drops RX: max {net_drop_rx['maximum']}")
    if net_drop_tx and net_drop_tx.get("maximum", 0) > 0:
        bottlenecks.append(f"Network drops TX: max {net_drop_tx['maximum']}")
    net_err_rx = stats.get("net_errors_rx", {})
    net_err_tx = stats.get("net_errors_tx", {})
    if net_err_rx and net_err_rx.get("maximum", 0) > 0:
        bottlenecks.append(f"Network errors RX: max {net_err_rx['maximum']}")
    if net_err_tx and net_err_tx.get("maximum", 0) > 0:
        bottlenecks.append(f"Network errors TX: max {net_err_tx['maximum']}")

    stats["per_disk"] = list(per_disk.values())
    stats["per_nic"] = list(per_nic.values())
    stats["sampling_metadata"] = _perf_sampling_meta(interval_minutes, max_samples)
    # Keep flat keys for backward compat
    stats["interval_minutes"] = interval_minutes
    stats["sampling_interval_seconds"] = 20
    stats["total_samples_requested"] = max_samples
    stats["collection_window"] = (
        f"{interval_minutes} min window, "
        f"20-sec sampling interval, "
        f"up to {max_samples} samples"
    )
    stats["bottlenecks"] = bottlenecks
    return stats


# ---------------------------------------------------------------------------
# 10. System Information (ESXi version, BIOS, firmware, NUMA, license)
# ---------------------------------------------------------------------------

def _ts_system_info(si, host):
    prod = host.summary.config.product
    bios = host.hardware.biosInfo
    sysinfo = host.hardware.systemInfo
    numa = host.hardware.numaInfo
    content = si.RetrieveContent()

    result = {
        "esxi_version": getattr(prod, "version", ""),
        "esxi_build": getattr(prod, "build", ""),
        "esxi_full_name": getattr(prod, "fullName", ""),
        "esxi_patch_level": getattr(prod, "patchLevel", ""),
        "esxi_api_version": getattr(prod, "apiVersion", ""),
        "os_type": getattr(prod, "osType", ""),
        "model": getattr(sysinfo, "model", ""),
        "vendor": getattr(sysinfo, "vendor", ""),
        "serial": getattr(sysinfo, "serialNumber", ""),
        "uuid": getattr(sysinfo, "uuid", ""),
        "bios_version": getattr(bios, "biosVersion", ""),
        "bios_release_date": str(getattr(bios, "releaseDate", "")),
        "bios_vendor": getattr(bios, "vendor", ""),
        "numa_nodes": getattr(numa, "numNodes", 0) if numa else 0,
    }

    # Other identifying info
    for oi in (getattr(sysinfo, "otherIdentifyingInfo", None) or []):
        key = getattr(oi.identifierType, "key", "")
        val = getattr(oi, "identifierValue", "")
        if key and val:
            result[f"id_{key}"] = val

    # License
    lm = content.licenseManager
    licenses = []
    if lm:
        for lic in (lm.licenses or []):
            licenses.append({
                "name": getattr(lic, "name", ""),
                "key": str(getattr(lic, "licenseKey", ""))[:8] + "...",
                "used": getattr(lic, "used", 0),
                "total": getattr(lic, "total", 0),
            })
    result["licenses"] = licenses

    return result


# ---------------------------------------------------------------------------
# 11. VM Details (full config, guest info, devices, snapshots)
# ---------------------------------------------------------------------------

def _ts_vm_details(host):
    vms = []
    for vm in (host.vm or []):
        info = {
            "vm_name": vm.name,
            "power_state": str(vm.runtime.powerState),
        }

        # Config
        if vm.config:
            cfg = vm.config
            hw = cfg.hardware
            info["guest_os"] = getattr(cfg, "guestFullName", "")
            info["vm_version"] = getattr(cfg, "version", "")
            info["uuid"] = getattr(cfg, "uuid", "")
            info["num_cpu"] = getattr(hw, "numCPU", 0)
            info["memory_mb"] = getattr(hw, "memoryMB", 0)
            info["annotation"] = getattr(cfg, "annotation", "") or ""
            info["cpu_hot_add_enabled"] = getattr(cfg, "cpuHotAddEnabled", False)
            info["memory_hot_add_enabled"] = getattr(cfg, "memoryHotAddEnabled", False)
            info["change_tracking_enabled"] = getattr(cfg, "changeTrackingEnabled", False)

            # Disks
            disks = []
            nics = []
            controllers = []
            for dev in (hw.device or []):
                dtype = type(dev).__name__
                label = dev.deviceInfo.label if dev.deviceInfo else ""
                if "VirtualDisk" in dtype:
                    cap_gb = 0
                    backing_file = ""
                    disk_mode = ""
                    provisioning = "unknown"
                    try:
                        cap_gb = round(dev.capacityInBytes / (1024 ** 3), 2)
                    except Exception:
                        try:
                            cap_gb = round(dev.capacityInKB / (1024 ** 2), 2)
                        except Exception:
                            pass
                    try:
                        backing = dev.backing
                        backing_file = getattr(backing, "fileName", "")
                        disk_mode = getattr(backing, "diskMode", "")
                        # Determine provisioning type from backing
                        thin = getattr(backing, "thinProvisioned", None)
                        eager = getattr(backing, "eagerlyScrub", None)
                        if thin:
                            provisioning = "thin"
                        elif eager:
                            provisioning = "eagerzeroedthick"
                        elif thin is False:
                            provisioning = "thick"  # lazyzeroed
                        # else unknown (e.g. RDM or other backing)
                    except Exception:
                        pass
                    disks.append({
                        "label": label,
                        "capacity_gb": cap_gb,
                        "backing_file": backing_file,
                        "provisioning": provisioning,
                        "disk_mode": disk_mode,
                        "controller_key": getattr(dev, "controllerKey", None),
                        "unit_number": getattr(dev, "unitNumber", None),
                        "key": getattr(dev, "key", None),
                    })
                elif "Vmxnet" in dtype or "E1000" in dtype or "Ethernet" in dtype:
                    net_name = ""
                    mac = ""
                    try:
                        net_name = dev.backing.deviceName if hasattr(dev.backing, "deviceName") else ""
                    except Exception:
                        pass
                    try:
                        mac = dev.macAddress
                    except Exception:
                        pass
                    nics.append({
                        "label": label,
                        "type": dtype.replace("vim.vm.device.", ""),
                        "network": net_name,
                        "mac": mac,
                        "connected": getattr(dev.connectable, "connected", False)
                        if dev.connectable else False,
                    })
                elif "Controller" in dtype:
                    controllers.append({
                        "label": label,
                        "type": dtype.replace("vim.vm.device.", ""),
                        "key": getattr(dev, "key", None),
                        "bus_number": getattr(dev, "busNumber", None),
                        "sharing": str(getattr(dev, "sharedBus", "noSharing")),
                        "hot_add_remove": getattr(dev, "hotAddRemove", None),
                    })
            info["disks"] = disks
            info["nics"] = nics
            info["controllers"] = controllers

        # Guest info
        guest = vm.guest
        if guest:
            info["guest_state"] = getattr(guest, "guestState", "")
            info["tools_status"] = str(getattr(guest, "toolsStatus", ""))
            info["tools_version"] = str(getattr(guest, "toolsVersionStatus2", ""))
            info["guest_hostname"] = getattr(guest, "hostName", "") or ""
            info["guest_ip"] = getattr(guest, "ipAddress", "") or ""
            guest_nics = []
            for n in (guest.net or []):
                guest_nics.append({
                    "network": getattr(n, "network", ""),
                    "ip_addresses": list(n.ipAddress) if n.ipAddress else [],
                    "connected": getattr(n, "connected", False),
                    "mac": getattr(n, "macAddress", ""),
                })
            info["guest_nics"] = guest_nics

        # Snapshots
        info["has_snapshots"] = vm.snapshot is not None
        if vm.snapshot:
            info["snapshots"] = _collect_snapshots(vm.snapshot.rootSnapshotList)
        else:
            info["snapshots"] = []

        # Resource config
        rc = vm.resourceConfig
        if rc:
            info["cpu_reservation_mhz"] = getattr(rc.cpuAllocation, "reservation", 0) if rc.cpuAllocation else 0
            info["mem_reservation_mb"] = getattr(rc.memoryAllocation, "reservation", 0) if rc.memoryAllocation else 0

        # Storage usage (committed / uncommitted)
        try:
            st = vm.storage
            if st and st.perDatastoreUsage:
                total_committed = 0
                total_uncommitted = 0
                total_unshared = 0
                for dsu in st.perDatastoreUsage:
                    total_committed += getattr(dsu, "committed", 0) or 0
                    total_uncommitted += getattr(dsu, "uncommitted", 0) or 0
                    total_unshared += getattr(dsu, "unshared", 0) or 0
                info["storage_committed_gb"] = round(total_committed / (1024**3), 2)
                info["storage_uncommitted_gb"] = round(total_uncommitted / (1024**3), 2)
                info["storage_unshared_gb"] = round(total_unshared / (1024**3), 2)
        except Exception:
            pass

        # Boot options
        try:
            if vm.config and vm.config.bootOptions:
                bo = vm.config.bootOptions
                info["boot_delay_ms"] = getattr(bo, "bootDelay", 0)
                info["boot_retry_enabled"] = getattr(bo, "bootRetryEnabled", False)
                info["boot_retry_delay_ms"] = getattr(bo, "bootRetryDelay", 0)
                info["enter_bios_setup"] = getattr(bo, "enterBIOSSetup", False)
                info["efi_secure_boot"] = getattr(bo, "efiSecureBootEnabled", False)
                # Boot order
                boot_order = []
                for dev in (getattr(bo, "bootOrder", None) or []):
                    boot_order.append(type(dev).__name__.replace("vim.vm.", ""))
                info["boot_order"] = boot_order
        except Exception:
            pass

        # Extra config (guestinfo, isolation, etc.)
        try:
            if vm.config and vm.config.extraConfig:
                extra = {}
                for opt in vm.config.extraConfig:
                    k = getattr(opt, "key", "")
                    v = getattr(opt, "value", "")
                    if k:
                        if not isinstance(v, (str, int, float, bool, type(None))):
                            v = str(v)
                        extra[k] = v
                info["extra_config"] = extra
        except Exception:
            pass

        # Latency sensitivity
        try:
            if vm.config and vm.config.latencySensitivity:
                ls = vm.config.latencySensitivity
                info["latency_sensitivity"] = str(getattr(ls, "level", "normal"))
        except Exception:
            pass

        # VM flags
        try:
            if vm.config and vm.config.flags:
                flags = vm.config.flags
                info["vm_flags"] = {
                    "disk_uuid_enabled": getattr(flags, "diskUuidEnabled", False),
                    "virtual_mmu_usage": str(getattr(flags, "virtualMmuUsage", "")),
                    "virtual_exec_usage": str(getattr(flags, "virtualExecUsage", "")),
                    "ht_sharing": str(getattr(flags, "htSharing", "")),
                    "snapshot_disabled": getattr(flags, "snapshotDisabled", False),
                    "snapshot_locked": getattr(flags, "snapshotLocked", False),
                    "cbrc_cache_enabled": getattr(flags, "enableLogging", False),
                }
        except Exception:
            pass

        vms.append(info)

    return {"vms": vms, "total_count": len(vms)}


def _collect_snapshots(snap_list):
    """Recursively collect snapshot tree."""
    result = []
    for snap in (snap_list or []):
        result.append({
            "name": snap.name,
            "description": snap.description or "",
            "create_time": str(snap.createTime),
            "state": str(snap.state),
        })
        result.extend(_collect_snapshots(snap.childSnapshotList))
    return result


# ---------------------------------------------------------------------------
# 12. Network Configuration (vSwitches, portgroups, pNICs, VMkernel, DNS)
# ---------------------------------------------------------------------------

def _ts_network_config(host):
    net = host.config.network
    if net is None:
        return {"status": "error", "error": "Network config not available"}

    # Physical NICs
    pnics = []
    for pnic in (net.pnic or []):
        speed_mb = 0
        try:
            speed_mb = pnic.linkSpeed.speedMb if pnic.linkSpeed else 0
        except Exception:
            pass
        pnic_info = {
            "device": pnic.device,
            "mac": getattr(pnic, "mac", ""),
            "driver": getattr(pnic, "driver", ""),
            "link_speed_mb": speed_mb,
            "link_up": speed_mb > 0,
        }
        # Offload / ring buffer settings
        try:
            spec = getattr(pnic, "spec", None)
            offload_dict = {}
            if spec:
                offload_dict["wake_on_lan"] = getattr(spec, "enableEnhancedNetworking", None)
            offload = getattr(pnic, "offloadCapabilities", None) if hasattr(pnic, "offloadCapabilities") else None
            if offload is None:
                offload = getattr(pnic.spec, "offloadPolicy", None) if spec else None
            if offload:
                offload_dict["tso_enabled"] = getattr(offload, "tcpSegmentation", None)
                offload_dict["cso_enabled"] = getattr(offload, "csumOffload", None)
            if offload_dict:
                pnic_info["offload"] = offload_dict
        except Exception:
            pass
        pnics.append(pnic_info)

    # ---------- helper to extract policy dict ----------
    def _policy_dict(policy):
        """Extract security, NIC teaming, and traffic shaping from a network policy."""
        result = {}
        if policy is None:
            return result
        sec = getattr(policy, "security", None)
        if sec:
            result["security"] = {
                "allow_promiscuous": getattr(sec, "allowPromiscuous", None),
                "mac_changes": getattr(sec, "macChanges", None),
                "forged_transmits": getattr(sec, "forgedTransmits", None),
            }
        team = getattr(policy, "nicTeaming", None)
        if team:
            team_info = {
                "policy": getattr(team, "policy", ""),
                "reverse_policy": getattr(team, "reversePolicy", None),
                "notify_switches": getattr(team, "notifySwitches", None),
                "rolling_order": getattr(team, "rollingOrder", None),
            }
            fo = getattr(team, "nicOrder", None)
            if fo:
                team_info["active_nics"] = list(getattr(fo, "activeNic", []) or [])
                team_info["standby_nics"] = list(getattr(fo, "standbyNic", []) or [])
            fc = getattr(team, "failureCriteria", None)
            if fc:
                team_info["check_beacon"] = getattr(fc, "checkBeacon", None)
            result["nic_teaming"] = team_info
        shaping = getattr(policy, "shapingPolicy", None)
        if shaping:
            result["traffic_shaping"] = {
                "enabled": getattr(shaping, "enabled", None),
                "average_bps": getattr(shaping, "averageBandwidth", None),
                "peak_bps": getattr(shaping, "peakBandwidth", None),
                "burst_size": getattr(shaping, "burstSize", None),
            }
        return result

    # vSwitches
    vswitches = []
    for vs in (net.vswitch or []):
        vs_info = {
            "name": vs.name,
            "num_ports": getattr(vs, "numPorts", 0),
            "mtu": getattr(vs, "mtu", 0),
            "pnics": [str(p).split("-")[-1] for p in (vs.pnic or [])],
        }
        # vSwitch-level policies
        spec = getattr(vs, "spec", None)
        if spec:
            pol = _policy_dict(getattr(spec, "policy", None))
            if pol:
                vs_info["policy"] = pol
        vswitches.append(vs_info)

    # Port groups
    portgroups = []
    for pg in (net.portgroup or []):
        spec = pg.spec
        pg_info = {
            "name": spec.name,
            "vlan_id": getattr(spec, "vlanId", 0),
            "vswitch": getattr(spec, "vswitchName", ""),
        }
        # Port group-level policy overrides
        pol = _policy_dict(getattr(spec, "policy", None))
        if pol:
            pg_info["policy_override"] = pol
        portgroups.append(pg_info)

    # VMkernel adapters
    vkernel = []
    for vnic in (net.vnic or []):
        ip_info = {}
        ipv6_info = {}
        if vnic.spec and vnic.spec.ip:
            ip_obj = vnic.spec.ip
            ip_info = {
                "ip": getattr(ip_obj, "ipAddress", ""),
                "subnet": getattr(ip_obj, "subnetMask", ""),
                "dhcp": getattr(ip_obj, "dhcp", False),
            }
            # IPv6
            ipv6 = getattr(ip_obj, "ipV6Config", None)
            if ipv6:
                addrs = []
                for a in (getattr(ipv6, "ipV6Address", None) or []):
                    addrs.append({
                        "address": getattr(a, "ipAddress", ""),
                        "prefix_length": getattr(a, "prefixLength", 0),
                        "origin": getattr(a, "origin", ""),
                    })
                ipv6_info = {
                    "addresses": addrs,
                    "autoconfig": getattr(ipv6, "autoConfigurationEnabled", None),
                    "dhcpv6": getattr(ipv6, "dhcpV6Enabled", None),
                }
        vk_entry = {
            "device": vnic.device,
            "portgroup": getattr(vnic, "portgroup", ""),
            "mac": getattr(vnic, "mac", ""),
            "mtu": getattr(vnic.spec, "mtu", None) if vnic.spec else None,
            "netstack": getattr(vnic.spec, "netStackInstanceKey", "") if vnic.spec else "",
            **ip_info,
        }
        if ipv6_info:
            vk_entry["ipv6"] = ipv6_info
        # Service flags (vMotion, FT, management, vSAN)
        try:
            vk_entry["vmotion_enabled"] = getattr(vnic.spec, "vMotionEnabled", None) if vnic.spec else None
        except Exception:
            pass
        vkernel.append(vk_entry)

    # DNS
    dns = {}
    if net.dnsConfig:
        dns = {
            "servers": list(net.dnsConfig.address or []),
            "search_domains": list(net.dnsConfig.searchDomain or []),
            "hostname": getattr(net.dnsConfig, "hostName", ""),
            "domain": getattr(net.dnsConfig, "domainName", ""),
        }

    # IP routes
    routes = []
    if net.ipRouteConfig:
        gw = getattr(net.ipRouteConfig, "defaultGateway", "")
        if gw:
            routes.append({"destination": "default", "gateway": gw})

    # CDP/LLDP
    cdp_lldp = []
    try:
        ns = host.configManager.networkSystem
        if ns:
            hints = ns.QueryNetworkHint()
            for h in (hints or []):
                entry = {"device": h.device}
                if h.connectedSwitchPort:
                    cdp = h.connectedSwitchPort
                    entry["switch_id"] = getattr(cdp, "devId", "")
                    entry["port_id"] = getattr(cdp, "portId", "")
                    entry["switch_address"] = getattr(cdp, "address", "")
                if h.lldpInfo:
                    entry["lldp_chassis"] = getattr(h.lldpInfo, "chassisId", "")
                    entry["lldp_port"] = getattr(h.lldpInfo, "portId", "")
                cdp_lldp.append(entry)
    except Exception:
        pass

    # NTP
    ntp = {"servers": [], "timezone": ""}
    dt = host.config.dateTimeInfo
    if dt:
        ntp["timezone"] = getattr(dt.timeZone, "key", "") if dt.timeZone else ""
        if dt.ntpConfig and dt.ntpConfig.server:
            ntp["servers"] = list(dt.ntpConfig.server)

    return {
        "pnics": pnics,
        "vswitches": vswitches,
        "portgroups": portgroups,
        "vmkernel_adapters": vkernel,
        "dns": dns,
        "routes": routes,
        "cdp_lldp": cdp_lldp,
        "ntp": ntp,
    }


# ---------------------------------------------------------------------------
# 13. Storage Configuration (HBAs, SCSI LUNs, multipath)
# ---------------------------------------------------------------------------

def _ts_storage_config(host):
    sd = host.config.storageDevice
    if sd is None:
        return {"status": "error", "error": "StorageDevice not available"}

    # HBAs
    hbas = []
    for hba in (sd.hostBusAdapter or []):
        hba_info = {
            "device": hba.device,
            "type": type(hba).__name__.replace("vim.host.", ""),
            "model": getattr(hba, "model", ""),
            "driver": getattr(hba, "driver", ""),
            "status": getattr(hba, "status", ""),
            "pci": getattr(hba, "pci", ""),
        }
        # iSCSI-specific fields
        if hasattr(hba, "iScsiName"):
            hba_info["iscsi_name"] = getattr(hba, "iScsiName", "")
            hba_info["iscsi_alias"] = getattr(hba, "iScsiAlias", "")
        hbas.append(hba_info)

    # iSCSI enabled flag
    iscsi_enabled = getattr(sd, "softwareInternetScsiEnabled", False)

    # SCSI LUNs
    luns = []
    for lun in (sd.scsiLun or []):
        cap_gb = 0
        cap = getattr(lun, "capacity", None)
        if cap:
            try:
                cap_gb = round((cap.block * cap.blockSize) / (1024 ** 3), 2)
            except Exception:
                pass
        op_state = ""
        try:
            op_state = str(lun.operationalState[0]) if lun.operationalState else ""
        except Exception:
            pass
        luns.append({
            "canonical_name": getattr(lun, "canonicalName", ""),
            "display_name": getattr(lun, "displayName", ""),
            "model": getattr(lun, "model", "").strip(),
            "vendor": getattr(lun, "vendor", "").strip(),
            "capacity_gb": cap_gb,
            "lun_type": getattr(lun, "lunType", ""),
            "operational_state": op_state,
            "revision": getattr(lun, "revision", ""),
            "uuid": getattr(lun, "uuid", ""),
            "serial_number": getattr(lun, "serialNumber", "").strip() if getattr(lun, "serialNumber", None) else "",
            "queue_depth": getattr(lun, "queueDepth", None),
            "ssd": getattr(lun, "ssd", None),
        })

    # Multipath info
    multipath = []
    if sd.multipathInfo:
        for mp_lun in (sd.multipathInfo.lun or []):
            paths = []
            for path in (mp_lun.path or []):
                paths.append({
                    "name": getattr(path, "name", ""),
                    "state": str(getattr(path, "state", "")),
                    "is_working": str(getattr(path, "state", "")) == "active",
                })
            multipath.append({
                "lun_id": getattr(mp_lun, "id", ""),
                "policy": getattr(mp_lun, "policy", None)
                    and getattr(mp_lun.policy, "policy", "") or "",
                "paths": paths,
                "path_count": len(paths),
            })

    # iSCSI targets (send targets + static targets from iSCSI HBAs)
    iscsi_targets = []
    for hba in (sd.hostBusAdapter or []):
        if not hasattr(hba, "iScsiName"):
            continue
        # Send targets (dynamically discovered)
        for tgt in (getattr(hba, "configuredSendTarget", None) or []):
            iscsi_targets.append({
                "hba_device": hba.device,
                "type": "send_target",
                "address": getattr(tgt, "address", ""),
                "port": getattr(tgt, "port", 3260),
            })
        # Static targets (manually configured)
        for tgt in (getattr(hba, "configuredStaticTarget", None) or []):
            iscsi_targets.append({
                "hba_device": hba.device,
                "type": "static_target",
                "address": getattr(tgt, "address", ""),
                "port": getattr(tgt, "port", 3260),
                "iscsi_name": getattr(tgt, "iScsiName", ""),
            })

    # File system volumes (VMFS extents, NFS mounts)
    volumes = []
    fsv = host.config.fileSystemVolume
    if fsv:
        for mount in (fsv.mountInfo or []):
            vol = mount.volume
            vol_info = {
                "name": getattr(vol, "name", ""),
                "type": getattr(vol, "type", ""),
                "capacity_bytes": getattr(vol, "capacity", 0),
                "capacity_gb": round(getattr(vol, "capacity", 0) / (1024 ** 3), 2),
            }
            if hasattr(vol, "version"):
                vol_info["vmfs_version"] = getattr(vol, "version", "")
            if hasattr(vol, "ssd"):
                vol_info["ssd"] = getattr(vol, "ssd", "")
            if hasattr(vol, "local"):
                vol_info["local"] = getattr(vol, "local", "")

            # VMFS extent info (underlying disk partitions)
            if hasattr(vol, "extent"):
                extents = []
                for ext in (vol.extent or []):
                    extents.append({
                        "disk_name": getattr(ext, "diskName", ""),
                        "partition": getattr(ext, "partition", 0),
                    })
                vol_info["extents"] = extents

            # VMFS block size, major/minor version
            if hasattr(vol, "blockSizeMb"):
                vol_info["block_size_mb"] = getattr(vol, "blockSizeMb", 0)
            if hasattr(vol, "maxBlocks"):
                vol_info["max_blocks"] = getattr(vol, "maxBlocks", 0)
            if hasattr(vol, "majorVersion"):
                vol_info["vmfs_major_version"] = getattr(vol, "majorVersion", 0)
            if hasattr(vol, "uuid"):
                vol_info["uuid"] = getattr(vol, "uuid", "")

            # NFS mount details
            if hasattr(vol, "remoteHost"):
                vol_info["nfs_remote_host"] = getattr(vol, "remoteHost", "")
                vol_info["nfs_remote_path"] = getattr(vol, "remotePath", "")
                vol_info["nfs_username"] = getattr(vol, "userName", "")
            # remoteHostNames for NFS 4.1 multi-path
            if hasattr(vol, "remoteHostNames"):
                hosts = getattr(vol, "remoteHostNames", None)
                if hosts:
                    vol_info["nfs_remote_hosts"] = list(hosts)
            if hasattr(vol, "securityType"):
                vol_info["nfs_security_type"] = getattr(vol, "securityType", "")

            mount_info = mount.mountInfo
            if mount_info:
                vol_info["path"] = getattr(mount_info, "path", "")
                vol_info["accessible"] = getattr(mount_info, "accessible", False)
                vol_info["mounted"] = getattr(mount_info, "mounted", False)
                vol_info["access_mode"] = getattr(mount_info, "accessMode", "")
            volumes.append(vol_info)

    return {
        "hbas": hbas,
        "iscsi_enabled": iscsi_enabled,
        "iscsi_targets": iscsi_targets,
        "scsi_luns": luns,
        "multipath": multipath,
        "file_system_volumes": volumes,
    }


# ---------------------------------------------------------------------------
# 14. Services
# ---------------------------------------------------------------------------

def _ts_services(host):
    svc = host.config.service
    if svc is None:
        return {"services": []}

    services = []
    running_count = 0
    for s in (svc.service or []):
        running = getattr(s, "running", False)
        if running:
            running_count += 1
        services.append({
            "key": getattr(s, "key", ""),
            "label": getattr(s, "label", ""),
            "running": running,
            "policy": getattr(s, "policy", ""),
            "required": getattr(s, "required", False),
        })

    return {
        "services": services,
        "total_count": len(services),
        "running_count": running_count,
    }


# ---------------------------------------------------------------------------
# 15. Events (recent host + VM events)
# ---------------------------------------------------------------------------

def _ts_events(si, host, event_days=7):
    content = si.RetrieveContent()
    em = content.eventManager

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=event_days)

    evtFilter = vim.event.EventFilterSpec()
    evtFilter.entity = vim.event.EventFilterSpec.ByEntity(
        entity=host, recursion="all",
    )
    evtFilter.time = vim.event.EventFilterSpec.ByTime(
        beginTime=cutoff, endTime=now,
    )

    events_out = []
    try:
        collector = em.CreateCollectorForEvents(evtFilter)
        try:
            collector.ResetCollector()
            # Read in batches to handle large event sets
            while len(events_out) < 1000:
                batch = collector.ReadNextEvents(maxCount=200)
                if not batch:
                    break
                for e in batch:
                    msg = ""
                    try:
                        msg = e.fullFormattedMessage or ""
                    except Exception:
                        pass
                    events_out.append({
                        "time": str(getattr(e, "createdTime", "")),
                        "type": type(e).__name__.replace("vim.event.", ""),
                        "message": msg[:500],
                        "user": getattr(e, "userName", "") or "",
                    })
        finally:
            try:
                collector.DestroyCollector()
            except Exception:
                pass
    except Exception as ex:
        return {"status": "error", "error": str(ex)}

    return {
        "events": events_out,
        "total_count": len(events_out),
        "collection_metadata": {
            "window_days": event_days,
            "window_start": str(cutoff),
            "window_end": str(now),
            "max_events": 1000,
        },
    }


# ---------------------------------------------------------------------------
# 16. PCI Devices
# ---------------------------------------------------------------------------

def _ts_pci_devices(host):
    devices = []
    for pci in (host.hardware.pciDevice or []):
        devices.append({
            "id": getattr(pci, "id", ""),
            "device_name": getattr(pci, "deviceName", ""),
            "vendor_name": getattr(pci, "vendorName", ""),
            "class_id": getattr(pci, "classId", 0),
            "sub_device_id": getattr(pci, "subDeviceId", 0),
            "vendor_id": getattr(pci, "vendorId", 0),
            "device_id": getattr(pci, "deviceId", 0),
        })
    return {"devices": devices, "total_count": len(devices)}


# ---------------------------------------------------------------------------
# 17. Advanced Settings (key ESXi tunables)
# ---------------------------------------------------------------------------

def _ts_advanced_settings(host):
    opts = host.config.option or []
    settings = {}
    for o in opts:
        val = o.value
        # Ensure JSON-serializable — some settings return pyVmomi objects
        if not isinstance(val, (str, int, float, bool, type(None))):
            val = str(val)
        settings[o.key] = val

    # Categorize key settings for quick review
    key_categories = {
        "memory": [
            "Mem.ShareForceSalting", "Mem.AllocGuestLargePage",
            "Mem.MemZipEnable", "Mem.ShareScanGHz",
        ],
        "network": [
            "Net.TcpipHeapSize", "Net.TcpipHeapMax",
            "Net.VmxnetSwLROSL", "Net.Vmxnet3RxPoll",
            "Net.NetSchedHClkMigration",
        ],
        "storage": [
            "Disk.SchedNumReqOutstanding", "Disk.DiskMaxIOSize",
            "VMFS3.HardwareAcceleratedLocking",
            "NFS.MaxVolumes", "NFS.HeartbeatMaxFailures",
        ],
        "syslog": [
            "Syslog.global.logHost", "Syslog.global.defaultRotate",
            "Syslog.global.defaultSize", "Syslog.global.logDir",
        ],
        "security": [
            "UserVars.SuppressShellWarning",
            "Config.HostAgent.log.level",
            "Security.AccountLockFailures",
            "Security.AccountUnlockTime",
            "Security.PasswordQualityControl",
        ],
        "scratch": [
            "ScratchConfig.ConfiguredScratchLocation",
            "ScratchConfig.CurrentScratchLocation",
        ],
        "power": [
            "Power.CpuPolicy", "Power.UsePStates",
            "Power.UseCStates",
        ],
    }

    categorized = {}
    for cat, keys in key_categories.items():
        categorized[cat] = {}
        for k in keys:
            if k in settings:
                categorized[cat][k] = settings[k]

    return {
        "categorized": categorized,
        "total_count": len(settings),
        "all_settings": settings,
    }


# ---------------------------------------------------------------------------
# 18. Firewall Rules
# ---------------------------------------------------------------------------

def _ts_firewall(host):
    fw = host.config.firewall
    if fw is None:
        return {"rulesets": []}

    rulesets = []
    enabled_count = 0
    for rs in (fw.ruleset or []):
        enabled = getattr(rs, "enabled", False)
        if enabled:
            enabled_count += 1
        rules = []
        for r in (rs.rule or []):
            rules.append({
                "port_start": getattr(r, "port", 0),
                "port_end": getattr(r, "endPort", 0),
                "direction": str(getattr(r, "direction", "")),
                "protocol": str(getattr(r, "protocol", "")),
            })
        rulesets.append({
            "key": getattr(rs, "key", ""),
            "label": getattr(rs, "label", ""),
            "enabled": enabled,
            "rules": rules,
        })

    return {
        "rulesets": rulesets,
        "total_count": len(rulesets),
        "enabled_count": enabled_count,
    }


# ---------------------------------------------------------------------------
# 19. Power Policy
# ---------------------------------------------------------------------------

def _ts_power_policy(host):
    result = {}

    # Power system info
    psi = host.config.powerSystemInfo
    if psi and psi.currentPolicy:
        result["current_policy_key"] = getattr(psi.currentPolicy, "key", "")
        result["current_policy_name"] = getattr(psi.currentPolicy, "shortName", "")
        result["current_policy_desc"] = getattr(psi.currentPolicy, "description", "")

    # CPU power management
    cpm = host.hardware.cpuPowerManagementInfo
    if cpm:
        result["cpu_policy"] = getattr(cpm, "currentPolicy", "")
        result["hw_support"] = getattr(cpm, "hardwareSupport", "")

    # Hyper-threading
    ht = host.config.hyperThread
    if ht:
        result["hyperthreading_active"] = getattr(ht, "active", False)
        result["hyperthreading_available"] = getattr(ht, "available", False)

    return result


# ---------------------------------------------------------------------------
# 20. Security Config (lockdown, SSL, TPM, auth, crypto)
# ---------------------------------------------------------------------------

def _ts_security_config(host):
    result = {}

    # Lockdown mode
    result["lockdown_mode"] = str(getattr(host.config, "lockdownMode", "lockdownDisabled"))
    result["admin_disabled"] = getattr(host.config, "adminDisabled", False)

    # SSL thumbprint
    result["ssl_thumbprint"] = getattr(host.summary.config, "sslThumbprint", "") or ""

    # Certificate info
    try:
        cert_data = getattr(host.config, "certificate", None)
        if cert_data:
            result["certificate_present"] = True
            # cert_data is DER bytes — just record presence and length
            if isinstance(cert_data, (bytes, bytearray)):
                result["certificate_bytes"] = len(cert_data)
            elif isinstance(cert_data, list):
                result["certificate_bytes"] = len(cert_data)
            else:
                result["certificate_bytes"] = 0
        else:
            result["certificate_present"] = False
    except Exception:
        result["certificate_present"] = "unknown"

    # TPM info
    try:
        tpm = getattr(host.hardware, "tpmInfo", None)
        if tpm:
            result["tpm_present"] = True
            result["tpm_version"] = getattr(tpm, "tpmVersion", "")
        else:
            result["tpm_present"] = False
    except Exception:
        result["tpm_present"] = "unknown"

    # Crypto manager state
    try:
        cm = host.configManager.cryptoManager
        if cm:
            result["crypto_enabled"] = True
            result["crypto_key_id"] = str(getattr(cm, "cryptoKeyId", "")) or ""
        else:
            result["crypto_enabled"] = False
    except Exception:
        result["crypto_enabled"] = "unknown"

    # Authentication manager — directory services
    try:
        am = host.configManager.authenticationManager
        if am:
            auth_info = am.info
            configs = []
            for ac in (getattr(auth_info, "authConfig", None) or []):
                ac_type = type(ac).__name__.replace("vim.host.", "")
                entry = {"type": ac_type, "enabled": getattr(ac, "enabled", False)}
                # Active Directory
                if hasattr(ac, "joinedDomain"):
                    entry["joined_domain"] = getattr(ac, "joinedDomain", "")
                    entry["trusted_domains"] = list(getattr(ac, "trustedDomain", []) or [])
                configs.append(entry)
            result["auth_configs"] = configs
        else:
            result["auth_configs"] = []
    except Exception:
        result["auth_configs"] = []

    return result


# ---------------------------------------------------------------------------
# 21. CPU Topology (packages, sockets, NUMA)
# ---------------------------------------------------------------------------

def _ts_cpu_topology(host):
    hw = host.hardware

    # CPU packages (per socket)
    packages = []
    for pkg in (getattr(hw, "cpuPkg", None) or []):
        packages.append({
            "index": getattr(pkg, "index", 0),
            "vendor": getattr(pkg, "vendor", ""),
            "hz": getattr(pkg, "hz", 0),
            "bus_hz": getattr(pkg, "busHz", 0),
            "description": getattr(pkg, "description", ""),
            "thread_ids": list(getattr(pkg, "threadId", []) or []),
            "thread_count": len(getattr(pkg, "threadId", []) or []),
        })

    # NUMA topology
    numa = {}
    ni = getattr(hw, "numaInfo", None)
    if ni:
        numa["num_nodes"] = getattr(ni, "numNodes", 0)
        numa["type"] = getattr(ni, "type", "")
        nodes = []
        for node in (getattr(ni, "numaNode", None) or []):
            nodes.append({
                "type_id": getattr(node, "typeId", 0),
                "cpu_ids": list(getattr(node, "cpuID", []) or []),
                "memory_range_begin": getattr(node, "memoryRangeBegin", 0),
                "memory_range_length": getattr(node, "memoryRangeLength", 0),
                "memory_size_gb": round(
                    getattr(node, "memoryRangeLength", 0) / (1024**3), 2
                ),
            })
        numa["nodes"] = nodes

    return {
        "num_cpu_pkgs": getattr(hw, "numCpuPkgs", 0),
        "num_cpu_cores": getattr(hw, "numCpuCores", 0),
        "num_cpu_threads": getattr(hw, "numCpuThreads", 0),
        "cores_per_socket": (
            getattr(hw, "numCpuCores", 0) // max(getattr(hw, "numCpuPkgs", 1), 1)
        ),
        "threads_per_core": (
            getattr(hw, "numCpuThreads", 0) // max(getattr(hw, "numCpuCores", 1), 1)
        ),
        "cpu_model": getattr(hw.cpuInfo, "hz", 0) if hw.cpuInfo else 0,
        "packages": packages,
        "numa": numa,
    }


# ---------------------------------------------------------------------------
# 22. Coredump / Swap / Scratch Config
# ---------------------------------------------------------------------------

def _ts_coredump_swap(host):
    result = {}

    # Diagnostic (coredump) partition
    try:
        diag = getattr(host.config, "activeDiagnosticPartition", None)
        if diag:
            result["coredump"] = {
                "disk_name": getattr(diag.id, "diskName", "") if diag.id else "",
                "partition": getattr(diag.id, "partition", 0) if diag.id else 0,
                "storage_type": str(getattr(diag, "storageType", "")),
                "diagnostic_type": str(getattr(diag, "diagnosticType", "")),
            }
        else:
            result["coredump"] = None
    except Exception as e:
        result["coredump"] = {"status": "error", "error": str(e)}

    # Swap datastore
    try:
        swap_ds = getattr(host.config, "localSwapDatastore", None)
        if swap_ds:
            result["swap_datastore"] = swap_ds.name
        else:
            result["swap_datastore"] = None
    except Exception:
        result["swap_datastore"] = None

    # Scratch location from advanced settings (already collected but handy here)
    try:
        opts = host.config.option or []
        for o in opts:
            if o.key == "ScratchConfig.ConfiguredScratchLocation":
                result["scratch_configured"] = str(o.value)
            elif o.key == "ScratchConfig.CurrentScratchLocation":
                result["scratch_current"] = str(o.value)
    except Exception:
        pass

    # System swap
    try:
        sys_swap = getattr(host.config, "systemSwapConfiguration", None)
        if sys_swap:
            result["system_swap_options"] = []
            for opt in (getattr(sys_swap, "option", None) or []):
                result["system_swap_options"].append({
                    "key": str(getattr(opt, "key", "")),
                })
        else:
            result["system_swap_config"] = None
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# 23. VM AutoStart Configuration
# ---------------------------------------------------------------------------

def _ts_vm_autostart(host):
    result = {"enabled": False, "vms": []}

    try:
        auto_start = host.config.autoStart
        if auto_start is None:
            return result

        defaults = auto_start.defaults
        if defaults:
            result["enabled"] = getattr(defaults, "enabled", False)
            result["default_start_delay"] = getattr(defaults, "startDelay", 0)
            result["default_stop_delay"] = getattr(defaults, "stopDelay", 0)
            result["default_stop_action"] = str(getattr(defaults, "stopAction", ""))
            result["default_wait_for_heartbeat"] = str(
                getattr(defaults, "waitForHeartbeat", "")
            )

        for entry in (auto_start.powerInfo or []):
            vm_name = ""
            try:
                vm_name = entry.key.name if entry.key else ""
            except Exception:
                pass
            result["vms"].append({
                "vm_name": vm_name,
                "start_order": getattr(entry, "startOrder", -1),
                "start_delay": getattr(entry, "startDelay", -1),
                "start_action": str(getattr(entry, "startAction", "")),
                "stop_delay": getattr(entry, "stopDelay", -1),
                "stop_action": str(getattr(entry, "stopAction", "")),
                "wait_for_heartbeat": str(getattr(entry, "waitForHeartbeat", "")),
            })
    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# 24. Graphics / GPU Devices
# ---------------------------------------------------------------------------

def _ts_graphics_gpu(host):
    result = {"devices": [], "config": {}}

    # Graphics info
    try:
        gfx = getattr(host.config, "graphicsInfo", None) or []
        for g in gfx:
            result["devices"].append({
                "device_name": getattr(g, "deviceName", ""),
                "vendor_name": getattr(g, "vendorName", ""),
                "pci_id": getattr(g, "pciId", ""),
                "gpu_memory_mb": getattr(g, "memorySizeMB", 0),
                "graphics_type": str(getattr(g, "graphicsType", "")),
                "vm_count": len(getattr(g, "vm", []) or []),
            })
    except Exception:
        pass

    # Graphics config
    try:
        gc = getattr(host.config, "graphicsConfig", None)
        if gc:
            result["config"] = {
                "host_default_graphics_type": str(
                    getattr(gc, "hostDefaultGraphicsType", "")
                ),
                "shared_passthru_assignment_policy": str(
                    getattr(gc, "sharedPassthruAssignmentPolicy", "")
                ),
            }
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# 25. IPMI / BMC (iDRAC) Config
# ---------------------------------------------------------------------------

def _ts_ipmi_bmc(host):
    result = {}

    try:
        ipmi = getattr(host.config, "ipmi", None)
        if ipmi:
            result["bmc_ip"] = getattr(ipmi, "bmcIpAddress", "") or ""
            result["bmc_mac"] = getattr(ipmi, "bmcMac", "") or ""
            result["login"] = getattr(ipmi, "login", "") or ""
            result["present"] = True
        else:
            result["present"] = False
    except Exception:
        result["present"] = "unknown"

    return result


# ---------------------------------------------------------------------------
# 26. TCP/IP Stacks
# ---------------------------------------------------------------------------

def _ts_tcpip_stacks(host):
    net = host.config.network
    if not net:
        return {"stacks": []}

    stacks = []
    for ns in (getattr(net, "netStackInstance", None) or []):
        stack = {
            "key": getattr(ns, "key", ""),
            "name": getattr(ns, "name", "") or getattr(ns, "key", ""),
        }

        # DNS
        dns_cfg = getattr(ns, "dnsConfig", None)
        if dns_cfg:
            stack["dns_servers"] = list(getattr(dns_cfg, "address", []) or [])
            stack["dns_search"] = list(getattr(dns_cfg, "searchDomain", []) or [])
            stack["dns_hostname"] = getattr(dns_cfg, "hostName", "")
            stack["dns_domain"] = getattr(dns_cfg, "domainName", "")

        # IP route
        route_cfg = getattr(ns, "ipRouteConfig", None)
        if route_cfg:
            stack["default_gateway"] = getattr(route_cfg, "defaultGateway", "")
            stack["ipv6_default_gateway"] = getattr(
                route_cfg, "ipV6DefaultGateway", ""
            ) or ""

        # Congestion control
        stack["congestion_algorithm"] = str(
            getattr(ns, "requestedMaxNumberOfConnections", "")
        )
        stack["ip_v6_enabled"] = getattr(ns, "ipV6Enabled", None)

        stacks.append(stack)

    return {"stacks": stacks, "total_count": len(stacks)}


# ---------------------------------------------------------------------------
# 27. Distributed Virtual Switch (Proxy Switch) Config
# ---------------------------------------------------------------------------

def _ts_dvs_config(host):
    net = host.config.network
    if not net:
        return {"proxy_switches": []}

    switches = []
    for ps in (getattr(net, "proxySwitch", None) or []):
        uplinks = []
        for spec in (getattr(ps, "spec", None) and
                      getattr(ps.spec, "backing", None) and
                      getattr(ps.spec.backing, "pnicSpec", None) or []):
            uplinks.append(getattr(spec, "pnicDevice", ""))

        switches.append({
            "dvs_uuid": getattr(ps, "dvsUuid", ""),
            "dvs_name": getattr(ps, "dvsName", ""),
            "key": getattr(ps, "key", ""),
            "num_ports": getattr(ps, "numPorts", 0),
            "configured_num_ports": getattr(ps, "configNumPorts", 0),
            "num_ports_available": getattr(ps, "numPortsAvailable", 0),
            "mtu": getattr(ps, "mtu", 0),
            "uplink_pnics": uplinks,
        })

    return {"proxy_switches": switches, "total_count": len(switches)}


# ---------------------------------------------------------------------------
# 28. vSAN Config
# ---------------------------------------------------------------------------

def _ts_vsan_config(host):
    result = {"enabled": False}

    try:
        vsan = getattr(host.config, "vsanHostConfig", None)
        if vsan:
            result["enabled"] = getattr(vsan, "enabled", False)
            # Cluster info
            ci = getattr(vsan, "clusterInfo", None)
            if ci:
                result["cluster_uuid"] = getattr(ci, "uuid", "")
                result["node_uuid"] = getattr(ci, "nodeUuid", "")
            # Storage info
            si = getattr(vsan, "storageInfo", None)
            if si:
                result["auto_claim"] = getattr(si, "autoClaimStorage", False)
                disk_mappings = []
                for dm in (getattr(si, "diskMapping", None) or []):
                    ssd_name = ""
                    try:
                        ssd_name = dm.ssd.canonicalName if dm.ssd else ""
                    except Exception:
                        pass
                    hdd_names = []
                    for nd in (dm.nonSsd or []):
                        try:
                            hdd_names.append(nd.canonicalName)
                        except Exception:
                            pass
                    disk_mappings.append({
                        "ssd": ssd_name,
                        "hdds": hdd_names,
                    })
                result["disk_mappings"] = disk_mappings
            # Fault domain
            fd = getattr(vsan, "faultDomainInfo", None)
            if fd:
                result["fault_domain"] = getattr(fd, "name", "")
            # Network info
            ni = getattr(vsan, "networkInfo", None)
            if ni:
                ports = []
                for p in (getattr(ni, "port", None) or []):
                    ports.append({
                        "device": getattr(p, "device", ""),
                        "ip_config": str(getattr(p, "ipConfig", "")) or "",
                    })
                result["network_ports"] = ports
    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# 29. Installed VIBs / Packages
# ---------------------------------------------------------------------------

def _ts_installed_vibs(host):
    result = {"vibs": [], "image_profile": ""}

    try:
        icm = host.configManager.imageConfigManager
        if icm is None:
            result["note"] = "ImageConfigManager not available"
            return result

        # Image profile name
        try:
            profile = icm.HostImageConfigGetProfile()
            if profile:
                result["image_profile"] = str(profile)
        except Exception:
            pass

        # Installed VIBs — try fetchSoftwarePackages first
        try:
            pkgs = icm.fetchSoftwarePackages()
            if pkgs:
                for pkg in pkgs:
                    result["vibs"].append({
                        "name": getattr(pkg, "name", ""),
                        "version": getattr(pkg, "version", ""),
                        "vendor": getattr(pkg, "vendor", ""),
                        "creation_date": str(getattr(pkg, "creationDate", "")),
                        "acceptance_level": str(
                            getattr(pkg, "acceptanceLevel", "")
                        ),
                    })
                result["total_count"] = len(result["vibs"])
                return result
        except Exception:
            pass

        # Fallback: try installDate from imageConfigGetAcceptance
        try:
            acceptance = icm.HostImageConfigGetAcceptance()
            result["acceptance_level"] = str(acceptance)
        except Exception:
            pass

    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# 30. SNMP Config
# ---------------------------------------------------------------------------

def _ts_snmp_config(host):
    result = {}

    try:
        snmp = host.configManager.snmpSystem
        if snmp is None:
            return {"present": False}

        spec = getattr(snmp, "configuration", None)
        if spec:
            result["enabled"] = getattr(spec, "enabled", False)
            result["port"] = getattr(spec, "port", 161)
            result["read_only_communities"] = list(
                getattr(spec, "readOnlyCommunities", []) or []
            )

            # Trap targets
            targets = []
            for t in (getattr(spec, "trapTargets", None) or []):
                targets.append({
                    "hostname": getattr(t, "hostName", ""),
                    "port": getattr(t, "port", 0),
                    "community": getattr(t, "community", ""),
                })
            result["trap_targets"] = targets

            result["engine_id"] = getattr(spec, "engineId", "") or ""
            result["log_level"] = str(getattr(spec, "option", None) or [])
        else:
            result["present"] = False

    except Exception as e:
        result["error"] = str(e)

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_uptime(seconds):
    """Format seconds into 'Xd Yh Zm' string."""
    if not seconds:
        return "0m"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# 31. Per-VM Contention Statistics
# ---------------------------------------------------------------------------

def _ts_vm_contention_stats(si, host, interval_minutes):
    """Per-VM CPU ready, co-stop, and memory pressure metrics."""
    content = si.RetrieveContent()
    perf_manager = content.perfManager

    # Build counter map
    counter_map = {}
    for counter in perf_manager.perfCounter:
        full_name = "{}.{}.{}".format(
            counter.groupInfo.key,
            counter.nameInfo.key,
            counter.rollupType,
        )
        counter_map[full_name] = counter.key

    _VM_COUNTERS = [
        ("cpu.ready.summation",    "cpu_ready_ms",    "raw"),
        ("cpu.costop.summation",   "cpu_costop_ms",   "raw"),
        ("cpu.usage.average",      "cpu_usage_pct",   "hundredths_pct"),
        ("mem.vmmemctl.average",   "mem_balloon_kb",  "raw"),
        ("mem.swapped.average",    "mem_swapped_kb",  "raw"),
        ("mem.active.average",     "mem_active_kb",   "raw"),
        ("mem.granted.average",    "mem_granted_kb",  "raw"),
        ("mem.usage.average",      "mem_usage_pct",   "hundredths_pct"),
    ]

    # Resolve counter IDs
    resolved = []
    for cname, label, utype in _VM_COUNTERS:
        cid = counter_map.get(cname)
        if cid is not None:
            resolved.append((cid, label, utype))

    if not resolved:
        return {"status": "error", "error": "No VM contention counters resolved"}

    metric_ids = [
        vim.PerformanceManager.MetricId(counterId=cid, instance="")
        for cid, _, _ in resolved
    ]
    id_to_info = {cid: (label, utype) for cid, label, utype in resolved}

    max_samples = max(1, interval_minutes * 3)
    interval_ms = 20 * 1000  # 20-second interval in ms

    # Batch QuerySpec for all powered-on VMs
    powered_on_vms = [
        vm for vm in (host.vm or [])
        if vm.runtime and str(vm.runtime.powerState) == "poweredOn"
    ]

    if not powered_on_vms:
        return {
            "vms": [],
            "total_count": 0,
            "sampling_metadata": _perf_sampling_meta(interval_minutes, max_samples),
        }

    query_specs = [
        vim.PerformanceManager.QuerySpec(
            entity=vm,
            metricId=metric_ids,
            intervalId=20,
            maxSample=max_samples,
        )
        for vm in powered_on_vms
    ]

    try:
        results = perf_manager.QueryPerf(querySpec=query_specs)
    except Exception:
        results = []

    # Map results back to VMs (results returned in same order as specs)
    vms_out = []
    for i, vm in enumerate(powered_on_vms):
        vm_data = {
            "vm_name": vm.name,
            "num_vcpu": getattr(vm.config.hardware, "numCPU", 0) if vm.config else 0,
            "memory_mb": getattr(vm.config.hardware, "memoryMB", 0) if vm.config else 0,
        }

        if i < len(results) and results[i] and results[i].value:
            for metric_series in results[i].value:
                cid = metric_series.id.counterId
                info = id_to_info.get(cid)
                if not info:
                    continue
                label, utype = info
                values = [v for v in metric_series.value if v >= 0]
                if not values:
                    continue
                if utype == "hundredths_pct":
                    values = [v / 100.0 for v in values]
                vm_data[label] = {
                    "latest": round(values[-1], 2),
                    "average": round(sum(values) / len(values), 2),
                    "minimum": round(min(values), 2),
                    "maximum": round(max(values), 2),
                    "samples": len(values),
                }

        # Derive CPU ready percentage
        ready = vm_data.get("cpu_ready_ms", {})
        avg_ready = ready.get("average", 0)
        # ready.summation is ms per 20-second interval
        # ready_pct = ready_ms / interval_ms * 100
        ready_pct = round(avg_ready / interval_ms * 100, 2) if interval_ms else 0
        vm_data["cpu_ready_pct"] = ready_pct

        # Verdict
        balloon_avg = vm_data.get("mem_balloon_kb", {}).get("average", 0)
        swap_avg = vm_data.get("mem_swapped_kb", {}).get("average", 0)
        if ready_pct > 10 or swap_avg > 102400:  # >10% ready or >100MB swap
            vm_data["verdict"] = "CRITICAL"
        elif ready_pct > 5 or balloon_avg > 0 or swap_avg > 0:
            vm_data["verdict"] = "WARNING"
        else:
            vm_data["verdict"] = "OK"

        vms_out.append(vm_data)

    return {
        "vms": vms_out,
        "total_count": len(vms_out),
        "sampling_metadata": _perf_sampling_meta(interval_minutes, max_samples),
    }


# ---------------------------------------------------------------------------
# 32. Datastore I/O Statistics
# ---------------------------------------------------------------------------

def _ts_datastore_io_stats(si, host, interval_minutes):
    """Per-datastore latency, IOPS, and throughput."""
    content = si.RetrieveContent()
    perf_manager = content.perfManager

    counter_map = {}
    for counter in perf_manager.perfCounter:
        full_name = "{}.{}.{}".format(
            counter.groupInfo.key,
            counter.nameInfo.key,
            counter.rollupType,
        )
        counter_map[full_name] = counter.key

    _DS_COUNTERS = [
        ("datastore.totalReadLatency.average",      "read_latency_ms",  "raw"),
        ("datastore.totalWriteLatency.average",     "write_latency_ms", "raw"),
        ("datastore.numberReadAveraged.average",    "read_iops",        "raw"),
        ("datastore.numberWriteAveraged.average",   "write_iops",       "raw"),
        ("datastore.read.average",                  "read_kbps",        "raw"),
        ("datastore.write.average",                 "write_kbps",       "raw"),
    ]

    resolved = []
    for cname, label, utype in _DS_COUNTERS:
        cid = counter_map.get(cname)
        if cid is not None:
            resolved.append((cid, label, utype))

    if not resolved:
        return {"status": "error", "error": "No datastore perf counters resolved"}

    metric_ids = [
        vim.PerformanceManager.MetricId(counterId=cid, instance="")
        for cid, _, _ in resolved
    ]
    id_to_info = {cid: (label, utype) for cid, label, utype in resolved}
    max_samples = max(1, interval_minutes * 3)

    datastores_out = []
    for ds in (host.datastore or []):
        ds_info = {
            "name": ds.name,
            "type": getattr(ds.summary, "type", ""),
            "capacity_gb": round(
                (getattr(ds.summary, "capacity", 0) or 0) / (1024 ** 3), 2
            ),
        }

        try:
            query_spec = vim.PerformanceManager.QuerySpec(
                entity=ds,
                metricId=metric_ids,
                intervalId=20,
                maxSample=max_samples,
            )
            results = perf_manager.QueryPerf(querySpec=[query_spec])
            if results:
                for metric_series in results[0].value:
                    cid = metric_series.id.counterId
                    info = id_to_info.get(cid)
                    if not info:
                        continue
                    label, _ = info
                    values = [v for v in metric_series.value if v >= 0]
                    if not values:
                        continue
                    ds_info[label] = {
                        "latest": round(values[-1], 2),
                        "average": round(sum(values) / len(values), 2),
                        "minimum": round(min(values), 2),
                        "maximum": round(max(values), 2),
                        "samples": len(values),
                    }
        except Exception:
            ds_info["perf_error"] = "Could not query datastore perf counters"

        datastores_out.append(ds_info)

    return {
        "datastores": datastores_out,
        "total_count": len(datastores_out),
        "sampling_metadata": _perf_sampling_meta(interval_minutes, max_samples),
    }


# ---------------------------------------------------------------------------
# 33. Resource Overcommit Ratios
# ---------------------------------------------------------------------------

def _ts_overcommit_ratios(host):
    """CPU and memory overcommitment ratios."""
    hw = host.summary.hardware
    host_threads = hw.numCpuThreads
    host_cores = hw.numCpuCores
    host_cpu_mhz = hw.cpuMhz * hw.numCpuCores
    host_mem_mb = round(host.hardware.memorySize / (1024 ** 2), 2)

    total_vm_vcpus = 0
    total_vm_mem_mb = 0
    total_vm_cpu_resv_mhz = 0
    total_vm_mem_resv_mb = 0
    powered_on = 0

    for vm in (host.vm or []):
        if not vm.config or str(vm.runtime.powerState) != "poweredOn":
            continue
        powered_on += 1
        total_vm_vcpus += vm.config.hardware.numCPU
        total_vm_mem_mb += vm.config.hardware.memoryMB
        rc = vm.resourceConfig
        if rc:
            total_vm_cpu_resv_mhz += (
                getattr(rc.cpuAllocation, "reservation", 0) or 0
            )
            total_vm_mem_resv_mb += (
                getattr(rc.memoryAllocation, "reservation", 0) or 0
            )

    vcpu_ratio = round(total_vm_vcpus / host_threads, 2) if host_threads else 0
    mem_ratio = round(total_vm_mem_mb / host_mem_mb, 2) if host_mem_mb else 0

    cpu_verdict = (
        "CRITICAL" if vcpu_ratio > 4 else
        "WARNING" if vcpu_ratio > 2 else "OK"
    )
    mem_verdict = (
        "CRITICAL" if mem_ratio > 1.5 else
        "WARNING" if mem_ratio > 1.0 else "OK"
    )

    return {
        "cpu": {
            "host_physical_cores": host_cores,
            "host_logical_threads": host_threads,
            "host_total_mhz": host_cpu_mhz,
            "total_vm_vcpus": total_vm_vcpus,
            "total_vm_reserved_mhz": total_vm_cpu_resv_mhz,
            "vcpu_to_pcpu_ratio": vcpu_ratio,
            "verdict": cpu_verdict,
        },
        "memory": {
            "host_total_mb": host_mem_mb,
            "total_vm_configured_mb": total_vm_mem_mb,
            "total_vm_reserved_mb": total_vm_mem_resv_mb,
            "overcommit_ratio": mem_ratio,
            "unreserved_gap_mb": total_vm_mem_mb - total_vm_mem_resv_mb,
            "verdict": mem_verdict,
        },
        "powered_on_vm_count": powered_on,
    }


# ---------------------------------------------------------------------------
# 34. Health Summary (runs after all other sections)
# ---------------------------------------------------------------------------

def _ts_health_summary(report):
    """Synthesize all collected data into traffic-light health checks."""

    def _get(path, default=None):
        """Safely navigate nested dict: 'a.b.c' → report['a']['b']['c']."""
        obj = report
        for k in path.split("."):
            if not isinstance(obj, dict):
                return default
            obj = obj.get(k, default)
            if obj is default:
                return default
        return obj

    checks = []

    def _add(category, status, value, detail):
        checks.append({
            "category": category,
            "status": status,
            "value": str(value),
            "detail": detail,
        })

    def _threshold_pct(category, val, g_max, y_max, detail):
        """GREEN < g_max, YELLOW < y_max, else RED."""
        if val is None:
            return
        s = "GREEN" if val < g_max else ("YELLOW" if val < y_max else "RED")
        _add(category, s, f"{val}%", detail)

    # 1. CPU Usage
    cpu_avg = _get("performance_stats.cpu_usage_pct.average")
    _threshold_pct("CPU Usage", cpu_avg, 70, 85,
                   "Host average CPU utilization")

    # 2. Memory Usage
    mem_avg = _get("performance_stats.memory_usage_pct.average")
    _threshold_pct("Memory Usage", mem_avg, 75, 90,
                   "Host average memory utilization")

    # 3. CPU Ready
    ready_avg = _get("performance_stats.cpu_ready_ms.average")
    if ready_avg is not None:
        s = "GREEN" if ready_avg < 1000 else ("YELLOW" if ready_avg < 2000 else "RED")
        _add("CPU Ready Time", s, f"{ready_avg} ms",
             "Host-level CPU scheduling delay (avg per 20s interval)")

    # 4. Memory Balloon
    balloon = _get("performance_stats.mem_balloon_kb.average")
    if balloon is not None:
        s = "GREEN" if balloon == 0 else ("YELLOW" if balloon < 102400 else "RED")
        _add("Memory Balloon", s,
             f"{round(balloon / 1024, 1)} MB" if balloon else "0",
             "Balloon driver reclaiming memory from VMs")

    # 5. Swap Activity
    swap = _get("performance_stats.mem_swapused_kb.average")
    if swap is not None:
        s = "GREEN" if swap == 0 else ("YELLOW" if swap < 10240 else "RED")
        _add("Swap Activity", s,
             f"{round(swap / 1024, 1)} MB" if swap else "0",
             "Host swap space in use")

    # 6-7. Disk Latency
    for rw, label in [("read", "Read"), ("write", "Write")]:
        lat = _get(f"io_stats.{rw}_latency_ms.average")
        if lat is not None:
            _threshold_pct(f"Disk {label} Latency", lat, 10, 25,
                           f"Average {rw} latency across all disks")

    # 8. Disk Errors
    aborted = _get("io_stats.commands_aborted.maximum", 0) or 0
    resets = _get("io_stats.bus_resets.maximum", 0) or 0
    disk_errs = aborted + resets
    s = "GREEN" if disk_errs == 0 else ("YELLOW" if disk_errs < 10 else "RED")
    _add("Disk Errors", s, f"{disk_errs}",
         "Commands aborted + bus resets (should be 0)")

    # 9. Network Drops
    drops_rx = _get("io_stats.net_dropped_rx.maximum", 0) or 0
    drops_tx = _get("io_stats.net_dropped_tx.maximum", 0) or 0
    total_drops = drops_rx + drops_tx
    s = "GREEN" if total_drops == 0 else ("YELLOW" if total_drops < 100 else "RED")
    _add("Network Drops", s, f"{total_drops}",
         "Packets dropped (RX + TX)")

    # 10. Network Errors
    err_rx = _get("io_stats.net_errors_rx.maximum", 0) or 0
    err_tx = _get("io_stats.net_errors_tx.maximum", 0) or 0
    total_errs = err_rx + err_tx
    s = "GREEN" if total_errs == 0 else ("YELLOW" if total_errs < 100 else "RED")
    _add("Network Errors", s, f"{total_errs}",
         "Packet errors (RX + TX)")

    # 11. Active Alarms
    crit_alarms = _get("alarms.critical_count", 0) or 0
    warn_alarms = _get("alarms.warning_count", 0) or 0
    s = "GREEN" if crit_alarms == 0 and warn_alarms == 0 else (
        "RED" if crit_alarms > 0 else "YELLOW"
    )
    _add("Active Alarms", s,
         f"{crit_alarms} critical, {warn_alarms} warning",
         "Host and VM triggered alarms")

    # 12. Hardware Sensors
    hw_crit = _get("hardware_health.summary.critical", 0) or 0
    hw_warn = _get("hardware_health.summary.warning", 0) or 0
    s = "GREEN" if hw_crit == 0 and hw_warn == 0 else (
        "RED" if hw_crit > 0 else "YELLOW"
    )
    _add("Hardware Health", s,
         f"{hw_crit} critical, {hw_warn} warning",
         "Hardware sensor status (temperature, fans, voltage)")

    # 13. CPU Overcommit
    cpu_ratio = _get("overcommit_ratios.cpu.vcpu_to_pcpu_ratio")
    if cpu_ratio is not None:
        s = "GREEN" if cpu_ratio < 2 else ("YELLOW" if cpu_ratio < 4 else "RED")
        _add("CPU Overcommit", s, f"{cpu_ratio}:1",
             "vCPU to physical thread ratio")

    # 14. Memory Overcommit
    mem_ratio = _get("overcommit_ratios.memory.overcommit_ratio")
    if mem_ratio is not None:
        s = "GREEN" if mem_ratio < 1.0 else ("YELLOW" if mem_ratio < 1.5 else "RED")
        _add("Memory Overcommit", s, f"{mem_ratio}:1",
             "VM configured memory to host physical ratio")

    # 15. Datastore Space
    datastores = _get("capacity_usage.datastores")
    if datastores and isinstance(datastores, list):
        worst_ds_pct = max(
            (d.get("usage_pct", 0) or 0 for d in datastores), default=0
        )
        s = "GREEN" if worst_ds_pct < 75 else ("YELLOW" if worst_ds_pct < 85 else "RED")
        _add("Datastore Space", s, f"{worst_ds_pct}% (worst)",
             "Highest datastore usage across all datastores")

    # 16. VM CPU Contention
    vm_cont = _get("vm_contention_stats.vms")
    if vm_cont and isinstance(vm_cont, list):
        worst_ready = max(
            (v.get("cpu_ready_pct", 0) or 0 for v in vm_cont), default=0
        )
        s = "GREEN" if worst_ready < 5 else ("YELLOW" if worst_ready < 10 else "RED")
        worst_vm = ""
        for v in vm_cont:
            if (v.get("cpu_ready_pct", 0) or 0) == worst_ready:
                worst_vm = v.get("vm_name", "")
                break
        _add("VM CPU Contention", s,
             f"{worst_ready}% ready" + (f" ({worst_vm})" if worst_vm else ""),
             "Worst per-VM CPU ready percentage")

    # Summarize
    good = [c["category"] for c in checks if c["status"] == "GREEN"]
    warnings = [c["category"] for c in checks if c["status"] == "YELLOW"]
    critical = [c["category"] for c in checks if c["status"] == "RED"]

    if critical:
        overall = "RED"
    elif warnings:
        overall = "YELLOW"
    else:
        overall = "GREEN"

    passed = len(good)
    total = len(checks)

    return {
        "overall_status": overall,
        "checks": checks,
        "good": good,
        "warnings": warnings,
        "critical": critical,
        "total_checks": total,
        "passed_checks": passed,
        "summary_text": (
            f"{passed} of {total} checks passed."
            + (f" {len(warnings)} warning(s)." if warnings else "")
            + (f" {len(critical)} critical issue(s)." if critical else "")
        ),
    }


# ---------------------------------------------------------------------------
# Helper: standard sampling metadata block
# ---------------------------------------------------------------------------

def _perf_sampling_meta(interval_minutes, max_samples):
    return {
        "interval_id_seconds": 20,
        "collection_window_minutes": interval_minutes,
        "max_samples_requested": max_samples,
        "description": (
            f"{interval_minutes} min window, "
            f"20-sec real-time interval, "
            f"up to {max_samples} samples"
        ),
    }
