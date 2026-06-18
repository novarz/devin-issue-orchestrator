"""Unit tests for the in-memory log broker and SSE streaming."""

from __future__ import annotations

import asyncio
import logging

import pytest

from devin_orchestrator.log_stream import (
    LOG_BROKER,
    BrokerHandler,
    LogBroker,
    format_sse,
    stream_logs,
)
from devin_orchestrator.logs_view import render_logs_page


def test_history_is_bounded_to_capacity() -> None:
    broker = LogBroker(capacity=3)
    for i in range(5):
        broker.publish(f"line {i}")
    assert broker.history() == ["line 2", "line 3", "line 4"]


def test_broker_handler_publishes_formatted_record() -> None:
    broker = LogBroker(capacity=10)
    handler = BrokerHandler(broker)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    handler.emit(record)
    assert broker.history() == ["INFO:hello world"]


def test_configure_logging_wires_broker_handler() -> None:
    from devin_orchestrator.logging_setup import configure_logging

    configure_logging()
    handlers = logging.getLogger().handlers
    assert any(isinstance(h, BrokerHandler) for h in handlers)
    assert isinstance(LOG_BROKER, LogBroker)


def test_format_sse_single_and_multiline() -> None:
    assert format_sse("one line") == "data: one line\n\n"
    assert format_sse("a\nb") == "data: a\ndata: b\n\n"


@pytest.mark.asyncio
async def test_publish_fans_out_to_subscribers() -> None:
    broker = LogBroker(capacity=10)
    broker.attach_loop(asyncio.get_running_loop())
    queue = broker.subscribe()
    broker.publish("live line")
    await asyncio.sleep(0)  # let call_soon_threadsafe run
    assert queue.get_nowait() == "live line"


@pytest.mark.asyncio
async def test_stream_logs_replays_history_then_stops_on_disconnect() -> None:
    broker = LogBroker(capacity=10)
    broker.attach_loop(asyncio.get_running_loop())
    broker.publish("past 1")
    broker.publish("past 2")

    async def disconnected() -> bool:
        return True  # disconnect immediately after history

    events = [chunk async for chunk in stream_logs(broker, disconnected)]
    assert events == ["data: past 1\n\n", "data: past 2\n\n"]
    # The subscriber was cleaned up on exit.
    assert broker.subscriber_count == 0


@pytest.mark.asyncio
async def test_stream_logs_emits_live_line() -> None:
    broker = LogBroker(capacity=10)
    broker.attach_loop(asyncio.get_running_loop())

    async def connected() -> bool:
        return False

    agen = stream_logs(broker, connected, keepalive=5.0)
    pending = asyncio.ensure_future(agen.__anext__())
    await asyncio.sleep(0.05)  # let the generator subscribe and block on get()
    broker.publish("live!")
    chunk = await asyncio.wait_for(pending, timeout=1.0)
    assert chunk == "data: live!\n\n"
    await agen.aclose()
    assert broker.subscriber_count == 0


def test_render_logs_page_is_self_contained_html() -> None:
    html = render_logs_page("novarz/superset")
    assert "<!doctype html>" in html
    assert "EventSource('/logs/stream')" in html
    assert "novarz/superset" in html
