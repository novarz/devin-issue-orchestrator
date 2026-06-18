"""Unit tests for Devin session-state helpers."""

from __future__ import annotations

from devin_orchestrator.clients.devin import (
    extract_pr_url,
    extract_summary,
    is_terminal,
)

PR_URL = "https://github.com/novarz/superset/pull/3"


def test_terminal_on_exit_status() -> None:
    assert is_terminal({"status": "exit"}) is True


def test_terminal_on_finished_detail() -> None:
    assert is_terminal({"status": "running", "status_detail": "finished"}) is True


def test_terminal_on_final_structured_output() -> None:
    # A completed result (criteria met or a PR) marks the session done.
    session = {
        "status": "running",
        "status_detail": "working",
        "structured_output": {"summary": "done", "acceptance_criteria_met": True},
    }
    assert is_terminal(session) is True
    assert (
        is_terminal(
            {
                "status": "running",
                "structured_output": {
                    "pr_url": PR_URL,
                    "acceptance_criteria_met": False,
                },
            }
        )
        is True
    )


def test_not_terminal_on_interim_structured_output() -> None:
    # Devin can submit interim output mid-task (no PR, criteria not yet met).
    session = {
        "status": "running",
        "status_detail": "working",
        "structured_output": {
            "summary": "Running pre-commit checks before committing.",
            "pr_url": None,
            "acceptance_criteria_met": False,
        },
    }
    assert is_terminal(session) is False


def test_terminal_on_waiting_for_user_with_pr() -> None:
    session = {
        "status": "running",
        "status_detail": "waiting_for_user",
        "pull_requests": [{"pr_url": PR_URL, "pr_state": "open"}],
    }
    assert is_terminal(session) is True


def test_not_terminal_while_working_without_output() -> None:
    assert is_terminal({"status": "running", "status_detail": "working"}) is False


def test_not_terminal_waiting_for_user_without_pr() -> None:
    session = {"status": "running", "status_detail": "waiting_for_user"}
    assert is_terminal(session) is False


def test_extract_pr_url_falls_back_to_structured_output() -> None:
    session = {"pull_requests": [], "structured_output": {"pr_url": PR_URL}}
    assert extract_pr_url(session) == PR_URL


def test_extract_summary() -> None:
    assert extract_summary({"structured_output": {"summary": "hi"}}) == "hi"
    assert extract_summary({}) is None
