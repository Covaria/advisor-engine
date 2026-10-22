"""Append-only audit log of assistant turns (one JSON object per line).

Lives under data/, which is gitignored, so logs stay local.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ._paths import AUDIT_PATH

_KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _redact(line: str) -> str:
    """Belt and braces: never let an API key reach disk, whatever is in the record."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if len(key) >= 8:
        line = line.replace(key, "[REDACTED]")
    return _KEY_PATTERN.sub("[REDACTED]", line)


def append_audit(record: dict, path: str | Path | None = None) -> dict:
    """Write `record` as one JSON line, adding timestamp and engine_version if absent.

    Expected keys: model, holdings_sha256, tool_calls (with outputs), reply,
    verification, blocked. Returns the record as written.
    """
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "engine_version": __version__,
        **record,
    }
    target = Path(path) if path else AUDIT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(_redact(json.dumps(record, default=str)) + "\n")
    return record
