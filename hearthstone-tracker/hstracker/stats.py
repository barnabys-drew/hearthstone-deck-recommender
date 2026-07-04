"""Win-rate queries over the games table."""
from __future__ import annotations

import sqlite3

_WINRATE = "ROUND(100.0 * SUM(result = 'WON') / COUNT(*), 1)"


def _filters(game_type: str | None, format_type: str | None,
             deck: str | None = None) -> tuple[str, list]:
    clauses, params = ["result IS NOT NULL"], []
    if game_type:
        clauses.append("game_type = ?")
        params.append(game_type)
    if format_type:
        clauses.append("format_type = ?")
        params.append(format_type)
    if deck:
        clauses.append("deck_name LIKE ?")
        params.append(f"%{deck}%")
    return " AND ".join(clauses), params


def _rows(conn: sqlite3.Connection, sql: str, params: list) -> list[sqlite3.Row]:
    return conn.execute(sql, params).fetchall()


def overall(conn, game_type=None, format_type=None):
    where, params = _filters(game_type, format_type)
    return _rows(conn, f"""
        SELECT game_type, format_type, COUNT(*) AS games,
               SUM(result = 'WON') AS wins, {_WINRATE} AS winrate
        FROM games WHERE {where}
        GROUP BY game_type, format_type ORDER BY games DESC""", params)


def by_deck(conn, game_type=None, format_type=None):
    where, params = _filters(game_type, format_type)
    return _rows(conn, f"""
        SELECT deck_name AS deck, friendly_class AS class, COUNT(*) AS games,
               SUM(result = 'WON') AS wins, {_WINRATE} AS winrate
        FROM games WHERE {where} AND deck_name IS NOT NULL
        GROUP BY deck_name, friendly_class ORDER BY games DESC""", params)


def by_class(conn, game_type=None, format_type=None):
    where, params = _filters(game_type, format_type)
    return _rows(conn, f"""
        SELECT friendly_class AS class, COUNT(*) AS games,
               SUM(result = 'WON') AS wins, {_WINRATE} AS winrate
        FROM games WHERE {where} AND friendly_class IS NOT NULL
        GROUP BY friendly_class ORDER BY games DESC""", params)


def matchups(conn, game_type=None, format_type=None, min_games: int = 1):
    where, params = _filters(game_type, format_type)
    return _rows(conn, f"""
        SELECT friendly_class AS mine, opponent_class AS theirs, COUNT(*) AS games,
               SUM(result = 'WON') AS wins, {_WINRATE} AS winrate
        FROM games
        WHERE {where} AND friendly_class IS NOT NULL AND opponent_class IS NOT NULL
        GROUP BY friendly_class, opponent_class
        HAVING COUNT(*) >= ? ORDER BY games DESC, winrate DESC""",
        params + [min_games])


def first_vs_second(conn, game_type=None, format_type=None):
    where, params = _filters(game_type, format_type)
    return _rows(conn, f"""
        SELECT CASE friendly_first WHEN 1 THEN 'first' ELSE 'second (coin)' END AS went,
               COUNT(*) AS games, SUM(result = 'WON') AS wins, {_WINRATE} AS winrate
        FROM games WHERE {where} AND friendly_first IS NOT NULL
        GROUP BY friendly_first ORDER BY friendly_first DESC""", params)


# BG hero picks share the game_cards table; constructed card views exclude them.
_CONSTRUCTED = "g.game_type NOT LIKE 'GT_BATTLEGROUNDS%' AND g.game_type NOT LIKE 'GT_MERCENARIES%'"


def card_performance(conn, game_type=None, format_type=None, deck=None, min_games: int = 1):
    """Per friendly card: win rate in games where it was played / drawn."""
    where, params = _filters(game_type, format_type, deck)
    where = f"{where} AND {_CONSTRUCTED}"
    return _rows(conn, f"""
        SELECT gc.card_id,
               SUM(gc.played > 0) AS games_played,
               ROUND(100.0 * SUM(gc.played > 0 AND g.result = 'WON')
                     / NULLIF(SUM(gc.played > 0), 0), 1) AS wr_played,
               SUM(gc.drawn > 0) AS games_drawn,
               ROUND(100.0 * SUM(gc.drawn > 0 AND g.result = 'WON')
                     / NULLIF(SUM(gc.drawn > 0), 0), 1) AS wr_drawn,
               ROUND(AVG(gc.first_played_turn), 1) AS avg_turn
        FROM game_cards gc JOIN games g ON g.id = gc.game_id
        WHERE {where} AND gc.friendly = 1
        GROUP BY gc.card_id
        HAVING games_played >= ?
        ORDER BY games_played DESC, wr_played DESC""", params + [min_games])


def mulligan(conn, game_type=None, format_type=None, deck=None, min_games: int = 1):
    """Per friendly card: how often it was kept in the mulligan and how that went."""
    where, params = _filters(game_type, format_type, deck)
    where = f"{where} AND {_CONSTRUCTED}"
    return _rows(conn, f"""
        SELECT gc.card_id,
               SUM(gc.mull_offered) AS offered,
               SUM(gc.mull_kept) AS kept,
               ROUND(100.0 * SUM(gc.mull_kept) / NULLIF(SUM(gc.mull_offered), 0), 1) AS keep_pct,
               ROUND(100.0 * SUM(gc.mull_kept > 0 AND g.result = 'WON')
                     / NULLIF(SUM(gc.mull_kept > 0), 0), 1) AS wr_kept
        FROM game_cards gc JOIN games g ON g.id = gc.game_id
        WHERE {where} AND gc.friendly = 1 AND gc.mull_offered > 0
        GROUP BY gc.card_id
        HAVING offered >= ?
        ORDER BY offered DESC, keep_pct DESC""", params + [min_games])


_BG = "game_type LIKE 'GT_BATTLEGROUNDS%'"


def bg_overall(conn):
    return _rows(conn, f"""
        SELECT CASE WHEN game_type LIKE '%DUO%' THEN 'duos' ELSE 'solo' END AS mode,
               COUNT(*) AS games,
               ROUND(AVG(bg_place), 2) AS avg_place,
               ROUND(100.0 * SUM(bg_place <= 4) / COUNT(*), 1) AS top4_pct,
               ROUND(100.0 * SUM(bg_place = 1) / COUNT(*), 1) AS first_pct,
               ROUND(AVG(bg_tech), 1) AS avg_tier
        FROM games WHERE {_BG} AND bg_place IS NOT NULL
        GROUP BY mode ORDER BY games DESC""", [])


def bg_heroes(conn, min_games: int = 1):
    return _rows(conn, f"""
        SELECT friendly_hero AS card_id, COUNT(*) AS games,
               ROUND(AVG(bg_place), 2) AS avg_place,
               ROUND(100.0 * SUM(bg_place <= 4) / COUNT(*), 1) AS top4_pct,
               SUM(bg_place = 1) AS firsts
        FROM games WHERE {_BG} AND bg_place IS NOT NULL AND friendly_hero IS NOT NULL
        GROUP BY friendly_hero
        HAVING games >= ?
        ORDER BY games DESC, avg_place ASC""", [min_games])


def bg_hero_picks(conn, min_games: int = 1):
    return _rows(conn, f"""
        SELECT gc.card_id,
               SUM(gc.mull_offered) AS offered,
               SUM(gc.mull_kept) AS picked,
               ROUND(100.0 * SUM(gc.mull_kept) / NULLIF(SUM(gc.mull_offered), 0), 1) AS pick_pct,
               ROUND(AVG(CASE WHEN gc.mull_kept > 0 THEN g.bg_place END), 2) AS avg_place_picked
        FROM game_cards gc JOIN games g ON g.id = gc.game_id
        WHERE g.{_BG} AND gc.friendly = 1 AND gc.mull_offered > 0
        GROUP BY gc.card_id
        HAVING offered >= ?
        ORDER BY offered DESC, pick_pct DESC""", [min_games])


def recent(conn, limit: int = 20):
    return _rows(conn, """
        SELECT start_time, game_type, friendly_class, opponent_class,
               opponent_name, result, turns, duration_seconds
        FROM games ORDER BY start_time DESC LIMIT ?""", [limit])


def resolve_card_names(rows: list[sqlite3.Row], name_of) -> list[dict]:
    """Replace the card_id column with a readable card name."""
    out = []
    for r in rows:
        d = dict(r)
        card_id = d.pop("card_id", None)
        out.append({"card": name_of(card_id) or card_id, **d})
    return out


def format_table(rows: list) -> str:
    if not rows:
        return "(no games recorded yet)"
    headers = list(rows[0].keys())
    table = [[("" if r[h] is None else str(r[h])) for h in headers] for r in rows]
    widths = [max(len(h), *(len(row[i]) for row in table)) for i, h in enumerate(headers)]
    lines = [
        "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)),
        "  ".join("-" * w for w in widths),
    ]
    lines += ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in table]
    return "\n".join(lines)
