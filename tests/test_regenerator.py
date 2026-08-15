"""Tests for dashboard.regenerator — the RED/GREEN contract.

These tests are written FIRST (TDD). They fail because regenerator.py
does not exist yet. Make them pass by implementing regenerator.py.

Public API being tested:
    regenerate(db_path: Path, output_path: Path) -> None
        Reads token_calls.db at db_path, writes the dashboard HTML to output_path.
        Returns None on success; raises on failure (so the caller can log).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from dashboard.regenerator import regenerate


def test_regenerate_writes_html_file(tmp_path: Path):
    """regenerate() should create a non-empty index.html at output_path."""
    from tests.conftest import make_fixture_db

    db = make_fixture_db(tmp_path / "token_calls.db")
    out = tmp_path / "index.html"

    regenerate(db, out)

    assert out.exists(), "regenerate did not write output_path"
    assert out.stat().st_size > 1000, "output is suspiciously small"


def test_regenerate_output_contains_summary_card(tmp_path: Path):
    """Output should contain the summary card JS template."""
    from tests.conftest import make_fixture_db

    db = make_fixture_db(tmp_path / "token_calls.db")
    out = tmp_path / "index.html"

    regenerate(db, out)
    html = out.read_text()

    # The summary-card render uses these keys. Any version with these
    # in the embedded JSON is acceptable.
    for needle in ("total_calls", "total_tokens", "total_cost"):
        assert needle in html, f"missing summary key: {needle}"


def test_regenerate_output_contains_breakdown_table(tmp_path: Path):
    """Output should contain the per-(provider, model) breakdown."""
    from tests.conftest import make_fixture_db

    db = make_fixture_db(tmp_path / "token_calls.db")
    out = tmp_path / "index.html"

    regenerate(db, out)
    html = out.read_text()

    # Each provider we put in the fixture must appear at least once
    for provider in ("openrouter", "ollama-cloud", "featherless", "deepseek"):
        assert provider in html, f"missing provider in breakdown: {provider}"


def test_regenerate_output_contains_picker_watch_panel(tmp_path: Path):
    """Output should include the model-picker-watch panel (regression
    test: dashboard.wire-in is part of the contract)."""
    from tests.conftest import make_fixture_db

    db = make_fixture_db(tmp_path / "token_calls.db")
    out = tmp_path / "index.html"

    regenerate(db, out)
    html = out.read_text()

    assert "picker-watch-section" in html, "missing picker-watch panel"
    assert "VERDICT_GLYPH" in html, "missing verdict glyph mapping"


def test_regenerate_missing_db_raises(tmp_path: Path):
    """regenerate() with a missing db should raise (not silently write
    an empty dashboard)."""
    missing_db = tmp_path / "does-not-exist.db"
    out = tmp_path / "index.html"

    with pytest.raises(Exception):
        regenerate(missing_db, out)


def test_regenerate_is_deterministic_for_same_input(tmp_path: Path):
    """Two regenerations against the same DB must produce identical bytes.

    Important so a /health probe can cache-hash and detect stale output.
    """
    from tests.conftest import make_fixture_db

    db = make_fixture_db(tmp_path / "token_calls.db")
    out_a = tmp_path / "a.html"
    out_b = tmp_path / "b.html"

    regenerate(db, out_a)
    regenerate(db, out_b)

    # Both should have the same non-timestamp content. We compare
    # everything except the __TIMESTAMP__ line which legitimately varies.
    a = out_a.read_text().split("Generated ")[1].split("·")[1]
    b = out_b.read_text().split("Generated ")[1].split("·")[1]
    assert a == b


def test_regenerate_accepts_rate_table_override(tmp_path: Path):
    """regenerate() should accept a rate_table_path that overrides the
    hardcoded ~/.hermes/rate_table.yaml location. This is what the
    container uses to read the rate table from a bind-mount."""
    from tests.conftest import make_fixture_db, make_fixture_rate_table

    db = make_fixture_db(tmp_path / "token_calls.db")
    rt = make_fixture_rate_table(tmp_path / "rate_table.yaml")
    out = tmp_path / "index.html"

    # Should not raise — even though ~/.hermes/rate_table.yaml doesn't
    # exist in the test environment, we provided an override.
    regenerate(db, out, rate_table_path=rt)

    assert out.exists()
    assert out.stat().st_size > 1000