"""The local website (http://127.0.0.1:8765): the dashboard page plus every component's endpoints."""
from __future__ import annotations

import json
import logging
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("gexpro.server")
DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"
ASSET_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
               ".png": "image/png", ".woff2": "font/woff2"}
ASSET_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")            # one plain file name: no folders, no ".." tricks
# the installable-app files live at the site's root (a service worker controls only its own folder and below)
ROOT_FILES = {"/manifest.webmanifest": "application/manifest+json", "/sw.js": "text/javascript; charset=utf-8"}


def collect_routes(components) -> dict:
    routes: dict = {}
    for c in components:
        for path, fn in c.routes().items():
            if path in routes:
                raise ValueError(f"two components claim {path}")
            routes[path] = fn
    return routes


def make_handler(components):
    routes = collect_routes(components)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.debug("http %s", fmt % args)

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                f = DASHBOARD / "index.html"           # read on every request: edits show up on reload
                if f.exists():
                    return self._send(200, f.read_bytes(), "text/html; charset=utf-8")
            if u.path in ROOT_FILES:
                return self._send(200, (DASHBOARD / u.path[1:]).read_bytes(), ROOT_FILES[u.path])
            if u.path.startswith("/assets/"):
                name = u.path[len("/assets/"):]
                f = DASHBOARD / "assets" / name
                if ASSET_NAME.match(name) and f.suffix in ASSET_TYPES and f.is_file():
                    return self._send(200, f.read_bytes(), ASSET_TYPES[f.suffix])
                return self._send(404, b'{"error": "not found"}', "application/json")
            fn = routes.get(u.path)
            if fn is None:
                return self._send(404, b'{"error": "not found"}', "application/json")
            try:
                code, body = fn(parse_qs(u.query))
            except Exception as e:                      # one failing endpoint never takes the site down
                log.exception("endpoint %s failed", u.path)
                code, body = 500, {"error": f"{type(e).__name__}: {e}"}
            if isinstance(body, str):
                return self._send(code, body.encode(), "text/plain; charset=utf-8")
            return self._send(code, json.dumps(body, default=str).encode(), "application/json")

    return Handler


class ExclusiveHTTPServer(ThreadingHTTPServer):
    """One server per port. Python's default (SO_REUSEADDR) lets a second copy bind the same port on
    Windows without any error, and the browser then silently keeps talking to the OLD copy."""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):                      # Windows
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve(components, host: str = "127.0.0.1", port: int = 8765) -> None:
    try:
        httpd = ExclusiveHTTPServer((host, port), make_handler(components))   # bind first: fail fast if port busy
    except OSError:
        print(f"\nGEX PRO is ALREADY RUNNING in another window, so this copy will not start.\n"
              f"Use that window, or close it and run START.bat again to pick up updates.\n"
              f"Website: http://{host}:{port}", flush=True)
        raise SystemExit(3)
    for c in components:
        c.start()
    log.info("serving on http://%s:%d (components: %s)", host, port, ", ".join(c.name for c in components))
    print(f"GEX PRO running - open http://{host}:{port}  (Ctrl+C to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for c in components:
            c.stop()
