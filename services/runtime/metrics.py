"""Minimal Prometheus-style metrics and health server utilities."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Dict, Tuple

try:  # pragma: no cover - ImportError path exercised in CI envs without stdlib http.server
    from http.server import BaseHTTPRequestHandler, HTTPServer

    HAVE_HTTP = True
except Exception:  # pragma: no cover - defensive
    HAVE_HTTP = False

StatusFn = Callable[[], Tuple[bool, str]]


class Metrics:
    """Thread-safe metrics container supporting counters and gauges."""

    def __init__(self) -> None:
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._lock = threading.Lock()

    def inc(self, name: str, amount: float = 1.0) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0.0) + amount

    def set(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def snapshot(self) -> Tuple[Dict[str, float], Dict[str, float]]:
        with self._lock:
            return dict(self._counters), dict(self._gauges)

    def render(self) -> str:
        counters, gauges = self.snapshot()
        lines = []
        for key, value in counters.items():
            lines.append(f"# TYPE {key} counter\n{key} {value}")
        for key, value in gauges.items():
            lines.append(f"# TYPE {key} gauge\n{key} {value}")
        return "\n".join(lines) + "\n"


class MetricsServer:
    """Expose metrics and health endpoints or fall back to console logging."""

    def __init__(
        self,
        metrics: Metrics,
        port: int,
        *,
        logger: logging.Logger | None = None,
        health_cb: StatusFn | None = None,
        ready_cb: StatusFn | None = None,
        console_interval: int = 30,
    ) -> None:
        self.metrics = metrics
        self.port = port
        self.logger = logger or logging.getLogger("metrics")
        self.health_cb = health_cb or (lambda: (True, "ok"))
        self.ready_cb = ready_cb or (lambda: (True, "ready"))
        self.console_interval = max(5, console_interval)
        self._http_thread: threading.Thread | None = None
        self._httpd: HTTPServer | None = None
        self._console_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if HAVE_HTTP and self.port > 0:
            try:
                self._start_http()
                return
            except OSError as exc:  # pragma: no cover - depends on runtime port availability
                self.logger.warning("metrics.http.unavailable", extra={"error": str(exc)})
        self._start_console()

    def _start_http(self) -> None:
        server_ref = self

        class Handler(BaseHTTPRequestHandler):  # pragma: no cover - exercised in integration
            protocol_version = "HTTP/1.1"

            def _write(self, code: int, body: str) -> None:
                payload = body.encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:  # type: ignore[override]
                if self.path == "/metrics":
                    self._write(200, server_ref.metrics.render())
                    return
                if self.path == "/healthz":
                    ok, message = server_ref.health_cb()
                    self._write(200 if ok else 503, message + "\n")
                    return
                if self.path == "/readyz":
                    ok, message = server_ref.ready_cb()
                    self._write(200 if ok else 503, message + "\n")
                    return
                self._write(404, "not found\n")

            def log_message(self, *_args: object, **_kwargs: object) -> None:  # noqa: D401
                """Silence default logging to stderr."""

        self._httpd = HTTPServer(("0.0.0.0", self.port), Handler)
        self._http_thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._http_thread.start()
        self.logger.info("metrics.http.started", extra={"port": self.port})

    def _start_console(self) -> None:
        if self._console_thread:
            return

        def loop() -> None:
            while not self._stop_event.wait(self.console_interval):
                counters, gauges = self.metrics.snapshot()
                payload = {"counters": counters, "gauges": gauges}
                self.logger.info("metrics.console", extra=payload)

        self._console_thread = threading.Thread(target=loop, daemon=True)
        self._console_thread.start()
        self.logger.info("metrics.console.started", extra={"interval_sec": self.console_interval})

    def stop(self) -> None:
        self._stop_event.set()
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:  # pragma: no cover - defensive
                pass
        if self._http_thread:
            self._http_thread.join(timeout=2)
        if self._console_thread:
            self._console_thread.join(timeout=2)
        self.logger.info("metrics.stopped")
