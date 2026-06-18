"""Pure retry/escalation decision logic.

Isolated from all I/O so it can be exhaustively unit-tested. ``attempts_used``
is the number of attempts that have already completed (1 after the first run).
``max_retries`` is the configured cap on *additional* attempts after the first.
"""

from __future__ import annotations

from .models import Action, Outcome


def decide_next_action(
    outcome: Outcome, attempts_used: int, max_retries: int
) -> Action:
    """Decide what to do after a remediation attempt.

    Rules (no infinite loops):
      * A successful attempt always completes.
      * A failed attempt retries while attempts remain within the cap.
      * Once the cap is exhausted, escalate to a human.
    """
    if attempts_used < 1:
        raise ValueError("attempts_used must be >= 1")
    if max_retries < 0:
        raise ValueError("max_retries must be >= 0")

    if outcome is Outcome.SUCCESS:
        return Action.COMPLETE

    # Total allowed attempts = 1 initial + max_retries.
    if attempts_used <= max_retries:
        return Action.RETRY
    return Action.ESCALATE
