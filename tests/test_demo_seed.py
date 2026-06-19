"""Tests for demo_seed module."""

from devin_orchestrator.demo_seed import seed
from devin_orchestrator.metrics import Metrics
from devin_orchestrator.store import IssueStore


def test_seed_populates_store_and_metrics() -> None:
    metrics = Metrics()
    store = IssueStore()
    count = seed("novarz/superset", metrics, store)

    assert count == 7
    assert len(store.all()) == 7
    assert metrics.issues_ingested == 7
    assert metrics.sessions_created == 7
    assert metrics.prs_opened == 6  # 1 escalated has no PR
    assert metrics.escalations == 1
    assert metrics.verifications_passed == 6
    assert metrics.retries_total == 4  # 1+1+0+0+0+2+0
    assert metrics.success_rate > 0.8
    snap = metrics.snapshot()
    assert snap["avg_time_to_pr_seconds"] > 0
    assert snap["total_acu_cost"] > 0


def test_seed_issues_use_negative_numbers() -> None:
    store = IssueStore()
    seed("owner/repo", Metrics(), store)
    for tracked in store.all():
        assert tracked.event.number < 0, "seed issues must use negative numbers"


def test_seed_marks_seen() -> None:
    store = IssueStore()
    seed("owner/repo", Metrics(), store)
    assert store.is_seen("owner/repo#-1")
    assert store.is_seen("owner/repo#-7")
    assert not store.is_seen("owner/repo#1")
