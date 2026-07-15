"""Diagnostic helpers: redaction, logging configuration, and failure capture.

Public API:
- ``redact(value)`` — returns ``value`` with API key and cookie values
  replaced by ``***``. Non-sensitive text is preserved unchanged.
- ``configure_logging(artifacts_dir)`` — configures the named
  ``browser_bot`` logger with a console handler plus a UTF-8 file
  handler whose path is ``run-<timestamp>.log`` under ``artifacts_dir``.
  Calling the function more than once clears previously installed
  handlers and writes a fresh log file, so concurrent runs and
  re-invocations do not duplicate handlers or overwrite history.
- ``capture_failure(tab, artifacts_dir, task_id)`` — writes a
  full-page screenshot (``<task_id>.png``) and a redacted, truncated
  HTML snapshot (``<task_id>.html``) for a single failed task. The
  original HTML is never written to disk; the snapshot is capped at
  200,000 characters.
"""

from __future__ import annotations

import logging
import re
import time
from itertools import count
from pathlib import Path
from typing import Any

_API_KEY_RE = re.compile(r"(MINIMAX_API_KEY=)[^\s;&'\"]+", re.IGNORECASE)
_COOKIE_RE = re.compile(r"(?<![\w-])(Cookie: )[^\r\n]+", re.IGNORECASE)
_HTML_MAX_CHARS = 200_000
_LOGGER_NAME = "browser_bot"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"

# Monotonic counter so back-to-back calls always produce a distinct log
# file even on systems where ``time.time_ns()`` has poor resolution.
_LOG_COUNTER = count()


def redact(value: str) -> str:
    """Return ``value`` with API keys and cookie values redacted.

    Replacements:
    - Case-insensitive ``MINIMAX_API_KEY=<value>`` -> ``MINIMAX_API_KEY=***``
    - Case-insensitive ``Cookie: <value>`` -> ``Cookie: ***`` (the
      negative lookbehind avoids matching inside ``Set-Cookie:``)

    Non-sensitive text is returned unchanged.
    """
    if not value:
        return value
    value = _API_KEY_RE.sub(r"\1***", value)
    value = _COOKIE_RE.sub(r"\1***", value)
    return value


def configure_logging(artifacts_dir: Path) -> logging.Logger:
    """Configure the ``browser_bot`` logger with console + file handlers.

    Creates ``artifacts_dir`` if it does not exist. Each call produces a
    fresh timestamped log file ``run-<timestamp>.log`` and clears
    previously installed handlers, so calling this multiple times does
    not duplicate handlers or overwrite earlier runs.
    """
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(console)

    # Combine a human-readable timestamp with a process-wide counter so
    # consecutive calls always produce a distinct file even on systems
    # where ``time.time_ns()`` has poor resolution.
    log_path = artifacts_dir / f"run-{time.time_ns()}-{next(_LOG_COUNTER)}.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(file_handler)

    logger.propagate = False
    return logger


def capture_failure(tab: Any, artifacts_dir: Path, task_id: str) -> None:
    """Capture a screenshot and a redacted HTML snapshot of the current page.

    Writes:
    - ``<task_id>.png`` via ``tab.get_screenshot(path, name, full_page=True)``
    - ``<task_id>.html`` from ``tab.html`` after ``redact()`` and
      truncation to 200,000 characters

    The original HTML is never persisted. Screenshot failures are
    silently swallowed so diagnostics never break the business flow.
    """
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    if hasattr(tab, "get_screenshot"):
        try:
            tab.get_screenshot(
                path=str(artifacts_dir), name=f"{task_id}.png", full_page=True
            )
        except Exception:
            pass

    raw_html = getattr(tab, "html", "")
    if isinstance(raw_html, str) and raw_html:
        redacted = redact(raw_html)
        truncated = redacted[:_HTML_MAX_CHARS]
        (artifacts_dir / f"{task_id}.html").write_text(truncated, encoding="utf-8")
