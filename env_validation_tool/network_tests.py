"""Network performance tests: ping, TCP throughput, HTTPS response, iperf3.

These tests are hypervisor-agnostic — they run from the tool host to
target VMs via standard protocols (ICMP, TCP, SSH).
"""

import json
import os
import re
import socket
import ssl
import statistics
import subprocess
import time
import urllib.request


# ── Defaults (overridable via CLI) ──
IPERF_PORT = 5201
IPERF_DURATION = 10
IPERF_PARALLEL = 4
UDP_TARGET_BW = "10G"


# ══════════════════════════════════════════════════════════════════════
#  SSH Helpers
# ══════════════════════════════════════════════════════════════════════

def _build_ssh_opts(ssh_key, ssh_user):
    """Build SSH command options list."""
    return [
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-o", "PubkeyAuthentication=yes",
        "-o", "PasswordAuthentication=no",
        "-i", ssh_key,
    ]


def ssh_cmd(ip, command, ssh_key, ssh_user="ubuntu", timeout=30):
    """Run a command on a remote host via SSH."""
    opts = _build_ssh_opts(ssh_key, ssh_user)
    full_cmd = ["ssh"] + opts + [f"{ssh_user}@{ip}", command]
    try:
        result = subprocess.run(
            full_cmd, capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "SSH timeout", -1


# ══════════════════════════════════════════════════════════════════════
#  Phase 2: Lightweight Network Tests
# ══════════════════════════════════════════════════════════════════════

def run_ping_test(target_ip, count=20):
    """Run ICMP ping test and return latency stats + packet loss."""
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-i", "0.2", target_ip],
            capture_output=True, text=True, timeout=30,
        )
        output = result.stdout

        loss_match = re.search(r"(\d+)% packet loss", output)
        loss_pct = float(loss_match.group(1)) if loss_match else None

        rtt_match = re.search(
            r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)",
            output,
        )
        if rtt_match:
            return {
                "target": target_ip,
                "packets_sent": count,
                "packet_loss_pct": loss_pct,
                "rtt_min_ms": float(rtt_match.group(1)),
                "rtt_avg_ms": float(rtt_match.group(2)),
                "rtt_max_ms": float(rtt_match.group(3)),
                "rtt_mdev_ms": float(rtt_match.group(4)),
                "status": "ok",
            }
        return {
            "target": target_ip, "packet_loss_pct": loss_pct,
            "status": "no_rtt_data",
        }
    except subprocess.TimeoutExpired:
        return {"target": target_ip, "status": "timeout"}
    except Exception as e:
        return {"target": target_ip, "status": "error", "error": str(e)}


def run_tcp_throughput_test(target_ip, port=443, duration_sec=5,
                            block_size=65536):
    """Measure TCP throughput by sending data over a raw socket."""
    data = b"\x00" * block_size
    total_bytes = 0
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((target_ip, port))
        start = time.monotonic()
        deadline = start + duration_sec
        errors = 0
        while time.monotonic() < deadline:
            try:
                sent = sock.send(data)
                total_bytes += sent
            except (BrokenPipeError, ConnectionResetError):
                errors += 1
                break
            except socket.timeout:
                errors += 1
                break
        elapsed = time.monotonic() - start
        sock.close()
        throughput_mbps = (
            (total_bytes * 8) / (elapsed * 1_000_000) if elapsed > 0 else 0
        )
        return {
            "target": target_ip,
            "port": port,
            "duration_sec": round(elapsed, 2),
            "bytes_sent": total_bytes,
            "throughput_mbps": round(throughput_mbps, 2),
            "errors": errors,
            "status": "ok",
        }
    except Exception as e:
        return {
            "target": target_ip, "port": port,
            "status": "error", "error": str(e),
        }


def run_https_response_test(target_ip, path="/", num_requests=5):
    """Measure HTTPS response time to the Edge node API endpoint."""
    url = f"https://{target_ip}{path}"
    ctx = ssl._create_unverified_context()
    times_ms = []
    errors = 0

    for _ in range(num_requests):
        try:
            start = time.monotonic()
            req = urllib.request.Request(url, method="GET")
            urllib.request.urlopen(req, timeout=10, context=ctx)
            elapsed = (time.monotonic() - start) * 1000
            times_ms.append(elapsed)
        except urllib.error.HTTPError:
            elapsed = (time.monotonic() - start) * 1000
            times_ms.append(elapsed)
        except Exception:
            errors += 1

    if times_ms:
        return {
            "target": target_ip,
            "url": url,
            "requests": num_requests,
            "successful": len(times_ms),
            "errors": errors,
            "response_min_ms": round(min(times_ms), 2),
            "response_avg_ms": round(statistics.mean(times_ms), 2),
            "response_max_ms": round(max(times_ms), 2),
            "response_stdev_ms": (
                round(statistics.stdev(times_ms), 2)
                if len(times_ms) > 1
                else 0
            ),
            "status": "ok",
        }
    return {
        "target": target_ip, "url": url,
        "requests": num_requests, "errors": errors,
        "status": "all_failed",
    }


def run_network_perf_suite(vm_name, vm_ip, server_tag=""):
    """Run Phase 2 network performance suite against one edge node."""
    print(f"  [net] Testing {vm_name} ({vm_ip})...")
    return {
        "node_name": vm_name,
        "node_ip": vm_ip,
        "server_tag": server_tag,
        "ping": run_ping_test(vm_ip, count=20),
        "tcp_throughput": run_tcp_throughput_test(vm_ip, port=443,
                                                  duration_sec=5),
        "https_response": run_https_response_test(vm_ip, num_requests=5),
    }


# ══════════════════════════════════════════════════════════════════════
#  Phase 3: iperf3 Bandwidth Tests
# ══════════════════════════════════════════════════════════════════════

def get_dev_vm_ip(target_ip):
    """Get the source IP used to reach a target IP."""
    result = subprocess.run(
        ["ip", "route", "get", target_ip],
        capture_output=True, text=True, timeout=5,
    )
    m = re.search(r"src (\d+\.\d+\.\d+\.\d+)", result.stdout)
    return m.group(1) if m else None


def start_local_iperf_server(port=IPERF_PORT):
    """Start iperf3 server locally. Returns Popen handle."""
    subprocess.run(["pkill", "-f", f"iperf3 -s -p {port}"],
                   capture_output=True)
    time.sleep(0.3)
    proc = subprocess.Popen(
        ["iperf3", "-s", "-p", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    return proc


def stop_local_iperf_server(proc):
    """Stop local iperf3 server."""
    if proc:
        proc.terminate()
        proc.wait(timeout=5)


def start_remote_iperf_server(ip, ssh_key, ssh_user="ubuntu",
                              port=IPERF_PORT):
    """Start iperf3 server on a remote edge node."""
    ssh_cmd(ip, f"pkill -f 'iperf3 -s -p {port}' 2>/dev/null; sleep 0.3",
            ssh_key, ssh_user, timeout=10)
    stdout, stderr, rc = ssh_cmd(
        ip,
        f"nohup iperf3 -s -p {port} > /dev/null 2>&1 & sleep 1 && echo started",
        ssh_key, ssh_user, timeout=15,
    )
    if "started" not in stdout:
        print(f"    [warn] iperf3 server on {ip}: {stderr}")


def stop_remote_iperf_server(ip, ssh_key, ssh_user="ubuntu",
                             port=IPERF_PORT):
    """Stop iperf3 server on a remote edge node."""
    ssh_cmd(ip, f"pkill -f 'iperf3 -s -p {port}' 2>/dev/null",
            ssh_key, ssh_user)


def parse_iperf_json(stdout, direction="upload", parallel=IPERF_PARALLEL):
    """Parse iperf3 JSON output and return summary dict."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return {"status": "error", "error": "Failed to parse iperf3 JSON"}

    end = data.get("end", {})

    if "sum_sent" in end:
        if direction == "download":
            summary = end.get("sum_received", end.get("sum_sent", {}))
        else:
            summary = end.get("sum_sent", {})
        return {
            "status": "ok",
            "direction": direction,
            "duration_sec": round(summary.get("seconds", 0), 2),
            "bytes": summary.get("bytes", 0),
            "bits_per_second": summary.get("bits_per_second", 0),
            "gbps": round(summary.get("bits_per_second", 0) / 1e9, 2),
            "retransmits": summary.get("retransmits", 0),
            "parallel_streams": parallel,
        }

    sum_key = "sum" if "sum" in end else None
    if sum_key is None and direction == "udp":
        sum_key = "sum_sent" if "sum_sent" in end else None
    if sum_key:
        summary = end[sum_key]
        return {
            "status": "ok",
            "protocol": "UDP",
            "target_bandwidth": UDP_TARGET_BW,
            "duration_sec": round(summary.get("seconds", 0), 2),
            "bytes": summary.get("bytes", 0),
            "bits_per_second": summary.get("bits_per_second", 0),
            "gbps": round(summary.get("bits_per_second", 0) / 1e9, 2),
            "jitter_ms": summary.get("jitter_ms", 0),
            "lost_packets": summary.get("lost_packets", 0),
            "total_packets": summary.get("packets", 0),
            "loss_pct": round(summary.get("lost_percent", 0), 3),
        }

    return {"status": "error", "error": "Unexpected iperf3 JSON structure"}


def run_devvm_node_tcp(node_ip, dev_ip, ssh_key, ssh_user="ubuntu",
                       port=IPERF_PORT, duration=IPERF_DURATION,
                       parallel=IPERF_PARALLEL, reverse=False):
    """TCP iperf3 test: client on edge node, server on local host."""
    rev_flag = "-R" if reverse else ""
    iperf_cmd = (
        f"iperf3 -c {dev_ip} -p {port} -t {duration} "
        f"-P {parallel} -J {rev_flag}"
    )
    stdout, stderr, rc = ssh_cmd(node_ip, iperf_cmd, ssh_key, ssh_user,
                                 timeout=duration + 30)
    if rc != 0:
        return {"status": "error", "error": stderr or "non-zero exit"}
    direction = "download" if reverse else "upload"
    return parse_iperf_json(stdout, direction, parallel)


def run_devvm_node_udp(node_ip, dev_ip, ssh_key, ssh_user="ubuntu",
                       port=IPERF_PORT, duration=IPERF_DURATION):
    """UDP iperf3 test: client on edge node, server on local host."""
    iperf_cmd = (
        f"iperf3 -c {dev_ip} -p {port} -u -b {UDP_TARGET_BW} "
        f"-t {duration} -J"
    )
    stdout, stderr, rc = ssh_cmd(node_ip, iperf_cmd, ssh_key, ssh_user,
                                 timeout=duration + 30)
    if rc != 0:
        return {"status": "error", "error": stderr or "non-zero exit"}
    return parse_iperf_json(stdout, direction="udp")


def open_firewall_port(ip, ssh_key, ssh_user="ubuntu", port=IPERF_PORT):
    """Temporarily open a port in iptables on a remote node."""
    ssh_cmd(ip,
            f"sudo iptables -I INPUT 1 -p tcp --dport {port} -j ACCEPT",
            ssh_key, ssh_user, timeout=10)


def close_firewall_port(ip, ssh_key, ssh_user="ubuntu", port=IPERF_PORT):
    """Remove the temporary iptables rule on a remote node."""
    ssh_cmd(ip,
            f"sudo iptables -D INPUT -p tcp --dport {port} -j ACCEPT",
            ssh_key, ssh_user, timeout=10)


def run_node_to_node_test(src_ip, dst_ip, ssh_key, ssh_user="ubuntu",
                          duration=5, port=IPERF_PORT,
                          parallel=IPERF_PARALLEL):
    """iperf3 between two edge nodes with temporary firewall opening."""
    open_firewall_port(dst_ip, ssh_key, ssh_user, port)
    start_remote_iperf_server(dst_ip, ssh_key, ssh_user, port)

    iperf_cmd = (
        f"iperf3 -c {dst_ip} -p {port} -t {duration} "
        f"-P {parallel} -J"
    )
    stdout, stderr, rc = ssh_cmd(src_ip, iperf_cmd, ssh_key, ssh_user,
                                 timeout=duration + 30)

    stop_remote_iperf_server(dst_ip, ssh_key, ssh_user, port)
    close_firewall_port(dst_ip, ssh_key, ssh_user, port)

    if rc != 0:
        err_detail = stderr or stdout or "non-zero exit"
        return {
            "status": "error", "src": src_ip, "dst": dst_ip,
            "error": err_detail[:500],
        }
    result = parse_iperf_json(stdout, direction="upload", parallel=parallel)
    result["src"] = src_ip
    result["dst"] = dst_ip
    return result


def run_iperf_suite(vm_ips, ssh_key, ssh_user="ubuntu",
                    duration=IPERF_DURATION, parallel=IPERF_PARALLEL,
                    port=IPERF_PORT):
    """Run full iperf3 bandwidth suite: host↔nodes + node-to-node.

    Args:
        vm_ips: list of dicts with 'vm_name' and 'vm_ip'.
        ssh_key: path to SSH private key.
        ssh_user: SSH username.
        duration: iperf3 test duration in seconds.
        parallel: iperf3 parallel streams.
        port: iperf3 port.

    Returns:
        dict with 'devvm_node' and 'node_to_node' results.
    """
    if not vm_ips:
        return {"devvm_node": [], "node_to_node": [], "status": "no_nodes"}

    dev_ip = get_dev_vm_ip(vm_ips[0]["vm_ip"])
    if not dev_ip:
        return {"devvm_node": [], "node_to_node": [],
                "status": "error",
                "error": "Could not determine source IP"}

    print(f"\n  [iperf] Source IP: {dev_ip}")
    print(f"  [iperf] Params: duration={duration}s, "
          f"streams={parallel}, UDP target={UDP_TARGET_BW}")

    server_proc = start_local_iperf_server(port)

    devvm_results = []
    for node in vm_ips:
        ip = node["vm_ip"]
        name = node["vm_name"]
        entry = {"node_name": name, "node_ip": ip}

        print(f"  [iperf] {name} ({ip}) -- TCP upload...")
        entry["tcp_upload"] = run_devvm_node_tcp(
            ip, dev_ip, ssh_key, ssh_user, port, duration, parallel,
            reverse=False,
        )
        time.sleep(1)

        print(f"  [iperf] {name} ({ip}) -- TCP download...")
        entry["tcp_download"] = run_devvm_node_tcp(
            ip, dev_ip, ssh_key, ssh_user, port, duration, parallel,
            reverse=True,
        )
        time.sleep(1)

        print(f"  [iperf] {name} ({ip}) -- UDP...")
        entry["udp"] = run_devvm_node_udp(
            ip, dev_ip, ssh_key, ssh_user, port, duration,
        )
        time.sleep(1)

        devvm_results.append(entry)

    stop_local_iperf_server(server_proc)

    n2n_results = []
    if len(vm_ips) > 1:
        src = vm_ips[0]
        for dst in vm_ips[1:]:
            print(f"  [iperf] Node-to-Node: {src['vm_ip']} -> {dst['vm_ip']}...")
            n2n = run_node_to_node_test(
                src["vm_ip"], dst["vm_ip"], ssh_key, ssh_user,
                duration=5, port=port, parallel=parallel,
            )
            n2n_results.append(n2n)

    return {"devvm_node": devvm_results, "node_to_node": n2n_results,
            "dev_vm_ip": dev_ip, "status": "ok"}
