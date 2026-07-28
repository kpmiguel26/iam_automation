from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def pending_marker_path(runtime_path: Path) -> Path:
    return runtime_path.with_name(f"{runtime_path.stem}.publish-pending.json")


def mark_publication_pending(runtime_path: Path, *, actor: str, reason: str) -> None:
    marker = pending_marker_path(runtime_path)
    marker.write_text(
        json.dumps(
            {
                "actor": actor,
                "reason": reason,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def clear_publication_pending(runtime_path: Path) -> None:
    pending_marker_path(runtime_path).unlink(missing_ok=True)


def publication_pending(runtime_path: Path | None) -> bool:
    return bool(runtime_path and pending_marker_path(runtime_path).is_file())
