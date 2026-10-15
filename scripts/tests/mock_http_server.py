"""Local stand-in for the responses verify-production.ps1 must read (used by test_http_helper.ps1).

Listens on 127.0.0.1 on a free port, prints the port on the first line, and serves until killed:
  GET  /ok                200 JSON
  POST /auth/login        401 {"error": {"code": "invalid_credentials", ...}}, sent CHUNKED like production
                          (Render/Cloudflare): PowerShell 5.1's Invoke-WebRequest then loses the body
  POST /echo              200, returns the JSON body it received
  GET  /redirect          301 Location: https://example.test/redirect         (must not be followed / not status 0)
  GET  /boom              500 {"error": {"code": "internal_error", ...}}, chunked
  OPTIONS /cors           400 without Access-Control-Allow-Origin
Standard library only.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # needed for chunked transfer encoding

    def _send_chunked(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Connection", "close")
        self.end_headers()
        for i in range(0, len(data), 16):  # several chunks, no Content-Length
            part = data[i : i + 16]
            self.wfile.write(f"{len(part):x}\r\n".encode() + part + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")

    def _send(self, status: int, body: dict | None = None, headers: dict[str, str] | None = None) -> None:
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # http.server calls do_<METHOD>
        if self.path == "/ok":
            self._send(200, {"status": "ok"})
        elif self.path == "/redirect":
            self._send(301, None, {"Location": "https://example.test/redirect"})
        elif self.path == "/boom":
            self._send_chunked(500, {"error": {"code": "internal_error", "message": "Internal server error"}})
        else:
            self._send(404, {"detail": "Not Found"})

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/auth/login":
            error = {"code": "invalid_credentials", "message": "Invalid phone number or password"}
            self._send_chunked(401, {"error": error})
        elif self.path == "/echo":
            self._send(200, {"received": json.loads(raw or b"null"), "content_type": self.headers.get("Content-Type")})
        else:
            self._send(404, {"detail": "Not Found"})

    def do_OPTIONS(self) -> None:
        self._send(400, {"detail": "Disallowed CORS origin"})

    def log_message(self, *args: object) -> None:  # keep the test output clean
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(server.server_address[1], flush=True)
    sys.stdout.flush()
    server.serve_forever()
