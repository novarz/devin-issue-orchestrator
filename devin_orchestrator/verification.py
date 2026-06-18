"""Verify a Devin-produced PR against an issue's acceptance criteria.

Minimum verification (always): confirm a PR was opened against the expected repo
and base branch. Optional verification (``await_ci``): poll the fork's CI on the
PR head SHA until it concludes or a timeout elapses, degrading gracefully when no
checks are reported.
"""

from __future__ import annotations

import asyncio
import logging
import time

from .clients.github import GitHubAPIError, GitHubClient, parse_pr_url
from .models import VerificationResult

logger = logging.getLogger(__name__)


class Verifier:
    """Checks PRs against repo/branch expectations and (optionally) CI."""

    def __init__(
        self,
        github: GitHubClient,
        expected_repo: str,
        expected_base_branch: str,
        await_ci: bool = True,
        ci_timeout_seconds: float = 1800.0,
        ci_poll_interval_seconds: float = 30.0,
    ) -> None:
        self._github = github
        self._expected_repo = expected_repo.lower()
        self._expected_branch = expected_base_branch
        self._await_ci = await_ci
        self._ci_timeout = ci_timeout_seconds
        self._ci_poll = ci_poll_interval_seconds

    async def verify(self, pr_url: str) -> VerificationResult:
        try:
            owner, repo, number = parse_pr_url(pr_url)
        except ValueError as exc:
            return VerificationResult(passed=False, reason=str(exc))

        full_repo = f"{owner}/{repo}"
        try:
            pull = await self._github.get_pull(full_repo, number)
        except GitHubAPIError as exc:
            return VerificationResult(passed=False, reason=f"Could not fetch PR: {exc}")

        base = pull.get("base") or {}
        base_repo = str((base.get("repo") or {}).get("full_name") or "")
        base_branch = str(base.get("ref") or "")
        head_sha = str((pull.get("head") or {}).get("sha") or "")

        if base_repo.lower() != self._expected_repo:
            return VerificationResult(
                passed=False,
                reason=(
                    f"PR targets repo `{base_repo}` but expected "
                    f"`{self._expected_repo}`."
                ),
                pr_base_repo=base_repo,
                pr_base_branch=base_branch,
            )
        if base_branch != self._expected_branch:
            return VerificationResult(
                passed=False,
                reason=(
                    f"PR targets branch `{base_branch}` but expected "
                    f"`{self._expected_branch}`."
                ),
                pr_base_repo=base_repo,
                pr_base_branch=base_branch,
            )

        if not self._await_ci or not head_sha:
            return VerificationResult(
                passed=True,
                reason="PR opened against the correct repo and branch.",
                ci_state="skipped" if not self._await_ci else "none",
                pr_base_repo=base_repo,
                pr_base_branch=base_branch,
            )

        ci_state = await self._await_ci_result(full_repo, head_sha)
        passed = ci_state in {"success", "none"}
        reason = (
            "PR opened against the correct repo/branch and CI passed."
            if ci_state == "success"
            else (
                "PR opened against the correct repo/branch; no CI reported."
                if ci_state == "none"
                else f"CI did not pass (state={ci_state})."
            )
        )
        return VerificationResult(
            passed=passed,
            reason=reason,
            ci_state=ci_state,
            pr_base_repo=base_repo,
            pr_base_branch=base_branch,
        )

    async def _await_ci_result(self, repo: str, sha: str) -> str:
        deadline = time.monotonic() + self._ci_timeout
        last: str = "none"
        while True:
            try:
                state = await self._github.get_combined_ci_state(repo, sha)
            except GitHubAPIError as exc:
                logger.warning("CI status fetch failed: %s", exc)
                return "none"
            last = state
            if state in {"success", "failure"}:
                return state
            if time.monotonic() >= deadline:
                logger.warning("CI await timed out (last=%s)", last)
                return "failure" if last == "pending" else last
            await asyncio.sleep(self._ci_poll)
