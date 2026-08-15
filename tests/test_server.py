"""Tests for dashboard.server — the HTTP serving layer.

Contract being tested:
    serve(output_dir: Path, port: int, refresh_interval: int,
          db_path: Path) -> None
        Blocks. On startup: regenerates immediately, then every refresh_interval
        seconds. HTTP server on port serves /data/index.html on /.

These tests use threading to spin up the server briefly in a thread.
"""
from __future__ import annotations

import http.client
import socket
import threading
import time
from pathlib import Path

import pytest

from dashboard.server import serve
from tests.conftest import make_fixture_db, make_fixture_rate_table


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_server_serves_index_html(tmp_path: Path):
    db = make_fixture_db(tmp_path / "token_calls.db")
    rt = make_fixture_rate_table(tmp_path / "rate_table.yaml")
    out = tmp_path / "out"
    out.mkdir()

    port = _free_port()
    # Run serve() in a thread. It blocks; we'll kill it after first response.
    t = threading.Thread(
        target=serve,
        args=(out, port, 60, db, rt),
        daemon=True,
    )
    t.start()

    # Wait for server up (max 2s)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            con = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            con.request("GET", "/")
            r = con.getresponse()
            body = r.read().decode()
            con.close()
            assert r.status == 200
            assert "Total Calls" in body or "total_calls" in body
            return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.05)
    raise AssertionError("server did not come up within 2s")


def test_server_health_endpoint_returns_ok(tmp_path: Path):
    db = make_fixture_db(tmp_path / "token_calls.db")
    rt = make_fixture_rate_table(tmp_path / "rate_table.yaml")
    out = tmp_path / "out"
    out.mkdir()

    port = _free_port()
    t = threading.Thread(
        target=serve,
        args=(out, port, 60, db, rt),
        daemon=True,
    )
    t.start()

    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            con = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            con.request("GET", "/health")
            r = con.getresponse()
            body = r.read().decode()
            con.close()
            assert r.status == 200
            assert "ok" in body.lower()
            return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.05)
    raise AssertionError("server did not come up within 2s")


def test_server_writes_index_html_on_startup(tmp_path: Path):
    db = make_fixture_db(tmp_path / "token_calls.db")
    rt = make_fixture_rate_table(tmp_path / "rate_table.yaml")
    out = tmp_path / "out"
    out.mkdir()

    port = _free_port()
    t = threading.Thread(
        target=serve,
        args=(out, port, 60, db, rt),
        daemon=True,
    )
    t.start()

    # Give it ~0.5s for the initial regeneration to land
    deadline = time.time() + 2.0
    while time.time() < deadline:
        if (out / "index.html").exists() and (out / "index.html").stat().st_size > 1000:
            return
        time.sleep(0.05)
    raise AssertionError("index.html not written on startup")