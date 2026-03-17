from __future__ import annotations

import json
import shutil
import subprocess


def ensure_ssh_binary() -> None:
    if shutil.which("ssh"):
        return
    raise RuntimeError("OpenSSH client is required for Tailscale SSH connect")


def resolve_peer_target(hostname: str) -> str:
    if shutil.which("tailscale"):
        status = _tailscale_status()
        if status:
            target = _find_peer_ip(status, hostname)
            if target:
                return target
    return hostname


def connect_via_tailscale(hostname: str, ssh_user: str) -> None:
    ensure_ssh_binary()
    target = resolve_peer_target(hostname)
    subprocess.run(["ssh", f"{ssh_user}@{target}"], check=True)


def run_via_tailscale(hostname: str, ssh_user: str, command: str) -> str:
    ensure_ssh_binary()
    target = resolve_peer_target(hostname)
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=accept-new", f"{ssh_user}@{target}", command],
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or exc.stdout or "").strip()
        raise RuntimeError(stderr[:500] if stderr else "remote command failed") from exc
    return result.stdout


def _tailscale_status() -> dict | None:
    try:
        completed = subprocess.run(
            ["tailscale", "status", "--json"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None


def _find_peer_ip(status: dict, expected_hostname: str) -> str | None:
    peers = status.get("Peer", {})
    if isinstance(peers, dict):
        peer_values = peers.values()
    elif isinstance(peers, list):
        peer_values = peers
    else:
        return None

    for peer in peer_values:
        if not isinstance(peer, dict):
            continue
        if not _matches_expected_hostname(peer, expected_hostname):
            continue

        addresses = peer.get("TailscaleIPs") or peer.get("Addresses") or []
        for address in addresses:
            if isinstance(address, str) and ":" not in address:
                return address
        for address in addresses:
            if isinstance(address, str):
                return address
    return None


def _matches_expected_hostname(peer: dict, expected_hostname: str) -> bool:
    expected = expected_hostname.strip().lower()
    if not expected:
        return False

    candidates: set[str] = set()
    for key in ("HostName", "DNSName", "Name"):
        value = peer.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = value.strip().lower().rstrip(".")
        candidates.add(normalized)
        candidates.add(normalized.split(".")[0])

    return expected in candidates or expected.split(".")[0] in candidates
