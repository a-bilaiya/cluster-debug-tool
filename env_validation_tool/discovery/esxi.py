"""VMware ESXi / vSphere discovery backend using pyVmomi."""

import re
import ssl

from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim

from .base import HypervisorDiscovery
from ..cpu_features import detect_features_from_cpuid, get_cpu_microarch
from ..specs import lookup_hdd_rpm


class ESXiDiscovery(HypervisorDiscovery):
    """Discover hardware from a single ESXi host via pyVmomi."""

    def __init__(self):
        self._si = None
        self._host = None

    @property
    def host(self):
        """The connected vim.HostSystem object."""
        return self._host

    @property
    def service_instance(self):
        """The connected ServiceInstance."""
        return self._si

    def connect(self, host, user, password, **kwargs):
        context = ssl._create_unverified_context()
        self._si = SmartConnect(
            host=host, user=user, pwd=password, sslContext=context,
        )
        content = self._si.RetrieveContent()
        container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.HostSystem], True,
        )
        if not container.view:
            raise RuntimeError(f"No ESXi hosts found on {host}")
        self._host = container.view[0]

    def disconnect(self):
        if self._si:
            Disconnect(self._si)
            self._si = None
            self._host = None

    # ── Identity ──

    def get_host_identity(self):
        hw = self._host.summary.hardware
        hw_full = self._host.hardware
        service_tag = "N/A"
        for info in hw_full.systemInfo.otherIdentifyingInfo:
            if info.identifierType.key == "ServiceTag":
                service_tag = info.identifierValue
        return {
            "name": self._host.name,
            "vendor": hw.vendor,
            "model": hw.model,
            "service_tag": service_tag,
            "bios_ver": hw_full.biosInfo.biosVersion,
        }

    def get_hypervisor_info(self):
        product = self._host.summary.config.product
        return {
            "name": product.name,
            "version": product.version,
            "build": product.build,
            "api_version": product.apiVersion,
            "full_name": product.fullName,
        }

    # ── CPU ──

    def get_cpu_info(self):
        hw = self._host.summary.hardware
        hw_full = self._host.hardware
        return {
            "model": hw.cpuModel,
            "clock_ghz": _get_cpu_clock_ghz(hw),
            "sockets": len(hw_full.cpuPkg) if hw_full.cpuPkg else 1,
            "cores": hw.numCpuCores,
            "threads": hw.numCpuThreads,
        }

    def get_cpu_features(self):
        return detect_features_from_cpuid(self._host.hardware.cpuFeature)

    # ── Memory ──

    def get_memory_info(self):
        return round(
            self._host.summary.hardware.memorySize / (1024 ** 3), 2
        )

    # ── Storage ──

    def get_storage_info(self):
        storage_system = self._host.configManager.storageSystem
        disks = []

        boot_devices = set()
        try:
            boot_info = self._host.runtime.bootDevice
            if boot_info:
                boot_devices.add(getattr(boot_info, "key", ""))
        except Exception:
            pass

        for lun in storage_system.storageDeviceInfo.scsiLun:
            # Skip non-disk LUNs (enclosures, processors, etc.)
            cap = getattr(lun, "capacity", None)
            if not cap:
                continue
            capacity_gb = round(
                (cap.block * cap.blockSize) / (1024 ** 3), 2
            )
            is_boot = lun.key in boot_devices or "BOSS" in getattr(
                lun, "model", ""
            )

            is_ssd = getattr(lun, "ssd", None)
            protocol = getattr(lun, "applicationProtocol", "").strip()
            if is_ssd:
                if protocol == "NVMe" or "NVMe" in lun.displayName:
                    disk_type = "NVMe SSD"
                elif protocol:
                    disk_type = f"{protocol} SSD"
                else:
                    disk_type = "SSD"
            else:
                disk_type = "HDD (rotational)"

            model_str = getattr(lun, "model", "N/A").strip()

            # RPM lookup — only meaningful for HDDs
            rpm = None
            rpm_series = None
            if not is_ssd:
                rpm, rpm_series = lookup_hdd_rpm(model_str)

            disk_entry = {
                "name": lun.displayName,
                "model": model_str,
                "vendor": getattr(lun, "vendor", "N/A").strip(),
                "capacity_gb": capacity_gb,
                "disk_type": disk_type,
                "is_ssd": is_ssd,
                "protocol": protocol if protocol else "N/A",
                "rpm": rpm,
                "rpm_series": rpm_series,
                "role": "os" if is_boot else "data",
                "partitions": [],
            }

            try:
                p_info = storage_system.RetrieveDiskPartitionInfo(
                    lun.devicePath
                )
                for part in p_info.spec.partition:
                    disk_entry["partitions"].append({
                        "number": part.partition,
                        "type": part.type,
                        "size_gb": round(
                            (part.endByte - part.startByte) / (1024 ** 3), 4
                        ),
                    })
            except Exception:
                disk_entry["partitions"] = "System/Locked Partition"
            disks.append(disk_entry)
        return disks

    # ── Network ──

    def get_network_info(self):
        net_data = {"vswitches": [], "pnic": []}
        for nic in self._host.config.network.pnic:
            net_data["pnic"].append({
                "device": nic.device,
                "mac": nic.mac,
                "link_speed_mb": (
                    nic.linkSpeed.speedMb if nic.linkSpeed else "Down"
                ),
            })
        for vss in self._host.config.network.vswitch:
            net_data["vswitches"].append({
                "name": vss.name,
                "pnics": vss.pnic,
                "portgroups": vss.portgroup,
                "mtu": vss.mtu,
            })
        return net_data

    # ── VM Discovery ──

    def discover_vms(self, pattern, exclude_patterns=None):
        if exclude_patterns is None:
            exclude_patterns = []
        rvc_vms = []
        for vm in self._host.vm:
            name_lower = vm.name.lower()
            is_excluded = any(
                pat.lower() in name_lower for pat in exclude_patterns
            )
            if pattern.lower() in name_lower and not is_excluded:
                guest_ip = None
                if vm.guest and vm.guest.ipAddress:
                    guest_ip = vm.guest.ipAddress
                elif vm.guest and vm.guest.net:
                    for nic in vm.guest.net:
                        for addr in (nic.ipAddress or []):
                            if "." in addr and not addr.startswith("127."):
                                guest_ip = addr
                                break
                        if guest_ip:
                            break
                rvc_vms.append({
                    "vm_name": vm.name,
                    "vm_ip": guest_ip,
                    "power_state": str(vm.runtime.powerState),
                    "num_cpu": (
                        vm.config.hardware.numCPU if vm.config else None
                    ),
                    "memory_mb": (
                        vm.config.hardware.memoryMB if vm.config else None
                    ),
                })
        return rvc_vms


# ── vCenter Discovery (standalone function, not per-host) ──

def discover_esxi_hosts_from_vcenter(vcenter_ip, user, pwd,
                                     host_model_filter=None,
                                     datacenter_filter=None,
                                     collect_alarms=False,
                                     alarm_days=7):
    """Connect to vCenter and auto-discover ESXi host IPs and cluster names.

    Args:
        vcenter_ip: vCenter server IP.
        user: vCenter user (e.g. administrator@vsphere.local).
        pwd: vCenter password.
        host_model_filter: Optional model substring to filter hosts.
        datacenter_filter: Optional datacenter name substring to filter hosts.
        collect_alarms: If True, collect datacenter-level alarms.
        alarm_days: Days of alarm history to collect (default: 7).

    Returns:
        dict with 'esxi_ips', 'cluster_name', 'datacenter',
        and optionally 'vcenter_alarms'.
    """
    context = ssl._create_unverified_context()
    si = None
    result = {"esxi_ips": [], "cluster_name": None, "datacenter": None}
    try:
        si = SmartConnect(
            host=vcenter_ip, user=user, pwd=pwd, sslContext=context,
        )
        content = si.RetrieveContent()

        if content.about.apiType != "VirtualCenter":
            print(f"  [WARN] {vcenter_ip} is not a vCenter "
                  f"(apiType={content.about.apiType})")
            return result

        for dc in content.rootFolder.childEntity:
            if isinstance(dc, vim.Datacenter):
                print(f"  Datacenter: {dc.name}")

        host_container = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.HostSystem], True,
        )

        matched_datacenters = set()
        for host in host_container.view:
            model = host.summary.hardware.model
            if host_model_filter and host_model_filter not in model:
                continue
            mgmt_ip = None
            for vnic in host.config.network.vnic:
                if vnic.device == "vmk0":
                    mgmt_ip = vnic.spec.ip.ipAddress
                    break
            if not mgmt_ip:
                mgmt_ip = host.name

            dc_name = None
            parent = host.parent
            while parent and not isinstance(parent, vim.Datacenter):
                parent = parent.parent
            if parent:
                dc_name = parent.name

            # Filter by datacenter name if specified
            if datacenter_filter and dc_name:
                if datacenter_filter.lower() not in dc_name.lower():
                    continue
            elif datacenter_filter and not dc_name:
                continue

            matched_datacenters.add(dc_name)

            cluster_name = None
            if isinstance(host.parent, vim.ClusterComputeResource):
                cluster_name = host.parent.name

            result["esxi_ips"].append(mgmt_ip)
            print(f"  Discovered: {mgmt_ip:16s}  Model: {model:25s}  "
                  f"DC: {dc_name}")

        if matched_datacenters:
            result["cluster_name"] = ", ".join(sorted(matched_datacenters))
            result["datacenter"] = result["cluster_name"]

        # Collect datacenter-level alarms (all objects)
        if collect_alarms:
            result["vcenter_alarms"] = _collect_vcenter_alarms(
                si, content, alarm_days)

        return result
    except Exception as e:
        print(f"  [ERROR] vCenter discovery failed: {e}")
        return result
    finally:
        if si:
            Disconnect(si)


def _collect_vcenter_alarms(si, content, alarm_days=7):
    """Collect all triggered alarms and alarm history from vCenter scope.

    This captures the same data visible in the vCenter UI Alarms tab —
    alarms across all hosts, VMs, datastores, and clusters.
    """
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    window_start = now - datetime.timedelta(days=alarm_days)

    # --- Currently triggered alarms (all objects) ---
    active = []
    for entity in [content.rootFolder]:
        for alarm_state in (entity.triggeredAlarmState or []):
            entry = _format_alarm_state(alarm_state)
            if entry:
                active.append(entry)

    # Walk datacenters, clusters, hosts, VMs for triggered alarms
    try:
        container = content.viewManager.CreateContainerView(
            content.rootFolder,
            [vim.HostSystem, vim.VirtualMachine, vim.Datastore,
             vim.ClusterComputeResource],
            True,
        )
        for obj in container.view:
            for alarm_state in (obj.triggeredAlarmState or []):
                entry = _format_alarm_state(alarm_state)
                if entry:
                    active.append(entry)
        container.Destroy()
    except Exception:
        pass

    # Deduplicate by (object, alarm_name, time)
    seen = set()
    deduped = []
    for a in active:
        key = (a.get("object_name"), a.get("alarm_name"),
               a.get("triggered_time"))
        if key not in seen:
            seen.add(key)
            deduped.append(a)
    active = deduped

    critical = sum(1 for a in active if a.get("status") == "red")
    warning = sum(1 for a in active if a.get("status") == "yellow")

    # --- Historical alarm events ---
    historical = []
    event_manager = content.eventManager
    if event_manager:
        filter_spec = vim.event.EventFilterSpec(
            time=vim.event.EventFilterSpec.ByTime(
                beginTime=window_start,
                endTime=now,
            ),
            eventTypeId=[
                "AlarmStatusChangedEvent",
                "AlarmActionTriggeredEvent",
                "AlarmAcknowledgedEvent",
                "AlarmClearedEvent",
                "AlarmCreatedEvent",
            ],
        )
        try:
            collector = event_manager.CreateCollectorForEvents(
                filter=filter_spec)
            collector.RewindCollector()
            while True:
                page = collector.ReadNextEvents(maxCount=500)
                if not page:
                    break
                for ev in page:
                    entry = {
                        "event_type": type(ev).__name__,
                        "time": str(getattr(ev, "createdTime", "")),
                        "message": str(
                            getattr(ev, "fullFormattedMessage", "")
                            or getattr(ev, "message", "") or ""),
                        "user": str(getattr(ev, "userName", "") or ""),
                    }
                    if hasattr(ev, "alarm") and ev.alarm:
                        try:
                            entry["alarm_name"] = str(
                                ev.alarm.info.name
                                if hasattr(ev.alarm, "info")
                                else "Unknown")
                        except Exception:
                            entry["alarm_name"] = "Unknown"
                    if hasattr(ev, "entity") and ev.entity:
                        try:
                            entry["entity_name"] = str(
                                ev.entity.name or "Unknown")
                            entry["entity_type"] = str(
                                type(ev.entity.entity).__name__)
                        except Exception:
                            pass
                    if hasattr(ev, "from"):
                        entry["from_status"] = str(
                            getattr(ev, "from", "") or "")
                    if hasattr(ev, "to"):
                        entry["to_status"] = str(
                            getattr(ev, "to", "") or "")
                    historical.append(entry)
                if len(historical) >= 2000:
                    break
            collector.DestroyCollector()
        except Exception:
            pass

    return {
        "active_alarms": active,
        "active_count": len(active),
        "critical_count": critical,
        "warning_count": warning,
        "alarm_history": historical,
        "history_count": len(historical),
        "total_count": len(active) + len(historical),
        "collection_metadata": {
            "window_days": alarm_days,
            "window_start": str(window_start),
            "window_end": str(now),
            "source": "vCenter (datacenter-wide)",
            "active_source": "triggeredAlarmState on all objects",
            "history_source": "EventManager (AlarmEvent filter)",
        },
    }


def _format_alarm_state(alarm_state):
    """Format a single vim.alarm.AlarmState into a dict."""
    try:
        alarm_name = "Unknown"
        try:
            alarm_name = str(alarm_state.alarm.info.name)
        except Exception:
            pass

        obj_name = "Unknown"
        obj_type = "unknown"
        try:
            obj_name = str(alarm_state.entity.name)
            obj_type = type(alarm_state.entity).__name__
            # Simplify type names
            type_map = {
                "vim.HostSystem": "host",
                "vim.VirtualMachine": "vm",
                "vim.Datastore": "datastore",
                "vim.ClusterComputeResource": "cluster",
            }
            obj_type = type_map.get(str(type(alarm_state.entity)),
                                    obj_type)
        except Exception:
            pass

        triggered = ""
        try:
            triggered = str(alarm_state.time)
        except Exception:
            pass

        ack_by = ""
        try:
            ack_by = str(alarm_state.acknowledgedByUser or "")
        except Exception:
            pass

        return {
            "object_name": obj_name,
            "object_type": obj_type,
            "alarm_name": alarm_name,
            "status": str(alarm_state.overallStatus),
            "triggered_time": triggered,
            "acknowledged_by": ack_by,
            "state": "active",
        }
    except Exception:
        return None


# ── Helper ──

def _get_cpu_clock_ghz(hw_summary):
    """Get CPU clock speed in GHz from ESXi hardware summary."""
    if hasattr(hw_summary, "cpuMhz") and hw_summary.cpuMhz:
        return round(hw_summary.cpuMhz / 1000.0, 2)
    match = re.search(r"@\s*([\d.]+)\s*GHz", hw_summary.cpuModel,
                      re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None
