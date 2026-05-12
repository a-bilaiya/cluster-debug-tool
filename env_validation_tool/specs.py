"""RVC minimum hardware specifications, CPU feature definitions, and
disk model-to-RPM lookup tables."""

import re

# RVC-LS Edge VM Minimum Requirements (VRVWLS / VR7400 Spec)
# Source: RVCLS Perf Qualification Tracker + Design Doc + FIO Benchmarks
RVC_MIN_REQUIREMENTS = {
    # CPU
    "cpu_clock_ghz": 2.0,
    "logical_cores": 24,             # 24 vCPUs minimum
    "cpu_reservation_ghz": 48,       # Reservation must be set to 48 GHz
    # Memory
    "memory_gb": 128,                # 128 GB minimum per node
    # Network
    "min_nics": 4,                   # 4 virtual network adapters
    # Storage — disk counts
    "min_data_disks": 3,
    "max_data_disks": 4,
    "min_os_disk_gb": 400,           # 400 GB SSD, Thick Provision Eager Zeroed
    # Storage — capacity range per node
    "min_data_capacity_tb": 12,      # 3 × 4 TB minimum
    "max_data_capacity_tb": 96,      # 4 × 24 TB maximum
    # Storage — IOPS / throughput (from FIO qualification benchmarks)
    "os_disk_iops_threshold": 750,   # Hard threshold for OS disk
    "os_disk_iops_recommended": 3000,  # Recommended IOPS for OS disk
    "data_disk_iops_threshold": 50,  # Hard threshold per data disk (randread 4K)
    "data_disk_throughput_mbps": 100,  # Sequential read throughput per data disk
    # Cluster
    "min_cluster_nodes": 4,
    "max_cluster_nodes": 12,
    # Intel CPU model number threshold (Skylake+)
    "min_cpu_model_stepping": 85,
}

# CPU features important for RVC workloads
REQUIRED_CPU_FEATURES = ["aes", "sse4.2"]
RECOMMENDED_CPU_FEATURES = ["avx512f", "avx2"]

# Intel CPU model-to-microarchitecture mapping (Family 6)
INTEL_MODEL_MAP = {
    63: "Haswell",
    79: "Broadwell",
    85: "Skylake / Cascade Lake",
    106: "Ice Lake",
    108: "Ice Lake-D",
    143: "Sapphire Rapids",
    207: "Emerald Rapids",
}

# ── HDD Model-to-RPM Lookup ──────────────────────────────────────────
# Each entry: (regex_pattern, rpm, series_name)
# Patterns are matched against the full model string (case-insensitive).
# Order matters — first match wins.

HDD_RPM_TABLE = [
    # ── Seagate ──
    (r"ST\d+NM",      7200,  "Seagate Exos 7E / X"),
    (r"ST\d+NS",      15000, "Seagate Exos 15E"),
    (r"ST\d+SS",      10000, "Seagate Savvio 10K"),
    (r"ST\d+MP",      15000, "Seagate Exos 15E (SAS)"),
    (r"ST\d+NX",      7200,  "Seagate Exos (NearLine)"),
    (r"ST\d+LM",      5400,  "Seagate Barracuda (2.5\")"),
    (r"ST\d+DM",      7200,  "Seagate Barracuda (3.5\")"),
    (r"ST\d+VN",      5900,  "Seagate IronWolf"),
    (r"ST\d+VE",      7200,  "Seagate IronWolf Pro"),
    (r"ST\d+NT",      7200,  "Seagate Exos X"),

    # ── WD / HGST ──
    (r"HUH\d+",       7200,  "HGST Ultrastar He"),
    (r"HUS\d+",       7200,  "HGST Ultrastar 7K"),
    (r"HUC\d+",       10000, "HGST Ultrastar C10K"),
    (r"HDN\d+",       7200,  "HGST Deskstar NAS"),
    (r"WUH\d+",       7200,  "WD Ultrastar HC"),
    (r"WUS\d+",       7200,  "WD Ultrastar DC"),
    (r"WD\d+PURZ",    5400,  "WD Purple (Surveillance)"),
    (r"WD\d+EFAX",    5400,  "WD Red"),
    (r"WD\d+EFRX",    5400,  "WD Red"),
    (r"WD\d+EFZX",    7200,  "WD Red Plus"),
    (r"WD\d+FZBX",    7200,  "WD Black"),

    # ── Toshiba ──
    (r"AL\d{2}SE",    10500, "Toshiba AL (10.5K)"),
    (r"AL\d{2}SX",    15000, "Toshiba AL (15K)"),
    (r"MG\d+",        7200,  "Toshiba MG Enterprise"),
    (r"MN\d+",        7200,  "Toshiba N300 NAS"),
    (r"HDWG\d+",      7200,  "Toshiba X300"),

    # ── Dell OEM labels ──
    (r"Dell.*SAS.*10K", 10000, "Dell SAS 10K"),
    (r"Dell.*SAS.*15K", 15000, "Dell SAS 15K"),
    (r"Dell.*NL.*SAS",  7200,  "Dell NearLine SAS"),
    (r"Dell.*SATA",     7200,  "Dell SATA"),
]


def lookup_hdd_rpm(model_string):
    """Return (rpm, series_name) for a HDD model string, or (None, None)."""
    if not model_string:
        return None, None
    for pattern, rpm, series in HDD_RPM_TABLE:
        if re.search(pattern, model_string, re.IGNORECASE):
            return rpm, series
    return None, None
