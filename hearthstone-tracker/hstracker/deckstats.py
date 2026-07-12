"""Deck stats for the overlay's stats panel.

Small, glanceable numbers for the deck currently being played: overall
record, current streak, last-10 form, best/worst matchups, and the
account-wide record across all decks. Written to the shared overlay folder
as deck_stats.json whenever a game finishes (and at feed startup), computed
from the tracker's games.db.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from .overlay import atomic_write_json, resolve_overlay_dir

_CONSTRUCTED = ("GT_RANKED", "GT_CASUAL")


def _streak(results: list[str]) -> str | None:
    """Current run length, newest-first results in, e.g. 'W3' or 'L1'."""
    if not results:
        return None
    count = 0
    for r in results:
        if r != results[0]:
            break
        count += 1
    return f"{'W' if results[0] == 'WON' else 'L'}{count}"


def _record(conn: sqlite3.Connection, *, deck_name: str | None) -> dict[str, Any]:
    if deck_name is None:
        rows = conn.execute(
            "SELECT result FROM games WHERE game_type IN (?, ?) AND result IN ('WON', 'LOST')",
            _CONSTRUCTED).fetchall()
    else:
        rows = conn.execute(
            "SELECT result FROM games WHERE deck_name = ? AND game_type IN (?, ?) "
            "AND result IN ('WON', 'LOST')", (deck_name, *_CONSTRUCTED)).fetchall()
    games = len(rows)
    wins = sum(1 for r in rows if r[0] == "WON")
    return {"games": games, "wins": wins, "losses": games - wins,
            "winrate": round(100 * wins / games) if games else 0}


def deck_stats(conn: sqlite3.Connection, deck_name: str | None = None) -> dict[str, Any] | None:
    """Stats payload for `deck_name`, defaulting to the most recently played deck."""
    if deck_name is None:
        row = conn.execute(
            "SELECT deck_name FROM games WHERE deck_name IS NOT NULL AND game_type IN (?, ?) "
            "ORDER BY start_time DESC LIMIT 1", _CONSTRUCTED).fetchone()
        if not row:
            return None
        deck_name = row[0]

    overall = _record(conn, deck_name=None)

    games = conn.execute(
        "SELECT result, opponent_class, start_time FROM games "
        "WHERE deck_name = ? AND game_type IN (?, ?) AND result IN ('WON', 'LOST') "
        "ORDER BY start_time DESC", (deck_name, *_CONSTRUCTED)).fetchall()
    if not games:
        # Newly selected deck with no history yet — still name it on the panel.
        return {"deck": deck_name, "games": 0, "wins": 0, "losses": 0,
                "winrate": 0, "streak": None, "last10": [], "matchups": [],
                "overall": overall}

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
        "streak": _streak([r[0] for r in games]),
        "last10": last10,  # newest first, True = win
        "matchups": matchups[:6],
        "overall": overall,  # all decks combined, same game types
    }


def write_deck_stats(conn: sqlite3.Connection, overlay_dir=None, deck_name: str | None = None) -> None:
    """Best-effort mirror of current-deck stats for the overlay panel."""
    try:
        payload = deck_stats(conn, deck_name)
        if payload:
            atomic_write_json(resolve_overlay_dir(overlay_dir) / "deck_stats.json", payload)
    except (sqlite3.Error, OSError):
        pass  # stats are display-only; never break the live loop over them
