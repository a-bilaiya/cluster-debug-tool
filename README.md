# RVC Cluster Debug Tool

A Python-based diagnostic and validation tool for **Rubrik Virtual Cluster (RVC)** environments. Connects directly to ESXi hosts via pyVmomi (no vCenter required) and collects hardware, VM, storage, network, performance, alarm, and task data. Generates JSON, PDF, and Excel reports.

---

## Requirements

- Python 3.8+
- Network access to ESXi hosts (port 443)
- ESXi root credentials

---

## Installation

### 1. Clone the repo

```bash
git clone https://github.com/a-bilaiya/rvc-cluster-debug-tool.git
cd rvc-cluster-debug-tool
```

### 2. Run the setup script

```bash
bash env_validation_tool/setup_env.sh
```

This will:
- Detect Python 3.8+
- Create a virtualenv at `.venv/`
- Install all dependencies (`pyVmomi`, `openpyxl`, `fpdf2`, `PyYAML`, `paramiko`, `requests`)
- Install the tool as an editable package
- Create the `/tool/out/` output directory

### 3. Activate the virtualenv

```bash
source .venv/bin/activate
```

---

## Configuration

Copy the sample config and fill in your ESXi details:

```bash
cp env_validation_tool/config.sample.yaml env_validation_tool/config.yaml
```

Edit `config.yaml`:

```yaml
# ESXi connection (required)
esxi_ips: 10.9.3.92,10.9.3.93,10.9.3.94,10.9.3.95
esxi_user: root
esxi_pass: yourpassword

# Optional: vCenter for auto-discovery
vcenter: 10.4.111.202
vcenter_user: administrator@vsphere.local
vcenter_pass: yourpassword

# VM pattern to match RVC VMs
vm_pattern: rvc-ls
vm_exclude: vcenter,vCenter

# Datacenter filter (if using vCenter)
datacenter: RVC_R7K_SILVER_SJC_B30303-24

# Lookback windows
perf_interval: 60   # minutes
event_days: 7

# Output paths
output: /tool/out/report.json
output_pdf: /tool/out/report.pdf
output_xlsx: /tool/out/report.xlsx
```

> **Note**: `config.yaml` is gitignored — never commit passwords.

---

## Usage

### Subcommands (quick one-shot checks)

```bash
# Check active and historical alarms
python -m env_validation_tool alarms        -c config.yaml

# Show recent tasks including failed operations
python -m env_validation_tool tasks         -c config.yaml

# Check CPU / memory reservations vs RVCLS spec
python -m env_validation_tool reservations  -c config.yaml

# Hardware sensor health (temps, fans, voltage)
python -m env_validation_tool hardware      -c config.yaml

# Datastore capacity and usage %
python -m env_validation_tool capacity      -c config.yaml

# Validate VMs against RVCLS spec (vCPU, disk, NIC, reservation)
python -m env_validation_tool validate      -c config.yaml

# Full report → JSON + PDF + Excel
python -m env_validation_tool report        -c config.yaml
python -m env_validation_tool report        -c config.yaml --output-base /tool/out/myrun
```

### Interactive menu

Connects from config and drops into a menu — no flags needed:

```bash
python -m env_validation_tool interactive   -c config.yaml
```

Menu options:

```
  1  Alarms          Active & historical alarms (7-day window)
  2  Reservations    CPU / memory reservation per VM vs RVCLS spec
  3  Tasks           Recent tasks + failed operations
  4  Hardware        Sensor health — temps, fans, voltage, power
  5  Performance     CPU, memory, disk & network metrics
  6  Validate VMs    Check VMs against RVCLS spec
  7  Capacity        Datastore free space and usage %
  8  Full Report     All data → JSON + PDF + Excel
  9  Reconnect       Change hosts or credentials

  h  Help            Detailed help for each option
  q  Quit
```

### Full troubleshoot run (original mode flag)

```bash
python -m env_validation_tool -c config.yaml --mode troubleshoot
python -m env_validation_tool -c config.yaml --mode pre-deploy
python -m env_validation_tool -c config.yaml --mode troubleshoot \
    -o /tool/out/report.json \
    --output-pdf /tool/out/report.pdf \
    --output-xlsx /tool/out/report.xlsx
```

### Help

```bash
python -m env_validation_tool help
python -m env_validation_tool --help
```

---

## Output

All reports are saved to `/tool/out/` by default.

| File | Contents |
|------|----------|
| `report.json` | Full raw data (all sections, machine-readable) |
| `report.pdf` | Human-readable summary report |
| `report.xlsx` | Excel workbook — 20 sheets per cluster |

### Excel sheet layout (troubleshoot mode)

| Sheet | Contents |
|-------|----------|
| Cluster Summary | Overall cluster health, node count, vCenter alarms |
| vCenter Alarms | Active alarms across all objects |
| `{tag} Overview` | Host identity, capacity, health summary, system info |
| `{tag} VMs` | VM summary, disks, NICs, guest NICs, snapshots, contention, autostart |
| `{tag} Resources` | Datastores, CPU/memory allocation per VM, overcommit ratios |
| `{tag} Performance` | CPU/mem/disk/net metrics with latest/avg/min/max |
| `{tag} Network` | Physical NICs, vSwitches, port groups, VMkernel, DNS/NTP, DVS |
| `{tag} Storage` | HBAs, SCSI LUNs, multipath, VMFS volumes |
| `{tag} Hardware` | Sensors, PCI devices, CPU topology, IPMI/BMC, power policy |
| `{tag} Config` | Services, firewall, security, advanced settings, VIBs, SNMP, vSAN |
| `{tag} Events` | Active alarms, alarm history, events, recent tasks |

---

## RVCLS Spec Validation

The tool validates each RVC VM against the RVCLS qualification spec:

| Check | Requirement |
|-------|-------------|
| vCPU count | ≥ 24 |
| Memory | ≥ 128 GB |
| Virtual NICs | ≥ 4 |
| OS disk size | ≥ 400 GB |
| OS disk provisioning | eagerzeroedthick |
| Data disk count | 3–4 |
| Data disk capacity | 12–96 TB |
| CPU reservation | ≥ 48 GHz |
| CPU limit | Unlimited (-1) |
| Memory reservation | = configured MB |

---

## Without vCenter

All subcommands and the full troubleshoot run work directly against ESXi hosts (port 443) — vCenter is optional. When vCenter is unavailable, the tool uses the ESXi TaskManager and EventManager directly for task/alarm data.

---

## Project Structure

```
rvc-cluster-debug-tool/
  setup.py                          # package definition
  requirements.txt                  # pip dependencies
  README.md
  .gitignore
  env_validation_tool/
    setup_env.sh                    # one-shot setup script
    config.sample.yaml              # config template (no passwords)
    cli.py                          # CLI entrypoint + subcommands
    interactive.py                  # interactive menu console
    troubleshoot.py                 # 30+ diagnostic collectors
    troubleshoot_excel.py           # Excel report generator
    troubleshoot_report.py          # console report printer
    pdf_report.py                   # PDF report generator
    validator.py                    # RVCLS spec validation
    specs.py                        # hardware specs & thresholds
    discovery/
      esxi.py                       # pyVmomi ESXi/vCenter discovery
```
