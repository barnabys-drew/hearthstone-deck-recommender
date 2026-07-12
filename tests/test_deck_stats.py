from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hearthstone-tracker"))

try:
    import hslog  # noqa: F401

    HAS_HSLOG = True
except ImportError:
    HAS_HSLOG = False


def make_record(**overrides):
    from hstracker.capture import GameRecord

    base = dict(
        start_time="2026-07-04 16:24:22",
        end_time="2026-07-04 16:30:46",
        duration_seconds=384,
        game_type="GT_RANKED",
        format_type="FT_STANDARD",
        scenario_id=2,
        build_number=245258,
        friendly_name="Me#1234",
        friendly_class="WARRIOR",
        friendly_hero="HERO_01",
        opponent_name="Them#5678",
        opponent_class="DRUID",
        opponent_hero="HERO_06",
        friendly_first=1,
        result="WON",
        turns=15,
        bg_place=None,
        source_file="test",
    )
    base.update(overrides)
    return GameRecord(**base)


@unittest.skipUnless(HAS_HSLOG, "hslog not installed (pip install -r hearthstone-tracker/requirements.txt)")
class DeckStatsTests(unittest.TestCase):
    def setUp(self) -> None:
        from hstracker.db import connect

        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "games.db")

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_no_games_at_all_returns_none(self) -> None:
        from hstracker.deckstats import deck_stats

        self.assertIsNone(deck_stats(self.conn))

    def test_new_deck_with_no_history_still_reports_overall(self) -> None:
        from hstracker.db import save_games
        from hstracker.deckstats import deck_stats

        save_games(self.conn, [make_record(deck_name="Old Deck", result="WON")])
        payload = deck_stats(self.conn, deck_name="Brand New Deck")

        self.assertEqual(payload["games"], 0)
        self.assertIsNone(payload["streak"])
        self.assertEqual(payload["overall"], {"games": 1, "wins": 1, "losses": 0, "winrate": 100})

    def test_streak_counts_consecutive_most_recent_results(self) -> None:
        from hstracker.db import save_games
        from hstracker.deckstats import deck_stats

        save_games(self.conn, [
            make_record(start_time="2026-07-01 00:00:00", deck_name="Burn Warrior", result="LOST"),
            make_record(start_time="2026-07-02 00:00:00", deck_name="Burn Warrior", result="WON"),
            make_record(start_time="2026-07-03 00:00:00", deck_name="Burn Warrior", result="WON"),
            make_record(start_time="2026-07-04 00:00:00", deck_name="Burn Warrior", result="WON"),
        ])
        payload = deck_stats(self.conn, deck_name="Burn Warrior")

        self.assertEqual(payload["streak"], "W3")
        self.assertEqual(payload["last10"], [True, True, True, False])

    def test_streak_after_a_loss_is_l1(self) -> None:
        from hstracker.db import save_games
        from hstracker.deckstats import deck_stats

        save_games(self.conn, [
            make_record(start_time="2026-07-01 00:00:00", deck_name="Burn Warrior", result="WON"),
            make_record(start_time="2026-07-02 00:00:00", deck_name="Burn Warrior", result="LOST"),
        ])
        payload = deck_stats(self.conn, deck_name="Burn Warrior")

        self.assertEqual(payload["streak"], "L1")

    def test_overall_spans_every_deck_not_just_the_current_one(self) -> None:
        from hstracker.db import save_games
        from hstracker.deckstats import deck_stats

        save_games(self.conn, [
            make_record(start_time="2026-07-01 00:00:00", deck_name="Burn Warrior", result="WON"),
            make_record(start_time="2026-07-02 00:00:00", deck_name="Control Priest", result="LOST",
                        opponent_name="Them#9999"),
        ])
        payload = deck_stats(self.conn, deck_name="Burn Warrior")

        self.assertEqual(payload["games"], 1)
        self.assertEqual(payload["overall"], {"games": 2, "wins": 1, "losses": 1, "winrate": 50})


if __name__ == "__main__":
    unittest.main()
