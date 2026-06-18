"""Event-driven orchestration service that remediates GitHub issues via Devin.

This package contains *only* orchestration logic. It never modifies the source
code of the repository it remediates (Apache Superset) -- all code changes are
produced by Devin sessions created through the Devin REST API (v3).
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
