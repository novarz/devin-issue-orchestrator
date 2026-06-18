"""Logging configuration for the orchestrator.

Provides a compact, demo-friendly formatter with optional ANSI colour and
per-level icons, plus a plain mode for production/log shippers. Configured
entirely from the environment so it can run before full ``Settings`` exist:

  * ``LOG_LEVEL``  - DEBUG | INFO | WARNING | ERROR (default INFO)
  * ``LOG_FORMAT`` - demo | plain (default demo)
  * ``LOG_COLOR``  - 1/0 to force colour on/off (default: auto-detect TTY)

``NO_COLOR`` (https://no-color.org) is honoured when set.
"""

from __future__ import annotations

import logging
import os
import sys

RESET = "\033[0m"

_LEVEL_COLORS = {
    logging.DEBUG: "\033[38;5;245m",  # grey
    logging.INFO: "\033[38;5;39m",  # blue
    logging.WARNING: "\033[38;5;214m",  # amber
    logging.ERROR: "\033[38;5;203m",  # red
    logging.CRITICAL: "\033[1;38;5;231;48;5;160m",  # white on red
}

_LEVEL_ICONS = {
    logging.DEBUG: "•",
    logging.INFO: "i",
    logging.WARNING: "!",
    logging.ERROR: "x",
    logging.CRITICAL: "X",
}


def _bool_env(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class DemoFormatter(logging.Formatter):
    """Colourful single-line formatter tuned for live demos."""

    def __init__(self, color: bool) -> None:
        super().__init__(datefmt="%H:%M:%S")
        self._color = color

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, self.datefmt)
        icon = _LEVEL_ICONS.get(record.levelno, "i")
        level = record.levelname.ljust(7)
        name = record.name.replace("devin_orchestrator", "orch")
        message = record.getMessage()
        line = f"{ts} {icon} {level} {name:<22} {message}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        if self._color:
            color = _LEVEL_COLORS.get(record.levelno, "")
            return f"{color}{line}{RESET}"
        return line


def _should_color(fmt: str) -> bool:
    forced = _bool_env("LOG_COLOR")
    if forced is not None:
        return forced
    if os.environ.get("NO_COLOR") is not None:
        return False
    if fmt != "demo":
        return False
    return sys.stderr.isatty()


def configure_logging() -> None:
    """Install the configured handler/formatter on the root logger."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = os.environ.get("LOG_FORMAT", "demo").strip().lower()

    handler = logging.StreamHandler(stream=sys.stderr)
    if fmt == "plain":
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    else:
        handler.setFormatter(DemoFormatter(color=_should_color(fmt)))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def banner(repo: str, dry_run: bool) -> str:
    """Return a multi-line startup banner for the logs."""
    mode = "DRY-RUN (no Devin/GitHub writes)" if dry_run else "LIVE"
    return (
        "\n"
        "  ____             _         ___           _           \n"
        " |  _ \\  _____   _(_)_ __   / _ \\ _ __ ___| |__   ___  \n"
        " | | | |/ _ \\ \\ / / | '_ \\ | | | | '__/ __| '_ \\ / _ \\ \n"
        " | |_| |  __/\\ V /| | | | || |_| | | | (__| | | |  __/ \n"
        " |____/ \\___| \\_/ |_|_| |_| \\___/|_|  \\___|_| |_|\\___| \n"
        "        Devin Issue Orchestrator\n"
        f"        repo={repo}  mode={mode}\n"
    )
