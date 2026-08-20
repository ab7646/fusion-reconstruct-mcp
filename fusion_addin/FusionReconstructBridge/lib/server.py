"""Local-only HTTP server exposing the bridge's actions at POST /command.

Stdlib only (http.server) - Fusion's embedded Python interpreter has no pip
access, so this add-in cannot depend on third-party packages the way the MCP
server side does.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import handlers, thread_bridge

_httpd = None
_thread = None


class _RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # keep Fusion's Text Commands palette / console quiet

    def do_POST(self):
        if self.path != "/command":
            self._respond(404, {"ok": False, "error": f"no such endpoint: {self.path}"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw or b"{}")
            action = body["action"]
            params = body.get("params") or {}
            fn = handlers.ACTIONS.get(action)
            if fn is None:
                raise ValueError(f"Unknown action '{action}'. Known actions: {sorted(handlers.ACTIONS)}")
            result = thread_bridge.run_on_main_thread(fn, params)
            self._respond(200, {"ok": True, "result": result})
        except Exception as exc:
            # Bridge-level failures (bad params, Fusion API errors, timeouts)
            # come back as HTTP 200 with ok=False - the MCP-side client
            # checks the "ok" field, matching a JSON-RPC-ish convention
            # rather than relying on HTTP status semantics for app errors.
            self._respond(200, {"ok": False, "error": str(exc)})

    def _respond(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start(host: str, port: int) -> None:
    global _httpd, _thread
    if _httpd is not None:
        return  # already running (e.g. add-in re-run without a clean stop)
    _httpd = ThreadingHTTPServer((host, port), _RequestHandler)
    _thread = threading.Thread(target=_httpd.serve_forever, name="FusionReconstructBridge-http", daemon=True)
    _thread.start()


def stop() -> None:
    global _httpd, _thread
    if _httpd is not None:
        _httpd.shutdown()
        _httpd.server_close()
    _httpd = None
    _thread = None
