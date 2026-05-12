"""Validate discovered hardware against RVC minimum requirements.

This module is hypervisor-agnostic — it operates on the report dict
produced by any HypervisorDiscovery.collect_host_report() call.
"""

from .specs import (
    RVC_MIN_REQUIREMENTS,
    REQUIRED_CPU_FEATURES,
    RECOMMENDED_CPU_FEATURES,
)
from .cpu_features import get_cpu_microarch


def validate_cluster_size(node_count):
    """Validate cluster node count against RVC-LS requirements.

    Returns a single check dict.
    """
    reqs = RVC_MIN_REQUIREMENTS
    min_n = reqs["min_cluster_nodes"]
    max_n = reqs["max_cluster_nodes"]
    in_range = min_n <= node_count <= max_n
    return {
        "check": "Cluster Node Count",
        "required": f"{min_n}-{max_n} nodes",
        "actual": f"{node_count} nodes",
        "status": "PASS" if in_range else "FAIL",
    }


def validate_requirements(report):
    """Validate a host report dict against RVC minimum specifications.

    Args:
        report: dict from HypervisorDiscovery.collect_host_report().

    Returns:
        list of check dicts, each with keys:
            check, required, actual, status ('PASS'|'FAIL'|'WARN')
    """
    checks = []
    reqs = RVC_MIN_REQUIREMENTS

    # ── CPU Clock Speed ──
    clock = report["cpu_details"].get("clock_ghz")
    if clock is not None:
        passed = clock >= reqs["cpu_clock_ghz"]
        checks.append({
            "check": "CPU Clock Speed",
            "required": f">= {reqs['cpu_clock_ghz']} GHz",
            "actual": f"{clock} GHz",
            "status": "PASS" if passed else "FAIL",
        })
    else:
        checks.append({
            "check": "CPU Clock Speed",
            "required": f">= {reqs['cpu_clock_ghz']} GHz",
            "actual": "Unable to parse",
            "status": "WARN",
        })

    # ── Logical Cores ──
    threads = report["cpu_details"]["threads"]
    passed = threads >= reqs["logical_cores"]
    checks.append({
        "check": "Logical Cores (threads)",
        "required": f">= {reqs['logical_cores']}",
        "actual": str(threads),
        "status": "PASS" if passed else "FAIL",
    })

    # ── Memory ──
    mem = report["memory_gb"]
    passed = mem >= reqs["memory_gb"]
    checks.append({
        "check": "Memory",
        "required": f">= {reqs['memory_gb']} GB",
        "actual": f"{mem} GB",
        "status": "PASS" if passed else "FAIL",
    })

    # ── NICs ──
    total_nics = len(report["network"]["pnic"])
    active_nics = [
        n for n in report["network"]["pnic"] if n["link_speed_mb"] != "Down"
    ]
    passed = total_nics >= reqs["min_nics"]
    checks.append({
        "check": "NICs (total)",
        "required": f">= {reqs['min_nics']}",
        "actual": f"{total_nics} total ({len(active_nics)} active)",
        "status": "PASS" if passed else "FAIL",
    })

    # ── Data Disks — Count ──
    data_disks = [d for d in report["storage"] if d.get("role") == "data"]
    os_disks = [d for d in report["storage"] if d.get("role") == "os"]
    data_count = len(data_disks)
    in_range = reqs["min_data_disks"] <= data_count <= reqs["max_data_disks"]
    data_capacity = sum(d["capacity_gb"] for d in data_disks)
    checks.append({
        "check": "Data Disks",
        "required": f"{reqs['min_data_disks']}-{reqs['max_data_disks']}",
        "actual": f"{data_count} disks, {round(data_capacity, 2)} GB total",
        "status": "PASS" if in_range else "FAIL",
    })

    # ── Data Disks — Capacity Range ──
    data_capacity_tb = round(data_capacity / 1024, 2)
    min_tb = reqs["min_data_capacity_tb"]
    max_tb = reqs["max_data_capacity_tb"]
    cap_ok = min_tb <= data_capacity_tb <= max_tb
    checks.append({
        "check": "Data Disk Capacity",
        "required": f"{min_tb}-{max_tb} TB",
        "actual": f"{data_capacity_tb} TB",
        "status": "PASS" if cap_ok else "FAIL",
    })

    # ── OS Disk ──
    if os_disks:
        os_size = os_disks[0]["capacity_gb"]
        passed = os_size >= reqs["min_os_disk_gb"]
        checks.append({
            "check": "OS Disk Size",
            "required": f">= {reqs['min_os_disk_gb']} GB",
            "actual": f"{os_size} GB",
            "status": "PASS" if passed else "FAIL",
        })
    else:
        checks.append({
            "check": "OS Disk Size",
            "required": f">= {reqs['min_os_disk_gb']} GB",
            "actual": "Could not identify OS disk",
            "status": "WARN",
        })

    # ── CPU Features ──
    cpu_feat = report.get("cpu_features", {})
    if "error" not in cpu_feat:
        for feat in REQUIRED_CPU_FEATURES:
            key = feat.replace(".", "_")
            present = cpu_feat.get(key, False)
            checks.append({
                "check": f"CPU Feature: {feat}",
                "required": "Present",
                "actual": "Present" if present else "Missing",
                "status": "PASS" if present else "FAIL",
            })
        for feat in RECOMMENDED_CPU_FEATURES:
            key = feat.replace(".", "_")
            present = cpu_feat.get(key, False)
            checks.append({
                "check": f"CPU Feature: {feat} (recommended)",
                "required": "Recommended",
                "actual": "Present" if present else "Missing",
                "status": "PASS" if present else "WARN",
            })

    # ── CPU Microarchitecture ──
    model_num = cpu_feat.get("cpu_model_number")
    if model_num is not None:
        arch = get_cpu_microarch(model_num)
        passed = model_num >= reqs["min_cpu_model_stepping"]
        checks.append({
            "check": "CPU Microarchitecture (model >= Skylake)",
            "required": f"model >= {reqs['min_cpu_model_stepping']}",
            "actual": f"model {model_num} ({arch})",
            "status": "PASS" if passed else "FAIL",
        })

    return checks


def validate_rvc_vm(vm, cpu_alloc_vm=None, mem_alloc_vm=None):
    """Validate a single RVC VM against RVCLS per-node spec.

    Args:
        vm: dict from troubleshoot vm_details (has name, disks, nics, etc.)
        cpu_alloc_vm: dict from cpu_allocation.per_vm for this VM (optional)
        mem_alloc_vm: dict from memory_allocation.per_vm for this VM (optional)

    Returns:
        list of check dicts with check, required, actual, status.
    """
    reqs = RVC_MIN_REQUIREMENTS
    checks = []
    vm_name = vm.get("vm_name", vm.get("name", "?"))

    # ── vCPU Count ──
    vcpus = vm.get("num_cpu", 0)
    checks.append({
        "check": "vCPU Count",
        "required": f">= {reqs['logical_cores']}",
        "actual": str(vcpus),
        "status": "PASS" if vcpus >= reqs["logical_cores"] else "FAIL",
    })

    # ── Memory ──
    mem_mb = vm.get("memory_mb", 0)
    mem_gb = round(mem_mb / 1024, 1)
    checks.append({
        "check": "Memory",
        "required": f">= {reqs['memory_gb']} GB",
        "actual": f"{mem_gb} GB ({mem_mb} MB)",
        "status": "PASS" if mem_gb >= reqs["memory_gb"] else "FAIL",
    })

    # ── NICs ──
    nics = vm.get("nics", [])
    nic_count = len(nics)
    checks.append({
        "check": "Virtual NICs",
        "required": f">= {reqs['min_nics']}",
        "actual": str(nic_count),
        "status": "PASS" if nic_count >= reqs["min_nics"] else "FAIL",
    })

    # ── Disks ──
    disks = vm.get("disks", [])
    if disks:
        # First disk is OS, rest are data (by convention: smallest or first)
        # Sort by capacity to identify OS vs data
        sorted_disks = sorted(disks, key=lambda d: d.get("capacity_gb", 0))
        os_disk = sorted_disks[0]
        data_disks = sorted_disks[1:]

        # OS Disk Size
        os_gb = os_disk.get("capacity_gb", 0)
        checks.append({
            "check": "OS Disk Size",
            "required": f">= {reqs['min_os_disk_gb']} GB",
            "actual": f"{os_gb} GB",
            "status": "PASS" if os_gb >= reqs["min_os_disk_gb"] else "FAIL",
        })

        # OS Disk Provisioning
        os_prov = os_disk.get("provisioning", "unknown")
        prov_ok = os_prov == "eagerzeroedthick"
        checks.append({
            "check": "OS Disk Provisioning",
            "required": "eagerzeroedthick",
            "actual": os_prov,
            "status": "PASS" if prov_ok else "WARN",
        })

        # Data Disk Count
        data_count = len(data_disks)
        in_range = reqs["min_data_disks"] <= data_count <= reqs["max_data_disks"]
        checks.append({
            "check": "Data Disk Count",
            "required": f"{reqs['min_data_disks']}-{reqs['max_data_disks']}",
            "actual": str(data_count),
            "status": "PASS" if in_range else "FAIL",
        })

        # Data Disk Total Capacity
        if data_disks:
            total_data_tb = round(
                sum(d.get("capacity_gb", 0) for d in data_disks) / 1024, 2)
            min_tb = reqs["min_data_capacity_tb"]
            max_tb = reqs["max_data_capacity_tb"]
            cap_ok = min_tb <= total_data_tb <= max_tb
            checks.append({
                "check": "Data Disk Capacity",
                "required": f"{min_tb}-{max_tb} TB",
                "actual": f"{total_data_tb} TB",
                "status": "PASS" if cap_ok else "FAIL",
            })

    # ── CPU Reservation ──
    if cpu_alloc_vm:
        resv_mhz = cpu_alloc_vm.get("reservation_mhz", 0)
        resv_ghz = round(resv_mhz / 1000, 1)
        req_ghz = reqs["cpu_reservation_ghz"]
        checks.append({
            "check": "CPU Reservation",
            "required": f">= {req_ghz} GHz",
            "actual": f"{resv_ghz} GHz ({resv_mhz} MHz)",
            "status": "PASS" if resv_ghz >= req_ghz else "FAIL",
        })

        # CPU Limit
        limit_mhz = cpu_alloc_vm.get("limit_mhz", -1)
        checks.append({
            "check": "CPU Limit",
            "required": "Unlimited (-1)",
            "actual": "Unlimited" if limit_mhz == -1 else f"{limit_mhz} MHz",
            "status": "PASS" if limit_mhz == -1 else "WARN",
        })

    # ── Memory Reservation ──
    if mem_alloc_vm:
        mem_resv_mb = mem_alloc_vm.get("reservation_mb", 0)
        mem_cfg_mb = mem_alloc_vm.get("configured_mb", 0)
        resv_match = mem_resv_mb >= mem_cfg_mb if mem_cfg_mb else False
        checks.append({
            "check": "Memory Reservation",
            "required": f"= configured ({mem_cfg_mb} MB)",
            "actual": f"{mem_resv_mb} MB",
            "status": "PASS" if resv_match else "WARN",
        })

    return {"vm_name": vm_name, "checks": checks}
