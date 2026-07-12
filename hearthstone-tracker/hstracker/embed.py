"""Tier-2 semantic retrieval: cosine over cached lesson embeddings (Phase 3).

Runs ONLY when Tier 0 (exact triggers) and Tier 1 (lexical) both return
nothing for a your-turn snapshot. Hits are labeled [T2 semantic] so the coach
weighs them below both exact trigger hits and lexical hits.

The tier exists to teach (and exploit) write-time vs read-time cost
asymmetry, so the costs live in exactly two places:

- WRITE TIME: each lesson is embedded once when recorded (best-effort hook in
  `append_lesson`, active only after `hst rag-embed` has initialized the
  cache) or backfilled by `hst rag-embed`. Vectors are unit-normalized and
  cached in embeddings.json keyed by lesson id + model name.
- ONCE PER GAME: the query vector is embedded from the first snapshot seen
  for a game (normally the mulligan) — never per turn.

The per-turn hot path is pure-python dot products over <=200 cached unit
vectors: no model, no numpy, no I/O. fastembed (ONNX MiniLM, local, no API)
is required only where vectors are CREATED; if the model or cache is missing
the tier degrades to silent and every other layer keeps working.

Lab-gated like Tier 1: the live loop runs Tier 2 only with HS_RAG_T2=1, and
rag-replay only with --t2 (so existing replay regression diffs stay stable).
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

from .config import DEFAULT_DB
from .lessons import Lesson
from .lexical import _lesson_doc
from .raglog import lesson_id

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
CACHE_PATH = DEFAULT_DB.parent / "embeddings.json"

# Cosine similarity gate, tuned via rag-replay --t2 --candidates on
# Hearthstone_2026_07_12_15_31_05 (5 games, 9 t0+t1-miss turns): plausible
# hits clustered at 0.517-0.554 (Coin/weapon lessons in a Coin-Rogue game);
# noise topped out at 0.446 ("Seismopod" firing in Seismopod-less games).
# 0.48 sits in that gap. Small basis — retune as sessions accumulate.
# HS_RAG_T2_MIN overrides per-run for tuning.
SIM_THRESHOLD = 0.48


def t2_live_enabled() -> bool:
    """Lab-first: the live loop runs Tier 2 only when HS_RAG_T2=1."""
    return os.environ.get("HS_RAG_T2") == "1"


def sim_threshold() -> float:
    """SIM_THRESHOLD, overridable via HS_RAG_T2_MIN for tuning runs."""
    try:
        return float(os.environ["HS_RAG_T2_MIN"])
    except (KeyError, ValueError):
        return SIM_THRESHOLD


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if not norm:
        return [0.0 for _ in vec]
    # Rounded so the JSON cache (and thus replay output) is byte-stable.
    return [round(x / norm, 6) for x in vec]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class Embedder:
    """Lazy fastembed wrapper. Import and model load happen on first use so
    `import hstracker.embed` stays free for processes that never create
    vectors (the live read path, tests, rag-report)."""

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self.model_name = model_name
        self._model = None

    def available(self) -> bool:
        try:
            import fastembed  # noqa: F401
            return True
        except ImportError:
            return False

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Unit-normalized vectors, one per text. Raises ImportError if
        fastembed is not installed — callers decide whether that's fatal."""
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(self.model_name)
        return [_unit([float(x) for x in vec]) for vec in self._model.embed(texts)]


def load_cache(path: Path | None = None) -> dict[str, Any]:
    """{"model": name, "vectors": {lesson_id: [floats]}}; {} on any failure
    or model mismatch (a model swap invalidates every cached vector)."""
    path = path or CACHE_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict) or raw.get("model") != MODEL_NAME:
        return {}
    vectors = raw.get("vectors")
    return raw if isinstance(vectors, dict) else {}


def save_cache(cache: dict[str, Any], path: Path | None = None) -> Path:
    path = path or CACHE_PATH
    payload = {"model": MODEL_NAME, "ts": time.time(),
               "vectors": cache.get("vectors", {})}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)
    return path


def backfill_embeddings(lessons: list[Lesson], path: Path | None = None,
                        embedder: Embedder | None = None) -> dict[str, int]:
    """Embed every store lesson missing a vector; prune vectors whose lesson
    left the store. The `hst rag-embed` command, and the cache initializer
    that turns on write-time embedding in append_lesson."""
    path = path or CACHE_PATH
    embedder = embedder or Embedder()
    cache = load_cache(path)
    vectors: dict[str, list[float]] = dict(cache.get("vectors") or {})
    by_id = {lesson_id(rec.lesson): rec for rec in lessons}
    stale = [lid for lid in vectors if lid not in by_id]
    for lid in stale:
        del vectors[lid]
    missing = [lid for lid in by_id if lid not in vectors]
    if missing:
        docs = [_lesson_doc(by_id[lid]) for lid in missing]
        for lid, vec in zip(missing, embedder.embed(docs)):
            vectors[lid] = vec
    save_cache({"vectors": vectors}, path)
    return {"embedded": len(missing), "pruned": len(stale), "total": len(vectors)}


def embed_new_lesson(record: Lesson, path: Path | None = None) -> bool:
    """Write-time hook for append_lesson. Only runs once the cache exists
    (i.e. the user opted into Tier 2 by running `hst rag-embed`), so lesson
    recording never pays a model load on an uninitialized lab."""
    path = path or CACHE_PATH
    if not path.exists():
        return False
    cache = load_cache(path)
    if not cache:
        return False
    lid = lesson_id(record.lesson)
    vectors = dict(cache.get("vectors") or {})
    if lid in vectors:
        return True
    embedder = Embedder()
    if not embedder.available():
        return False
    vectors[lid] = embedder.embed([_lesson_doc(record)])[0]
    save_cache({"vectors": vectors}, path)
    return True


def game_query_text(snapshot: dict[str, Any]) -> str:
    """Mulligan-context query: opponent class, my hand (names + rules text),
    my deck's card names. Deliberately game-level, not turn-level — the query
    is embedded once per game, so it describes the matchup, not the board."""
    me, opp = snapshot.get("me") or {}, snapshot.get("opp") or {}
    parts = [str(opp.get("class") or "")]
    for card in (me.get("hand") or []):
        parts.append(str(card.get("name") or ""))
        parts.append(str(card.get("text") or ""))
    for card in (me.get("deck_cards_left") or []):
        parts.append(str(card.get("name") or ""))
    return " ".join(p for p in parts if p)


class SemanticIndex:
    """Lessons that have a cached vector, ready for dot-product matching.

    The headline record is excluded for the same reason Tier 1 excludes it:
    it is generic cross-game synthesis already pinned to the overlay panel.
    """

    def __init__(self, lessons: list[Lesson], cache: dict[str, Any]) -> None:
        vectors = cache.get("vectors") or {}
        self.entries: list[tuple[Lesson, list[float]]] = []
        for rec in lessons:
            if rec.headline:
                continue
            vec = vectors.get(lesson_id(rec.lesson))
            if vec:
                self.entries.append((rec, vec))

    def match(self, query_vec: list[float], cap: int = 3) -> list[tuple[Lesson, float]]:
        """Threshold-gated cosine hits, best first. Empty list = stay quiet."""
        threshold = sim_threshold()
        hits = []
        for rec, vec in self.entries:
            sim = round(_dot(query_vec, vec), 3)
            if sim >= threshold:
                hits.append((rec, sim))
        hits.sort(key=lambda h: (-h[1], lesson_id(h[0].lesson)))
        return hits[:cap]

    def candidates(self, query_vec: list[float], top: int = 3) -> list[dict[str, Any]]:
        """Top similarities regardless of the gate — replay's threshold-tuning
        aid, mirroring lexical.t1_candidates."""
        scored = [{"id": lesson_id(rec.lesson), "sim": round(_dot(query_vec, vec), 3)}
                  for rec, vec in self.entries]
        scored.sort(key=lambda c: (-c["sim"], c["id"]))
        return scored[:top]


class T2Retriever:
    """Everything the live loop / replay needs to run Tier 2 on a snapshot:
    a per-game query vector (embedded once, on the first snapshot of each
    game) and a SemanticIndex rebuilt only when the store list changes.

    `prime()` must be called on every snapshot; it is a no-op except on the
    first snapshot of a new game. `match()` is the pure hot-path lookup.
    """

    def __init__(self, cache_path: Path | None = None,
                 embedder: Embedder | None = None) -> None:
        self.cache_path = cache_path or CACHE_PATH
        self.embedder = embedder or Embedder()
        self._cache: dict[str, Any] | None = None
        self._index: SemanticIndex | None = None
        self._index_key: int | None = None
        self._game: int | None = None
        self._query_vec: list[float] | None = None
        self._warned = False

    def ready(self) -> bool:
        if self._cache is None:
            self._cache = load_cache(self.cache_path)
        return bool(self._cache) and self.embedder.available()

    def prime(self, snapshot: dict[str, Any], game_no: int) -> None:
        """Embed this game's query if not done yet. Called every snapshot;
        pays the model exactly once per game (and the model load once per
        process, at the first game's mulligan)."""
        if game_no == self._game:
            return
        if not self.ready():
            if not self._warned:
                self._warned = True
                print("!! Tier 2 enabled but unavailable "
                      "(run `hst rag-embed`; needs fastembed)", flush=True)
            return
        try:
            self._query_vec = self.embedder.embed([game_query_text(snapshot)])[0]
            self._game = game_no
        except Exception:
            self._query_vec = None  # embed failure = tier silent this game

    def match(self, lessons: list[Lesson], cap: int = 3) -> list[tuple[Lesson, float]]:
        if not self._query_vec or not self._cache:
            return []
        if self._index is None or self._index_key != id(lessons):
            self._index_key = id(lessons)
            self._index = SemanticIndex(lessons, self._cache)
        return self._index.match(self._query_vec, cap=cap)

    def candidates(self, lessons: list[Lesson], top: int = 3) -> list[dict[str, Any]]:
        if not self._query_vec or not self._cache:
            return []
        if self._index is None or self._index_key != id(lessons):
            self._index_key = id(lessons)
            self._index = SemanticIndex(lessons, self._cache)
        return self._index.candidates(self._query_vec, top=top)
