"""HTTP server for the token-dashboard.

Mirrors the gallery-base REFRESH_INTERVAL pattern (minimal): on startup
regenerate the dashboard immediately, then on a background thread every
N seconds. Serve /data/index.html on / and a JSON /health.

Block forever. Intended to be the CMD of the container.
"""
from __future__ import annotations

import http.server
import json
import logging
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from dashboard.regenerator import regenerate

logger = logging.getLogger("token-dashboard")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class _Handler(BaseHTTPRequestHandler):
    output_dir: Path = Path("/data")  # set by serve() before server starts

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        if self.path == "/health":
            self._send_health()
            return
        if self.path in ("/", "/index.html"):
            self._send_index()
            return
        self.send_error(404, "not found")

    def _send_health(self):
        index_html = self.output_dir / "index.html"
        body = json.dumps({
            "status": "ok",
            "index_exists": index_html.exists(),
            "index_size": index_html.stat().st_size if index_html.exists() else 0,
            "ts": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_index(self):
        index_html = self.output_dir / "index.html"
        if not index_html.exists():
            self.send_error(503, "dashboard not yet generated")
            return
        body = index_html.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Quiet by default — the container logs INFO-level regenerations.
        pass


def _regenerator_loop(db_path: Path, output_dir: Path, interval_s: int, stop: threading.Event, rate_table_path: Optional[Path] = None):
    """Background thread: regenerate every interval_s seconds."""
    while not stop.is_set():
        try:
            out = regenerate(db_path, output_dir / "index.html", rate_table_path=rate_table_path)
            logger.info("regenerated dashboard: %s (%d bytes)", out, out.stat().st_size)
        except Exception:
            logger.exception("regeneration failed")
        # Wait, but be interruptible
        stop.wait(interval_s)


def serve(
    output_dir: Path,
    port: int,
    refresh_interval: int = 300,
    db_path: Optional[Path] = None,
    rate_table_path: Optional[Path] = None,
    host: str = "0.0.0.0",
) -> None:
    """Start the dashboard server. Blocks forever.

    Args:
        output_dir: where to write index.html (and where to serve from).
        port: TCP port to bind.
        refresh_interval: seconds between regenerations. Default: 300 (5min).
        db_path: token_calls.db to read. Default: /data/token_calls.db
                 (the convention for the Runtipi mount).
        rate_table_path: rate_table.yaml to read. Default: /data/rate_table.yaml
                         (the convention for the Runtipi mount).
        host: bind address. Default: 0.0.0.0.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    db = Path(db_path) if db_path else Path("/data/token_calls.db")
    rt = Path(rate_table_path) if rate_table_path else Path("/data/rate_table.yaml")

    # Initial regeneration (synchronous, so /health is honest)
    if db.exists():
        try:
            out = regenerate(db, output_dir / "index.html", rate_table_path=rt)
            logger.info("initial regeneration: %s (%d bytes)", out, out.stat().st_size)
        except Exception:
            logger.exception("initial regeneration failed")
    else:
        logger.warning("db not found at %s; serving stale or empty dashboard", db)

    # Background regenerator thread
    stop = threading.Event()
    t = threading.Thread(
        target=_regenerator_loop,
        args=(db, output_dir, refresh_interval, stop, rt),
        daemon=True,
        name="regenerator",
    )
    t.start()

    # HTTP server
    _Handler.output_dir = output_dir
    server = ThreadingHTTPServer((host, port), _Handler)
    logger.info("serving on %s:%d, output_dir=%s, refresh_interval=%ds",
                host, port, output_dir, refresh_interval)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop.set()
        server.shutdown()


def main() -> None:
    """CLI entry point for `python -m dashboard.server`."""
    import os
    output_dir = Path(os.environ.get("DATA_DIR", "/data"))
    port = int(os.environ.get("PORT", "8000"))
    refresh_interval = int(os.environ.get("REFRESH_INTERVAL", "300"))
    db_path_str = os.environ.get("DB_PATH")
    db_path = Path(db_path_str) if db_path_str else None
    rate_table_str = os.environ.get("RATE_TABLE_PATH")
    rate_table_path = Path(rate_table_str) if rate_table_str else None
    serve(
        output_dir=output_dir,
        port=port,
        refresh_interval=refresh_interval,
        db_path=db_path,
        rate_table_path=rate_table_path,
    )


if __name__ == "__main__":
    main()