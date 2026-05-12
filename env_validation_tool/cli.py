"""CLI argument parser and main orchestration logic."""

import argparse
import json
import os
import sys
import textwrap
import time
import yaml

from .discovery.esxi import ESXiDiscovery, discover_esxi_hosts_from_vcenter
from .validator import validate_requirements, validate_cluster_size, validate_rvc_vm
from .network_tests import run_network_perf_suite, run_iperf_suite
from .report import (
    print_validation_summary,
    print_network_summary,
    print_iperf_summary,
    print_quick_summary_table,
)
from .pdf_report import generate_pdf_report, generate_troubleshoot_pdf
from .troubleshoot import collect_troubleshoot_report
from .troubleshoot_excel import generate_troubleshoot_xlsx
from .troubleshoot_report import print_troubleshoot_summary, print_vcenter_alarms


def _load_config(path):
    """Load YAML config file. Returns empty dict if file doesn't exist."""
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


# Maps config YAML keys to argparse dest names (only where they differ).
_CONFIG_KEY_MAP = {
    "vcenter_user": "vcenter_user",
    "vcenter_pass": "vcenter_pass",
    "esxi_ips": "esxi_ips",
    "esxi_user": "esxi_user",
    "esxi_pass": "esxi_pass",
    "host_model_filter": "host_model_filter",
    "vm_pattern": "vm_pattern",
    "vm_exclude": "vm_exclude",
    "ssh_key": "ssh_key",
    "ssh_user": "ssh_user",
    "iperf_duration": "iperf_duration",
    "iperf_streams": "iperf_streams",
    "output_pdf": "output_pdf",
    "output_xlsx": "output_xlsx",
}


def _merge_config(args, cfg):
    """Apply config values to args where the CLI didn't set them."""
    for cfg_key, val in cfg.items():
        # Map config key to argparse dest (replace - with _)
        dest = _CONFIG_KEY_MAP.get(cfg_key, cfg_key.replace("-", "_"))
        if not hasattr(args, dest):
            continue
        current = getattr(args, dest)
        # Only apply config value if CLI left the default
        if current is None:
            setattr(args, dest, val)


def build_parser():
    """Build the CLI argument parser."""
    epilog = textwrap.dedent("""\
    USAGE EXAMPLES
    ──────────────
      # Pre-deploy hardware check (vCenter auto-discovery)
      env_validation_tool -c config.yaml --mode pre-deploy

      # Full validation with iperf bandwidth tests
      env_validation_tool -c config.yaml --mode full --ssh-key ~/.ssh/id_rsa

      # Troubleshoot with all output formats
      env_validation_tool -c config.yaml --mode troubleshoot \\
          -o report.json --output-pdf report.pdf --output-xlsx report.xlsx

      # Custom perf window and event history
      env_validation_tool -c config.yaml --mode troubleshoot \\
          --perf-interval 120 --event-days 14

      # Manual ESXi IPs (no vCenter)
      env_validation_tool --esxi-ips 10.0.1.1,10.0.1.2 \\
          --esxi-pass secret --mode troubleshoot

    DIAGNOSTIC SCENARIOS
    ────────────────────
      VM performance issues:
        → Check health_summary, vm_contention_stats (cpu_ready_pct),
          performance_stats (cpu.ready, cpu.costop)

      Slow disk IOPS / high latency:
        → Check io_stats (per-disk latency), datastore_io_stats,
          storage_config (RAID, multipath)

      Memory pressure / ballooning:
        → Check performance_stats (mem_balloon, mem_swap*),
          vm_contention_stats (per-VM balloon/swap), overcommit_ratios

      Network packet loss / errors:
        → Check io_stats (per-NIC drops/errors), network_config
          (offloads, MTU, teaming policy)

      Resource overcommitment:
        → Check overcommit_ratios, cpu_allocation, memory_allocation

      Hardware degradation:
        → Check hardware_health (sensors), alarms (critical),
          pci_devices, system_info (BIOS version)

      Recent change caused regression:
        → Check events (last 7 days), recent_tasks, advanced_settings
    """)

    parser = argparse.ArgumentParser(
        prog="env_validation_tool",
        description="RVC Environment Validation Tool — validate hypervisor "
                    "host hardware for Rubrik Virtual Cluster deployment.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Interactive mode
    parser.add_argument("--interactive", "-i", action="store_true",
                        help="Launch interactive menu-driven console")

    # Config file
    parser.add_argument("--config", "-c", metavar="FILE",
                        default="config.yaml",
                        help="Path to YAML config file (default: config.yaml)")

    # Connection
    conn = parser.add_argument_group("Connection")
    conn.add_argument("--hypervisor", default="esxi",
                      choices=["esxi"],
                      help="Hypervisor type (default: esxi)")
    conn.add_argument("--vcenter", metavar="IP",
                      help="vCenter IP for auto-discovery")
    conn.add_argument("--vcenter-user", metavar="USER",
                      help="vCenter username")
    conn.add_argument("--vcenter-pass", metavar="PASS",
                      help="vCenter password")
    conn.add_argument("--esxi-ips", metavar="IPs",
                      help="Comma-separated ESXi IPs (fallback if no vCenter)")
    conn.add_argument("--esxi-user", default=None,
                      help="ESXi username (default: root)")
    conn.add_argument("--esxi-pass", metavar="PASS",
                      help="ESXi password")

    # Discovery
    disc = parser.add_argument_group("Discovery")
    disc.add_argument("--host-model-filter", metavar="SUBSTR",
                      help="Filter hosts by server model substring "
                           "(e.g. 'XR4510')")
    disc.add_argument("--datacenter", metavar="NAME",
                      help="Filter hosts by datacenter name substring")
    disc.add_argument("--mode", default=None,
                      choices=["pre-deploy", "post-deploy", "full",
                               "troubleshoot"],
                      help="Validation mode (default: full)")
    disc.add_argument("--vm-pattern", default=None,
                      help="Substring pattern to identify RVC VMs "
                           "(default: vc-vr7400)")
    disc.add_argument("--vm-exclude", default=None,
                      help="Comma-separated patterns to exclude from VM match")

    # Troubleshoot
    ts = parser.add_argument_group("Troubleshoot Mode")
    ts.add_argument("--perf-interval", type=int, default=None,
                    help="Performance stats lookback in minutes (default: 60)")
    ts.add_argument("--event-days", type=int, default=None,
                    help="Events/tasks lookback in days (default: 7)")

    # Network / iperf
    net = parser.add_argument_group("Network Tests (post-deploy)")
    net.add_argument("--ssh-key", metavar="PATH",
                     help="Path to SSH private key for edge VM access")
    net.add_argument("--ssh-user", default=None,
                     help="SSH username for edge VMs (default: ubuntu)")
    net.add_argument("--iperf-duration", type=int, default=None,
                     help="iperf3 test duration in seconds (default: 10)")
    net.add_argument("--iperf-streams", type=int, default=None,
                     help="iperf3 parallel streams (default: 4)")

    # Output
    out = parser.add_argument_group("Output")
    out.add_argument("--output", "-o", metavar="FILE",
                     help="Path to write JSON report (default: stdout)")
    out.add_argument("--output-pdf", metavar="FILE",
                     help="Path to write PDF report")
    out.add_argument("--output-xlsx", metavar="FILE",
                     help="Path to write Excel troubleshoot report")
    out.add_argument("--output-base", metavar="PATH",
                     help="Base path for report subcommand outputs "
                          "(default: /tool/out/report)")

    return parser


_SUBCOMMANDS = {
    "interactive", "alarms", "tasks", "reservations",
    "hardware", "capacity", "validate", "vminfo", "report", "help",
}

_USAGE_TEXT = """\
RVC Environment Validation Tool
================================

SUBCOMMANDS (quick one-shot checks):
  -c config.yaml is optional for all subcommands.
  Without it, the tool prompts for ESXi IPs and credentials.

  python -m env_validation_tool alarms        [-c config.yaml]
  python -m env_validation_tool tasks         [-c config.yaml]
  python -m env_validation_tool reservations  [-c config.yaml]
  python -m env_validation_tool hardware      [-c config.yaml]
  python -m env_validation_tool capacity      [-c config.yaml]
  python -m env_validation_tool validate      [-c config.yaml]
  python -m env_validation_tool vminfo        [-c config.yaml]
  python -m env_validation_tool report        [-c config.yaml] [--output-base /tool/out/report]
  python -m env_validation_tool interactive   [-c config.yaml]

FULL RUN (existing --mode flag):
  python -m env_validation_tool -c config.yaml --mode troubleshoot
  python -m env_validation_tool -c config.yaml --mode pre-deploy

OPTIONS:
  -c / --config FILE      Config file (default: config.yaml)
  --esxi-ips IPs          Comma-separated ESXi IPs (override config)
  --esxi-user USER        ESXi username (default: root)
  --esxi-pass PASS        ESXi password
  --mode MODE             pre-deploy | post-deploy | full | troubleshoot
  --output-base PATH      Base path for report subcommand outputs
  -i / --interactive      Launch interactive menu
  --help                  Full argument reference
"""


def _subcommand_parse_args(argv):
    """Parse minimal args for subcommand mode: -c/--config, --host, --output-base."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("-c", "--config", default="config.yaml")
    p.add_argument("--host", default=None)
    p.add_argument("--output-base", default="/tool/out/report")
    known, _ = p.parse_known_args(argv)
    return known


def _prompt_if_missing(cfg, host_override=None):
    """Fill missing connection fields from cfg by prompting the user."""
    import getpass

    raw_ips = cfg.get("esxi_ips", "")
    esxi_ips = [ip.strip() for ip in str(raw_ips).split(",") if ip.strip()]
    if host_override:
        esxi_ips = [h.strip() for h in host_override.split(",") if h.strip()]

    if not esxi_ips:
        raw = input("  ESXi IPs (comma-separated): ").strip()
        esxi_ips = [ip.strip() for ip in raw.split(",") if ip.strip()]
        if not esxi_ips:
            raise SystemExit("[ERROR] No ESXi IPs provided.")

    user = cfg.get("esxi_user", "") or input("  ESXi username [root]: ").strip() or "root"

    password = cfg.get("esxi_pass", "")
    if not password:
        password = getpass.getpass("  ESXi password: ")
        if not password:
            raise SystemExit("[ERROR] Password is required.")

    vm_pattern = cfg.get("vm_pattern", "")
    if not vm_pattern:
        vm_pattern = input("  VM name filter (e.g. rvc-ls, leave blank for all): ").strip()

    return esxi_ips, user, password, vm_pattern


def _build_subcommand_session(cfg, host_override=None):
    """Build an interactive-style session dict, prompting for any missing fields."""
    import ssl
    from pyVim.connect import SmartConnect
    from pyVmomi import vim

    esxi_ips, user, password, vm_pattern = _prompt_if_missing(cfg, host_override)

    session = {
        "esxi_ips": esxi_ips,
        "esxi_user": user,
        "esxi_pass": password,
        "hosts": {},
        "vm_pattern": vm_pattern,
    }

    print("  Connecting...")
    context = ssl._create_unverified_context()
    for ip in esxi_ips:
        try:
            si = SmartConnect(host=ip, user=user, pwd=password, sslContext=context)
            content = si.RetrieveContent()
            container = content.viewManager.CreateContainerView(
                content.rootFolder, [vim.HostSystem], True,
            )
            if not container.view:
                raise RuntimeError(f"No host found on {ip}")
            host = container.view[0]
            container.Destroy()
            model = host.summary.hardware.model
            ver = host.summary.config.product.version
            print(f"  OK  {ip:<18} {model}  ESXi {ver}")
            session["hosts"][ip] = {"si": si, "content": content, "host": host}
        except Exception as e:
            print(f"  FAIL  {ip:<18} {e}")

    connected = [ip for ip in esxi_ips if ip in session["hosts"]]
    if not connected:
        raise SystemExit("[ERROR] No hosts connected. Check IPs and credentials.")

    print(f"  {len(connected)} host(s) connected.\n")
    return session


def _subcommand_disconnect(session):
    """Disconnect all hosts in a subcommand session."""
    from pyVim.connect import Disconnect
    for ip, h in session.get("hosts", {}).items():
        try:
            Disconnect(h["si"])
        except Exception:
            pass


def _run_subcommand(subcommand, argv):
    """Parse subcommand args, connect, run the check, disconnect, and exit."""
    from .interactive import (
        _check_alarms, _check_tasks, _check_reservations,
        _check_hardware, _check_capacity, _check_vm_validation,
        _check_vm_info, _full_troubleshoot,
    )

    sub_args = _subcommand_parse_args(argv)
    cfg = _load_config(sub_args.config)
    if cfg:
        print(f"[*] Loaded config from {sub_args.config}")
    else:
        print("[*] No config file found — prompting for connection details.")

    if subcommand == "interactive":
        from .interactive import run_interactive
        run_interactive(preload_cfg=cfg)
        return 0

    session = _build_subcommand_session(cfg, host_override=sub_args.host)

    try:
        if subcommand == "alarms":
            _check_alarms(session)
        elif subcommand == "tasks":
            _check_tasks(session)
        elif subcommand == "reservations":
            _check_reservations(session)
        elif subcommand == "hardware":
            _check_hardware(session)
        elif subcommand == "capacity":
            _check_capacity(session)
        elif subcommand == "validate":
            _check_vm_validation(session)
        elif subcommand == "vminfo":
            _check_vm_info(session)
        elif subcommand == "report":
            # Inject the output base into the session so _full_troubleshoot can pick it up
            session["_output_base"] = sub_args.output_base
            _run_report_subcommand(session, sub_args.output_base)
    finally:
        _subcommand_disconnect(session)

    return 0


def _run_report_subcommand(session, base_path):
    """Run the full troubleshoot report from a subcommand session."""
    import json as _json
    from .troubleshoot import collect_troubleshoot_report
    from .troubleshoot_report import print_troubleshoot_summary
    from .troubleshoot_excel import generate_troubleshoot_xlsx
    from .pdf_report import generate_troubleshoot_pdf
    from .discovery.esxi import ESXiDiscovery
    from .validator import validate_requirements

    out_json = base_path + ".json"
    out_pdf  = base_path + ".pdf"
    out_xlsx = base_path + ".xlsx"

    print(f"  Output: {base_path}.{{json,pdf,xlsx}}")

    reports = []
    for ip in [ip for ip in session["esxi_ips"] if ip in session["hosts"]]:
        h = session["hosts"][ip]
        print(f"\n  [{ip}] Collecting data...")
        try:
            discovery = ESXiDiscovery()
            discovery._si = h["si"]
            discovery._host = h["host"]

            vm_pat = session.get("vm_pattern", "")
            host_report = discovery.collect_host_report(
                vm_pattern=vm_pat or None,
                vm_exclude=[],
            )
            host_report["esxi_ip"] = ip
            host_report["validation"] = validate_requirements(host_report)
            host_report["troubleshoot"] = collect_troubleshoot_report(
                discovery, perf_interval_minutes=60, event_days=7,
            )
            tag = host_report.get("host_identity", {}).get("service_tag", "?")
            ts  = host_report["troubleshoot"]
            state  = ts.get("host_state", {})
            alarms = ts.get("alarms", {})
            print(f"  OK  {ip} — tag={tag}  "
                  f"uptime={state.get('uptime_human','?')}  "
                  f"alarms={alarms.get('total_count', 0)}")
            reports.append(host_report)
        except Exception as e:
            import traceback
            print(f"  ERROR on {ip}: {e}")
            traceback.print_exc()

    if not reports:
        print("[ERROR] No data collected.")
        return

    result = {"hosts": reports, "cluster_name": "Subcommand", "vcenter_ip": "?"}

    out_dir = os.path.dirname(out_json)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(out_json, "w") as f:
        _json.dump(result, f, indent=2, default=str)
    print(f"\n  JSON  saved: {out_json}")

    try:
        generate_troubleshoot_xlsx(result, out_xlsx)
        print(f"  Excel saved: {out_xlsx}")
    except Exception as e:
        print(f"  Excel failed: {e}")

    try:
        generate_troubleshoot_pdf(result, out_pdf)
        print(f"  PDF   saved: {out_pdf}")
    except Exception as e:
        print(f"  PDF failed: {e}")

    for rep in reports:
        ip  = rep.get("esxi_ip", "?")
        tag = rep.get("host_identity", {}).get("service_tag", "?")
        ts  = rep.get("troubleshoot", {})
        print_troubleshoot_summary(ip, tag, ts)
        print()


def main(argv=None):
    """Main entry point."""
    raw_argv = argv if argv is not None else sys.argv[1:]

    # ── Subcommand pre-check ──
    first = raw_argv[0] if raw_argv else None
    if first in _SUBCOMMANDS:
        if first == "help":
            print(_USAGE_TEXT)
            return 0
        return _run_subcommand(first, raw_argv[1:])

    # Show clean usage when no args and no config.yaml found
    if not raw_argv and not os.path.isfile("config.yaml"):
        print(_USAGE_TEXT)
        return 0

    parser = build_parser()
    args = parser.parse_args(raw_argv)

    # Interactive mode — bypass all normal flow
    if getattr(args, "interactive", False):
        from .interactive import run_interactive
        run_interactive()
        return 0

    # Load config file and merge
    cfg = _load_config(args.config)
    if cfg:
        print(f"[*] Loaded config from {args.config}")
    _merge_config(args, cfg)

    # Apply defaults for values that may still be None
    if args.esxi_user is None:
        args.esxi_user = "root"
    if args.mode is None:
        args.mode = "full"
    if args.vm_pattern is None:
        args.vm_pattern = "vc-vr7400"
    if args.vm_exclude is None:
        args.vm_exclude = "vcenter,vCenter"
    if args.ssh_user is None:
        args.ssh_user = "ubuntu"
    if args.iperf_duration is None:
        args.iperf_duration = 10
    if args.iperf_streams is None:
        args.iperf_streams = 4
    if args.perf_interval is None:
        args.perf_interval = 60
    if args.event_days is None:
        args.event_days = 7

    # Validate required fields
    if not args.esxi_pass:
        parser.error("ESXi password required — set esxi_pass in config "
                     "or pass --esxi-pass")

    vm_exclude = [p.strip() for p in args.vm_exclude.split(",") if p.strip()]
    is_post_deploy = args.mode in ("post-deploy", "full")
    is_troubleshoot = args.mode == "troubleshoot"

    cluster_report = {
        "cluster": None,
        "collection_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hosts": [],
        "network_performance": [],
    }

    # ── Phase 0: Discover ESXi IPs ──
    esxi_ips = []
    if args.vcenter:
        print("=" * 70)
        print("  PHASE 0: vCenter Discovery")
        print("=" * 70)
        print(f"\n[*] Connecting to vCenter {args.vcenter}...")
        vcenter_info = discover_esxi_hosts_from_vcenter(
            args.vcenter, args.vcenter_user, args.vcenter_pass,
            host_model_filter=args.host_model_filter,
            datacenter_filter=getattr(args, "datacenter", None),
            collect_alarms=is_troubleshoot,
            alarm_days=args.event_days,
        )
        esxi_ips = vcenter_info["esxi_ips"]
        cluster_report["cluster"] = (
            vcenter_info.get("cluster_name")
            or args.host_model_filter
            or "Unknown"
        )
        if vcenter_info.get("datacenter"):
            cluster_report["datacenter"] = vcenter_info["datacenter"]
        cluster_report["vcenter"] = args.vcenter
        if vcenter_info.get("vcenter_alarms"):
            cluster_report["vcenter_alarms"] = vcenter_info["vcenter_alarms"]

    if not esxi_ips and args.esxi_ips:
        esxi_ips = [ip.strip() for ip in args.esxi_ips.split(",")]

    if not esxi_ips:
        print("[ERROR] No ESXi hosts to audit. "
              "Provide --vcenter or --esxi-ips.")
        return 1

    if not cluster_report["cluster"]:
        cluster_report["cluster"] = "Manual"

    print(f"\n  Cluster: {cluster_report['cluster']}")
    print(f"  ESXi hosts to audit: {esxi_ips}")

    # ── Phase 1: Hardware Discovery & Validation ──
    print("\n" + "=" * 70)
    print("  PHASE 1: ESXi Host Discovery & Validation")
    print("=" * 70)

    for esxi_ip in esxi_ips:
        print(f"\n[*] Discovering ESXi host {esxi_ip}...")
        discovery = ESXiDiscovery()
        try:
            discover_vms = is_post_deploy or is_troubleshoot
            discovery.connect(esxi_ip, args.esxi_user, args.esxi_pass)
            report = discovery.collect_host_report(
                vm_pattern=args.vm_pattern if discover_vms else None,
                vm_exclude=vm_exclude,
            )
            report["esxi_ip"] = esxi_ip
            report["validation"] = validate_requirements(report)

            tag = report["host_identity"]["service_tag"]
            vms = report.get("rvc_vms", [])
            vm_names = [v["vm_name"] for v in vms]
            print(f"  Tag={tag}  RVC VMs found: {vm_names}")
            print_validation_summary(report["validation"])

            # Troubleshoot: collect runtime diagnostics while still connected
            if is_troubleshoot:
                print(f"\n[*] Collecting troubleshoot data for {esxi_ip}...")
                report["troubleshoot"] = collect_troubleshoot_report(
                    discovery,
                    perf_interval_minutes=args.perf_interval,
                    event_days=args.event_days,
                )
                ts = report["troubleshoot"]
                state = ts.get("host_state", {})
                alarms = ts.get("alarms", {})
                health = ts.get("hardware_health", {})
                print(f"  State={state.get('connection_state', '?')}  "
                      f"Uptime={state.get('uptime_human', '?')}  "
                      f"Alarms={alarms.get('total_count', 0)}  "
                      f"Sensors={health.get('summary', {}).get('total', 0)}")

                # Validate RVC VMs against RVCLS spec
                vm_details = ts.get("vm_details", {})
                cpu_alloc = ts.get("cpu_allocation", {})
                mem_alloc = ts.get("memory_allocation", {})
                cpu_per_vm = {v["vm_name"]: v
                              for v in cpu_alloc.get("per_vm", [])}
                mem_per_vm = {v["vm_name"]: v
                              for v in mem_alloc.get("per_vm", [])}
                rvc_vm_checks = []
                for vm in vm_details.get("vms", []):
                    vm_name = vm.get("vm_name", "")
                    # Only validate VMs matching the RVC pattern
                    if (args.vm_pattern
                            and args.vm_pattern.lower()
                            in vm_name.lower()):
                        result_vm = validate_rvc_vm(
                            vm,
                            cpu_alloc_vm=cpu_per_vm.get(vm_name),
                            mem_alloc_vm=mem_per_vm.get(vm_name),
                        )
                        rvc_vm_checks.append(result_vm)
                        # Print VM validation
                        fails = [c for c in result_vm["checks"]
                                 if c["status"] == "FAIL"]
                        warns = [c for c in result_vm["checks"]
                                 if c["status"] == "WARN"]
                        tag_str = ("PASS" if not fails
                                   else f"{len(fails)} FAIL")
                        if warns:
                            tag_str += f", {len(warns)} warn"
                        print(f"\n  RVC VM: {vm_name} — {tag_str}")
                        for c in result_vm["checks"]:
                            icon = {"PASS": "OK", "FAIL": "FAIL",
                                    "WARN": "WARN"}[c["status"]]
                            print(f"    [{icon:4s}] "
                                  f"{c['check']:30s} {c['actual']}")
                if rvc_vm_checks:
                    report["rvc_vm_validation"] = rvc_vm_checks

            cluster_report["hosts"].append(report)
        except Exception as e:
            print(f"  [ERROR] {e}")
            cluster_report["hosts"].append({
                "esxi_ip": esxi_ip, "status": "error", "message": str(e),
            })
        finally:
            discovery.disconnect()

    # ── Phase 2 + 3: Network tests (post-deploy only) ──
    net_results = []
    iperf_results = None

    if is_post_deploy and not is_troubleshoot:
        print("\n" + "=" * 70)
        print("  PHASE 2: Network Performance Tests")
        print("=" * 70)
        for host_report in cluster_report["hosts"]:
            if host_report.get("status") == "error":
                continue
            tag = host_report["host_identity"]["service_tag"]
            for vm in host_report.get("rvc_vms", []):
                if vm["vm_ip"] and vm["power_state"] == "poweredOn":
                    result = run_network_perf_suite(
                        vm["vm_name"], vm["vm_ip"], tag,
                    )
                    net_results.append(result)
                else:
                    state = vm["power_state"]
                    print(f"  [skip] {vm['vm_name']} -- "
                          f"{'no IP' if not vm['vm_ip'] else state}")
        cluster_report["network_performance"] = net_results

        # Phase 3: iperf3
        if args.ssh_key:
            print("\n" + "=" * 70)
            print("  PHASE 3: iperf3 Real Bandwidth Tests")
            print("=" * 70)

            iperf_nodes = []
            for host_report in cluster_report["hosts"]:
                if host_report.get("status") == "error":
                    continue
                for vm in host_report.get("rvc_vms", []):
                    if vm["vm_ip"] and vm["power_state"] == "poweredOn":
                        iperf_nodes.append({
                            "vm_name": vm["vm_name"],
                            "vm_ip": vm["vm_ip"],
                        })

            if iperf_nodes:
                iperf_results = run_iperf_suite(
                    iperf_nodes,
                    ssh_key=args.ssh_key,
                    ssh_user=args.ssh_user,
                    duration=args.iperf_duration,
                    parallel=args.iperf_streams,
                )
                cluster_report["iperf_bandwidth"] = iperf_results
            else:
                print("\n  [WARN] No powered-on RVC VMs with IPs -- "
                      "skipping iperf tests.")
        else:
            print("\n  [INFO] No --ssh-key provided -- skipping iperf tests.")

    # ── Output ──
    if args.output:
        with open(args.output, "w") as f:
            json.dump(cluster_report, f, indent=4)
        print(f"\n[*] JSON report written to {args.output}")
    else:
        print("\n\n" + "#" * 70)
        print("  FULL CLUSTER REPORT (JSON)")
        print("#" * 70)
        print(json.dumps(cluster_report, indent=4))

    # ── PDF report ──
    if args.output_pdf:
        if is_troubleshoot:
            generate_troubleshoot_pdf(cluster_report, args.output_pdf)
        else:
            generate_pdf_report(cluster_report, args.output_pdf,
                                net_results=net_results,
                                iperf_results=iperf_results)
        print(f"\n[*] PDF report written to {args.output_pdf}")

    # ── Excel report (troubleshoot only) ──
    if args.output_xlsx and is_troubleshoot:
        generate_troubleshoot_xlsx(cluster_report, args.output_xlsx)
        print(f"\n[*] Excel report written to {args.output_xlsx}")

    # Troubleshoot console output
    if is_troubleshoot:
        for host_report in cluster_report["hosts"]:
            if host_report.get("status") == "error":
                continue
            ts_data = host_report.get("troubleshoot")
            if ts_data:
                print_troubleshoot_summary(
                    host_report["esxi_ip"],
                    host_report["host_identity"]["service_tag"],
                    ts_data,
                )
        # vCenter-wide alarms (datacenter scope)
        if cluster_report.get("vcenter_alarms"):
            print_vcenter_alarms(cluster_report["vcenter_alarms"])

    # ── Cluster-level validation ──
    ok_hosts = [h for h in cluster_report["hosts"]
                if h.get("status") != "error"]
    cluster_check = validate_cluster_size(len(ok_hosts))
    cluster_report["cluster_validation"] = [cluster_check]
    status_icon = {"PASS": "OK", "FAIL": "FAIL", "WARN": "WARN"}
    print(f"\n  [{status_icon.get(cluster_check['status'], '?'):4s}] "
          f"{cluster_check['check']:40s} {cluster_check['actual']}")

    # Print summaries
    for i, host_report in enumerate(cluster_report["hosts"]):
        if host_report.get("status") == "error":
            print(f"\n>>> Host {i + 1}: {host_report['esxi_ip']} -- ERROR")
            continue
        tag = host_report["host_identity"]["service_tag"]
        print(f"\n>>> Host {i + 1}: {host_report['esxi_ip']} [{tag}]")
        print_validation_summary(host_report["validation"])

    if net_results:
        print_network_summary(net_results)

    if iperf_results and iperf_results.get("status") == "ok":
        print_iperf_summary(iperf_results)

    print_quick_summary_table(cluster_report, net_results, iperf_results)

    # Return non-zero if any host had a FAIL
    for host_report in cluster_report["hosts"]:
        for c in host_report.get("validation", []):
            if c["status"] == "FAIL":
                return 1
    return 0
