"""Test fixtures: a populated token_calls.db for the regenerator tests."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id                INTEGER PRIMARY KEY,
  ts                TEXT    NOT NULL,
  tz_offset_min     INTEGER NOT NULL,
  task_id           TEXT    NOT NULL,
  session_id        TEXT,
  agent             TEXT    NOT NULL,
  task_kind         TEXT,
  provider          TEXT    NOT NULL,
  account_tier      TEXT    NOT NULL,
  model             TEXT    NOT NULL,
  endpoint          TEXT,
  prompt_uncached   INTEGER NOT NULL DEFAULT 0,
  prompt_cached     INTEGER NOT NULL DEFAULT 0,
  completion        INTEGER NOT NULL DEFAULT 0,
  reasoning         INTEGER NOT NULL DEFAULT 0,
  cost_reported     REAL,
  cost_derived      REAL,
  cost_status       TEXT,
  status            INTEGER NOT NULL,
  finish_reason     TEXT,
  attempt           INTEGER NOT NULL DEFAULT 1,
  fallback_reason   TEXT,
  ttft_ms           INTEGER,
  latency_ms        INTEGER,
  estimated         INTEGER NOT NULL DEFAULT 0
);
"""


def make_fixture_db(path: Path) -> Path:
    """Create a populated token_calls.db at `path` and return it.

    Includes enough rows to exercise the dashboard's summary, breakdown,
    latency, and error paths. Deterministic — same data every run.
    """
    if path.exists():
        path.unlink()
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    now = datetime.now(tz=timezone.utc)
    rows = [
        # provider, model, account_tier, prompt_uncached, prompt_cached,
        # completion, reasoning, cost_derived, status, latency_ms, ts_offset_min
        ("openrouter", "nemotron:free", "free", 100, 0, 50, 0, 0.0, 200, 800, -60),
        ("openrouter", "nemotron:free", "free", 120, 0, 60, 0, 0.0, 200, 850, -55),
        ("openrouter", "nemotron:free", "free", 110, 0, 55, 0, 0.0, 200, 820, -50),
        ("ollama-cloud", "minimax-m3", "metered", 200, 50, 100, 30, 0.0042, 200, 1100, -45),
        ("ollama-cloud", "minimax-m3", "metered", 220, 60, 110, 35, 0.0048, 200, 1200, -40),
        ("featherless", "zai-org/GLM-5.2", "metered", 180, 0, 90, 0, 0.0033, 200, 950, -35),
        ("featherless", "zai-org/GLM-5.2", "metered", 0, 0, 0, 0, 0.0, 429, 100, -30),
        ("deepseek", "deepseek-v4-pro", "metered", 300, 100, 150, 80, 0.0075, 200, 1600, -25),
        ("deepseek", "deepseek-v4-pro", "metered", 310, 110, 155, 90, 0.0081, 200, 1700, -20),
        ("deepseek", "deepseek-v4-flash", "metered", 90, 0, 45, 0, 0.0011, 200, 700, -15),
        ("openrouter", "nemotron:free", "free", 105, 0, 52, 0, 0.0, 200, 810, -10),
        ("openrouter", "nemotron:free", "free", 0, 0, 0, 0, 0.0, 502, 50, -5),
    ]
    for i, (provider, model, tier, pu, pc, c, r, cost, status, lat, off) in enumerate(rows):
        ts = (now + timedelta(minutes=off)).isoformat(timespec="milliseconds")
        con.execute(
            """INSERT INTO calls (
                 ts, tz_offset_min, task_id, agent, provider, account_tier,
                 model, prompt_uncached, prompt_cached, completion, reasoning,
                 cost_derived, status, latency_ms, estimated
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (ts, off, f"task-{i:03d}", "hermes", provider, tier,
             model, pu, pc, c, r, cost, status, lat),
        )
    con.commit()
    con.close()
    return path


def make_fixture_rate_table(path: Path) -> Path:
    """Write a minimal valid rate_table.yaml so the regenerator's
    RATE_TABLE read doesn't FileNotFoundError."""
    path.write_text("""\
# Minimal fixture rate table
- provider: ollama-cloud
  model: minimax-m3
  effective_from: 2026-01-01
  tier: metered
  input_per_mtok: 0.0
  cached_input_per_mtok: 0.0
  output_per_mtok: 0.0
- provider: openrouter
  model: nemotron:free
  effective_from: 2026-01-01
  tier: free
  input_per_mtok: 0.0
  cached_input_per_mtok: 0.0
  output_per_mtok: 0.0
""")
    return path