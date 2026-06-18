"""Unit tests for the demo logging setup."""

from __future__ import annotations

import logging

from devin_orchestrator.log_stream import BrokerHandler
from devin_orchestrator.logging_setup import DemoFormatter, banner, configure_logging


def _stream_handlers(root: logging.Logger) -> list[logging.Handler]:
    return [h for h in root.handlers if not isinstance(h, BrokerHandler)]


def _record(level: int = logging.INFO, msg: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(
        name="devin_orchestrator.orchestrator",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


def test_demo_formatter_plain_is_uncolored_and_shortens_name() -> None:
    line = DemoFormatter(color=False).format(_record())
    assert "\033[" not in line
    assert "orch.orchestrator" in line
    assert "hello" in line


def test_demo_formatter_color_wraps_ansi() -> None:
    line = DemoFormatter(color=True).format(_record(logging.WARNING, "watch out"))
    assert line.startswith("\033[")
    assert line.endswith("\033[0m")
    assert "watch out" in line


def test_configure_logging_respects_env(monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("LOG_FORMAT", "plain")
    configure_logging()
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    stream = _stream_handlers(root)
    assert len(stream) == 1
    # plain mode must never emit a DemoFormatter on the stream handler
    assert not isinstance(stream[0].formatter, DemoFormatter)
    # the broker handler is always attached for the /logs/stream endpoint
    assert any(isinstance(h, BrokerHandler) for h in root.handlers)


def test_no_color_env_disables_color(monkeypatch) -> None:
    monkeypatch.setenv("LOG_FORMAT", "demo")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("LOG_COLOR", raising=False)
    configure_logging()
    formatter = _stream_handlers(logging.getLogger())[0].formatter
    assert isinstance(formatter, DemoFormatter)
    assert "\033[" not in formatter.format(_record())


def test_banner_reports_mode_and_repo() -> None:
    assert "DRY-RUN" in banner("novarz/superset", dry_run=True)
    assert "LIVE" in banner("novarz/superset", dry_run=False)
    assert "novarz/superset" in banner("novarz/superset", dry_run=False)
