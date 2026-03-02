"""Centralised logging setup — called once at application startup."""

from __future__ import annotations

import logging

from src.core.config import LoggingConfig


def setup_logging(cfg: LoggingConfig) -> None:
    """Configure the root logger from the LoggingConfig dataclass."""
    numeric_level = getattr(logging, cfg.level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format=cfg.format,
        force=True,
    )
