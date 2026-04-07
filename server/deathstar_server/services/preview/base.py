from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass
class PreviewResult:
    """Result from a preview provider operation."""

    provider_service_id: str
    preview_url: str | None = None
    status: str = "pending"
    error_message: str | None = None


class PreviewProvider(abc.ABC):
    """Abstract base for preview deployment providers (Render, Vercel, etc.)."""

    @abc.abstractmethod
    async def create_preview(
        self,
        *,
        repo_full_name: str,
        branch: str,
        service_name: str,
    ) -> PreviewResult:
        """Create a new preview deployment for the given branch."""

    @abc.abstractmethod
    async def get_status(self, provider_service_id: str) -> PreviewResult:
        """Fetch current status and URL of a preview deployment."""

    @abc.abstractmethod
    async def delete_preview(self, provider_service_id: str) -> None:
        """Tear down and delete a preview deployment."""

    @abc.abstractmethod
    async def is_configured(self) -> bool:
        """Return True if this provider has the required credentials."""
