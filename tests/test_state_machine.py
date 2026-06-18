"""Unit tests for the retry/escalation decision logic."""

from __future__ import annotations

import pytest

from devin_orchestrator.models import Action, Outcome
from devin_orchestrator.state_machine import decide_next_action


def test_success_always_completes() -> None:
    assert decide_next_action(Outcome.SUCCESS, 1, 2) is Action.COMPLETE
    assert decide_next_action(Outcome.SUCCESS, 3, 2) is Action.COMPLETE


def test_failure_retries_until_cap() -> None:
    # max_retries=2 -> attempts 1 and 2 retry, attempt 3 escalates.
    assert decide_next_action(Outcome.NO_PR, 1, 2) is Action.RETRY
    assert decide_next_action(Outcome.PR_VERIFICATION_FAILED, 2, 2) is Action.RETRY
    assert decide_next_action(Outcome.SESSION_ERROR, 3, 2) is Action.ESCALATE


def test_zero_retries_escalates_immediately() -> None:
    assert decide_next_action(Outcome.NO_PR, 1, 0) is Action.ESCALATE


def test_stall_is_treated_as_failure() -> None:
    assert decide_next_action(Outcome.STALLED, 1, 1) is Action.RETRY
    assert decide_next_action(Outcome.STALLED, 2, 1) is Action.ESCALATE


def test_invalid_inputs_raise() -> None:
    with pytest.raises(ValueError, match="attempts_used"):
        decide_next_action(Outcome.NO_PR, 0, 2)
    with pytest.raises(ValueError, match="max_retries"):
        decide_next_action(Outcome.NO_PR, 1, -1)
