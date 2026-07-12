"""Tier-1 lexical retrieval: BM25 over lesson text (progressive-RAG Phase 2).

Runs ONLY when Tier 0 (exact trigger matching) returns nothing for a
your-turn snapshot. Scores each lesson's text against the snapshot's text
(card names, rules text, opponent class) and fires only past a score
threshold AND a minimum informative-token overlap — a fuzzy tier that stays
quiet beats one that fills markers with coincidences. Hits are labeled
[T1 fuzzy] so the coach weighs them below exact trigger hits.

Trigger-less lessons (condition_count()==0) are deliberately eligible: Tier 0
can never fire them, and giving text-only knowledge a path into turn markers
is the point of this tier.

Pure python, no dependencies; the corpus is capped at 200 lessons so the
index is rebuilt whole whenever the store changes (mtime), never per turn.
"""
from __future__ import annotations

import math
import os
import re
from typing import Any

from .lessons import Lesson, match_lessons
from .raglog import lesson_id

# BM25 constants — standard defaults; tuned only if replay evidence demands.
K1 = 1.5
B = 0.75

# Both gates must pass for a T1 hit. Tune SCORE_THRESHOLD via rag-replay's
# --candidates output (unthresholded scores), not live; HS_RAG_T1_MIN
# overrides it per-run so tuning needs no code edits.
# 7.5 tuned on Hearthstone_2026_07_12_04_50_10 (13 games): thresholds
# 2.0/5.5/6.5/7.5 fired on 18/12/8/5 of 18 t0-miss turns; 7.5 sits in the
# score gap under the 8.18+ cluster and lands near the <20%-of-misses bar.
SCORE_THRESHOLD = 7.5
MIN_OVERLAP = 2  # distinct informative query tokens shared with the lesson

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_STOPWORDS = frozenset(
    # English function words...
    "the and for you your their they them this that with when into onto out "
    "not always every each has have had was were are is its it's dont "
    "don goes only than then them all any but can one two more most "
    # ...plus domain words present in nearly every lesson AND snapshot, which
    # would otherwise create meaningless overlap ("never" stays — it carries
    # real meaning in lessons like "never feed Poisonous").
    "card cards turn turns game games play plays played playing minion minions".split()
)


def score_threshold() -> float:
    """SCORE_THRESHOLD, overridable via HS_RAG_T1_MIN for tuning runs."""
    try:
        return float(os.environ["HS_RAG_T1_MIN"])
    except (KeyError, ValueError):
        return SCORE_THRESHOLD


def t1_live_enabled() -> bool:
    """Lab-first: the live loop runs Tier 1 only when HS_RAG_T1=1."""
    return os.environ.get("HS_RAG_T1") == "1"


def tokenize(text: str) -> list[str]:
    """Lowercase alnum runs of 3+ chars, minus stopwords. Deterministic."""
    return [t for t in _TOKEN_RE.findall(str(text).lower()) if t not in _STOPWORDS]


def _lesson_doc(rec: Lesson) -> str:
    trigger = rec.trigger
    return " ".join(filter(None, [
        rec.lesson, rec.title or "", rec.matchup or "", rec.deck or "",
        " ".join(trigger.enemy_board + trigger.my_board + trigger.my_hand
                 + trigger.enemy_flags),
        trigger.opp_class or "",
    ]))


def snapshot_query(snapshot: dict[str, Any]) -> list[str]:
    """Query tokens from everything visible on the board and in hand."""
    me, opp = snapshot.get("me") or {}, snapshot.get("opp") or {}
    parts = [str(opp.get("class") or "")]
    for card in (me.get("hand") or []) + (me.get("board") or []) + (opp.get("board") or []):
        parts.append(str(card.get("name") or ""))
        parts.append(str(card.get("text") or ""))
        parts.extend(str(f) for f in (card.get("flags") or []))
    return tokenize(" ".join(parts))


class LessonIndex:
    """BM25 index over the lesson store. Rebuild on store change, not per turn.

    The headline record is excluded: it is deliberately generic cross-game
    synthesis, already permanently displayed on the overlay lessons panel —
    firing it as a turn match would add noise without new information.
    """

    def __init__(self, lessons: list[Lesson]) -> None:
        self.lessons = [rec for rec in lessons if not rec.headline]
        lessons = self.lessons
        self._docs = [tokenize(_lesson_doc(rec)) for rec in lessons]
        self._doc_lens = [len(d) for d in self._docs]
        self._avg_len = (sum(self._doc_lens) / len(self._docs)) if self._docs else 0.0
        # document frequency per token
        df: dict[str, int] = {}
        for doc in self._docs:
            for token in set(doc):
                df[token] = df.get(token, 0) + 1
        n = len(self._docs)
        # +0.5 smoothing keeps IDF sane at tiny corpus sizes
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query: list[str], doc_i: int) -> tuple[float, int]:
        """(BM25 score, distinct informative tokens shared) for one lesson."""
        doc = self._docs[doc_i]
        if not doc or not query:
            return 0.0, 0
        tf: dict[str, int] = {}
        for token in doc:
            tf[token] = tf.get(token, 0) + 1
        norm = K1 * (1 - B + B * self._doc_lens[doc_i] / (self._avg_len or 1))
        score, overlap = 0.0, 0
        # sorted() so float summation order (and thus the score) is
        # deterministic across runs — replay output must byte-diff clean.
        for token in sorted(set(query)):
            f = tf.get(token)
            if not f:
                continue
            overlap += 1
            score += self._idf.get(token, 0.0) * f * (K1 + 1) / (f + norm)
        return score, overlap


# StoreWatcher.lessons() returns the same list object until the store's
# mtime changes, so identity comparison gives "rebuild only on store change"
# for free — the live loop never rebuilds per turn.
_cached: tuple[int, LessonIndex] | None = None


def index_for(lessons: list[Lesson]) -> LessonIndex:
    global _cached
    if _cached is None or _cached[0] != id(lessons):
        _cached = (id(lessons), LessonIndex(lessons))
    return _cached[1]


def lexical_match(snapshot: dict[str, Any], index: LessonIndex,
                  cap: int = 3) -> list[tuple[Lesson, float]]:
    """Threshold-gated BM25 hits, best first. Empty list = stay quiet."""
    query = snapshot_query(snapshot)
    if not query:
        return []
    threshold = score_threshold()
    hits = []
    for i, rec in enumerate(index.lessons):
        score, overlap = index.score(query, i)
        if score >= threshold and overlap >= MIN_OVERLAP:
            hits.append((rec, round(score, 3)))
    hits.sort(key=lambda h: (-h[1], lesson_id(h[0].lesson)))
    return hits[:cap]


def t1_candidates(snapshot: dict[str, Any], index: LessonIndex,
                  top: int = 3) -> list[dict[str, Any]]:
    """Top-scored candidates regardless of gates — replay's threshold-tuning
    aid. Shows what T1 *would* fire at other thresholds."""
    query = snapshot_query(snapshot)
    if not query:
        return []
    scored = []
    for i, rec in enumerate(index.lessons):
        score, overlap = index.score(query, i)
        if score > 0:
            scored.append({"id": lesson_id(rec.lesson), "score": round(score, 3),
                           "overlap": overlap})
    scored.sort(key=lambda c: (-c["score"], c["id"]))
    return scored[:top]


def retrieve_lessons(snapshot: dict[str, Any], lessons: list[Lesson],
                     index: LessonIndex | None = None, cap: int = 3,
                     t1_enabled: bool = True) -> tuple[list[dict[str, Any]], list[str]]:
    """Tiered retrieval entry point for the live loop and replay.

    Returns (results, tiers_ran) where results are
    [{lesson: Lesson, tier: "t0"|"t1", score: float|None}] and tiers_ran
    lists the tiers that executed. Tier 1 runs only on a Tier-0 miss.
    """
    exact = match_lessons(snapshot, lessons, cap=cap)
    if exact:
        return [{"lesson": rec, "tier": "t0", "score": None} for rec in exact], ["t0"]
    if not t1_enabled:
        return [], ["t0"]
    index = index if index is not None else index_for(lessons)
    fuzzy = lexical_match(snapshot, index, cap=cap)
    return ([{"lesson": rec, "tier": "t1", "score": score} for rec, score in fuzzy],
            ["t0", "t1"])
