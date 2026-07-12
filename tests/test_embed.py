from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hearthstone-tracker"))

from hstracker import embed  # noqa: E402
from hstracker.embed import (  # noqa: E402
    MODEL_NAME, SemanticIndex, T2Retriever, _dot, _unit, game_query_text,
    load_cache, save_cache,
)
from hstracker.lessons import Lesson  # noqa: E402
from hstracker.lexical import retrieve_lessons  # noqa: E402
from hstracker.raglog import lesson_id  # noqa: E402


def make_lesson(text: str, **fields) -> Lesson:
    trigger = fields.pop("trigger", {})
    return Lesson.model_validate({"lesson": text, "trigger": trigger, **fields})


def snap(my_hand=(), opp_class="WARRIOR", deck=()):
    def cards(names):
        return [{"name": n, "text": t} for n, t in names]
    return {
        "whose_turn": "me", "raw_turn": 3, "turn": 2, "phase": "playing",
        "me": {"hand": cards(my_hand), "board": [],
               "deck_cards_left": cards(deck)},
        "opp": {"class": opp_class, "board": [], "hand": [], "hand_hidden": 0},
    }


def axis(i: int, dim: int = 4) -> list[float]:
    vec = [0.0] * dim
    vec[i] = 1.0
    return vec


def mix(a: int, b: int, wa: float, wb: float, dim: int = 4) -> list[float]:
    vec = [0.0] * dim
    vec[a], vec[b] = wa, wb
    return _unit(vec)


class UnitDotTests(unittest.TestCase):
    def test_unit_normalizes(self) -> None:
        vec = _unit([3.0, 4.0])
        self.assertAlmostEqual(math.hypot(*vec), 1.0, places=5)

    def test_zero_vector_stays_zero(self) -> None:
        self.assertEqual(_unit([0.0, 0.0]), [0.0, 0.0])

    def test_dot_of_orthogonal_is_zero(self) -> None:
        self.assertEqual(_dot(axis(0), axis(1)), 0.0)


class CacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "embeddings.json"

    def test_roundtrip(self) -> None:
        save_cache({"vectors": {"abc": [1.0, 0.0]}}, self.path)
        cache = load_cache(self.path)
        self.assertEqual(cache["model"], MODEL_NAME)
        self.assertEqual(cache["vectors"], {"abc": [1.0, 0.0]})

    def test_model_mismatch_invalidates(self) -> None:
        self.path.write_text(json.dumps(
            {"model": "some-other-model", "vectors": {"abc": [1.0]}}))
        self.assertEqual(load_cache(self.path), {})

    def test_corrupt_cache_is_empty(self) -> None:
        self.path.write_text("{not json")
        self.assertEqual(load_cache(self.path), {})


class ThresholdPinned(unittest.TestCase):
    """Synthetic vectors make similarities exact; pin the gate mid-range."""

    def setUp(self) -> None:
        import os
        os.environ["HS_RAG_T2_MIN"] = "0.5"
        self.addCleanup(os.environ.pop, "HS_RAG_T2_MIN", None)


class SemanticIndexTests(ThresholdPinned):
    def setUp(self) -> None:
        super().setUp()
        self.close = make_lesson("close lesson")
        self.far = make_lesson("far lesson")
        self.head = make_lesson("headline lesson", headline=True)
        self.cache = {"vectors": {
            lesson_id(self.close.lesson): mix(0, 1, 0.9, 0.1),   # sim ~0.994
            lesson_id(self.far.lesson): axis(1),                 # sim 0
            lesson_id(self.head.lesson): axis(0),                # sim 1, but headline
        }}
        self.index = SemanticIndex([self.close, self.far, self.head], self.cache)

    def test_gate_passes_close_blocks_far(self) -> None:
        hits = self.index.match(axis(0))
        self.assertEqual([rec.lesson for rec, _ in hits], [self.close.lesson])
        self.assertGreaterEqual(hits[0][1], 0.5)

    def test_headline_excluded_even_at_perfect_similarity(self) -> None:
        self.assertNotIn(self.head.lesson,
                         [rec.lesson for rec, _ in self.index.match(axis(0))])

    def test_lesson_without_vector_invisible(self) -> None:
        stranger = make_lesson("never embedded")
        index = SemanticIndex([stranger], self.cache)
        self.assertEqual(index.match(axis(0)), [])

    def test_candidates_ignore_gate(self) -> None:
        cands = self.index.candidates(axis(0))
        self.assertEqual(len(cands), 2)  # far included despite sim 0
        self.assertEqual(cands[0]["id"], lesson_id(self.close.lesson))

    def test_deterministic_order(self) -> None:
        a = self.index.match(axis(0))
        b = self.index.match(axis(0))
        self.assertEqual([(r.lesson, s) for r, s in a],
                         [(r.lesson, s) for r, s in b])


class FakeEmbedder:
    """Maps any text to a fixed vector; counts calls to prove once-per-game."""

    def __init__(self, vec) -> None:
        self.vec, self.calls = vec, 0

    def available(self) -> bool:
        return True

    def embed(self, texts):
        self.calls += 1
        return [self.vec for _ in texts]


class T2RetrieverTests(ThresholdPinned):
    def setUp(self) -> None:
        super().setUp()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "embeddings.json"
        self.lesson = make_lesson("don't overextend into board clears")
        save_cache({"vectors": {lesson_id(self.lesson.lesson): axis(0)}}, self.path)

    def retriever(self, vec=None) -> tuple[T2Retriever, FakeEmbedder]:
        fake = FakeEmbedder(vec or axis(0))
        return T2Retriever(cache_path=self.path, embedder=fake), fake

    def test_query_embedded_once_per_game(self) -> None:
        t2, fake = self.retriever()
        for _ in range(5):
            t2.prime(snap(), game_no=1)
        self.assertEqual(fake.calls, 1)
        t2.prime(snap(), game_no=2)
        self.assertEqual(fake.calls, 2)

    def test_match_fires_and_is_silent_without_prime(self) -> None:
        t2, _ = self.retriever()
        self.assertEqual(t2.match([self.lesson]), [])  # unprimed = silent
        t2.prime(snap(), game_no=1)
        hits = t2.match([self.lesson])
        self.assertEqual([rec.lesson for rec, _ in hits], [self.lesson.lesson])

    def test_missing_cache_never_fires(self) -> None:
        t2 = T2Retriever(cache_path=Path(self.dir.name) / "absent.json",
                         embedder=FakeEmbedder(axis(0)))
        t2.prime(snap(), game_no=1)
        self.assertEqual(t2.match([self.lesson]), [])


class RetrieveIntegrationTests(ThresholdPinned):
    """Tier 2 slots under t0 and t1 in retrieve_lessons."""

    def setUp(self) -> None:
        super().setUp()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "embeddings.json"
        self.semantic = make_lesson("do not overextend into area damage")
        save_cache({"vectors": {lesson_id(self.semantic.lesson): axis(0)}},
                   self.path)
        self.t2 = T2Retriever(cache_path=self.path, embedder=FakeEmbedder(axis(0)))
        self.t2.prime(snap(), game_no=1)

    def test_t2_fires_on_t0_t1_miss(self) -> None:
        results, tiers = retrieve_lessons(snap(), [self.semantic], t2=self.t2)
        self.assertEqual(tiers, ["t0", "t1", "t2"])
        self.assertEqual(results[0]["tier"], "t2")
        self.assertIsInstance(results[0]["score"], float)

    def test_t0_hit_short_circuits_t2(self) -> None:
        triggered = make_lesson("exact", trigger={"opp_class": "WARRIOR"})
        results, tiers = retrieve_lessons(snap(), [triggered, self.semantic],
                                          t2=self.t2)
        self.assertEqual(tiers, ["t0"])
        self.assertEqual(results[0]["tier"], "t0")

    def test_no_t2_keeps_old_contract(self) -> None:
        results, tiers = retrieve_lessons(snap(), [self.semantic], t2=None)
        self.assertEqual((results, tiers), ([], ["t0", "t1"]))


class QueryTextTests(unittest.TestCase):
    def test_covers_class_hand_and_deck(self) -> None:
        text = game_query_text(snap(
            my_hand=(("Backstab", "Deal 2 damage to an undamaged minion."),),
            deck=(("Preparation", ""),), opp_class="PALADIN"))
        for expected in ("PALADIN", "Backstab", "undamaged", "Preparation"):
            self.assertIn(expected, text)


@unittest.skipUnless(embed.Embedder().available(), "fastembed not installed")
class RealModelSmokeTest(unittest.TestCase):
    """One end-to-end sanity check against the real local model."""

    def test_semantically_close_beats_unrelated(self) -> None:
        embedder = embed.Embedder()
        query, close, far = embedder.embed([
            "PALADIN board flood divine shield minions early aggression",
            "deny the board every turn against wide aggressive paladin decks",
            "always draw cards with your weapon before it breaks",
        ])
        self.assertGreater(_dot(query, close), _dot(query, far))
