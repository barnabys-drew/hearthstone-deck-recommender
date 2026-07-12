"""Bridge files for the Hearthstone coach overlay.

The live tracker runs in WSL, but the native always-on-top overlay runs on the
Windows side.  This module writes tiny JSON files to a shared directory that a
Windows Electron process can poll without needing a server.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .config import DEFAULT_DB

_SYSTEM_WINDOWS_USERS = {
    "all users",
    "default",
    "default user",
    "defaultuser0",
    "desktop.ini",
    "public",
    "wsiaccount",
}
_VALID_KINDS = {"idle", "turn", "mulligan", "lethal", "update", "gameover"}


def _coerce_text(value: Any, *, max_len: int = 600) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def _coerce_steps(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = [line.strip() for line in value.splitlines()]
    elif isinstance(value, (list, tuple)):
        raw = [str(item).strip() for item in value]
    else:
        raw = [str(value).strip()]
    return [text[:240] + ("…" if len(text) > 240 else "") for text in raw if text][:12]


def _coerce_mulligan(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    result: list[dict[str, Any]] = []
    if not isinstance(value, list):
        value = [value]
    for item in value[:10]:
        if isinstance(item, dict):
            card = _coerce_text(item.get("card") or item.get("name"), max_len=80)
            if not card:
                continue
            result.append({
                "card": card,
                "keep": bool(item.get("keep")),
                "reason": _coerce_text(item.get("reason"), max_len=180),
            })
        else:
            text = _coerce_text(item, max_len=180)
            if text:
                result.append({"card": text, "keep": False, "reason": None})
    return result


def _coerce_lethal(value: Any, *, kind: str) -> dict[str, Any] | None:
    if value is None:
        if kind == "lethal":
            return {"is_lethal": True, "math": None}
        return None
    if isinstance(value, dict):
        return {
            "is_lethal": bool(value.get("is_lethal") or value.get("lethal") or kind == "lethal"),
            "math": _coerce_text(value.get("math"), max_len=160),
        }
    if isinstance(value, bool):
        return {"is_lethal": value or kind == "lethal", "math": None}
    return {"is_lethal": True, "math": _coerce_text(value, max_len=160)}


def default_overlay_dir() -> Path:
    """Best-effort default shared folder for a WSL tracker + Windows overlay."""
    env_user = os.environ.get("HS_WINDOWS_USER")
    users_root = Path("/mnt/c/Users")
    if env_user:
        return users_root / env_user / "hs-overlay"
    if users_root.is_dir():
        candidates = [
            path for path in users_root.iterdir()
            if path.is_dir() and path.name.lower() not in _SYSTEM_WINDOWS_USERS and not path.name.startswith(".")
        ]
        if len(candidates) == 1:
            return candidates[0] / "hs-overlay"
        for path in candidates:
            if path.name.lower() in {"drewt", "drewpweiner"}:
                return path / "hs-overlay"
    return DEFAULT_DB.parent / "overlay"


def resolve_overlay_dir(override: str | os.PathLike[str] | None = None) -> Path:
    raw = override or os.environ.get("HS_OVERLAY_DIR")
    return Path(raw).expanduser() if raw else default_overlay_dir()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def normalize_advice(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(payload or {})
    kind = str(payload.get("kind") or "turn").lower()
    if kind not in _VALID_KINDS:
        kind = "turn"
    turn = payload.get("turn")
    try:
        turn = int(turn) if turn is not None and str(turn).strip() else None
    except (TypeError, ValueError):
        turn = None

    advice = {
        "ts": float(payload.get("ts") or time.time()),
        "kind": kind,
        "turn": turn,
        "headline": _coerce_text(payload.get("headline"), max_len=120) or _default_headline(kind),
        "why": _coerce_text(payload.get("why"), max_len=900),
        "steps": _coerce_steps(payload.get("steps")),
        "warning": _coerce_text(payload.get("warning"), max_len=240),
        "lethal": _coerce_lethal(payload.get("lethal"), kind=kind),
        "mulligan": _coerce_mulligan(payload.get("mulligan")),
        "game_over": _coerce_text(payload.get("game_over"), max_len=20),
        "discover": _coerce_text(payload.get("discover"), max_len=240),
        "lessons": _coerce_steps(payload.get("lessons"))[:4],
    }
    if kind == "gameover" and not advice["game_over"]:
        advice["game_over"] = "UNKNOWN"
    return advice


def _default_headline(kind: str) -> str:
    return {
        "idle": "Waiting for live coach",
        "turn": "Do this now",
        "mulligan": "Mulligan advice",
        "lethal": "LETHAL",
        "update": "Update",
        "gameover": "Game over",
    }.get(kind, "Do this now")


def clear_advice(turn: int | None = None) -> dict[str, Any]:
    return normalize_advice({
        "kind": "idle",
        "turn": turn,
        "headline": "Waiting for live coach",
        "why": "Start a Hearthstone game and publish turn advice to populate this panel.",
        "steps": [],
    })


def write_advice(payload: dict[str, Any], overlay_dir: str | os.PathLike[str] | None = None) -> Path:
    directory = resolve_overlay_dir(overlay_dir)
    advice = normalize_advice(payload)
    if advice.get("lessons"):
        append_lessons(advice["lessons"], overlay_dir)
    return atomic_write_json(directory / "advice.json", advice)


def write_clear_advice(overlay_dir: str | os.PathLike[str] | None = None, *, turn: int | None = None) -> Path:
    directory = resolve_overlay_dir(overlay_dir)
    return atomic_write_json(directory / "advice.json", clear_advice(turn))


def append_lessons(lessons: list[str], overlay_dir: str | os.PathLike[str] | None = None) -> Path | None:
    """Accumulate lessons in lessons.json across games (newest first, deduped)."""
    lessons = [text for text in (_coerce_text(l, max_len=240) for l in lessons) if text]
    if not lessons:
        return None
    directory = resolve_overlay_dir(overlay_dir)
    path = directory / "lessons.json"
    try:
        existing = json.loads(path.read_text(encoding="utf-8")).get("lessons", [])
    except (OSError, json.JSONDecodeError):
        existing = []
    merged = list(dict.fromkeys(lessons + [l for l in existing if isinstance(l, str)]))[:30]
    return atomic_write_json(path, {"ts": time.time(), "lessons": merged})


def write_discover(text: str, overlay_dir: str | os.PathLike[str] | None = None) -> Path:
    """Merge a Discover pick into the current advice card without clobbering it.

    Discovers fire mid-turn while the turn plan is still on screen; the pick
    gets its own slot so both stay visible. The next full advice write
    (which omits `discover`) clears the slot naturally.
    """
    directory = resolve_overlay_dir(overlay_dir)
    path = directory / "advice.json"
    try:
        current = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        current = {}
    current["discover"] = text
    current["ts"] = time.time()
    return atomic_write_json(path, normalize_advice(current))


def mirror_live_snapshot(snapshot: dict[str, Any], overlay_dir: str | os.PathLike[str] | None = None) -> Path:
    directory = resolve_overlay_dir(overlay_dir)
    return atomic_write_json(directory / "live.json", snapshot)
