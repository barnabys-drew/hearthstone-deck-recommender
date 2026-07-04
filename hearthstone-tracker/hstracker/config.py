"""Locate the Hearthstone log directory and the tracker database."""
from __future__ import annotations

import os
from pathlib import Path

# Known install locations, checked in order. WSL sees Windows drives under /mnt.
LOG_ROOT_CANDIDATES = [
    "/mnt/d/Battle.net/Hearthstone/Logs",
    "/mnt/c/Program Files (x86)/Hearthstone/Logs",
    "/mnt/c/Battle.net/Hearthstone/Logs",
]

DEFAULT_DB = Path.home() / ".local" / "share" / "hearthstone-tracker" / "games.db"


def find_log_root(override: str | None = None) -> Path:
    if override:
        root = Path(override)
        if not root.is_dir():
            raise FileNotFoundError(f"Log directory not found: {root}")
        return root
    env = os.environ.get("HS_LOG_ROOT")
    if env:
        return find_log_root(env)
    for cand in LOG_ROOT_CANDIDATES:
        if Path(cand).is_dir():
            return Path(cand)
    raise FileNotFoundError(
        "Could not find the Hearthstone Logs directory. Pass --logs-root or set HS_LOG_ROOT."
    )


def session_dirs(log_root: Path) -> list[Path]:
    """Per-launch log folders (Hearthstone_YYYY_MM_DD_HH_MM_SS), oldest first."""
    return sorted(d for d in log_root.glob("Hearthstone_*") if d.is_dir())


def resolve_db_path(override: str | None = None) -> Path:
    path = Path(override) if override else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
