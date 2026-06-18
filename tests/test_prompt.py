"""Unit tests for prompt generation."""

from __future__ import annotations

from devin_orchestrator.models import IssueEvent
from devin_orchestrator.prompt import (
    build_acceptance_criteria,
    build_feedback_prompt,
    build_prompt,
)

EVENT = IssueEvent(
    repo="novarz/superset",
    number=42,
    title="Dashboard fails to load",
    body="Steps to reproduce: open dashboard, see error.",
    url="https://github.com/novarz/superset/issues/42",
)


def test_prompt_includes_issue_body_and_link() -> None:
    prompt = build_prompt(EVENT, "novarz/superset", "master")
    assert "Steps to reproduce" in prompt
    assert "#42" in prompt
    assert EVENT.url in prompt
    assert "novarz/superset" in prompt


def test_prompt_includes_acceptance_criteria() -> None:
    prompt = build_prompt(EVENT, "novarz/superset", "master")
    assert "Acceptance criteria" in prompt
    # branch and repo are referenced in the criteria
    assert "`master`" in prompt


def test_acceptance_criteria_are_explicit_and_nonempty() -> None:
    criteria = build_acceptance_criteria(EVENT, "novarz/superset", "develop")
    assert len(criteria) >= 4
    assert any("pull request" in c.lower() for c in criteria)
    assert any("develop" in c for c in criteria)


def test_empty_body_is_handled() -> None:
    event = IssueEvent(
        repo="novarz/superset",
        number=7,
        title="Empty",
        body="",
        url="https://github.com/novarz/superset/issues/7",
    )
    prompt = build_prompt(event, "novarz/superset", "master")
    assert "no description provided" in prompt


def test_feedback_prompt_references_reason_and_attempt() -> None:
    msg = build_feedback_prompt(EVENT, "PR targeted wrong branch", 1, 2)
    assert "PR targeted wrong branch" in msg
    assert "#42" in msg
    assert "retry 1 of 2" in msg
