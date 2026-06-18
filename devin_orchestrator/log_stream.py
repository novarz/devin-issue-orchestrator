"""In-memory log fan-out for live streaming over Server-Sent Events.

A :class:`LogBroker` keeps a bounded ring buffer of recently formatted log
lines (so a new client immediately sees recent history) and fans every new
line out to any number of subscribed async consumers. A :class:`BrokerHandler`
plugs the broker into the standard logging stack.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from typing import AsyncIterator, Awaitable, Callable, Deque, Optional


class LogBroker:
    """Ring buffer of log lines plus a set of async subscriber queues."""

    def __init__(self, capacity: int = 500, queue_size: int = 1000) -> None:
        self._buffer: Deque[str] = deque(maxlen=capacity)
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._queue_size = queue_size
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the broker to the running event loop for thread-safe fan-out."""
        self._loop = loop

    def publish(self, line: str) -> None:
        """Record a line and deliver it to all subscribers (thread-safe)."""
        self._buffer.append(line)
        loop = self._loop
        if loop is None:
            return
        for queue in list(self._subscribers):
            loop.call_soon_threadsafe(self._safe_put, queue, line)

    @staticmethod
    def _safe_put(queue: "asyncio.Queue[str]", line: str) -> None:
        try:
            queue.put_nowait(line)
        except asyncio.QueueFull:
            pass

    def history(self) -> list[str]:
        return list(self._buffer)

    def subscribe(self) -> "asyncio.Queue[str]":
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[str]") -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


class BrokerHandler(logging.Handler):
    """Logging handler that publishes formatted records to a :class:`LogBroker`."""

    def __init__(self, broker: LogBroker) -> None:
        super().__init__()
        self._broker = broker

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:  # noqa: BLE001 - never let logging raise
            return
        self._broker.publish(message)


def format_sse(line: str) -> str:
    """Encode a (possibly multi-line) log line as one SSE event."""
    payload = "".join(f"data: {part}\n" for part in line.splitlines() or [""])
    return f"{payload}\n"


async def stream_logs(
    broker: LogBroker,
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    keepalive: float = 15.0,
) -> AsyncIterator[str]:
    """Yield SSE events: buffered history first, then live lines."""
    queue = broker.subscribe()
    try:
        for line in broker.history():
            yield format_sse(line)
        while not await is_disconnected():
            try:
                line = await asyncio.wait_for(queue.get(), timeout=keepalive)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield format_sse(line)
    finally:
        broker.unsubscribe(queue)


def _capacity_from_env() -> int:
    raw = os.environ.get("LOG_BUFFER_SIZE", "").strip()
    if not raw:
        return 500
    try:
        return max(1, int(raw))
    except ValueError:
        return 500


# Module-level broker shared by the logging setup and the HTTP endpoints.
LOG_BROKER = LogBroker(capacity=_capacity_from_env())
