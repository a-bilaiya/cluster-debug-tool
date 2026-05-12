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
git clone https://github.com/a-bilaiya/cluster-debug-tool.git
cd cluster-debug-tool
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

`-c config.yaml` is optional — omit it to use `config.yaml` in the current directory,
or the tool will warn and prompt if not found.

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

`-c` is **optional** for interactive mode:

```bash
# Auto-connects from config — skips the connection prompt
python -m env_validation_tool interactive -c config.yaml

# No config — shows connection menu (enter IPs/creds manually or pick a config file)
python -m env_validation_tool interactive
```

When no config is provided (or config file is not found), the tool prompts:

```
  How to connect?
    1. Enter ESXi credentials manually
    2. Load from config file
```

> **Tip**: `-c` is also optional for all other subcommands. Without it, the tool
> looks for `config.yaml` in the current directory and warns if not found.

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

## Standalone Executables (No Python Required)

Pre-built executables for Linux, macOS, and Windows are on the
[Releases page](https://github.com/a-bilaiya/cluster-debug-tool/releases).

```bash
# Linux x86_64
chmod +x rvc-cluster-debug-tool-*-linux-x86_64
./rvc-cluster-debug-tool-*-linux-x86_64 interactive

# macOS (Intel or Apple Silicon)
chmod +x rvc-cluster-debug-tool-*-macos-*
./rvc-cluster-debug-tool-*-macos-* interactive
```

```powershell
# Windows PowerShell
.\rvc-cluster-debug-tool-*-windows-x86_64.exe interactive
```

These bundle Python and all dependencies into a single ~26 MB file —
customers don't need to install Python or pip.

### Building executables locally

Each release contains **two binaries per platform**:

| Binary | Purpose |
|--------|---------|
| `rvc-cluster-debug-tool` | Full diagnostic tool — interactive menu + all subcommands |
| `vminfo-report` | Quick standalone VM info → ZIP for support tickets |

To build on your own machine, use the script that matches your OS:

| OS | Build both | Build one only |
|----|------------|----------------|
| Linux  | `bash build.sh`     | `bash build.sh --target main` <br/> `bash build.sh --target vminfo` |
| macOS  | `bash build.sh`     | `bash build.sh --target main` <br/> `bash build.sh --target vminfo` |
| Windows | `.\build.ps1`      | `.\build.ps1 -Target main` <br/> `.\build.ps1 -Target vminfo` |

Common options (work for both scripts):

| Option | Behavior |
|--------|----------|
| `--onefile` (default) | Single executable, ~26 MB, ~2s startup |
| `--onedir`            | Folder with executable + libs, instant startup |
| `--clean`             | Delete `dist/` `build/` `dist-release/` first |

Output appears in `dist-release/`. The build uses **PyInstaller** and takes
~1 minute. PyInstaller **cannot cross-compile** — build on each target OS.

### Cutting a release (maintainers)

Tag a version and push — GitHub Actions builds for all 4 platforms in parallel
and publishes a GitHub Release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Builds produced:

| Platform | Runner | Output |
|----------|--------|--------|
| Linux x86_64        | `ubuntu-latest` | `*-linux-x86_64` |
| macOS Apple Silicon | `macos-14`      | `*-macos-arm64`  |
| Windows x86_64      | `windows-latest`| `*-windows-x86_64.exe` |

> **Note:** Intel macOS (macos-13) is no longer in the matrix — GitHub Actions Intel macOS runners are scarce and most Macs since 2020 are Apple Silicon. If you need an Intel macOS binary, build it manually on an Intel Mac with `bash build.sh`.

The workflow at `.github/workflows/release.yml` generates SHA256 checksums
and attaches all binaries to the GitHub Release.

---

## Sharing Reports with Rubrik Support

When contacting Rubrik Support about cluster issues, run the full report and attach:

| File | Contents |
|------|----------|
| `report.xlsx` | Excel workbook — easiest to read, share this first |
| `report.json` | Full raw data — engineers use this for deep analysis |
| `report.pdf` | Printable summary |

In your support case, also include:
- Rubrik cluster serial number
- Rubrik software version
- Description of symptoms

### Quick report generation

```bash
python -m env_validation_tool report -c config.yaml
```

Reports are saved to `/tool/out/` by default.

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
cluster-debug-tool/
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

---
