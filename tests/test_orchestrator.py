"""End-to-end tests of the core remediation loop using fakes.

Covers the full state machine: session start, PR opened, verification, the
simulated-failure -> feedback -> retry -> escalation path, and bot comments at
each transition.
"""

from __future__ import annotations

from typing import Any, Optional

import pytest

from devin_orchestrator.config import Settings
from devin_orchestrator.metrics import Metrics
from devin_orchestrator.models import IssueEvent, IssueState
from devin_orchestrator.orchestrator import Orchestrator
from devin_orchestrator.store import IssueStore
from devin_orchestrator.verification import Verifier

REPO = "novarz/superset"
PR_URL = "https://github.com/novarz/superset/pull/100"


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "github_token": "t",
        "github_repo": REPO,
        "devin_api_key": "k",
        "devin_org_id": "org-1",
        "session_poll_interval_seconds": 0.0,
        "session_timeout_seconds": 5.0,
        "max_retries": 1,
        "expected_base_branch": "master",
        "verify_await_ci": False,
        "max_acu_limit": 5,
    }
    base.update(overrides)
    return Settings(**base)


class FakeDevin:
    def __init__(self, sessions: list[dict[str, Any]]) -> None:
        # ``sessions`` is the sequence of get_session payloads, consumed in order
        # (the last one repeats once exhausted).
        self._sessions = sessions
        self._idx = 0
        self.created: list[str] = []
        self.messages: list[str] = []

    async def create_session(
        self,
        prompt: str,
        max_acu_limit: int,
        repos: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        title: Optional[str] = None,
    ) -> dict[str, Any]:
        self.created.append(prompt)
        return {
            "session_id": "devin-1",
            "url": "https://app.devin.ai/sessions/devin-1",
            "status": "running",
        }

    async def get_session(self, session_id: str) -> dict[str, Any]:
        payload = self._sessions[min(self._idx, len(self._sessions) - 1)]
        self._idx += 1
        return payload

    async def send_message(self, session_id: str, message: str) -> dict[str, Any]:
        self.messages.append(message)
        return {}


class FakeGitHub:
    def __init__(self, pull: Optional[dict[str, Any]] = None) -> None:
        self.comments: list[str] = []
        self.labels: list[str] = []
        self._pull = pull or {
            "base": {"repo": {"full_name": REPO}, "ref": "master"},
            "head": {"sha": "abc"},
        }

    async def create_comment(self, repo: str, number: int, body: str) -> None:
        self.comments.append(body)

    async def add_labels(self, repo: str, number: int, labels: list[str]) -> None:
        self.labels.extend(labels)

    async def get_pull(self, repo: str, number: int) -> dict[str, Any]:
        return self._pull

    async def get_combined_ci_state(self, repo: str, ref: str) -> str:
        return "success"


def make_event() -> IssueEvent:
    return IssueEvent(
        repo=REPO,
        number=100,
        title="Broken thing",
        body="It is broken",
        url="https://github.com/novarz/superset/issues/100",
    )


def build(
    devin: FakeDevin, github: FakeGitHub, settings: Settings
) -> tuple[Orchestrator, Metrics, IssueStore]:
    metrics = Metrics()
    store = IssueStore()
    verifier = Verifier(
        github=github,  # type: ignore[arg-type]
        expected_repo=settings.github_repo,
        expected_base_branch=settings.expected_base_branch,
        await_ci=settings.verify_await_ci,
    )
    orch = Orchestrator(
        settings=settings,
        github=github,  # type: ignore[arg-type]
        devin=devin,  # type: ignore[arg-type]
        verifier=verifier,
        metrics=metrics,
        store=store,
    )
    return orch, metrics, store


@pytest.mark.asyncio
async def test_happy_path_opens_pr_and_verifies() -> None:
    devin = FakeDevin(
        [
            {
                "session_id": "devin-1",
                "status": "exit",
                "status_detail": "finished",
                "pull_requests": [{"pr_url": PR_URL, "pr_state": "open"}],
                "acus_consumed": 3.5,
            }
        ]
    )
    github = FakeGitHub()
    orch, metrics, _ = build(devin, github, make_settings())

    tracked = await orch.handle_event(make_event())

    assert tracked.state is IssueState.VERIFIED_PASSED
    assert tracked.pr_url == PR_URL
    assert metrics.verifications_passed == 1
    assert metrics.prs_opened == 1
    # Comments cover session start, PR opened, and verification result.
    joined = "\n".join(github.comments)
    assert "Started a Devin session" in joined
    assert "opened a pull request" in joined
    assert "Verification passed" in joined


@pytest.mark.asyncio
async def test_simulated_failure_retries_then_escalates() -> None:
    # Every poll returns a terminal session with no PR -> NO_PR each attempt.
    no_pr = {
        "session_id": "devin-1",
        "status": "exit",
        "status_detail": "finished",
        "pull_requests": [],
        "acus_consumed": 1.0,
    }
    devin = FakeDevin([no_pr])
    github = FakeGitHub()
    orch, metrics, _ = build(devin, github, make_settings(max_retries=1))

    tracked = await orch.handle_event(make_event())

    assert tracked.state is IssueState.ESCALATED
    assert tracked.attempts == 2  # initial + 1 retry
    assert tracked.retries == 1
    assert metrics.escalations == 1
    assert metrics.retries_total == 1
    # Exactly one corrective feedback message was delivered before the retry.
    assert len(devin.messages) == 1
    # The needs-human label was applied on escalation.
    assert "needs-human" in github.labels
    joined = "\n".join(github.comments)
    assert "Escalating for human review" in joined


@pytest.mark.asyncio
async def test_verification_fails_on_wrong_branch_then_escalates() -> None:
    pr_session = {
        "session_id": "devin-1",
        "status": "exit",
        "status_detail": "finished",
        "pull_requests": [{"pr_url": PR_URL, "pr_state": "open"}],
        "acus_consumed": 2.0,
    }
    devin = FakeDevin([pr_session])
    github = FakeGitHub(
        pull={
            "base": {"repo": {"full_name": REPO}, "ref": "some-other-branch"},
            "head": {"sha": "abc"},
        }
    )
    orch, metrics, _ = build(devin, github, make_settings(max_retries=0))

    tracked = await orch.handle_event(make_event())

    assert tracked.state is IssueState.ESCALATED
    assert metrics.verifications_failed >= 1
    joined = "\n".join(github.comments)
    assert "Verification failed" in joined


@pytest.mark.asyncio
async def test_duplicate_event_is_not_reprocessed() -> None:
    devin = FakeDevin(
        [
            {
                "session_id": "devin-1",
                "status": "exit",
                "status_detail": "finished",
                "pull_requests": [{"pr_url": PR_URL}],
                "acus_consumed": 1.0,
            }
        ]
    )
    github = FakeGitHub()
    orch, _, _ = build(devin, github, make_settings())
    event = make_event()

    await orch.handle_event(event)
    await orch.handle_event(event)

    assert len(devin.created) == 1  # second call short-circuits
