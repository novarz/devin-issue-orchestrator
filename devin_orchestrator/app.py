"""FastAPI application wiring the orchestrator together.

Exposes:
  * GET /healthz     - liveness probe
  * GET /metrics     - JSON metrics (success rate, time-to-PR, ACU cost, retries)
  * GET /dashboard   - minimal HTML dashboard rendering the same metrics
  * GET /issues      - current tracked-issue state (observability)
  * GET /logs        - live HTML log viewer (SSE-backed)
  * GET /logs/stream - Server-Sent Events stream of log lines
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .clients.devin import DevinClient
from .clients.github import GitHubClient
from .config import Settings
from .dashboard import render_dashboard
from .demo_seed import seed as demo_seed
from .ingestion.polling import PollingIngestionAdapter
from .log_stream import LOG_BROKER, stream_logs
from .logging_setup import banner, configure_logging
from .logs_view import render_logs_page
from .metrics import Metrics
from .orchestrator import Orchestrator
from .runner import PollerLoop
from .store import IssueStore
from .verification import Verifier

configure_logging()
logger = logging.getLogger(__name__)


class AppState:
    """Holds long-lived objects for the running service."""

    settings: Settings
    metrics: Metrics
    store: IssueStore
    github: GitHubClient
    devin: DevinClient
    poller: PollerLoop | None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    LOG_BROKER.attach_loop(asyncio.get_running_loop())
    for line in banner(settings.github_repo, settings.dry_run).splitlines():
        logger.info(line)
    metrics = Metrics()
    store = IssueStore()

    if settings.demo_seed:
        count = demo_seed(settings.github_repo, metrics, store)
        logger.info("DEMO_SEED: injected %d sample issues into metrics/store", count)

    github = GitHubClient(
        token=settings.github_token,
        api_url=settings.github_api_url,
        timeout=settings.http_timeout_seconds,
    )
    devin = DevinClient(
        api_key=settings.devin_api_key,
        org_id=settings.devin_org_id,
        base_url=settings.devin_base_url,
        timeout=settings.http_timeout_seconds,
    )

    state = AppState()
    state.settings = settings
    state.metrics = metrics
    state.store = store
    state.github = github
    state.devin = devin
    state.poller = None
    app.state.app_state = state

    if settings.dry_run:
        logger.warning(
            "DRY_RUN enabled: background poller is NOT started "
            "(no GitHub polling, no Devin sessions)."
        )
    else:
        settings.validate_for_live()
        verifier = Verifier(
            github=github,
            expected_repo=settings.github_repo,
            expected_base_branch=settings.expected_base_branch,
            await_ci=settings.verify_await_ci,
            ci_timeout_seconds=settings.ci_timeout_seconds,
            ci_poll_interval_seconds=settings.ci_poll_interval_seconds,
        )
        orchestrator = Orchestrator(
            settings=settings,
            github=github,
            devin=devin,
            verifier=verifier,
            metrics=metrics,
            store=store,
        )
        adapter = PollingIngestionAdapter(
            github=github,
            repo=settings.github_repo,
            seen=store,
            label_filter=settings.issue_label_filter,
            skip_label=settings.needs_human_label,
        )
        poller = PollerLoop(adapter, orchestrator, settings.poll_interval_seconds)
        poller.start()
        state.poller = poller
        logger.info(
            "Orchestrator online | repo=%s | poll=%ss | acu_cap=%s | max_retries=%s",
            settings.github_repo,
            settings.poll_interval_seconds,
            settings.max_acu_limit,
            settings.max_retries,
        )

    try:
        yield
    finally:
        if state.poller is not None:
            await state.poller.stop()
        await github.aclose()
        await devin.aclose()


app = FastAPI(title="Devin Issue Orchestrator", lifespan=lifespan)


def _state(app: FastAPI) -> AppState:
    state: AppState = app.state.app_state
    return state


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> JSONResponse:
    state = _state(app)
    payload = state.metrics.snapshot()
    payload["repo"] = state.settings.github_repo
    payload["tracked_issues"] = len(state.store.all())
    return JSONResponse(payload)


@app.get("/issues")
async def issues() -> JSONResponse:
    state = _state(app)
    rows = [
        {
            "id": t.event.id,
            "number": t.event.number,
            "title": t.event.title,
            "state": t.state.value,
            "session_id": t.session_id,
            "session_url": t.session_url,
            "pr_url": t.pr_url,
            "attempts": t.attempts,
            "retries": t.retries,
            "acus_consumed": t.acus_consumed,
            "time_to_pr_seconds": t.time_to_pr_seconds,
        }
        for t in state.store.all()
    ]
    return JSONResponse({"issues": rows})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    state = _state(app)
    html = render_dashboard(
        repo=state.settings.github_repo,
        metrics=state.metrics.snapshot(),
        issues=state.store.all(),
    )
    return HTMLResponse(html)


@app.get("/logs", response_class=HTMLResponse)
async def logs() -> HTMLResponse:
    return HTMLResponse(render_logs_page(_state(app).settings.github_repo))


@app.get("/logs/stream")
async def logs_stream(request: Request) -> StreamingResponse:
    async def is_disconnected() -> bool:
        return await request.is_disconnected()

    return StreamingResponse(
        stream_logs(LOG_BROKER, is_disconnected),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
