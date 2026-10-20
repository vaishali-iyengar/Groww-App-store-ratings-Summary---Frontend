"""Structured logging and run_id helper shared by every stage."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Optional


def new_run_id(now: Optional[datetime] = None) -> str:
    """Sortable run id, for example 20261004T091500Z."""
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "run_id": getattr(record, "run_id", None),
            "stage": getattr(record, "stage", None),
            "msg": record.getMessage(),
        }
        extra = getattr(record, "data", None)
        if extra:
            payload["data"] = extra
        return json.dumps(payload, default=str)


class StageLogger(logging.LoggerAdapter):
    """Logger bound to a run_id and stage name; extra fields go in `data`."""

    def process(self, msg: Any, kwargs: Any):
        data = kwargs.pop("data", None)
        extra = dict(self.extra)
        if data:
            extra["data"] = data
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(run_id: str, stage: str, level: int = logging.INFO) -> StageLogger:
    base = logging.getLogger("pulse")
    if not base.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_JsonFormatter())
        base.addHandler(handler)
        base.propagate = False
    base.setLevel(level)
    return StageLogger(base, {"run_id": run_id, "stage": stage})
