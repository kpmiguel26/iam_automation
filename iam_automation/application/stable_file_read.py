"""File reads that tolerate files still being synchronized by a provider."""

from __future__ import annotations

import time
from pathlib import Path


def read_stable_bytes(path: Path, *, attempts: int = 3, delay_seconds: float = 0.05) -> bytes:
    """Read bytes only when size and mtime remain stable for the whole read."""
    last_error: OSError | None = None
    for attempt in range(max(1, attempts)):
        try:
            before = path.stat()
            content = path.read_bytes()
            after = path.stat()
            if before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns:
                return content
            last_error = OSError(f"File changed while it was being read: {path}")
        except OSError as exc:
            last_error = exc
        if attempt + 1 < max(1, attempts):
            time.sleep(delay_seconds)
    raise last_error or OSError(f"Unable to read file: {path}")
