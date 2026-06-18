"""In-memory metrics collection exposed via ``GET /metrics``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


@dataclass
class Metrics:
    """Aggregated counters and timings for the orchestration loop."""

    issues_ingested: int = 0
    sessions_created: int = 0
    prs_opened: int = 0
    verifications_passed: int = 0
    verifications_failed: int = 0
    escalations: int = 0
    retries_total: int = 0
    failures_total: int = 0
    time_to_pr_seconds: list[float] = field(default_factory=list)
    acu_cost_per_issue: list[float] = field(default_factory=list)
    retry_counts: list[int] = field(default_factory=list)

    def record_issue(self) -> None:
        self.issues_ingested += 1

    def record_session_created(self) -> None:
        self.sessions_created += 1

    def record_pr_opened(self, time_to_pr: float | None) -> None:
        self.prs_opened += 1
        if time_to_pr is not None:
            self.time_to_pr_seconds.append(round(time_to_pr, 3))

    def record_retry(self) -> None:
        self.retries_total += 1

    def record_verification(self, passed: bool) -> None:
        if passed:
            self.verifications_passed += 1
        else:
            self.verifications_failed += 1

    def record_escalation(self) -> None:
        self.escalations += 1

    def record_failure(self) -> None:
        self.failures_total += 1

    def record_issue_completed(self, acus: float, retries: int) -> None:
        self.acu_cost_per_issue.append(round(acus, 3))
        self.retry_counts.append(retries)

    @property
    def success_rate(self) -> float:
        total = self.verifications_passed + self.verifications_failed + self.escalations
        if total == 0:
            return 0.0
        return round(self.verifications_passed / total, 3)

    def snapshot(self) -> dict[str, Any]:
        return {
            "issues_ingested": self.issues_ingested,
            "sessions_created": self.sessions_created,
            "prs_opened": self.prs_opened,
            "verifications_passed": self.verifications_passed,
            "verifications_failed": self.verifications_failed,
            "escalations": self.escalations,
            "failures_total": self.failures_total,
            "retries_total": self.retries_total,
            "success_rate": self.success_rate,
            "avg_time_to_pr_seconds": _avg(self.time_to_pr_seconds),
            "avg_acu_cost_per_issue": _avg(self.acu_cost_per_issue),
            "total_acu_cost": round(sum(self.acu_cost_per_issue), 3),
            "avg_retries_per_issue": _avg([float(r) for r in self.retry_counts]),
        }
