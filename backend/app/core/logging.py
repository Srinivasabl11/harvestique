"""Logging configuration: plain text for development, one JSON object per line in production (LOG_FORMAT=json), so
a hosting log viewer can filter by level, request id, path or status. Every line carries the request id (or "-")."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] :: %(message)s"
# extra fields the request log adds; copied into JSON lines when present
_EXTRA = ("method", "path", "status", "duration_ms", "client_version")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key in _EXTRA:
            if hasattr(record, key):
                out[key] = getattr(record, key)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    if not any(getattr(h, "_harvestique", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.addFilter(_RequestIdFilter())
        handler._harvestique = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    for h in root.handlers:
        if getattr(h, "_harvestique", False):
            h.setFormatter(JsonFormatter() if fmt == "json" else logging.Formatter(_FORMAT))
