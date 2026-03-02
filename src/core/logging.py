"""
Centralised logging setup — called once at application startup.

Supports three output targets (all independently configurable):
  1. Console (stderr) — human-readable, always on
  2. Rotating text file — same human-readable format, optional
  3. Rotating JSON Lines file — structured logs for parsing/monitoring, optional
"""

from __future__ import annotations

import json as _json
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from src.core.config import LoggingConfig


class _JsonFormatter(logging.Formatter):
    """Emits one JSON object per line — easy to parse, grep, or ship to a log aggregator."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        for attr in ("phone", "direction", "status", "error_code", "score", "event"):
            val = getattr(record, attr, None)
            if val is not None:
                entry[attr] = val
        return _json.dumps(entry, ensure_ascii=False)


def setup_logging(cfg: LoggingConfig) -> None:
    """Configure the root logger with all enabled handlers."""

    numeric_level = getattr(logging, cfg.level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setLevel(numeric_level)
    console.setFormatter(logging.Formatter(cfg.format))
    root.addHandler(console)

    if cfg.file_enabled:
        _add_rotating_file(root, cfg.file_path, cfg.file_max_bytes,
                           cfg.file_backup_count, cfg.format, numeric_level)

    if cfg.json_enabled:
        _add_rotating_json(root, cfg.json_path, cfg.json_max_bytes,
                           cfg.json_backup_count, numeric_level)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _add_rotating_file(
    root: logging.Logger,
    path_str: str,
    max_bytes: int,
    backup_count: int,
    fmt: str,
    level: int,
) -> None:
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt))
    root.addHandler(handler)


def _add_rotating_json(
    root: logging.Logger,
    path_str: str,
    max_bytes: int,
    backup_count: int,
    level: int,
) -> None:
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
