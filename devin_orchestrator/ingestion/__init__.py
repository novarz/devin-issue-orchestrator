"""Ingestion adapters (the swappable edge of the orchestrator)."""

from .base import IngestionAdapter
from .polling import PollingIngestionAdapter

__all__ = ["IngestionAdapter", "PollingIngestionAdapter"]
