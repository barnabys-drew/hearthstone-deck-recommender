from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hearthstone-tracker"))

from hstracker.budget import (  # noqa: E402
    assemble, line_cost, rank, rank_score,
)
from hstracker.lessons import Lesson, LessonStats  # noqa: E402
from hstracker.raglog import lesson_id  # noqa: E402

TODAY = date(2026, 7, 12)


def make_result(text: str, tier: str = "t0", trigger=None, rec_date=None,
                stats=None, cost=None) -> dict:
    rec = Lesson.model_validate({
        "lesson": text, "trigger": trigger or {}, "date": rec_date,
        "cost": cost,
    })
    if stats:
        rec.stats = LessonStats.model_validate(stats)
    return {"lesson": rec, "tier": tier, "score": None}


class RankScoreTests(unittest.TestCase):
    def test_more_trigger_conditions_outrank(self) -> None:
        vague = make_result("lesson a", rec_date="2026-07-10")
        specific = make_result("lesson b", rec_date="2026-07-10",
                               trigger={"enemy_board": ["X"], "opp_class": "MAGE"})
        self.assertGreater(rank_score(specific, TODAY), rank_score(vague, TODAY))

    def test_tier_trust_ordering(self) -> None:
        scores = [rank_score(make_result("same text", tier=t,
                                         rec_date="2026-07-10"), TODAY)
                  for t in ("t0", "t1", "t2")]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_recency_decays(self) -> None:
        fresh = make_result("lesson", rec_date="2026-07-10")
        stale = make_result("lesson", rec_date="2026-04-10")  # ~3 months old
        undated = make_result("lesson")  # treated as 180 days old
        self.assertGreater(rank_score(fresh, TODAY), rank_score(stale, TODAY))
        self.assertGreater(rank_score(stale, TODAY), rank_score(undated, TODAY))

    def test_winning_evidence_beats_losing_evidence(self) -> None:
        winner = make_result("lesson", rec_date="2026-07-10",
                             stats={"games_fired": 4, "won_when_fired": 4})
        loser = make_result("lesson", rec_date="2026-07-10",
                            stats={"games_fired": 4, "won_when_fired": 0})
        neutral = make_result("lesson", rec_date="2026-07-10")
        self.assertGreater(rank_score(winner, TODAY), rank_score(neutral, TODAY))
        self.assertGreater(rank_score(neutral, TODAY), rank_score(loser, TODAY))

    def test_applied_acks_boost(self) -> None:
        acked = make_result("lesson", rec_date="2026-07-10",
                            stats={"games_fired": 3, "won_when_fired": 2,
                                   "applied": 3})
        unacked = make_result("lesson", rec_date="2026-07-10",
                              stats={"games_fired": 3, "won_when_fired": 2})
        self.assertGreater(rank_score(acked, TODAY), rank_score(unacked, TODAY))


class RankTests(unittest.TestCase):
    def test_evidence_ranker_deterministic(self) -> None:
        results = [make_result(f"lesson {i}", rec_date="2026-07-10")
                   for i in range(4)]
        a = rank(results, ranker="evidence", today=TODAY)
        b = rank(list(reversed(results)), ranker="evidence", today=TODAY)
        self.assertEqual([r["lesson"].lesson for r in a],
                         [r["lesson"].lesson for r in b])

    def test_legacy_ranker_reproduces_old_order(self) -> None:
        old = make_result("old specific", rec_date="2026-01-01",
                          trigger={"enemy_board": ["X"], "opp_class": "MAGE"})
        new_vague = make_result("new vague", rec_date="2026-07-12")
        # Legacy: condition count dominates, so the stale specific record
        # still wins — exactly the behavior the evidence ranker can beat.
        legacy = rank([new_vague, old], ranker="legacy", today=TODAY)
        self.assertEqual(legacy[0]["lesson"].lesson, "old specific")

    def test_rankers_disagree_when_evidence_says_so(self) -> None:
        stale_specific = make_result(
            "stale specific", rec_date="2025-11-01",
            trigger={"enemy_board": ["X"]},
            stats={"games_fired": 5, "won_when_fired": 0})
        fresh_winner = make_result(
            "fresh winner", rec_date="2026-07-11",
            trigger={"opp_class": "MAGE"},
            stats={"games_fired": 5, "won_when_fired": 5, "applied": 3})
        results = [stale_specific, fresh_winner]
        self.assertEqual(rank(results, ranker="evidence", today=TODAY)[0]
                         ["lesson"].lesson, "fresh winner")


class AssembleTests(unittest.TestCase):
    def test_budget_cuts_worst_first(self) -> None:
        good = make_result("g" * 100, rec_date="2026-07-10",
                           trigger={"enemy_board": ["X"], "opp_class": "MAGE"})
        ok = make_result("o" * 100, rec_date="2026-07-10",
                         trigger={"opp_class": "MAGE"})
        weak = make_result("w" * 100, rec_date="2026-07-10")
        cost = line_cost(good)
        kept, dropped, spent = assemble([weak, good, ok], budget=cost * 2,
                                        ranker="evidence", today=TODAY)
        self.assertEqual([r["lesson"].lesson[0] for r in kept], ["g", "o"])
        self.assertEqual(dropped, [lesson_id(weak["lesson"].lesson)])
        self.assertEqual(spent, cost * 2)

    def test_top_candidate_kept_even_over_budget(self) -> None:
        only = make_result("x" * 200, rec_date="2026-07-10")
        kept, dropped, spent = assemble([only], budget=10, today=TODAY)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped, [])
        self.assertGreater(spent, 10)

    def test_cap_holds_under_generous_budget(self) -> None:
        results = [make_result(f"lesson number {i}", rec_date="2026-07-10")
                   for i in range(8)]
        kept, dropped, _ = assemble(results, budget=100_000, cap=5, today=TODAY)
        self.assertEqual((len(kept), len(dropped)), (5, 3))

    def test_cost_string_counts_against_budget(self) -> None:
        with_cost = make_result("lesson", cost="the whole game")
        without = make_result("lesson")
        self.assertGreater(line_cost(with_cost), line_cost(without))


if __name__ == "__main__":
    unittest.main()
