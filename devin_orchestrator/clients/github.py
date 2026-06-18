"""Async GitHub REST client scoped to the operations the orchestrator needs.

This client is *read/write on issues* (list, comment, label) and *read-only on
pull requests and CI status*. It never mutates repository code.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_PR_URL_RE = re.compile(r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<n>\d+)")


class GitHubAPIError(RuntimeError):
    """Raised when a GitHub API call fails."""


def parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    """Parse ``owner``, ``repo`` and PR number from a PR URL."""
    match = _PR_URL_RE.search(pr_url)
    if not match:
        raise ValueError(f"Unrecognized PR URL: {pr_url!r}")
    return match["owner"], match["repo"], int(match["n"])


class GitHubClient:
    """Thin async wrapper around the GitHub REST API."""

    def __init__(
        self,
        token: str,
        api_url: str = "https://api.github.com",
        timeout: float = 30.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base = api_url.rstrip("/")
        self._timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = f"{self._base}{path}"
        try:
            response = await self._client.request(
                method, url, json=json, params=params, timeout=self._timeout
            )
        except httpx.TimeoutException as exc:
            raise GitHubAPIError(f"GitHub API timeout on {method} {path}") from exc
        except httpx.HTTPError as exc:
            raise GitHubAPIError(
                f"GitHub API network error on {method} {path}: {exc}"
            ) from exc
        if response.status_code >= 400:
            raise GitHubAPIError(
                f"GitHub API {response.status_code} on {method} {path}: "
                f"{response.text[:500]}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    async def list_open_issues(
        self, repo: str, since: Optional[str] = None, labels: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """List open issues (pull requests are filtered out)."""
        params: dict[str, Any] = {
            "state": "open",
            "sort": "created",
            "direction": "asc",
            "per_page": 100,
        }
        if since:
            params["since"] = since
        if labels:
            params["labels"] = labels
        data = await self._request("GET", f"/repos/{repo}/issues", params=params)
        if not isinstance(data, list):
            return []
        # The issues endpoint also returns PRs; exclude them.
        return [item for item in data if "pull_request" not in item]

    async def create_comment(self, repo: str, number: int, body: str) -> None:
        await self._request(
            "POST",
            f"/repos/{repo}/issues/{number}/comments",
            json={"body": body},
        )

    async def add_labels(self, repo: str, number: int, labels: list[str]) -> None:
        await self._request(
            "POST",
            f"/repos/{repo}/issues/{number}/labels",
            json={"labels": labels},
        )

    async def add_assignees(self, repo: str, number: int, assignees: list[str]) -> None:
        await self._request(
            "POST",
            f"/repos/{repo}/issues/{number}/assignees",
            json={"assignees": assignees},
        )

    async def get_pull(self, repo: str, number: int) -> dict[str, Any]:
        data = await self._request("GET", f"/repos/{repo}/pulls/{number}")
        if not isinstance(data, dict):
            raise GitHubAPIError("Unexpected pull request payload")
        return data

    async def get_combined_ci_state(self, repo: str, ref: str) -> str:
        """Aggregate commit statuses + check runs for ``ref`` into one state.

        Returns one of: ``success``, ``failure``, ``pending`` or ``none``.
        """
        states: list[str] = []

        status = await self._request("GET", f"/repos/{repo}/commits/{ref}/status")
        if isinstance(status, dict):
            state = str(status.get("state", ""))
            if state and state != "pending" or status.get("total_count"):
                states.append(state)

        checks = await self._request("GET", f"/repos/{repo}/commits/{ref}/check-runs")
        if isinstance(checks, dict):
            for run in checks.get("check_runs", []) or []:
                if not isinstance(run, dict):
                    continue
                if run.get("status") != "completed":
                    states.append("pending")
                    continue
                conclusion = str(run.get("conclusion") or "")
                if conclusion in {"success", "neutral", "skipped"}:
                    states.append("success")
                elif conclusion in {
                    "failure",
                    "timed_out",
                    "cancelled",
                    "action_required",
                }:
                    states.append("failure")
                else:
                    states.append("pending")

        return _reduce_ci_states(states)


def _reduce_ci_states(states: list[str]) -> str:
    if not states:
        return "none"
    if any(s == "failure" or s == "error" for s in states):
        return "failure"
    if any(s == "pending" for s in states):
        return "pending"
    if all(s == "success" for s in states):
        return "success"
    return "pending"
