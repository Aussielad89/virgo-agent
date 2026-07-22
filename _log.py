"""
_log — shared logging setup for virgo.

Usage in any module::

    from _log import log
    log.info("Pipeline started")
    log.debug("Discovered %d files", n)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Allow import without crashing if dotenv is missing
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# Shared runtime-output directory. All generated reports (network maps,
# diagnostics, alerts, search memory, etc.) are written here instead of
# polluting the repo root. Git-ignored (see .gitignore: output/).
HERE = Path(__file__).resolve().parent
OUTDIR = HERE / "output"
OUTDIR.mkdir(exist_ok=True)


def _setup_logger(name: str = "virgo") -> logging.Logger:
    """Create and configure a logger with level from env / sane default.

    VIRGO_LOG_LEVEL  — DEBUG | INFO | WARNING | ERROR (default: INFO)
    VIRGO_LOG_FILE  — path to a log file (optional; stdout if not set)
    """
    logger = logging.getLogger(name)

    # Avoid duplicate handlers on re-import
    if logger.handlers:
        return logger

    level_name = os.environ.get("VIRGO_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    fmt = logging.Formatter("%(levelname)s [%(name)s] %(message)s")

    log_file = os.environ.get("VIRGO_LOG_FILE", "")
    if log_file:
        handler: logging.Handler = logging.FileHandler(log_file, encoding="utf-8")
    else:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(fmt)
    logger.addHandler(handler)

    return logger


log = _setup_logger()
