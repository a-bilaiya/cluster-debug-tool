# scripts/

Standalone scripts that complement the main `env_validation_tool` package.
These can be run directly from the project root and produce focused, single-purpose outputs.

---

## `vminfo_report.py`

Standalone VM hardware info collector. Connects to ESXi host(s), gathers
per-VM hardware details (same data as `python -m env_validation_tool vminfo`),
and bundles **JSON + PDF + Excel** into a single ZIP file ready to share
with Rubrik Support.

### Usage

```bash
# With a config file
python scripts/vminfo_report.py -c config.yaml

# With CLI flags
python scripts/vminfo_report.py --esxi-ips 10.0.0.10 --esxi-user root --esxi-pass MYPASS

# Fully interactive — prompts for everything
python scripts/vminfo_report.py

# Custom output directory and customer name
python scripts/vminfo_report.py -c config.yaml --output-dir ./out --customer "Acme Corp"
```

### Output

```
/tool/out/vminfo_2026-05-12T14-30-22Z.zip
  ├── vminfo_2026-05-12T14-30-22Z.json   # raw structured data
  ├── vminfo_2026-05-12T14-30-22Z.pdf    # human-readable report
  └── vminfo_2026-05-12T14-30-22Z.xlsx   # Excel workbook
```

The ZIP contains all three formats — share it as-is with Rubrik Support.

### What it collects (per VM)

- **Identity**: name, power state, VM hardware version, guest OS, hostname, IP
- **Compute**: vCPUs, memory MB, CPU reservation/limit/shares, memory reservation/limit
- **Disks**: label, size, provisioning (thin/thick/eagerzeroedthick), disk mode, controller key, unit number, backing file
- **Network adapters**: label, type (VMXNET3/E1000/etc), network, MAC, connected state
- **Storage controllers**: label, type (PVSCSI/LSI Logic/AHCI/NVMe/USB), bus number, sharing mode, hot-add capability

### Requirements

Same as the main tool — `pyVmomi`, `PyYAML`, `openpyxl`, `fpdf2`. Run
`bash env_validation_tool/setup_env.sh` once to install everything.
