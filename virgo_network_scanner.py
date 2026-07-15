"""
virgo_network_scanner — local subnet device discovery.

Scans the /24 subnet for active hosts on common developer/service ports
using concurrent threads. Saves results to virgo_network_map.json.
"""

from __future__ import annotations

import socket
import struct
import threading
from concurrent.futures import ThreadPoolExecutor
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _console import icon
from _log import OUTDIR

NETWORK_MAP_FILE = str(OUTDIR / "virgo_network_map.json")


def get_local_ip() -> str:
    """Dynamically find the active local network IP of this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't actually connect, just routes to find primary interface
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def check_target(ip: str, port: int) -> bool:
    """Attempt a quick connection to a specific IP and port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    result = sock.connect_ex((ip, port))
    sock.close()
    return result == 0


def scan_host(ip: str, common_ports: list[int]) -> list[int]:
    """Scan a single host for a list of common developer/service ports."""
    found_ports = []
    for port in common_ports:
        if check_target(ip, port):
            found_ports.append(port)
    return found_ports


def run_subnet_scan() -> None:
    local_ip = get_local_ip()
    print(f"{icon('antenna')} Local Machine IP Detected: {local_ip}")

    if local_ip == "127.0.0.1":
        print(f"{icon('error')} Error: Not connected to an active local network. Aborting subnet scan.")
        return

    # Extract the subnet prefix (e.g., '192.168.1.')
    ip_parts = local_ip.split(".")
    subnet_prefix = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}."

    # Common ports to check on active local devices
    ports_to_check = [22, 80, 11434, 8000, 8080, 1883]

    print(f"{icon('search')} Scanning subnet {subnet_prefix}0/24 for active hosts on ports: {ports_to_check}...")
    print(f"{icon('bolt')} Utilizing ThreadPoolExecutor for rapid multi-threaded scanning...")

    active_devices: dict[str, list[int]] = {}

    # Scan IPs .1 through .254 concurrently using threads
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {
            executor.submit(scan_host, f"{subnet_prefix}{i}", ports_to_check): f"{subnet_prefix}{i}"
            for i in range(1, 255)
        }

        for future in futures:
            ip = futures[future]
            try:
                open_ports = future.result()
                if open_ports:
                    active_devices[ip] = open_ports
                    print(f"{icon('sparkle')} Found Active Host: {ip} -> Open Ports: {open_ports}")
            except Exception as exc:
                print(f"{icon('warn')} Scan error for {ip}: {exc}")

    # Save results to a clean log
    import json

    output_file = NETWORK_MAP_FILE
    with open(output_file, "w") as f:
        json.dump({"subnet_scan_results": active_devices}, f, indent=4)

    print(f"\n{icon('done')} Subnet mapping complete!")
    print(f"Saved live network landscape to: {output_file}")


if __name__ == "__main__":
    run_subnet_scan()
