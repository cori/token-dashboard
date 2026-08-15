# Re-export dashboard.generate and the helpers it needs, so callers
# (the host cron, the container regenerator) can import from a single
# stable namespace.
from dashboard.legacy import generate  # noqa: F401

__all__ = ["generate"]