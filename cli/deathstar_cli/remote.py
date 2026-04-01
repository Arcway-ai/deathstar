from __future__ import annotations

import httpx

from deathstar_cli.config import CLIConfig
from deathstar_cli.ssm import SSMPortForward
from deathstar_cli.tailscale import resolve_peer_target
from deathstar_cli.terraform import terraform_outputs
from deathstar_shared.models import (
    BackupRequest,
    BackupResponse,
    LogsResponse,
    RestoreRequest,
    RestoreResponse,
    StatusResponse,
    WorkflowRequest,
    WorkflowResponse,
)


class RemoteAPIClient:
    def __init__(self, config: CLIConfig, region: str, transport: str | None = None) -> None:
        self.config = config
        self.region = region
        outputs = terraform_outputs(config, region)
        self.instance_id = str(outputs["instance_id"])
        self.remote_api_port = int(outputs.get("remote_api_port", 8080))
        self.tailscale_enabled = bool(outputs.get("tailscale_enabled", False))
        self.tailscale_hostname = str(
            outputs.get("tailscale_hostname") or config.tailscale_hostname
        ).strip()
        requested = transport or config.remote_transport
        self.transport = self._resolve_transport(requested)
        self._can_fallback_to_ssm = (
            requested.strip().lower() == "auto" and self.transport == "tailscale"
        )

    def _resolve_transport(self, requested_transport: str) -> str:
        normalized = requested_transport.strip().lower()
        if normalized not in {"auto", "tailscale", "ssm"}:
            raise RuntimeError(f"unsupported transport: {requested_transport}")
        if normalized == "auto":
            return "tailscale" if self.tailscale_enabled else "ssm"
        if normalized == "tailscale" and not self.tailscale_enabled:
            raise RuntimeError(
                "this deployment does not have Tailscale enabled; use --transport ssm or redeploy with Tailscale"
            )
        return normalized

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        if self.transport == "tailscale":
            target = resolve_peer_target(self.tailscale_hostname)
            try:
                response = httpx.request(
                    method,
                    f"http://{target}:{self.remote_api_port}{path}",
                    json=payload,
                    timeout=300.0,
                )
            except httpx.HTTPError as exc:
                if self._can_fallback_to_ssm:
                    import logging
                    logging.getLogger(__name__).warning(
                        "Tailscale transport failed (%s), falling back to SSM", exc,
                    )
                    return self._request_via_ssm(method, path, payload)
                raise RuntimeError(
                    "tailscale transport failed; confirm your local device is on the tailnet and use --transport ssm for break-glass access"
                ) from exc

            response.raise_for_status()
            return response.json()

        return self._request_via_ssm(method, path, payload)

    def _request_via_ssm(self, method: str, path: str, payload: dict | None = None) -> dict:
        with SSMPortForward(
            config=self.config,
            region=self.region,
            instance_id=self.instance_id,
            remote_port=self.remote_api_port,
        ) as tunnel:
            response = httpx.request(
                method,
                f"http://127.0.0.1:{tunnel.local_port}{path}",
                json=payload,
                timeout=300.0,
            )
            response.raise_for_status()
            return response.json()

    def run(self, request: WorkflowRequest) -> WorkflowResponse:
        return WorkflowResponse.model_validate(self._request("POST", "/v1/run", request.model_dump()))

    def status(self) -> StatusResponse:
        return StatusResponse.model_validate(self._request("GET", "/v1/status"))

    def logs(self, tail: int) -> LogsResponse:
        return LogsResponse.model_validate(self._request("GET", f"/v1/logs?tail={int(tail)}"))

    def backup(self, request: BackupRequest) -> BackupResponse:
        return BackupResponse.model_validate(self._request("POST", "/v1/backup", request.model_dump()))

    def restore(self, request: RestoreRequest) -> RestoreResponse:
        return RestoreResponse.model_validate(
            self._request("POST", "/v1/restore", request.model_dump())
        )
