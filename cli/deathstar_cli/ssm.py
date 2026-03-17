from __future__ import annotations

import contextlib
import os
import shutil
import socket
import subprocess
import time

from deathstar_cli.config import CLIConfig


def _ensure_session_manager_prereqs() -> None:
    if not shutil.which("aws"):
        raise RuntimeError("AWS CLI v2 is required")
    if not shutil.which("session-manager-plugin"):
        raise RuntimeError("AWS Session Manager plugin is required")


def _aws_env(config: CLIConfig, region: str) -> dict[str, str]:
    env = os.environ.copy()
    env["AWS_REGION"] = region
    env["AWS_DEFAULT_REGION"] = region
    if config.aws_profile:
        env["AWS_PROFILE"] = config.aws_profile
    return env


def _aws_base_command(config: CLIConfig, region: str) -> list[str]:
    command = ["aws", "ssm"]
    if config.aws_profile:
        command.extend(["--profile", config.aws_profile])
    command.extend(["--region", region])
    return command


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_port(port: int, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError(f"timed out waiting for local port {port}")


def run_via_ssm(config: CLIConfig, region: str, instance_id: str, command: str) -> str:
    import boto3

    session_kwargs: dict[str, str] = {"region_name": region}
    if config.aws_profile:
        session_kwargs["profile_name"] = config.aws_profile

    session = boto3.Session(**session_kwargs)
    ssm = session.client("ssm")

    response = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command]},
        TimeoutSeconds=30,
    )
    command_id = response["Command"]["CommandId"]

    for _ in range(60):
        time.sleep(1)
        try:
            invocation = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id,
            )
        except ssm.exceptions.InvocationDoesNotExist:
            continue

        if invocation["Status"] in ("Success", "Failed", "Cancelled", "TimedOut"):
            if invocation["Status"] != "Success":
                stderr = invocation.get("StandardErrorContent", "")
                raise RuntimeError(f"remote command failed: {stderr[:200] if stderr else 'unknown error'}")
            return invocation["StandardOutputContent"]

    raise RuntimeError("remote command timed out waiting for response")


def start_shell_session(config: CLIConfig, region: str, instance_id: str) -> None:
    _ensure_session_manager_prereqs()

    command = [
        *_aws_base_command(config, region),
        "start-session",
        "--target",
        instance_id,
    ]

    subprocess.run(command, env=_aws_env(config, region), check=True)


class SSMPortForward:
    def __init__(
        self,
        config: CLIConfig,
        region: str,
        instance_id: str,
        remote_port: int = 8080,
        remote_host: str = "127.0.0.1",
    ) -> None:
        self.config = config
        self.region = region
        self.instance_id = instance_id
        self.remote_port = remote_port
        self.remote_host = remote_host
        self.local_port = find_free_port()
        self.process: subprocess.Popen[str] | None = None

    def __enter__(self) -> "SSMPortForward":
        _ensure_session_manager_prereqs()

        parameters = (
            f'host=["{self.remote_host}"],'
            f'portNumber=["{self.remote_port}"],'
            f'localPortNumber=["{self.local_port}"]'
        )

        command = [
            *_aws_base_command(self.config, self.region),
            "start-session",
            "--target",
            self.instance_id,
            "--document-name",
            "AWS-StartPortForwardingSessionToRemoteHost",
            "--parameters",
            parameters,
        ]

        self.process = subprocess.Popen(
            command,
            env=_aws_env(self.config, self.region),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

        try:
            wait_for_port(self.local_port)
        except (OSError, RuntimeError):
            self.close()
            raise

        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
