"""Domain models shared across the orchestrator."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class IssueState(str, Enum):
    """Lifecycle of a tracked issue within the orchestrator."""

    NEW = "new"
    SESSION_STARTED = "session_started"
    PR_OPENED = "pr_opened"
    VERIFIED_PASSED = "verified_passed"
    VERIFIED_FAILED = "verified_failed"
    ESCALATED = "escalated"
    FAILED = "failed"


class Outcome(str, Enum):
    """Result of a single remediation attempt."""

    SUCCESS = "success"
    PR_VERIFICATION_FAILED = "pr_verification_failed"
    NO_PR = "no_pr"
    SESSION_ERROR = "session_error"
    STALLED = "stalled"


class Action(str, Enum):
    """Decision emitted by the retry/escalation state machine."""

    COMPLETE = "complete"
    RETRY = "retry"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class IssueEvent:
    """An internal event emitted by an ingestion adapter for a new issue."""

    repo: str  # "owner/name"
    number: int
    title: str
    body: str
    url: str
    labels: tuple[str, ...] = ()
    created_at: Optional[str] = None

    @property
    def id(self) -> str:
        """Stable, globally-unique identifier used for dedupe."""
        return f"{self.repo}#{self.number}"


@dataclass
class TrackedIssue:
    """Mutable orchestration state persisted per issue."""

    event: IssueEvent
    state: IssueState = IssueState.NEW
    session_id: Optional[str] = None
    session_url: Optional[str] = None
    pr_url: Optional[str] = None
    attempts: int = 0
    retries: int = 0
    acus_consumed: float = 0.0
    created_at: float = field(default_factory=time.time)
    session_started_at: Optional[float] = None
    pr_opened_at: Optional[float] = None
    completed_at: Optional[float] = None

    @property
    def time_to_pr_seconds(self) -> Optional[float]:
        if self.session_started_at is None or self.pr_opened_at is None:
            return None
        return self.pr_opened_at - self.session_started_at


@dataclass(frozen=True)
class SessionResult:
    """Terminal snapshot of a Devin session."""

    session_id: str
    status: str
    status_detail: Optional[str]
    pr_url: Optional[str]
    acus_consumed: float
    structured_output: Optional[dict[str, object]] = None
    timed_out: bool = False


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of verifying a PR against the issue's acceptance criteria."""

    passed: bool
    reason: str
    ci_state: Optional[str] = None
    pr_base_repo: Optional[str] = None
    pr_base_branch: Optional[str] = None
