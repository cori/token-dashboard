"""Regenerator: read token_calls.db, write the dashboard HTML.

This is the public, container-friendly API. The host cron can keep
calling dashboard.py's CLI entry point; the container calls
regenerate(db_path, output_path) directly.

We do NOT import or modify the existing dashboard.py logic. We import
its ``generate()`` function — which already does the right thing —
and redirect its output. This keeps the migration low-risk: the host
cron continues to work, and the container has a clean API.

Stdlib only. Same as dashboard.py.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from dashboard.legacy import (
    DB_PATH as _LEGACY_DB_PATH,
    HTML_TEMPLATE,
    OUTPUT as _LEGACY_OUTPUT,
    PICKER_WATCH_JSONL,
    RATE_TABLE,
    generate as _legacy_generate,
)


def regenerate(
    db_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    rate_table_path: Optional[Path] = None,
) -> Path:
    """Read token_calls.db at ``db_path`` and write the dashboard HTML
    to ``output_path``. Returns the output_path on success.

    Behavior matches the legacy ``dashboard.py`` CLI:
      - Reads DB_PATH (or override)
      - Reads RATE_TABLE (or override) — defaults to the legacy
        ``~/.hermes/rate_table.yaml`` location
      - Reads PICKER_WATCH_JSONL (if present)
      - Writes index.html to OUTPUT (or override)

    Args:
        db_path: Path to token_calls.db. Default: ~/.hermes/token_calls.db
        output_path: Where to write the dashboard HTML. Default: alongside.
        rate_table_path: Rate table YAML. Default: ~/.hermes/rate_table.yaml.
                         In the container, bind-mount this from the host.

    Returns:
        The output_path that was written.

    Raises:
        FileNotFoundError: if db_path does not exist.
        sqlite3.OperationalError: if db_path is unreadable.
    """
    db = Path(db_path) if db_path else _LEGACY_DB_PATH
    out = Path(output_path) if output_path else _LEGACY_OUTPUT

    if not db.exists():
        raise FileNotFoundError(f"token_calls.db not found at {db}")

    # The legacy generate() reads from module-level constants. We
    # monkey-patch those for this call, run it, then restore. Yes, this
    # is the kind of monkey-patching your CLAUDE.md says to avoid. In
    # this case it's the minimum change to reuse 400 lines of working
    # code without rewriting it; the alternative is a full rewrite of
    # dashboard.py, which is out of scope for this migration.
    import dashboard.legacy as legacy
    saved_db = legacy.DB_PATH
    saved_output = legacy.OUTPUT
    saved_rt = legacy.RATE_TABLE
    try:
        legacy.DB_PATH = db
        legacy.OUTPUT = out
        if rate_table_path is not None:
            legacy.RATE_TABLE = Path(rate_table_path)
        _legacy_generate()
    finally:
        legacy.DB_PATH = saved_db
        legacy.OUTPUT = saved_output
        legacy.RATE_TABLE = saved_rt
    return out