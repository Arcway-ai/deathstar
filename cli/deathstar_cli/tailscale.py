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


def push_image_via_tailscale(hostname: str, ssh_user: str, image_tag: str) -> None:
    """Push a Docker image to a remote host via Tailscale SSH.

    Runs: docker save <tag> | gzip | ssh <host> docker load
    """
    ensure_ssh_binary()
    target = resolve_peer_target(hostname)
    ssh_dest = f"{ssh_user}@{target}"

    # Pipeline: docker save → gzip → ssh docker load
    save_proc = subprocess.Popen(
        ["docker", "save", image_tag],
        stdout=subprocess.PIPE,
    )
    gzip_proc = subprocess.Popen(
        ["gzip", "-1"],
        stdin=save_proc.stdout,
        stdout=subprocess.PIPE,
    )
    # Allow save_proc to receive SIGPIPE if gzip exits
    if save_proc.stdout:
        save_proc.stdout.close()

    load_proc = subprocess.Popen(
        ["ssh", "-o", "StrictHostKeyChecking=accept-new", ssh_dest, "docker load"],
        stdin=gzip_proc.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if gzip_proc.stdout:
        gzip_proc.stdout.close()

    stdout, stderr = load_proc.communicate()

    # Check all processes
    save_rc = save_proc.wait()
    gzip_rc = gzip_proc.wait()
    load_rc = load_proc.returncode

    if save_rc != 0:
        raise RuntimeError(f"docker save failed (exit {save_rc})")
    if gzip_rc != 0:
        raise RuntimeError(f"gzip failed (exit {gzip_rc})")
    if load_rc != 0:
        raise RuntimeError(f"docker load failed: {stderr.strip()[:300]}")


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
