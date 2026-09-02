from __future__ import annotations

import contextlib
import threading
import unittest
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tools.deployment.common import DeploymentError
from tools.deployment.health_check import check_deployment
from tools.deployment.tests.fixtures import build_runtime


_HTML = (
    b'<!doctype html><div id="root"></div>'
    b'<script type="module" src="/assets/app-123.js"></script>'
    b'<link rel="stylesheet" href="/assets/app-123.css">'
)


def _content_type(path: str) -> str:
    if path == "/" or path.endswith(".html"):
        return "text/html; charset=utf-8"
    if path.endswith(".js"):
        return "application/javascript"
    if path.endswith(".css"):
        return "text/css"
    if path.endswith(".json"):
        return "application/json"
    if path.endswith(".webp"):
        return "image/webp"
    return "application/octet-stream"


@contextlib.contextmanager
def serve(
    *,
    bad_cache_path: str | None = None,
    missing_as_spa: bool = False,
) -> Iterator[str]:
    runtime, _ = build_runtime()
    routes = {
        "/": _HTML,
        "/assets/app-123.js": b"console.log('fixture')\n",
        "/assets/app-123.css": b"body{}\n",
        **runtime,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = routes.get(self.path)
            if body is None:
                if missing_as_spa:
                    body = _HTML
                    status = 200
                else:
                    body = b"not found\n"
                    status = 404
            else:
                status = 200
            self.send_response(status)
            self.send_header("Content-Type", _content_type(self.path if status == 200 else ".txt"))
            if status == 404:
                cache = "no-store"
            elif self.path in {"/", "/datasets/index.json"} or self.path.startswith(
                "/datasets/manifests/"
            ):
                cache = "no-cache, must-revalidate"
            else:
                cache = "public, max-age=31536000, immutable"
            if self.path == bad_cache_path:
                cache = "public, max-age=31536000, immutable"
            self.send_header("Cache-Control", cache)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class HealthCheckTests(unittest.TestCase):
    def test_checks_discovered_runtime_graph(self) -> None:
        with serve() as base_url:
            result = check_deployment(base_url, timeout=2, cache_policy="strict")
        self.assertEqual(result["status"], "healthy")
        self.assertEqual(result["datasets"], 1)
        self.assertGreaterEqual(result["checked"], 10)

    def test_rejects_immutable_cache_on_mutable_index(self) -> None:
        with serve(bad_cache_path="/datasets/index.json") as base_url:
            with self.assertRaisesRegex(DeploymentError, "force revalidation"):
                check_deployment(base_url, timeout=2, cache_policy="strict")

    def test_warn_policy_reports_cache_problem(self) -> None:
        with serve(bad_cache_path="/datasets/index.json") as base_url:
            result = check_deployment(base_url, timeout=2, cache_policy="warn")
        self.assertTrue(result["warnings"])

    def test_rejects_spa_fallback_for_missing_dataset_file(self) -> None:
        with serve(missing_as_spa=True) as base_url:
            with self.assertRaisesRegex(DeploymentError, "must be 404"):
                check_deployment(base_url, timeout=2, cache_policy="strict")


if __name__ == "__main__":
    unittest.main()
