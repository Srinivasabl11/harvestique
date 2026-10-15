"""Request id + one log line per request (pure ASGI, so streaming responses are untouched).

The id comes from a well-formed X-Request-ID header (the app or a proxy may send one) or is generated; it is
returned in the response header, attached to every log line of the request and put in 500 error bodies, so a
failure seen on a phone can be found in the server log. The line holds method, route TEMPLATE (never ids, query
strings or bodies), status and duration only: no tokens, phone numbers or photos."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any

from app.core.logging import request_id_var

logger = logging.getLogger("harvestique.request")
_GOOD_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_QUIET = ("/health/live",)  # polled by the host every few seconds: logged at DEBUG only
_SLOW_MS = 10_000


class RequestLogMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _GOOD_ID.match(incoming) else uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status = 500
        started_response = False

        async def send_with_id(message: dict[str, Any]) -> None:
            nonlocal status, started_response
            if message["type"] == "http.response.start":
                started_response = True
                status = int(message["status"])
                message["headers"] = [*message.get("headers", []), (b"x-request-id", rid.encode("latin-1"))]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            # An unhandled error: answer here (not in Starlette's outer error middleware, which runs after this
            # request's id is gone) with the safe envelope plus the id, and log the traceback under that id.
            logger.exception("Unhandled error")
            if status == 500 and not started_response:
                body = json.dumps(
                    {
                        "error": {
                            "code": "internal_error",
                            "message": f"Internal server error (reference {rid})",
                            "details": {"request_id": rid},
                        }
                    }
                ).encode()
                await send_with_id(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send_with_id({"type": "http.response.body", "body": body})
            raise  # standard ASGI semantics: the server (and test clients) still see the error
        finally:
            ms = int((time.perf_counter() - started) * 1000)
            # the matched route as a template: each path parameter value is put back as {name} (no ids logged)
            path = str(scope.get("path", "")) if scope.get("route") is not None else "unmatched"
            for name, value in (scope.get("path_params") or {}).items():
                path = path.replace(str(value), "{" + name + "}")
            level = logging.DEBUG if path.endswith(_QUIET) and status < 400 else logging.INFO
            if status >= 500 or ms >= _SLOW_MS:
                level = logging.WARNING
            client = headers.get(b"x-client-version", b"").decode("latin-1")[:32]
            logger.log(
                level,
                "%s %s -> %s in %d ms",
                scope.get("method"),
                path,
                status,
                ms,
                extra={
                    "method": scope.get("method"),
                    "path": path,
                    "status": status,
                    "duration_ms": ms,
                    **({"client_version": client} if client else {}),
                },
            )
            request_id_var.reset(token)
