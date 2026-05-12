# RVC Environment Validation Tool — Diagnostics Reference

## Overview

The RVC Environment Validation Tool audits ESXi hypervisor hosts for Rubrik
Virtual Cluster (RVC) deployment. In **troubleshoot mode** (`--mode troubleshoot`),
it collects ~35 sections of runtime diagnostics via pyVmomi, producing a
comprehensive snapshot for support engineers.

### Customer Workflow

1. Run the tool against the target cluster (vCenter or manual ESXi IPs)
2. Collect JSON, PDF, and/or Excel output
3. Sanitize sensitive data if needed (passwords are never stored)
4. Send the report to Rubrik engineering for diagnosis

### Output Formats

| Format | Flag | Description |
|--------|------|-------------|
| JSON | `-o report.json` | Machine-readable, complete data for programmatic analysis |
| PDF | `--output-pdf report.pdf` | Human-readable report with color-coded health summary |
| Excel | `--output-xlsx report.xlsx` | Multi-sheet workbook, one sheet per data category |
| Console | (always) | Terminal summary with key findings |

---

## Health Summary

The health summary provides a traffic-light assessment of host health. It runs
**after** all data collection and examines the collected sections to produce
an overall status.

### Overall Status

- **GREEN** — All checks passed, no issues detected
- **YELLOW** — One or more warnings; investigate but not critical
- **RED** — One or more critical issues; immediate attention required

### Health Checks (16 total)

| # | Check | GREEN | YELLOW | RED | Data Source |
|---|-------|-------|--------|-----|-------------|
| 1 | CPU Usage | < 70% | 70–85% | > 85% | `performance_stats.cpu_usage_pct` |
| 2 | Memory Usage | < 75% | 75–90% | > 90% | `performance_stats.memory_usage_pct` |
| 3 | CPU Ready Time | < 1000 ms avg | 1000–2000 ms | > 2000 ms | `performance_stats.cpu_ready_ms` |
| 4 | Memory Balloon | 0 KB | > 0 KB | > 100 MB | `performance_stats.mem_balloon_kb` |
| 5 | Swap Activity | 0 KB | > 0 KB | > 10 MB | `performance_stats.mem_swapused_kb` |
| 6 | Disk Read Latency | < 10 ms | 10–25 ms | > 25 ms | `io_stats` (per-disk avg) |
| 7 | Disk Write Latency | < 10 ms | 10–25 ms | > 25 ms | `io_stats` (per-disk avg) |
| 8 | Disk Errors | 0 | > 0 | > 10 | `io_stats` (aborts + resets) |
| 9 | Network Drops | 0 | > 0 | > 100 | `io_stats` (RX + TX drops) |
| 10 | Network Errors | 0 | > 0 | > 100 | `io_stats` (RX + TX errors) |
| 11 | Active Alarms | 0 critical | warnings > 0 | critical > 0 | `alarms` |
| 12 | Hardware Health | all green | warnings > 0 | critical > 0 | `hardware_health` |
| 13 | CPU Overcommit | < 2:1 | 2–4:1 | > 4:1 | `overcommit_ratios` |
| 14 | Memory Overcommit | < 1.0 | 1.0–1.5 | > 1.5 | `overcommit_ratios` |
| 15 | Datastore Space | < 75% | 75–85% | > 85% | `capacity_usage` |
| 16 | VM CPU Contention | all < 5% ready | any 5–10% | any > 10% | `vm_contention_stats` |

---

## Data Categories

### Host Identity & State

| Section | Key | What It Shows |
|---------|-----|---------------|
| `host_state` | Connection, power, uptime, maintenance mode | Is the host reachable and operational? |
| `system_info` | BIOS, model, serial, ESXi build, boot time | Hardware/firmware identification |
| `capacity_usage` | Datastore names, capacity, free space, usage % | Storage capacity and utilization |

### Resource Allocation

| Section | Key | What It Shows |
|---------|-----|---------------|
| `cpu_allocation` | Per-VM vCPU count, reservation, limit, shares | CPU resource guarantees and caps |
| `memory_allocation` | Per-VM memory config, reservation, overhead | Memory guarantees and balloon risk |
| `overcommit_ratios` | vCPU:pCPU ratio, memory config:physical ratio | Is the host overcommitted? |

### Performance Metrics (Real-Time)

Collected via `QueryPerf` with 20-second real-time intervals.

| Counter | JSON Key | Units | What It Shows |
|---------|----------|-------|---------------|
| `cpu.usage.average` | `cpu_usage_pct` | % | Overall CPU utilization |
| `cpu.ready.summation` | `cpu_ready_ms` | ms/interval | CPU scheduling delay (VM waiting for pCPU) |
| `cpu.costop.summation` | `cpu_costop_ms` | ms/interval | SMP co-stop (multi-vCPU scheduling penalty) |
| `cpu.latency.average` | `cpu_latency_pct` | % | CPU contention percentage |
| `cpu.wait.summation` | `cpu_wait_ms` | ms/interval | Idle + I/O wait time |
| `cpu.used.summation` | `cpu_used_ms` | ms/interval | Actual CPU time consumed |
| `cpu.swapwait.summation` | `cpu_swapwait_ms` | ms/interval | Time waiting for swapped memory |
| `mem.usage.average` | `memory_usage_pct` | % | Host memory utilization |
| `mem.vmmemctl.average` | `mem_balloon_kb` | KB | Balloon driver reclaimed memory |
| `mem.swapused.average` | `mem_swapused_kb` | KB | Host swap in use |
| `mem.swapin.average` | `mem_swapin_kbps` | KB/s | Swap-in rate |
| `mem.swapout.average` | `mem_swapout_kbps` | KB/s | Swap-out rate |
| `mem.compressed.average` | `mem_compressed_kb` | KB | Compressed memory |
| `mem.active.average` | `mem_active_kb` | KB | Actively used memory |
| `mem.granted.average` | `mem_granted_kb` | KB | Memory granted to VMs |

Each counter reports: `latest`, `average`, `minimum`, `maximum`, `samples`.

### Per-VM Contention Stats

Per powered-on VM, collected via batch `QueryPerf`:

| Counter | JSON Key | Units | What It Shows |
|---------|----------|-------|---------------|
| `cpu.ready.summation` | `cpu_ready_ms` | ms/interval | Per-VM CPU starvation |
| `cpu.costop.summation` | `cpu_costop_ms` | ms/interval | Per-VM SMP scheduling delays |
| `cpu.usage.average` | `cpu_usage_pct` | % | Per-VM CPU utilization |
| `mem.vmmemctl.average` | `mem_balloon_kb` | KB | Per-VM balloon pressure |
| `mem.swapped.average` | `mem_swapped_kb` | KB | Per-VM swap |
| `mem.active.average` | `mem_active_kb` | KB | Per-VM active memory |
| `mem.granted.average` | `mem_granted_kb` | KB | Per-VM granted memory |
| `mem.usage.average` | `mem_usage_pct` | % | Per-VM memory utilization |

**Derived metrics:**
- `cpu_ready_pct` — `avg_ready_ms / (20000 ms) * 100` — percentage of time VM waited for CPU
- `verdict` — CRITICAL (ready >10% or swap >100MB), WARNING (ready >5% or any balloon/swap), OK

### Datastore I/O Stats

Per-datastore metrics collected via `QueryPerf` with `entity=datastore`:

| Counter | JSON Key | Units | What It Shows |
|---------|----------|-------|---------------|
| `datastore.totalReadLatency.average` | `read_latency_ms` | ms | Average read latency |
| `datastore.totalWriteLatency.average` | `write_latency_ms` | ms | Average write latency |
| `datastore.numberReadAveraged.average` | `read_iops` | IOPS | Read operations per second |
| `datastore.numberWriteAveraged.average` | `write_iops` | IOPS | Write operations per second |
| `datastore.read.average` | `read_kbps` | KB/s | Read throughput |
| `datastore.write.average` | `write_kbps` | KB/s | Write throughput |

### I/O Stats (Per-Device)

| Section | What It Shows |
|---------|---------------|
| `io_stats.disks` | Per-disk: commands issued/completed/aborted, bus resets, latency (read/write/kernel avg) |
| `io_stats.nics` | Per-NIC: packets/bytes (RX/TX), drops, errors, broadcast, multicast |

### Network Configuration

| Section | What It Shows |
|---------|---------------|
| `network_config.vswitch` | Virtual switch config (ports, MTU, uplinks, NIC teaming policy) |
| `network_config.portgroups` | Port group VLAN, active/standby NICs, failback, promiscuous mode |
| `network_config.pnic_details` | Physical NIC driver, firmware, link speed, MAC, wake-on-LAN |
| `network_config.offloads` | TCP segmentation offload, checksum offload per NIC |
| `network_config.dns` | DNS servers, search domains, hostname |

### Storage Configuration

| Section | What It Shows |
|---------|---------------|
| `storage_config.hba` | HBA adapters (model, driver, firmware, status) |
| `storage_config.multipath` | Multipath policies per LUN (active paths, preferred) |
| `storage_config.scsi_luns` | SCSI LUN details (model, vendor, capacity, device type) |
| `storage_config.raid_config` | RAID controller configuration |

### Hardware Health

| Section | What It Shows |
|---------|---------------|
| `hardware_health.sensors` | Temperature, voltage, fan sensors with status/reading/units |
| `hardware_health.summary` | Aggregate: total sensors, green/yellow/red/unknown counts |

### Alarms

| Section | What It Shows |
|---------|---------------|
| `alarms.entries` | Triggered alarms: entity, type, severity, time, description |
| `alarms.total_count` | Total alarm count |
| `alarms.by_severity` | Breakdown by critical/warning/info |

### VM Details

| Section | What It Shows |
|---------|---------------|
| `vm_details.vms` | Per-VM: name, guest OS, power state, IP, tools status, vCPU, memory |
| VM `extra_config` | Advanced parameters (guestinfo.*, sched.*, etc.) |
| VM flags | `cpuHotAddEnabled`, `memoryHotAddEnabled`, `disableAcceleration` |

### Events & Tasks

| Section | What It Shows | Default Window |
|---------|---------------|----------------|
| `events` | Host and VM events with timestamps | Last 7 days |
| `recent_tasks` | Task history (migrations, snapshots, config changes) | Last 7 days |

Both include `collection_metadata` with `window_days`, `window_start`, `window_end`.

### System Configuration

| Section | What It Shows |
|---------|---------------|
| `services` | Running ESXi services (SSH, NTP, SNMP, etc.) |
| `firewall` | Firewall rulesets (enabled/disabled, ports) |
| `advanced_settings` | Key ESXi advanced settings (syslog, NFS, CBRC, etc.) |
| `security_config` | Lockdown mode, SSH policy, certificate info, authentication |
| `power_policy` | Power management policy (High Performance, Balanced, etc.) |
| `snmp_config` | SNMP configuration |

### Infrastructure

| Section | What It Shows |
|---------|---------------|
| `cpu_topology` | Sockets, cores, threads, NUMA nodes, packages, HT status |
| `pci_devices` | PCI devices (GPU, NIC, storage controllers) |
| `coredump_swap` | Coredump and swap partition configuration |
| `vm_autostart` | VM auto-start order and delays |
| `graphics_gpu` | GPU assignment and graphics configuration |
| `ipmi_bmc` | BMC/IPMI IP address and access info |
| `tcpip_stacks` | TCP/IP stack configuration (default, vMotion, provisioning) |
| `dvs_config` | Distributed virtual switch configuration |
| `vsan_config` | vSAN cluster configuration |
| `installed_vibs` | Installed VIBs (drivers, patches) |

---

## Sampling & Collection Metadata

### Performance Counters

All `QueryPerf`-based sections include `sampling_metadata`:

```json
{
  "interval_id_seconds": 20,
  "collection_window_minutes": 60,
  "max_samples_requested": 180,
  "description": "60 min window, 20-sec real-time interval, up to 180 samples"
}
```

- **Interval ID 20** = ESXi real-time statistics (20-second granularity)
- **Collection window** = configurable via `--perf-interval` (default: 60 minutes)
- **Max samples** = `interval_minutes * 3` (20s intervals = 3 per minute)

### Events & Tasks

Time-windowed sections include `collection_metadata`:

```json
{
  "window_days": 7,
  "window_start": "2026-04-03T03:00:00Z",
  "window_end": "2026-04-10T03:00:00Z",
  "method": "EventFilterSpec.ByTime"
}
```

- Configurable via `--event-days` (default: 7 days)
- Events capped at 1000 per host
- Tasks collected via `TaskFilterSpec` with time range

---

## Diagnostic Scenarios

### 1. VM Not Performing Well

**Symptoms:** Slow application response, high latency inside VM.

**Check these sections:**

1. **`health_summary`** — Look for RED/YELLOW on CPU Usage, CPU Ready, VM CPU Contention
2. **`vm_contention_stats`** — Find the affected VM:
   - `cpu_ready_pct > 5%` → VM is starved for CPU time
   - `cpu_ready_pct > 10%` → Critical CPU contention
   - `cpu_costop_ms` high → SMP scheduling issue (reduce vCPUs?)
3. **`performance_stats`** — Host-level context:
   - `cpu_usage_pct > 85%` → Host is overloaded
   - `cpu_latency_pct > 5%` → Scheduling contention
4. **`overcommit_ratios`** — If CPU ratio > 4:1, too many vCPUs per physical thread
5. **`cpu_allocation`** — Check if VM has CPU reservation or is limited

### 2. Slow Disk IOPS / High Latency

**Symptoms:** Slow backup, restore, or file operations.

**Check these sections:**

1. **`health_summary`** — Disk Read/Write Latency checks
2. **`datastore_io_stats`** — Per-datastore latency:
   - Read/write latency > 10ms → Investigate storage backend
   - Read/write latency > 25ms → Critical storage issue
3. **`io_stats.disks`** — Per-physical-disk:
   - `commands_aborted > 0` → Disk errors, check hardware
   - `bus_resets > 0` → Storage path issues
   - High `read_latency_avg_ms` or `write_latency_avg_ms`
4. **`storage_config`** — RAID config, multipath policies, HBA firmware
5. **`capacity_usage`** — Datastore > 85% full degrades performance

### 3. Memory Pressure / Ballooning

**Symptoms:** VM performance degradation, guest OS reporting less memory
than configured.

**Check these sections:**

1. **`health_summary`** — Memory Balloon, Swap Activity, Memory Overcommit checks
2. **`performance_stats`**:
   - `mem_balloon_kb > 0` → Balloon driver active, reclaiming VM memory
   - `mem_swapused_kb > 0` → Host swapping (severe performance impact)
   - `mem_swapin_kbps / mem_swapout_kbps > 0` → Active swap I/O
   - `mem_compressed_kb > 0` → Memory compression in use
3. **`vm_contention_stats`** — Per-VM:
   - `mem_balloon_kb` sustained > 0 → This VM is losing memory
   - `mem_swapped_kb > 100MB` → Critical, VM memory on disk
4. **`overcommit_ratios`** — Memory ratio > 1.0 means overcommit
5. **`memory_allocation`** — Check reservations; unreserved memory is at risk

### 4. Network Packet Loss / Errors

**Symptoms:** Connectivity issues, slow replication, timeout errors.

**Check these sections:**

1. **`health_summary`** — Network Drops, Network Errors checks
2. **`io_stats.nics`** — Per-NIC:
   - `rx_drops` or `tx_drops > 0` → Packets being discarded
   - `rx_errors` or `tx_errors > 0` → Link-level errors
3. **`network_config`**:
   - `pnic_details` → Link speed (1G vs 10G vs 25G), driver version
   - `offloads` → TSO/CSO disabled can cause CPU overhead
   - `vswitch` → MTU mismatch (jumbo frames), NIC teaming policy
   - `portgroups` → VLAN config, failover order
4. **`dvs_config`** — Distributed switch issues

### 5. Resource Overcommitment

**Symptoms:** Inconsistent performance, some VMs affected more than others.

**Check these sections:**

1. **`health_summary`** — CPU Overcommit, Memory Overcommit checks
2. **`overcommit_ratios`**:
   - CPU `ratio > 4:1` → Critical overcommit (reduce vCPUs or add hosts)
   - CPU `ratio > 2:1` → Warning, monitor closely
   - Memory `ratio > 1.5` → Critical (not enough physical RAM)
   - Memory `ratio > 1.0` → Overcommitted, relying on balloon/swap
3. **`cpu_allocation`** — Which VMs consume the most vCPUs?
4. **`memory_allocation`** — Which VMs have the largest configurations?
5. **`vm_contention_stats`** — Which VMs are actually suffering?

### 6. Hardware Degradation

**Symptoms:** Intermittent failures, PSOD, sensor warnings.

**Check these sections:**

1. **`health_summary`** — Hardware Health, Disk Errors checks
2. **`hardware_health`**:
   - Any sensor with `status != "Green"` → Investigate
   - Temperature sensors trending high → Cooling issue
   - Fan sensors showing failures → Hardware replacement
3. **`alarms`** — Critical alarms indicate active issues
4. **`pci_devices`** — Device errors or degraded status
5. **`system_info`** — BIOS version (outdated firmware can cause issues)
6. **`io_stats.disks`** — `commands_aborted`, `bus_resets` indicate hardware problems

### 7. Recent Change Caused Regression

**Symptoms:** Performance was fine before, now degraded after a change.

**Check these sections:**

1. **`events`** — Filter by recent timestamps:
   - VM migration events → Resource pool changed?
   - Configuration changes → Settings modified?
   - Host disconnects/reconnects → Instability?
2. **`recent_tasks`** — Recent operations (snapshots, storage vMotion, etc.)
3. **`advanced_settings`** — Non-default settings that may have been changed
4. **`installed_vibs`** — Recently installed patches or drivers

### 8. Storage Failure / Datastore Issues

**Symptoms:** VMs paused, datastore unavailable, I/O errors.

**Check these sections:**

1. **`capacity_usage`** — Datastore full? (> 85% triggers warning)
2. **`datastore_io_stats`** — Latency spikes or zero IOPS
3. **`io_stats.disks`** — Per-disk errors (aborts, resets)
4. **`storage_config`**:
   - `multipath` → Path failures, no active paths?
   - `hba` → HBA adapter offline or degraded?
   - `raid_config` → RAID degraded?
5. **`alarms`** — Storage-related alarms
6. **`events`** — SCSI sense codes, datastore connectivity events

---

## CLI Reference

### Basic Usage

```bash
# Pre-deploy hardware check (vCenter auto-discovery)
env_validation_tool -c config.yaml --mode pre-deploy

# Full validation with iperf bandwidth tests
env_validation_tool -c config.yaml --mode full --ssh-key ~/.ssh/id_rsa

# Troubleshoot with all output formats
env_validation_tool -c config.yaml --mode troubleshoot \
    -o report.json --output-pdf report.pdf --output-xlsx report.xlsx

# Custom perf window and event history
env_validation_tool -c config.yaml --mode troubleshoot \
    --perf-interval 120 --event-days 14

# Manual ESXi IPs (no vCenter)
env_validation_tool --esxi-ips 10.0.1.1,10.0.1.2 \
    --esxi-pass secret --mode troubleshoot
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--config`, `-c` | `config.yaml` | Path to YAML config file |
| `--hypervisor` | `esxi` | Hypervisor type |
| `--vcenter` | — | vCenter IP for auto-discovery |
| `--vcenter-user` | — | vCenter username |
| `--vcenter-pass` | — | vCenter password |
| `--esxi-ips` | — | Comma-separated ESXi IPs |
| `--esxi-user` | `root` | ESXi username |
| `--esxi-pass` | — | ESXi password (required) |
| `--host-model-filter` | — | Filter hosts by server model substring |
| `--mode` | `full` | `pre-deploy`, `post-deploy`, `full`, or `troubleshoot` |
| `--vm-pattern` | `vc-vr7400` | Substring to identify RVC VMs |
| `--vm-exclude` | `vcenter,vCenter` | Patterns to exclude from VM match |
| `--perf-interval` | `60` | Performance stats lookback in minutes |
| `--event-days` | `7` | Events/tasks lookback in days |
| `--ssh-key` | — | SSH key for edge VM access (iperf tests) |
| `--ssh-user` | `ubuntu` | SSH username for edge VMs |
| `--iperf-duration` | `10` | iperf3 test duration in seconds |
| `--iperf-streams` | `4` | iperf3 parallel streams |
| `--output`, `-o` | stdout | JSON report output path |
| `--output-pdf` | — | PDF report output path |
| `--output-xlsx` | — | Excel report output path |

### Config File

All CLI arguments can be set in YAML config (`config.yaml`):

```yaml
vcenter: 10.4.111.202
vcenter_user: administrator@vsphere.local
vcenter_pass: <password>
esxi_user: root
esxi_pass: <password>
host_model_filter: XR4510
mode: troubleshoot
perf_interval: 120
event_days: 14
output: report.json
output_pdf: report.pdf
output_xlsx: report.xlsx
```

CLI arguments override config file values.
