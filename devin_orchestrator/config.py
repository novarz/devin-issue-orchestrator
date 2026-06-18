"""Configuration loaded exclusively from environment variables.

No secret is ever hard-coded or persisted to disk by the orchestrator.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings sourced from the environment."""

    # GitHub
    github_token: str
    github_repo: str  # "owner/name"
    github_api_url: str = "https://api.github.com"

    # Devin v3 API
    devin_api_key: str = ""
    devin_org_id: str = ""
    devin_base_url: str = "https://api.devin.ai/v3"

    # Orchestration behaviour
    poll_interval_seconds: float = 60.0
    session_poll_interval_seconds: float = 30.0
    session_timeout_seconds: float = 3600.0
    max_acu_limit: int = 10
    max_retries: int = 2
    expected_base_branch: str = "master"
    needs_human_label: str = "needs-human"
    issue_label_filter: str = ""  # only process issues carrying this label
    bot_comment_marker: str = "<!-- devin-orchestrator -->"

    # Verification
    verify_await_ci: bool = True
    ci_timeout_seconds: float = 1800.0
    ci_poll_interval_seconds: float = 30.0

    # HTTP
    http_timeout_seconds: float = 30.0

    # Operational
    dry_run: bool = False  # when true, never call the Devin API (testing only)
    process_existing_on_start: bool = False

    labels: tuple[str, ...] = field(default=())

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            github_token=_require("GITHUB_TOKEN"),
            github_repo=_require("GITHUB_REPO"),
            github_api_url=os.environ.get(
                "GITHUB_API_URL", "https://api.github.com"
            ).rstrip("/"),
            devin_api_key=os.environ.get("DEVIN_API_KEY", "").strip(),
            devin_org_id=os.environ.get("DEVIN_ORG_ID", "").strip(),
            devin_base_url=os.environ.get(
                "DEVIN_BASE_URL", "https://api.devin.ai/v3"
            ).rstrip("/"),
            poll_interval_seconds=_get_float("POLL_INTERVAL_SECONDS", 60.0),
            session_poll_interval_seconds=_get_float(
                "SESSION_POLL_INTERVAL_SECONDS", 30.0
            ),
            session_timeout_seconds=_get_float("SESSION_TIMEOUT_SECONDS", 3600.0),
            max_acu_limit=_get_int("MAX_ACU_LIMIT", 10),
            max_retries=_get_int("MAX_RETRIES", 2),
            expected_base_branch=os.environ.get("EXPECTED_BASE_BRANCH", "master"),
            needs_human_label=os.environ.get("NEEDS_HUMAN_LABEL", "needs-human"),
            issue_label_filter=os.environ.get("ISSUE_LABEL_FILTER", "").strip(),
            verify_await_ci=_get_bool("VERIFY_AWAIT_CI", True),
            ci_timeout_seconds=_get_float("CI_TIMEOUT_SECONDS", 1800.0),
            ci_poll_interval_seconds=_get_float("CI_POLL_INTERVAL_SECONDS", 30.0),
            http_timeout_seconds=_get_float("HTTP_TIMEOUT_SECONDS", 30.0),
            dry_run=_get_bool("DRY_RUN", False),
            process_existing_on_start=_get_bool("PROCESS_EXISTING_ON_START", False),
        )

    def validate_for_live(self) -> None:
        """Ensure Devin credentials exist unless running in dry-run mode."""
        if self.dry_run:
            return
        if not self.devin_api_key:
            raise ConfigError("DEVIN_API_KEY is required unless DRY_RUN=true")
        if not self.devin_org_id:
            raise ConfigError("DEVIN_ORG_ID is required unless DRY_RUN=true")

    @property
    def max_attempts(self) -> int:
        """Total attempts allowed = first attempt + retries."""
        return self.max_retries + 1
