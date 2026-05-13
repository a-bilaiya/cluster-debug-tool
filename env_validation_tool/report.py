"""Report generation — human-readable output formatting.

All functions print to stdout. The JSON report is produced by the caller
(cli.py) using json.dumps on the cluster report dict.
"""


def print_validation_summary(checks):
    """Pretty-print per-host validation results."""
    print("\n" + "=" * 70)
    print("  HOST HARDWARE VALIDATION RESULTS")
    print("=" * 70)

    fail_count = 0
    warn_count = 0
    for c in checks:
        icon = {"PASS": "[OK]", "FAIL": "[FAIL]", "WARN": "[WARN]"}.get(
            c["status"], "[??]"
        )
        print(f"  {icon:6s} {c['check']:<42s} {c['actual']}")
        if c["status"] == "FAIL":
            fail_count += 1
        elif c["status"] == "WARN":
            warn_count += 1

    print("-" * 70)
    if fail_count == 0 and warn_count == 0:
        print("  RESULT: ALL CHECKS PASSED")
    elif fail_count == 0:
        print(f"  RESULT: PASSED with {warn_count} warning(s)")
    else:
        print(f"  RESULT: {fail_count} FAILED, {warn_count} warning(s)")
    print("=" * 70 + "\n")


def print_network_summary(net_results):
    """Pretty-print Phase 2 network performance results."""
    print("\n" + "=" * 70)
    print("  CLUSTER - NETWORK PERFORMANCE RESULTS")
    print("=" * 70)

    for nr in net_results:
        ping = nr["ping"]
        tcp = nr["tcp_throughput"]
        https = nr["https_response"]

        print(f"\n  Node: {nr['node_name']} ({nr['node_ip']}) "
              f"[{nr['server_tag']}]")
        print(f"  {'─' * 60}")

        if ping.get("status") == "ok":
            loss_icon = "[OK]" if ping["packet_loss_pct"] == 0 else "[WARN]"
            print(f"    {loss_icon:6s} Ping Latency      "
                  f"avg={ping['rtt_avg_ms']:.2f}ms  "
                  f"min={ping['rtt_min_ms']:.2f}ms  "
                  f"max={ping['rtt_max_ms']:.2f}ms  "
                  f"jitter={ping['rtt_mdev_ms']:.2f}ms")
            print(f"    {loss_icon:6s} Packet Loss       "
                  f"{ping['packet_loss_pct']}%")
        else:
            print(f"    [FAIL] Ping: {ping.get('status')}")

        if tcp.get("status") == "ok":
            tp = tcp["throughput_mbps"]
            icon = "[OK]" if tp > 100 else "[WARN]"
            print(f"    {icon:6s} TCP Throughput     "
                  f"{tp:.1f} Mbps  "
                  f"({tcp['bytes_sent'] / (1024*1024):.1f} MB "
                  f"in {tcp['duration_sec']}s)")
        else:
            print(f"    [FAIL] TCP Throughput: "
                  f"{tcp.get('error', tcp.get('status'))}")

        if https.get("status") == "ok":
            print(f"    [OK]   HTTPS Response      "
                  f"avg={https['response_avg_ms']:.1f}ms  "
                  f"min={https['response_min_ms']:.1f}ms  "
                  f"max={https['response_max_ms']:.1f}ms  "
                  f"({https['successful']}/{https['requests']} ok)")
        else:
            print(f"    [FAIL] HTTPS Response: {https.get('status')}")

    print("\n" + "=" * 70)


def print_iperf_summary(iperf_results):
    """Pretty-print Phase 3 iperf3 bandwidth results."""
    print("\n" + "=" * 78)
    print("  CLUSTER -- iperf3 BANDWIDTH TEST RESULTS")
    print("=" * 78)

    for r in iperf_results.get("devvm_node", []):
        print(f"\n  {r['node_name']} ({r['node_ip']})")
        print(f"  {'─' * 70}")

        tcp_up = r.get("tcp_upload", {})
        if tcp_up.get("status") == "ok":
            icon = "[OK]" if tcp_up["gbps"] >= 1.0 else "[WARN]"
            retrans = (f"  retransmits={tcp_up['retransmits']}"
                       if tcp_up.get("retransmits") else "")
            print(f"    {icon:6s} TCP Upload (Node->Host)  "
                  f"{tcp_up['gbps']:.2f} Gbps  "
                  f"({tcp_up['parallel_streams']}P, "
                  f"{tcp_up['duration_sec']}s){retrans}")
        else:
            print(f"    [FAIL] TCP Upload: "
                  f"{tcp_up.get('error', 'unknown')}")

        tcp_dn = r.get("tcp_download", {})
        if tcp_dn.get("status") == "ok":
            icon = "[OK]" if tcp_dn["gbps"] >= 1.0 else "[WARN]"
            retrans = (f"  retransmits={tcp_dn['retransmits']}"
                       if tcp_dn.get("retransmits") else "")
            print(f"    {icon:6s} TCP Download (Host->Node) "
                  f"{tcp_dn['gbps']:.2f} Gbps  "
                  f"({tcp_dn['parallel_streams']}P, "
                  f"{tcp_dn['duration_sec']}s){retrans}")
        else:
            print(f"    [FAIL] TCP Download: "
                  f"{tcp_dn.get('error', 'unknown')}")

        udp = r.get("udp", {})
        if udp.get("status") == "ok":
            if "loss_pct" in udp:
                loss_icon = "[OK]" if udp["loss_pct"] < 1.0 else "[WARN]"
                print(f"    {loss_icon:6s} UDP Throughput           "
                      f"{udp['gbps']:.2f} Gbps  "
                      f"jitter={udp.get('jitter_ms', 0):.3f}ms  "
                      f"loss={udp['loss_pct']:.2f}%")
            else:
                icon = "[OK]" if udp["gbps"] >= 1.0 else "[WARN]"
                print(f"    {icon:6s} UDP Throughput           "
                      f"{udp['gbps']:.2f} Gbps")
        else:
            print(f"    [FAIL] UDP: {udp.get('error', 'unknown')}")

    n2n = iperf_results.get("node_to_node", [])
    if n2n:
        print(f"\n  {'─' * 70}")
        print("  Node-to-Node Bandwidth (inter-cluster)")
        print(f"  {'─' * 70}")
        for t in n2n:
            if t.get("status") == "ok":
                icon = "[OK]" if t["gbps"] >= 1.0 else "[WARN]"
                print(f"    {icon:6s} {t['src']:15s} -> {t['dst']:15s}  "
                      f"{t['gbps']:.2f} Gbps  "
                      f"retrans={t.get('retransmits', 0)}")
            else:
                print(f"    [FAIL] {t.get('src','?')} -> {t.get('dst','?')}: "
                      f"{t.get('error')}")

    print("\n" + "=" * 78)


def print_quick_summary_table(cluster_report, net_results=None,
                              iperf_results=None):
    """Print the cluster quick summary table."""
    print("\n" + "=" * 120)
    print("  CLUSTER QUALIFICATION -- QUICK SUMMARY")
    print("=" * 120)
    cluster_name = cluster_report.get("cluster", "?")
    vcenter = cluster_report.get("vcenter", "?")
    ts = cluster_report.get("collection_time", "?")
    print(f"  Cluster: {cluster_name}    vCenter: {vcenter}    Time: {ts}")
    print("-" * 120)

    print(f"  {'ESXi IP':<16s} {'Tag':<10s} {'Model':<22s} "
          f"{'CPU':<12s} {'RAM':<8s} {'Disks':<8s} "
          f"{'AES':<5s} {'SSE4.2':<7s} {'AVX2':<5s} "
          f"{'VM IP':<16s} {'Ping':<8s} {'iperf TCP↑':<11s} "
          f"{'iperf TCP↓':<11s} {'Result'}")
    print("-" * 120)

    if net_results is None:
        net_results = []
    if iperf_results is None:
        iperf_results = {}

    for host_report in cluster_report.get("hosts", []):
        if host_report.get("status") == "error":
            print(f"  {host_report['esxi_ip']:<16s} {'—':10s} {'ERROR'}")
            continue

        ident = host_report["host_identity"]
        cpu = host_report["cpu_details"]
        feat = host_report.get("cpu_features", {})
        mem = host_report["memory_gb"]
        data_disks = [
            d for d in host_report["storage"] if d.get("role") == "data"
        ]
        esxi_ip = host_report.get("esxi_ip", "?")

        checks = host_report.get("validation", [])
        fails = sum(1 for c in checks if c["status"] == "FAIL")
        warns = sum(1 for c in checks if c["status"] == "WARN")
        if fails:
            result = f"FAIL({fails})"
        elif warns:
            result = f"PASS({warns}w)"
        else:
            result = "PASS"

        aes = "Y" if feat.get("aes") else "N"
        sse42 = "Y" if feat.get("sse4_2") else "N"
        avx2 = "Y" if feat.get("avx2") else "N"

        vms = host_report.get("vms", [])
        vm_ip = vms[0]["vm_ip"] if vms and vms[0].get("vm_ip") else "—"

        ping_str = "—"
        tcp_up_str = "—"
        tcp_dn_str = "—"
        for nr in net_results:
            if nr["node_ip"] == vm_ip:
                p = nr.get("ping", {})
                if p.get("status") == "ok":
                    ping_str = f"{p['rtt_avg_ms']:.1f}ms"
                break

        if iperf_results.get("status") == "ok":
            for ir in iperf_results.get("devvm_node", []):
                if ir["node_ip"] == vm_ip:
                    tu = ir.get("tcp_upload", {})
                    td = ir.get("tcp_download", {})
                    if tu.get("status") == "ok":
                        tcp_up_str = f"{tu['gbps']:.1f} Gbps"
                    if td.get("status") == "ok":
                        tcp_dn_str = f"{td['gbps']:.1f} Gbps"
                    break

        cpu_str = f"{cpu['threads']}T@{cpu['clock_ghz']}G"
        mem_str = f"{int(mem)}GB"
        if data_disks:
            types = set(d.get("disk_type", "?") for d in data_disks)
            dtype = (
                types.pop().replace(" SSD", "") if len(types) == 1 else "mixed"
            )
        else:
            dtype = "none"
        disk_str = f"{len(data_disks)}x{dtype}"

        print(f"  {esxi_ip:<16s} {ident['service_tag']:<10s} "
              f"{ident['model']:<22s} "
              f"{cpu_str:<12s} {mem_str:<8s} {disk_str:<8s} "
              f"{aes:<5s} {sse42:<7s} {avx2:<5s} "
              f"{vm_ip:<16s} {ping_str:<8s} {tcp_up_str:<11s} "
              f"{tcp_dn_str:<11s} {result}")

    if iperf_results.get("node_to_node"):
        print("-" * 120)
        print("  Node-to-Node:")
        for t in iperf_results["node_to_node"]:
            if t.get("status") == "ok":
                print(f"    {t['src']} -> {t['dst']}  {t['gbps']:.1f} Gbps")
            else:
                print(f"    {t.get('src','?')} -> {t.get('dst','?')}  FAIL")

    print("=" * 120)
