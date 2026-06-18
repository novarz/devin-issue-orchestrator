"""The core remediation loop and retry/escalation state machine.

This module orchestrates Devin sessions only. It contains no logic that edits
Apache Superset source code -- all code changes are produced by Devin sessions
via the Devin REST API.
"""

from __future__ import annotations

import asyncio
import logging
import time

from .clients.devin import (
    REMEDIATION_OUTPUT_SCHEMA,
    DevinAPIError,
    DevinClient,
    extract_pr_url,
    extract_summary,
    is_error,
    is_terminal,
)
from .clients.github import GitHubAPIError, GitHubClient
from .config import Settings
from .metrics import Metrics
from .models import (
    Action,
    IssueEvent,
    IssueState,
    Outcome,
    SessionResult,
    TrackedIssue,
)
from .prompt import build_feedback_prompt, build_prompt
from .state_machine import decide_next_action
from .store import IssueStore
from .verification import Verifier

logger = logging.getLogger(__name__)


class Orchestrator:
    """Drives an issue from ingestion through remediation and verification."""

    def __init__(
        self,
        settings: Settings,
        github: GitHubClient,
        devin: DevinClient,
        verifier: Verifier,
        metrics: Metrics,
        store: IssueStore,
    ) -> None:
        self._settings = settings
        self._github = github
        self._devin = devin
        self._verifier = verifier
        self._metrics = metrics
        self._store = store

    # ------------------------------------------------------------------ #
    # Entry point
    # ------------------------------------------------------------------ #
    async def handle_event(self, event: IssueEvent) -> TrackedIssue:
        """Process a single new-issue event end to end."""
        existing = self._store.get(event.id)
        if existing is not None:
            logger.info(
                "\u23ed\ufe0f  Issue #%s already tracked; skipping", event.number
            )
            return existing

        tracked = self._store.track(event)
        self._metrics.record_issue()
        logger.info(
            "\U0001f4e5 INGESTED issue #%s \u2014 %r%s",
            event.number,
            event.title,
            f" [{', '.join(event.labels)}]" if event.labels else "",
        )
        try:
            await self._process_issue(tracked)
        except Exception:  # noqa: BLE001 - never let one issue kill the loop
            logger.exception("Unhandled error processing %s", event.id)
            tracked.state = IssueState.FAILED
            self._metrics.record_failure()
            await self._safe_comment(
                tracked, "Orchestrator hit an unexpected error processing this issue."
            )
        finally:
            await self._safe_terminate(tracked)
            self._metrics.record_issue_completed(tracked.acus_consumed, tracked.retries)
        return tracked

    # ------------------------------------------------------------------ #
    # Core loop
    # ------------------------------------------------------------------ #
    async def _process_issue(self, tracked: TrackedIssue) -> None:
        settings = self._settings
        for attempt in range(1, settings.max_attempts + 1):
            tracked.attempts = attempt

            if attempt == 1:
                if not await self._start_session(tracked):
                    return  # session creation failed irrecoverably
            else:
                await self._send_feedback(tracked, attempt)

            result = await self._run_session(tracked)
            tracked.acus_consumed = result.acus_consumed

            outcome = await self._evaluate(tracked, result)
            action = decide_next_action(outcome, attempt, settings.max_retries)
            logger.info(
                "\U0001f9ed Issue #%s attempt %s/%s \u2014 outcome=%s \u2192 action=%s",
                tracked.event.number,
                attempt,
                settings.max_attempts,
                outcome.value,
                action.value,
            )

            if action is Action.COMPLETE:
                tracked.state = IssueState.VERIFIED_PASSED
                tracked.completed_at = time.time()
                logger.info(
                    "\U0001f389 DONE issue #%s remediated in %s attempt(s) "
                    "| %.1f ACU | time-to-PR=%.0fs",
                    tracked.event.number,
                    attempt,
                    tracked.acus_consumed,
                    tracked.time_to_pr_seconds or 0.0,
                )
                return
            if action is Action.ESCALATE:
                await self._escalate(tracked, outcome)
                return
            # RETRY
            tracked.retries += 1
            self._metrics.record_retry()
            logger.warning(
                "\U0001f501 RETRY issue #%s (retry %s/%s) \u2014 %s",
                tracked.event.number,
                tracked.retries,
                settings.max_retries,
                outcome.value,
            )
            await self._safe_comment(
                tracked,
                f"Attempt {attempt} did not pass verification "
                f"({outcome.value}). Sending corrective feedback and retrying.",
            )

    # ------------------------------------------------------------------ #
    # Steps
    # ------------------------------------------------------------------ #
    async def _start_session(self, tracked: TrackedIssue) -> bool:
        event = tracked.event
        prompt = build_prompt(
            event, self._settings.github_repo, self._settings.expected_base_branch
        )
        settings = self._settings
        try:
            session = await self._devin.create_session(
                prompt=prompt,
                max_acu_limit=settings.max_acu_limit,
                repos=[settings.github_repo],
                tags=["devin-orchestrator", f"issue-{event.number}"],
                title=f"Fix issue #{event.number}: {event.title}"[:120],
                create_as_user_id=settings.devin_create_as_user_id or None,
                structured_output_schema=(
                    REMEDIATION_OUTPUT_SCHEMA
                    if settings.devin_structured_output
                    else None
                ),
                structured_output_required=(
                    True if settings.devin_structured_output else None
                ),
            )
        except (DevinAPIError, ValueError) as exc:
            logger.error("Failed to create session for %s: %s", event.id, exc)
            tracked.state = IssueState.FAILED
            self._metrics.record_failure()
            await self._safe_comment(tracked, f"Failed to start a Devin session: {exc}")
            return False

        tracked.session_id = str(session.get("session_id") or "")
        tracked.session_url = str(session.get("url") or "")
        tracked.session_started_at = time.time()
        tracked.state = IssueState.SESSION_STARTED
        self._metrics.record_session_created()
        logger.info(
            "\U0001f680 SESSION started for issue #%s | id=%s | acu_cap=%s | %s",
            event.number,
            tracked.session_id or "?",
            self._settings.max_acu_limit,
            tracked.session_url or "(no url)",
        )
        await self._safe_comment(
            tracked,
            f"Started a Devin session to remediate this issue (ACU cap "
            f"{self._settings.max_acu_limit}).\nSession: {tracked.session_url}",
        )
        return True

    async def _send_feedback(self, tracked: TrackedIssue, attempt: int) -> None:
        if not tracked.session_id:
            return
        message = build_feedback_prompt(
            tracked.event,
            reason="Previous attempt did not satisfy the acceptance criteria.",
            attempt=attempt - 1,
            max_attempts=self._settings.max_retries,
        )
        logger.info(
            "\U0001f4ac FEEDBACK \u2192 session %s for issue #%s (attempt %s)",
            tracked.session_id,
            tracked.event.number,
            attempt,
        )
        try:
            await self._devin.send_message(tracked.session_id, message)
        except DevinAPIError as exc:
            logger.warning("Failed to send feedback to %s: %s", tracked.session_id, exc)

    async def _run_session(self, tracked: TrackedIssue) -> SessionResult:
        """Poll the session until terminal or timeout; detect PR opening."""
        assert tracked.session_id  # noqa: S101 - invariant after _start_session
        session_id = tracked.session_id
        deadline = time.monotonic() + self._settings.session_timeout_seconds
        last: dict[str, object] = {}
        last_status: str | None = None

        while True:
            try:
                session = await self._devin.get_session(session_id)
                last = session
                status = str(session.get("status") or "")
                if status and status != last_status:
                    logger.info(
                        "\u23f3 SESSION %s issue #%s | status=%s",
                        session_id,
                        tracked.event.number,
                        status,
                    )
                    last_status = status
            except DevinAPIError as exc:
                logger.warning("get_session failed for %s: %s", session_id, exc)
                if time.monotonic() >= deadline:
                    break
                await asyncio.sleep(self._settings.session_poll_interval_seconds)
                continue

            await self._maybe_record_pr(tracked, session)

            if is_terminal(session):
                return self._to_result(session, timed_out=False)
            if time.monotonic() >= deadline:
                logger.warning("Session %s timed out", session_id)
                return self._to_result(last, timed_out=True)
            await asyncio.sleep(self._settings.session_poll_interval_seconds)

        return self._to_result(last, timed_out=True)

    async def _maybe_record_pr(
        self, tracked: TrackedIssue, session: dict[str, object]
    ) -> None:
        if tracked.pr_url:
            return
        pr_url = extract_pr_url(session)
        if not pr_url:
            return
        tracked.pr_url = pr_url
        tracked.pr_opened_at = time.time()
        tracked.state = IssueState.PR_OPENED
        self._metrics.record_pr_opened(tracked.time_to_pr_seconds)
        summary = extract_summary(session)
        logger.info(
            "\U0001f500 PR OPENED for issue #%s | %s | time-to-PR=%.0fs%s",
            tracked.event.number,
            pr_url,
            tracked.time_to_pr_seconds or 0.0,
            f" | {summary}" if summary else "",
        )
        await self._safe_comment(
            tracked,
            f"Devin opened a pull request: {pr_url}"
            + (f"\n\n**Summary:** {summary}" if summary else ""),
        )

    async def _evaluate(self, tracked: TrackedIssue, result: SessionResult) -> Outcome:
        if result.pr_url:
            logger.info(
                "\U0001f50e VERIFYING issue #%s against acceptance criteria \u2014 %s",
                tracked.event.number,
                result.pr_url,
            )
            verification = await self._verifier.verify(result.pr_url)
            self._metrics.record_verification(verification.passed)
            status = "passed" if verification.passed else "failed"
            logger.info(
                "%s VERIFICATION %s for issue #%s \u2014 %s%s",
                "\u2705" if verification.passed else "\u274c",
                status,
                tracked.event.number,
                verification.reason,
                f" | CI={verification.ci_state}" if verification.ci_state else "",
            )
            await self._safe_comment(
                tracked,
                f"Verification {status}: {verification.reason}"
                + (
                    f"\nCI state: {verification.ci_state}"
                    if verification.ci_state
                    else ""
                ),
            )
            if verification.passed:
                return Outcome.SUCCESS
            tracked.state = IssueState.VERIFIED_FAILED
            if result.structured_output and result.structured_output.get("unresolved"):
                logger.info(
                    "\U0001f4dd Devin reported unresolved work on issue #%s: %s",
                    tracked.event.number,
                    result.structured_output["unresolved"],
                )
            return Outcome.PR_VERIFICATION_FAILED

        # No PR produced.
        if result.timed_out:
            return Outcome.STALLED
        if is_error({"status": result.status, "status_detail": result.status_detail}):
            return Outcome.SESSION_ERROR
        return Outcome.NO_PR

    async def _escalate(self, tracked: TrackedIssue, outcome: Outcome) -> None:
        tracked.state = IssueState.ESCALATED
        tracked.completed_at = time.time()
        self._metrics.record_escalation()
        label = self._settings.needs_human_label
        logger.warning(
            "\U0001f6a8 ESCALATING issue #%s after %s attempt(s) "
            "(last outcome: %s) \u2014 labelling %r",
            tracked.event.number,
            tracked.attempts,
            outcome.value,
            label,
        )
        assignees = self._settings.escalation_assignees
        mention = (
            " Assigning " + ", ".join(f"@{name}" for name in assignees) + "."
            if assignees
            else ""
        )
        await self._safe_comment(
            tracked,
            f"Automated remediation failed after {tracked.attempts} attempts "
            f"(last outcome: {outcome.value}). Escalating for human review and "
            f"applying the `{label}` label.{mention}",
        )
        try:
            await self._github.add_labels(
                self._settings.github_repo, tracked.event.number, [label]
            )
        except GitHubAPIError as exc:
            logger.warning("Failed to apply escalation label: %s", exc)
        if assignees:
            try:
                await self._github.add_assignees(
                    self._settings.github_repo, tracked.event.number, list(assignees)
                )
                logger.info(
                    "\U0001f464 Assigned issue #%s to %s",
                    tracked.event.number,
                    ", ".join(assignees),
                )
            except GitHubAPIError as exc:
                logger.warning("Failed to assign escalation: %s", exc)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _to_result(self, session: dict[str, object], timed_out: bool) -> SessionResult:
        structured = session.get("structured_output")
        acus = session.get("acus_consumed")
        return SessionResult(
            session_id=str(session.get("session_id") or ""),
            status=str(session.get("status") or ""),
            status_detail=(
                str(session.get("status_detail"))
                if session.get("status_detail") is not None
                else None
            ),
            pr_url=extract_pr_url(session),
            acus_consumed=float(acus) if isinstance(acus, (int, float)) else 0.0,
            structured_output=structured if isinstance(structured, dict) else None,
            timed_out=timed_out,
        )

    async def _safe_terminate(self, tracked: TrackedIssue) -> None:
        """Terminate the session so an idle (e.g. waiting_for_user) one is freed."""
        session_id = tracked.session_id
        if not session_id:
            return
        try:
            await self._devin.terminate_session(session_id)
            logger.info(
                "\U0001f9f9 Terminated session %s for issue #%s",
                session_id,
                tracked.event.number,
            )
        except DevinAPIError as exc:
            logger.warning(
                "Failed to terminate session %s for issue #%s: %s",
                session_id,
                tracked.event.number,
                exc,
            )

    async def _safe_comment(self, tracked: TrackedIssue, body: str) -> None:
        marked = f"{self._settings.bot_comment_marker}\n{body}"
        try:
            await self._github.create_comment(
                self._settings.github_repo, tracked.event.number, marked
            )
        except GitHubAPIError as exc:
            logger.warning(
                "Failed to comment on issue #%s: %s", tracked.event.number, exc
            )
