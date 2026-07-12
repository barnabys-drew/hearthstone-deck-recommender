"""Deck stats for the overlay's stats panel.

Small, glanceable numbers for the deck currently being played: overall
record, last-10 form, and the best/worst matchups. Written to the shared
overlay folder as deck_stats.json whenever a game finishes (and at feed
startup), computed from the tracker's games.db.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .overlay import atomic_write_json, resolve_overlay_dir

_CONSTRUCTED = ("GT_RANKED", "GT_CASUAL")


def deck_stats(conn: sqlite3.Connection, deck_name: str | None = None) -> dict[str, Any] | None:
    """Stats payload for `deck_name`, defaulting to the most recently played deck."""
    if deck_name is None:
        row = conn.execute(
            "SELECT deck_name FROM games WHERE deck_name IS NOT NULL AND game_type IN (?, ?) "
            "ORDER BY start_time DESC LIMIT 1", _CONSTRUCTED).fetchone()
        if not row:
            return None
        deck_name = row[0]

    games = conn.execute(
        "SELECT result, opponent_class, start_time FROM games "
        "WHERE deck_name = ? AND game_type IN (?, ?) AND result IN ('WON', 'LOST') "
        "ORDER BY start_time DESC", (deck_name, *_CONSTRUCTED)).fetchall()
    if not games:
        # Newly selected deck with no history yet — still name it on the panel.
        return {"deck": deck_name, "games": 0, "wins": 0, "losses": 0,
                "winrate": 0, "last10": [], "matchups": []}

    wins = sum(1 for r in games if r[0] == "WON")
    last10 = [r[0] == "WON" for r in games[:10]]

    by_class: dict[str, list[int]] = {}
    for result, opp_class, _ in games:
        if not opp_class:
            continue
        tally = by_class.setdefault(opp_class, [0, 0])
        tally[0] += result == "WON"
        tally[1] += 1
    matchups = sorted(
        ({"opp_class": cls, "wins": w, "games": n, "winrate": round(100 * w / n)}
         for cls, (w, n) in by_class.items()),
        key=lambda m: (-m["games"], m["opp_class"]))

    return {
        "deck": deck_name,
        "games": len(games),
        "wins": wins,
        "losses": len(games) - wins,
        "winrate": round(100 * wins / len(games)),
        "last10": last10,  # newest first, True = win
        "matchups": matchups[:6],
    }


def write_deck_stats(conn: sqlite3.Connection, overlay_dir=None, deck_name: str | None = None) -> None:
    """Best-effort mirror of current-deck stats for the overlay panel."""
    try:
        payload = deck_stats(conn, deck_name)
        if payload:
            atomic_write_json(resolve_overlay_dir(overlay_dir) / "deck_stats.json", payload)
    except (sqlite3.Error, OSError):
        pass  # stats are display-only; never break the live loop over them
