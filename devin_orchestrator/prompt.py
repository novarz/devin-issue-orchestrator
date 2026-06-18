"""Prompt-generation logic (pure and independently testable).

Turns a GitHub issue into a Devin session prompt that contains the full issue
context and explicit acceptance criteria. No I/O happens here.
"""

from __future__ import annotations

from .models import IssueEvent


def build_acceptance_criteria(
    event: IssueEvent, repo: str, base_branch: str
) -> list[str]:
    """Explicit, checkable acceptance criteria for the remediation."""
    return [
        f"A pull request is opened against the `{base_branch}` branch of `{repo}`.",
        f"The PR directly addresses the problem described in issue #{event.number}.",
        "The change is minimal and scoped to the issue; unrelated files are "
        "not modified.",
        "Existing tests still pass and new tests are added when behaviour changes.",
        "The PR description references the issue and summarizes the fix.",
        "Repository lint/type checks (pre-commit) pass for the changed files.",
    ]


def build_prompt(event: IssueEvent, repo: str, base_branch: str) -> str:
    """Compose the full Devin session prompt for an issue."""
    criteria = build_acceptance_criteria(event, repo, base_branch)
    criteria_block = "\n".join(f"{i}. {c}" for i, c in enumerate(criteria, 1))
    body = event.body.strip() or "(no description provided)"

    return f"""\
You are remediating a GitHub issue on the repository `{repo}`.

## Issue #{event.number}: {event.title}
Link: {event.url}

### Issue body
{body}

## Your task
Investigate the issue in `{repo}`, implement a fix on a new branch, and open a
pull request against the `{base_branch}` branch of `{repo}`. Keep the change
minimal and focused on this issue only.

## Acceptance criteria (all must be satisfied)
{criteria_block}

## Notes
- Open exactly one pull request that targets `{base_branch}`.
- Do not make unrelated changes.
- Ensure the repository's pre-commit / lint checks pass for files you touch.
"""


def build_feedback_prompt(
    event: IssueEvent, reason: str, attempt: int, max_attempts: int
) -> str:
    """Corrective feedback sent to an existing session after a failed attempt."""
    return f"""\
The previous attempt to resolve issue #{event.number} did not pass verification.

Reason: {reason}

This is retry {attempt} of {max_attempts}. Please:
1. Re-read the acceptance criteria for issue #{event.number}.
2. Address the specific reason above.
3. Ensure a pull request is open against the correct repository and branch.
4. Make sure lint/type checks pass for the files you changed.
"""
