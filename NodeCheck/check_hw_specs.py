#!/usr/bin/env python3
"""
Hardware specs gatherer for remote Linux hosts (e.g. Raspberry Pi).

SSHes into a host and collects model, SoC, CPU, memory, storage, network,
OS, firmware, and temperature specs, then prints a pretty two-column table.

Prompts for a sudo password only if the remote sudo requires one
(tries passwordless first, falls back to password).

Usage:
    uv run NodeCheck/check_hw_specs.py --ip 192.168.1.200
    uv run NodeCheck/check_hw_specs.py --ip 192.168.1.200 --user abutala
"""

import argparse
import getpass
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
from typing import List, Tuple

SSH_TIMEOUT = 60

# Unit separator (0x1f) delimits key/value; safe vs values containing tabs/=.
KV_SEP = "\x1f"

# Gathered remotely. Emits one `KEY␟VALUE` line per field (single-line values).
# Uses `sudo -n` to test passwordless sudo; if that fails, reads one password
# line from stdin and caches sudo creds via `sudo -S -v`.
# bash's stdin is ssh's stdin, so the password is piped from the local process.
REMOTE_SCRIPT = r"""
set -u
emit() { printf '%s\x1f%s\n' "$1" "$2"; }

if command -v sudo >/dev/null 2>&1; then
    if sudo -n true 2>/dev/null; then
        : # passwordless sudo available
    else
        read -r PW
        if ! printf '%s\n' "$PW" | sudo -S -v 2>/dev/null; then
            echo "SUDO_AUTH_FAILED"
            exit 1
        fi
        unset PW
    fi
fi

emit "Model" "$(cat /proc/device-tree/model 2>/dev/null || echo n/a)"
emit "SoC" "$(tr '\0' ' ' </proc/device-tree/compatible 2>/dev/null | xargs || echo n/a)"

CPU_MODEL=$(lscpu 2>/dev/null | awk -F: '/Model name/ {gsub(/^ +/,"",$2); print $2; exit}')
[ -z "$CPU_MODEL" ] && CPU_MODEL=$(awk -F: '/model name/ {gsub(/^ +/,"",$2); print $2; exit}' /proc/cpuinfo 2>/dev/null)
emit "CPU" "${CPU_MODEL:-n/a}"
emit "Cores" "$(lscpu 2>/dev/null | awk -F: '/^CPU\(s\):/ {gsub(/^ +/,"",$2); print $2; exit}')"
emit "Max clock" "$(lscpu 2>/dev/null | awk -F: '/CPU max MHz/ {gsub(/^ +/,"",$2); printf "%.0f MHz",$2; exit}')"
emit "L2 cache" "$(lscpu 2>/dev/null | awk -F: '/L2 cache/ {gsub(/^ +/,"",$2); print $2; exit}')"

emit "Memory" "$(free -h 2>/dev/null | awk '/^Mem:/ {print $2}') / Swap $(free -h 2>/dev/null | awk '/^Swap:/ {print $2}')"

ROOT_FS=$(df -h / 2>/dev/null | awk 'NR==2 {print $2" total, "$3" used ("$5")"}')
DISK=$(lsblk -do NAME,SIZE,MODEL 2>/dev/null | awk 'NR>1 && $1 ~ /mmcblk|nvme|sd|vd/ {print $1": "$2" "$3; exit}')
emit "Storage" "${ROOT_FS:-n/a} | ${DISK:-n/a}"

IFACE=$(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | grep -v '^lo$' | head -1)
emit "Ethernet" "$IFACE"
if [ -n "$IFACE" ]; then
    LINK=$(sudo ethtool "$IFACE" 2>/dev/null | awk -F: '/Speed|Duplex|Link detected/ {gsub(/^ +/,"",$2); printf "%s; ",$2}')
    emit "Link" "${LINK%; }"
else
    emit "Link" "n/a"
fi

emit "PCI" "$(lspci 2>/dev/null | grep -iE 'net|usb|bridge' | sed 's/^[0-9:.]* [^:]*: //; s/ (rev [0-9]*)//' | paste -sd ';' || echo n/a)"
emit "USB" "$(lsusb 2>/dev/null | sed 's/^Bus [0-9]* Device [0-9]*: ID [0-9a-f:]* //' | paste -sd ';' || echo n/a)"

OS_NAME=$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")
emit "OS" "${OS_NAME:-n/a}"
emit "Kernel" "$(uname -srm 2>/dev/null)"
emit "Firmware" "$(vcgencmd version 2>/dev/null | head -1 | sed 's/^ *//')"
TEMP=$(vcgencmd measure_temp 2>/dev/null | sed "s/temp=//; s/'C/ C/")
[ -z "$TEMP" ] && TEMP=$(awk '{printf "%.1f C",$1/1000}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
emit "Temperature" "${TEMP:-n/a}"
"""

SUDO_AUTH_FAILED_MARKER = "SUDO_AUTH_FAILED"


def run_remote(host: str, port: int, stdin_str: str) -> subprocess.CompletedProcess:
    """SSH into host, run REMOTE_SCRIPT via `bash -c`, feeding stdin_str to bash.

    `bash -c <quoted_script>` reads the script from its -c argument, leaving
    bash's stdin (== ssh's stdin) free for the sudo password.
    """
    remote_cmd = f"bash -c {shlex.quote(REMOTE_SCRIPT)}"
    return subprocess.run(
        ["ssh", "-p", str(port), host, remote_cmd],
        input=stdin_str,
        capture_output=True,
        text=True,
        timeout=SSH_TIMEOUT,
    )


def parse_pairs(output: str) -> List[Tuple[str, str]]:
    """Parse `KEY␟VALUE` lines into an ordered list of (key, value) pairs."""
    pairs: List[Tuple[str, str]] = []
    for line in output.splitlines():
        if KV_SEP in line:
            key, _, value = line.partition(KV_SEP)
            pairs.append((key, value))
    return pairs


def render_table(pairs: List[Tuple[str, str]]) -> str:
    """Render an ordered list of (key, value) pairs as a bordered table.

    Long values are word-wrapped to fit the terminal width.
    """
    term_width = shutil.get_terminal_size((80, 24)).columns
    key_w = max((len(k) for k, _ in pairs), default=4)
    # Reserve: 1 (left border) + key_w + 3 (" │ ") + 1 (right border) = key_w + 5
    val_w = max(20, min(80, term_width - key_w - 5))

    top = f"┌{'─' * key_w}┬{'─' * val_w}┐"
    head = f"│{'Field':<{key_w}}│{'Value':<{val_w}}│"
    sep = f"├{'─' * key_w}┼{'─' * val_w}┤"
    bottom = f"└{'─' * key_w}┴{'─' * val_w}┘"

    lines: List[str] = [top, head, sep]
    for key, value in pairs:
        wrapped = textwrap.wrap(value, width=val_w) or [""]
        for i, chunk in enumerate(wrapped):
            k = key if i == 0 else ""
            lines.append(f"│{k:<{key_w}}│{chunk:<{val_w}}│")
    lines.append(bottom)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gather hardware specs from a remote Linux host via SSH."
    )
    parser.add_argument("--ip", required=True, help="IP address or hostname of the remote host")
    parser.add_argument(
        "--user",
        default=os.getenv("USER", ""),
        help="SSH user (default: current local user)",
    )
    parser.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    args = parser.parse_args()

    host = f"{args.user}@{args.ip}" if args.user else args.ip

    # Adaptive fallback: try passwordless sudo first (empty stdin -> read gets EOF).
    result = run_remote(host, args.port, "")

    if result.returncode != 0 and SUDO_AUTH_FAILED_MARKER in result.stdout:
        try:
            pw = getpass.getpass(f"sudo password for {host}: ")
        except EOFError:
            print(
                "Error: no interactive terminal available to read the sudo password.\n"
                "Run this script from a terminal.",
                file=sys.stderr,
            )
            sys.exit(1)
        result = run_remote(host, args.port, pw + "\n")
        # Clear the password from memory promptly.
        del pw

    if SUDO_AUTH_FAILED_MARKER in result.stdout:
        print("Error: sudo authentication failed on the remote host.", file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        print(f"Error: SSH command failed (exit {result.returncode}).", file=sys.stderr)
        sys.exit(result.returncode)

    pairs = parse_pairs(result.stdout)
    if not pairs:
        print("Error: no specs parsed from remote output.", file=sys.stderr)
        sys.stderr.write(result.stdout)
        sys.exit(1)

    print(render_table(pairs))
    if result.stderr:
        sys.stderr.write(result.stderr)


if __name__ == "__main__":
    main()
