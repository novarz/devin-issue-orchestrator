"""Async client for the Devin REST API (v3, organization scope).

Endpoints used (verified against docs.devin.ai):
  * POST   /v3/organizations/{org_id}/sessions
  * GET    /v3/organizations/{org_id}/sessions/{devin_id}
  * POST   /v3/organizations/{org_id}/sessions/{devin_id}/messages

Every call is wrapped with a timeout and explicit error handling. Network and
non-2xx responses are surfaced as :class:`DevinAPIError`.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Statuses that indicate the session is no longer doing work.
TERMINAL_STATUSES = frozenset({"exit", "error", "suspended"})
ERROR_STATUSES = frozenset({"error"})


class DevinAPIError(RuntimeError):
    """Raised when a Devin API call fails."""


class DevinClient:
    """Thin async wrapper around the Devin v3 organization API."""

    def __init__(
        self,
        api_key: str,
        org_id: str,
        base_url: str = "https://api.devin.ai/v3",
        timeout: float = 30.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._org_id = org_id
        self._base = f"{base_url.rstrip('/')}/organizations/{org_id}"
        self._timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self, method: str, path: str, json: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        url = f"{self._base}{path}"
        try:
            response = await self._client.request(
                method, url, json=json, timeout=self._timeout
            )
        except httpx.TimeoutException as exc:
            raise DevinAPIError(f"Devin API timeout on {method} {path}") from exc
        except httpx.HTTPError as exc:
            raise DevinAPIError(
                f"Devin API network error on {method} {path}: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise DevinAPIError(
                f"Devin API {response.status_code} on {method} {path}: "
                f"{response.text[:500]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise DevinAPIError(
                f"Devin API returned non-JSON on {method} {path}"
            ) from exc
        if not isinstance(data, dict):
            raise DevinAPIError(f"Unexpected Devin API payload on {method} {path}")
        return data

    async def create_session(
        self,
        prompt: str,
        max_acu_limit: int,
        repos: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        title: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a session with a mandatory ACU cap."""
        if max_acu_limit <= 0:
            raise ValueError("max_acu_limit must be positive")
        body: dict[str, Any] = {"prompt": prompt, "max_acu_limit": max_acu_limit}
        if repos:
            body["repos"] = repos
        if tags:
            body["tags"] = tags
        if title:
            body["title"] = title
        logger.info("Creating Devin session (acu_cap=%s)", max_acu_limit)
        return await self._request("POST", "/sessions", json=body)

    async def get_session(self, session_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/sessions/{session_id}")

    async def send_message(self, session_id: str, message: str) -> dict[str, Any]:
        return await self._request(
            "POST", f"/sessions/{session_id}/messages", json={"message": message}
        )


def extract_pr_url(session: dict[str, Any]) -> Optional[str]:
    """Return the first PR URL from a session payload, if any."""
    prs = session.get("pull_requests")
    if isinstance(prs, list):
        for pr in prs:
            if isinstance(pr, dict) and pr.get("pr_url"):
                return str(pr["pr_url"])
    return None


def is_terminal(session: dict[str, Any]) -> bool:
    """A session is terminal when it stops working or reports completion."""
    status = str(session.get("status", "")).lower()
    detail = str(session.get("status_detail") or "").lower()
    if status in TERMINAL_STATUSES:
        return True
    return detail == "finished"


def is_error(session: dict[str, Any]) -> bool:
    """Whether the terminal session represents a failure/stall."""
    status = str(session.get("status", "")).lower()
    detail = str(session.get("status_detail") or "").lower()
    if status in ERROR_STATUSES:
        return True
    if status == "suspended" and detail not in {"finished", "user_request"}:
        return True
    return False
