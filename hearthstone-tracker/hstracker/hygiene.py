"""Phase 4: lesson-store consolidation + decay (KB hygiene).

The store accumulates knowledge forever; this module is the maintenance pass
that keeps it honest, run at boundaries (post-session, `hst rag-maintain`) —
never on the retrieval hot path:

- **Stats stamping** — per-lesson firing/outcome stats computed from the
  retrieval log land on the record itself (`Lesson.stats`), so provenance
  and confidence travel with the knowledge wherever the store is mirrored.
- **Near-duplicate merge** — Jaccard similarity over the same token stream
  Tier 1 indexes; the weaker record of a pair is archived, not deleted.
- **Decay** — records that sat in the corpus for >= N telemetry games and
  never fired (any tier) are archived. Headline records are exempt from
  both merge and decay.
- **Headline candidates** — repeat-firers with wins are *reported* as
  promotion candidates only: composing headline prose is an LLM job at a
  boundary (the post-game coach), not deterministic code's.

Everything is DRY-RUN by default; `apply=True` (CLI `--apply`) writes the
store, appends the archive, and refreshes the overlay mirror. Archived
records go to lesson_archive.json beside the store with the reason attached
— knowledge is demoted, never destroyed.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .lessons import Lesson, LessonStats, STORE_PATH, load_store, mirror_store
from .lexical import _lesson_doc, tokenize
from .raglog import join_games, lesson_id, read_events

ARCHIVE_PATH = STORE_PATH.parent / "lesson_archive.json"

# Jaccard gate for "these two lessons say the same thing". Tuned loose-ish
# because lesson texts are short; the dry-run report shows every pair with
# its similarity so the user eyeballs before --apply.
DEDUPE_THRESHOLD = 0.6

# A lesson must have sat unfired through this many telemetry games before
# decay archives it. Conservative on purpose: with a young corpus nothing
# should decay.
DECAY_GAMES = 15


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts).date().isoformat() if ts else None


def compute_stats(events: list[dict[str, Any]],
                  store: list[Lesson]) -> dict[str, LessonStats]:
    """Per-lesson stats from the retrieval log, live and replay events alike
    excluded — replay events are tagged and skipped so rehearsing history
    doesn't inflate real firing counts."""
    events = [ev for ev in events if not ev.get("replay")]
    games = join_games(events)
    today = date.today().isoformat()
    last_fired: dict[str, float] = {}
    fired_turns: dict[str, set[tuple]] = {}
    for ev in events:
        if ev.get("ev") != "match":
            continue
        key = (ev.get("session"), ev.get("game_no"), ev.get("raw_turn"))
        for m in ev.get("matched") or []:
            lid = m.get("id")
            if not lid:
                continue
            fired_turns.setdefault(lid, set()).add(key)
            ts = ev.get("ts") or 0
            if ts > last_fired.get(lid, 0):
                last_fired[lid] = ts

    stats: dict[str, LessonStats] = {}
    for rec in store:
        lid = lesson_id(rec.lesson)
        games_fired = won = corpus = applied = 0
        for g in games.values():
            if lid in g["corpus_ids"]:
                corpus += 1
            if lid in g["fired_ids"]:
                games_fired += 1
                if g["result"] == "WON":
                    won += 1
            if lid in g["applied_ids"]:
                applied += 1
        stats[lid] = LessonStats(
            times_fired=len(fired_turns.get(lid, ())),
            games_fired=games_fired, games_in_corpus=corpus,
            won_when_fired=won, applied=applied,
            last_fired=_iso(last_fired.get(lid)), updated=today,
        )
    return stats


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _keeper(a: Lesson, b: Lesson) -> tuple[Lesson, Lesson]:
    """(keep, drop), deterministically: more trigger conditions wins (the
    more actionable record), then newer date, then titled over untitled,
    then smaller id — so repeated runs always pick the same survivor."""
    def rank(rec: Lesson) -> tuple:
        return (rec.trigger.condition_count(), rec.date or "",
                rec.title is not None, lesson_id(rec.lesson))
    return (a, b) if rank(a) >= rank(b) else (b, a)


def near_duplicates(store: list[Lesson],
                    threshold: float = DEDUPE_THRESHOLD) -> list[dict[str, Any]]:
    """Pairs saying the same thing. Headlines never participate; records
    pinned to DIFFERENT opponent classes are different knowledge even when
    the words match (real case: 'deny the board' vs two different classes)."""
    candidates = [rec for rec in store if not rec.headline]
    docs = {lesson_id(rec.lesson): set(tokenize(_lesson_doc(rec)))
            for rec in candidates}
    pairs = []
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            ca, cb = a.trigger.opp_class, b.trigger.opp_class
            if ca and cb and ca != cb:
                continue
            sim = _jaccard(docs[lesson_id(a.lesson)], docs[lesson_id(b.lesson)])
            if sim >= threshold:
                keep, drop = _keeper(a, b)
                pairs.append({"similarity": round(sim, 3), "keep": keep, "drop": drop})
    pairs.sort(key=lambda p: (-p["similarity"], lesson_id(p["drop"].lesson)))
    return pairs


def decay_candidates(store: list[Lesson], stats: dict[str, LessonStats],
                     min_games: int = DECAY_GAMES) -> list[Lesson]:
    """Never fired (any tier) across >= min_games telemetry games."""
    out = []
    for rec in store:
        if rec.headline:
            continue
        s = stats.get(lesson_id(rec.lesson))
        if s and s.times_fired == 0 and s.games_in_corpus >= min_games:
            out.append(rec)
    return out


def headline_candidates(store: list[Lesson], stats: dict[str, LessonStats],
                        top: int = 3) -> list[dict[str, Any]]:
    """Repeat-firers worth promoting into the next synthesized headline —
    reported for the post-game coach to write up, never auto-applied."""
    rows = []
    for rec in store:
        if rec.headline:
            continue
        s = stats.get(lesson_id(rec.lesson))
        if not s or s.games_fired < 2:
            continue
        rows.append({"id": lesson_id(rec.lesson),
                     "title": rec.title or rec.lesson[:60],
                     "games_fired": s.games_fired, "won": s.won_when_fired,
                     "applied": s.applied})
    rows.sort(key=lambda r: (-r["games_fired"], -r["won"], r["id"]))
    return rows[:top]


def _append_archive(records: list[tuple[Lesson, str]],
                    path: Path | None = None) -> Path:
    """Demote records with their reason. Append-only; never rewrites."""
    path = path or ARCHIVE_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        archived = raw.get("lessons", [])
    except (OSError, json.JSONDecodeError):
        archived = []
    today = date.today().isoformat()
    for rec, reason in records:
        entry = rec.model_dump(mode="json")
        entry["archived"] = {"reason": reason, "date": today}
        archived.append(entry)
    payload = {"ts": time.time(), "lessons": archived}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _save_store(store: list[Lesson], path: Path) -> None:
    payload = {"ts": time.time(),
               "lessons": [rec.model_dump(mode="json") for rec in store][:200]}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def maintain(store_path: Path | None = None, log_path: Path | None = None,
             archive_path: Path | None = None, *, apply: bool = False,
             dedupe_threshold: float = DEDUPE_THRESHOLD,
             decay_games: int = DECAY_GAMES) -> dict[str, Any]:
    """One maintenance pass. Returns the report; mutates files only when
    apply=True (stats stamped, merge losers + decayed records archived and
    removed, store saved, overlay mirror refreshed)."""
    store_path = store_path or STORE_PATH
    store = load_store(store_path)
    stats = compute_stats(read_events(log_path), store)
    dupes = near_duplicates(store, threshold=dedupe_threshold)
    decayed = decay_candidates(store, stats, min_games=decay_games)
    heads = headline_candidates(store, stats)

    report = {
        "lessons": len(store),
        "stats": {lid: s.model_dump(mode="json") for lid, s in stats.items()},
        "duplicates": [{"similarity": p["similarity"],
                        "keep": lesson_id(p["keep"].lesson),
                        "keep_title": p["keep"].title or p["keep"].lesson[:60],
                        "drop": lesson_id(p["drop"].lesson),
                        "drop_title": p["drop"].title or p["drop"].lesson[:60]}
                       for p in dupes],
        "decayed": [{"id": lesson_id(rec.lesson),
                     "title": rec.title or rec.lesson[:60],
                     "games_in_corpus": stats[lesson_id(rec.lesson)].games_in_corpus}
                    for rec in decayed],
        "headline_candidates": heads,
        "applied": apply,
    }
    if not apply:
        return report

    drop: dict[str, str] = {}
    for p in dupes:
        lid = lesson_id(p["drop"].lesson)
        # A record already merged away can't also merge/decay again.
        drop.setdefault(lid, f"merged into #{lesson_id(p['keep'].lesson)} "
                             f"(similarity {p['similarity']})")
    for rec in decayed:
        drop.setdefault(lesson_id(rec.lesson),
                        f"decay: 0 fires in {stats[lesson_id(rec.lesson)].games_in_corpus} games")

    kept: list[Lesson] = []
    archived: list[tuple[Lesson, str]] = []
    for rec in store:
        lid = lesson_id(rec.lesson)
        if lid in drop:
            archived.append((rec, drop[lid]))
            continue
        rec.stats = stats.get(lid)
        kept.append(rec)
    if archived:
        _append_archive(archived, archive_path)
    _save_store(kept, store_path)
    if store_path == STORE_PATH:
        mirror_store(store_path)
    report["archived_count"] = len(archived)
    report["remaining"] = len(kept)
    return report
