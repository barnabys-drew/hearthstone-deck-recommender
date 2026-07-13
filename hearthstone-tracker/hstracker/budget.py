"""Phase 5: context budgeting — progressive assembly under a token budget.

The marker's lessons block is the retrieved context a coaching decision
gets. This module makes its size an explicit budget instead of a fixed
count, and makes the ordering an explicit, evidence-based ranking instead
of "most conditions, then newest":

- **Ranking**: `specificity x recency x confidence`. Specificity comes from
  trigger conditions and retrieval tier (an exact trigger hit outranks a
  lexical guess outranks a semantic one); recency decays with the lesson's
  age; confidence comes from the Phase-4 stats stamped on the record
  (win-rate-when-fired, coach acks). A lesson that keeps firing in games
  you win outranks a same-shape lesson that never helped.
- **Budgeting**: candidates are taken best-first until the character budget
  (a deterministic stand-in for tokens at ~4 chars/token) is spent. If even
  the best candidate exceeds the budget it is kept anyway — a decision with
  zero context is worse than one slightly over budget.

Lab-gated like Tiers 1/2: the live loop budgets only with HS_RAG_BUDGET=1
(HS_RAG_BUDGET_CHARS overrides the default 600); rag-replay only with
--budget. HS_RAG_RANKER=legacy swaps in the pre-Phase-5 ordering so ranking
functions can be A/B-diffed through the replay harness.

Gate honesty: at build time only ~1% of 173 replayed turns had more
candidates than the cap — the budget rarely binds yet. The ranker is the
part earning its keep today; the budget is machinery awaiting evidence.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from .raglog import lesson_id

DEFAULT_BUDGET_CHARS = 600  # ~150 tokens for the whole lessons block
MAX_KEPT = 5  # sanity cap even under a generous budget

# An exact trigger hit is trustworthy; fuzzy tiers are progressively less so.
TIER_WEIGHT = {"t0": 1.0, "t1": 0.6, "t2": 0.4}

# Recency half-life-ish: a lesson from ~2 months ago scores half a fresh one.
RECENCY_SCALE_DAYS = 60.0
DEFAULT_AGE_DAYS = 180.0  # undated records are treated as old, not fresh


def budget_enabled() -> bool:
    """Lab-first: the live loop budgets only when HS_RAG_BUDGET=1."""
    return os.environ.get("HS_RAG_BUDGET") == "1"


def budget_chars() -> int:
    try:
        return int(os.environ["HS_RAG_BUDGET_CHARS"])
    except (KeyError, ValueError):
        return DEFAULT_BUDGET_CHARS


def ranker_name() -> str:
    """"evidence" (Phase-5 ranking) or "legacy" (pre-Phase-5 order) — the
    A/B lever for the replay harness."""
    name = os.environ.get("HS_RAG_RANKER", "evidence")
    return name if name in ("evidence", "legacy") else "evidence"


def _age_days(rec_date: str | None, today: date) -> float:
    if not rec_date:
        return DEFAULT_AGE_DAYS
    try:
        return max(0.0, float((today - date.fromisoformat(rec_date)).days))
    except ValueError:
        return DEFAULT_AGE_DAYS


def rank_score(result: dict[str, Any], today: date | None = None) -> float:
    """specificity x tier trust x recency x confidence, rounded so replay
    output is byte-stable."""
    rec = result["lesson"]
    today = today or date.today()
    specificity = 1.0 + rec.trigger.condition_count()
    tier = TIER_WEIGHT.get(result.get("tier") or "t0", 0.4)
    recency = 1.0 / (1.0 + _age_days(rec.date, today) / RECENCY_SCALE_DAYS)
    s = rec.stats
    if s and s.games_fired:
        # Laplace-smoothed win rate when fired, boosted by coach acks.
        confidence = ((s.won_when_fired + 1) / (s.games_fired + 2)
                      * (1.0 + 0.25 * min(s.applied, 4)))
    else:
        confidence = 0.5  # no evidence yet: neutral, not zero
    return round(specificity * tier * recency * confidence, 6)


def _legacy_key(result: dict[str, Any]) -> tuple:
    """The pre-Phase-5 ordering match_lessons used: most trigger conditions,
    then newest — kept callable so A/B replays can reproduce history."""
    rec = result["lesson"]
    return (rec.trigger.condition_count(), rec.date or "")


def line_cost(result: dict[str, Any]) -> int:
    """Approximate rendered marker-line size for one lesson: the text, the
    cost suffix, and the fixed label/id overhead format_snapshot adds."""
    rec = result["lesson"]
    return len(rec.lesson) + (len(rec.cost) + 20 if rec.cost else 0) + 30


def rank(results: list[dict[str, Any]], *, ranker: str | None = None,
         today: date | None = None) -> list[dict[str, Any]]:
    """Best-first, deterministic (ties break on lesson id)."""
    if (ranker or ranker_name()) == "legacy":
        return sorted(results, reverse=True,
                      key=lambda r: (_legacy_key(r), lesson_id(r["lesson"].lesson)))
    return sorted(results,
                  key=lambda r: (-rank_score(r, today),
                                 lesson_id(r["lesson"].lesson)))


def assemble(results: list[dict[str, Any]], budget: int | None = None,
             cap: int = MAX_KEPT, *, ranker: str | None = None,
             today: date | None = None
             ) -> tuple[list[dict[str, Any]], list[str], int]:
    """(kept, dropped_ids, chars_spent): rank, then take best-first while
    the budget and cap hold. The top candidate is always kept even if it
    alone busts the budget."""
    budget = budget if budget is not None else budget_chars()
    ranked = rank(results, ranker=ranker, today=today)
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    spent = 0
    for result in ranked:
        cost = line_cost(result)
        if not kept or (spent + cost <= budget and len(kept) < cap):
            kept.append(result)
            spent += cost
        else:
            dropped.append(lesson_id(result["lesson"].lesson))
    return kept, dropped, spent
