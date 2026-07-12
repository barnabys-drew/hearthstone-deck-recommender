from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hearthstone-tracker"))

from hstracker import lexical  # noqa: E402
from hstracker.lessons import Lesson  # noqa: E402
from hstracker.lexical import (  # noqa: E402
    LessonIndex, lexical_match, retrieve_lessons, snapshot_query, t1_candidates,
    tokenize,
)


def make_lesson(text: str, **fields) -> Lesson:
    trigger = fields.pop("trigger", {})
    return Lesson.model_validate({"lesson": text, "trigger": trigger, **fields})


def snap(my_hand=(), my_board=(), opp_board=(), opp_class="WARRIOR"):
    def cards(names):
        return [{"name": n, "text": t, "flags": list(f)}
                for n, t, f in names]
    return {
        "whose_turn": "me", "raw_turn": 3, "turn": 2, "phase": "playing",
        "me": {"hand": cards(my_hand), "board": cards(my_board)},
        "opp": {"class": opp_class, "board": cards(opp_board), "hand": [],
                "hand_hidden": 0},
    }


CARD = ("Bloodhoof Brave", "Taunt. Has +3 Attack while damaged.", ("taunt",))

# BM25's IDF is degenerate on a one-lesson corpus (every term is "common"),
# so tests that expect firing use a small realistic store: the lesson under
# test plus unrelated filler, like the real 17-lesson store.
FILLER = [
    "coin only when it converts something that would not fit",
    "spend every weapon charge before replacing the weapon",
    "budget the reborn copy against deathrattle boards",
]


def store_with(*texts: str) -> list:
    return [make_lesson(t) for t in (*texts, *FILLER)]


class TokenizeTests(unittest.TestCase):
    def test_lowercase_min_length_stopwords(self) -> None:
        tokens = tokenize("The Brave has +3 Attack; do NOT trade")
        self.assertIn("brave", tokens)
        self.assertIn("attack", tokens)
        self.assertIn("trade", tokens)
        self.assertNotIn("the", tokens)   # stopword
        self.assertNotIn("do", tokens)    # under 3 chars
        self.assertNotIn("not", tokens)   # stopword

    def test_deterministic(self) -> None:
        self.assertEqual(tokenize("Alpha beta alpha"), tokenize("Alpha beta alpha"))


class Bm25Tests(unittest.TestCase):
    def test_rare_shared_token_beats_common_shared_token(self) -> None:
        # "minion" appears in every doc (low IDF); "seismopod" in one (high IDF).
        store = [make_lesson("watch the minion trades vs seismopod explosions"),
                 make_lesson("minion positioning matters against cleaves"),
                 make_lesson("minion curve beats greed")]
        index = LessonIndex(store)
        rare = index.score(["seismopod", "explosions"], 0)
        common = index.score(["minion"], 1)
        self.assertGreater(rare[0], common[0])

    def test_empty_docs_and_queries_score_zero(self) -> None:
        index = LessonIndex([make_lesson("something entirely different")])
        self.assertEqual(index.score([], 0), (0.0, 0))


class ThresholdPinned(unittest.TestCase):
    """Pin the score gate low: these tests exercise gating LOGIC on a tiny
    synthetic corpus whose BM25 scores sit far below the production
    threshold (tuned on the real 17-lesson store)."""

    def setUp(self) -> None:
        import os
        os.environ["HS_RAG_T1_MIN"] = "2.0"
        self.addCleanup(os.environ.pop, "HS_RAG_T1_MIN", None)


class GateTests(ThresholdPinned):
    def test_single_token_coincidence_stays_silent(self) -> None:
        # Only one informative token ("warrior") shared -> MIN_OVERLAP gate blocks.
        store = [make_lesson("warrior removal punishes double drops")]
        hits = lexical_match(snap(opp_class="WARRIOR"), LessonIndex(store))
        self.assertEqual(hits, [])

    def test_real_text_overlap_fires(self) -> None:
        store = store_with(
            "Kill Bloodhoof Brave in ONE hit or leave it alone: taunt gains attack while damaged")
        hits = lexical_match(snap(opp_board=(CARD,)), LessonIndex(store))
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][0].lesson, store[0].lesson)
        self.assertGreaterEqual(hits[0][1], lexical.score_threshold())

    def test_deterministic_ordering(self) -> None:
        store = [make_lesson("bloodhoof brave taunt attack damaged one"),
                 make_lesson("brave bloodhoof damaged attack taunt two")]
        a = lexical_match(snap(opp_board=(CARD,)), LessonIndex(store))
        b = lexical_match(snap(opp_board=(CARD,)), LessonIndex(store))
        self.assertEqual([(r.lesson, s) for r, s in a], [(r.lesson, s) for r, s in b])


class RetrieveTests(ThresholdPinned):
    def setUp(self) -> None:
        super().setUp()
        self.triggered = make_lesson(
            "one-hit Bloodhoof Brave or leave it",
            trigger={"enemy_board": ["Bloodhoof Brave"]})
        self.textual = make_lesson(
            "taunt gains attack while damaged: kill Bloodhoof Brave in one hit")
        self.store = [self.textual, *store_with()]

    def test_t0_hit_short_circuits_t1(self) -> None:
        results, tiers = retrieve_lessons(snap(opp_board=(CARD,)),
                                          [self.triggered, *self.store])
        self.assertEqual(tiers, ["t0"])
        self.assertEqual([r["tier"] for r in results], ["t0"])
        self.assertIsNone(results[0]["score"])

    def test_t1_runs_only_on_t0_miss_and_fires_triggerless(self) -> None:
        results, tiers = retrieve_lessons(snap(opp_board=(CARD,)), self.store)
        self.assertEqual(tiers, ["t0", "t1"])
        self.assertEqual(results[0]["tier"], "t1")
        self.assertIsInstance(results[0]["score"], float)
        self.assertEqual(results[0]["lesson"].lesson, self.textual.lesson)

    def test_t1_disabled_returns_empty_on_miss(self) -> None:
        results, tiers = retrieve_lessons(snap(opp_board=(CARD,)), self.store,
                                          t1_enabled=False)
        self.assertEqual((results, tiers), ([], ["t0"]))

    def test_headline_lesson_never_fires_via_t1(self) -> None:
        headline = make_lesson(
            "taunt gains attack while damaged: kill Bloodhoof Brave in one hit",
            headline=True)
        results, tiers = retrieve_lessons(snap(opp_board=(CARD,)),
                                          [headline, *store_with()])
        self.assertEqual(tiers, ["t0", "t1"])
        self.assertEqual(results, [])

    def test_no_lessons_no_results(self) -> None:
        results, tiers = retrieve_lessons(snap(), [])
        self.assertEqual(results, [])


class CandidateTests(unittest.TestCase):
    def test_candidates_include_below_threshold_scores(self) -> None:
        store = [make_lesson("warrior removal punishes double drops")]
        cands = t1_candidates(snap(opp_class="WARRIOR"), LessonIndex(store))
        self.assertEqual(len(cands), 1)  # gated out of lexical_match, visible here
        self.assertGreater(cands[0]["score"], 0)
        self.assertEqual(cands[0]["overlap"], 1)

    def test_query_tokens_cover_names_text_flags_class(self) -> None:
        tokens = snapshot_query(snap(opp_board=(CARD,), opp_class="PALADIN"))
        for expected in ("bloodhoof", "brave", "attack", "damaged", "taunt", "paladin"):
            self.assertIn(expected, tokens)


if __name__ == "__main__":
    unittest.main()
