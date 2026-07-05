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
class SaveGamesTests(unittest.TestCase):
    def setUp(self) -> None:
        from hstracker.db import connect

        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "games.db")

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_insert_and_dedupe(self) -> None:
        from hstracker.db import save_games

        record = make_record()
        self.assertEqual(save_games(self.conn, [record]), 1)
        self.assertEqual(save_games(self.conn, [record]), 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 1)

    def test_card_rows_saved_and_backfilled_for_existing_games(self) -> None:
        from hstracker.db import save_games

        cards = [dict(card_id="CS2_106", friendly=1, drawn=1, played=2,
                      mull_offered=1, mull_kept=1, first_played_turn=3)]
        save_games(self.conn, [make_record()])  # game exists without card rows
        save_games(self.conn, [make_record(cards=cards)])  # re-import fills them
        row = self.conn.execute("SELECT card_id, played FROM game_cards").fetchone()
        self.assertEqual((row["card_id"], row["played"]), ("CS2_106", 2))

    def test_bg_fields_upgrade_when_previously_null(self) -> None:
        from hstracker.db import save_games

        bg = dict(game_type="GT_BATTLEGROUNDS", result="LOST",
                  friendly_hero="TB_BaconShop_HERO_PH", opponent_name="Bob#0")
        save_games(self.conn, [make_record(**bg)])
        save_games(self.conn, [make_record(**{**bg, "friendly_hero": "TB_BaconShop_HERO_23",
                                              "bg_place": 2, "bg_tech": 4})])
        row = self.conn.execute("SELECT bg_place, bg_tech, friendly_hero FROM games").fetchone()
        self.assertEqual(tuple(row), (2, 4, "TB_BaconShop_HERO_23"))


@unittest.skipUnless(HAS_HSLOG, "hslog not installed (pip install -r hearthstone-tracker/requirements.txt)")
class StatsQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        from hstracker.db import connect, save_games

        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / "games.db")
        hero_rows = [
            dict(card_id="TB_BaconShop_HERO_23", friendly=1, drawn=0, played=0,
                 mull_offered=1, mull_kept=1, first_played_turn=None),
            dict(card_id="TB_BaconShop_HERO_16", friendly=1, drawn=0, played=0,
                 mull_offered=1, mull_kept=0, first_played_turn=None),
        ]
        save_games(self.conn, [
            make_record(deck_name="Burn Warrior", result="WON"),
            make_record(start_time="2026-07-04 17:00:00", deck_name="Burn Warrior",
                        result="LOST", opponent_class="MAGE",
                        cards=[dict(card_id="CS2_106", friendly=1, drawn=1, played=1,
                                    mull_offered=1, mull_kept=1, first_played_turn=3)]),
            make_record(start_time="2026-07-04 18:00:00", game_type="GT_BATTLEGROUNDS",
                        result="LOST", friendly_hero="TB_BaconShop_HERO_23",
                        bg_place=2, bg_tech=4, opponent_name="Bob#0", cards=hero_rows),
        ])

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_by_deck_aggregates_wins(self) -> None:
        from hstracker import stats

        rows = stats.by_deck(self.conn)
        self.assertEqual((rows[0]["deck"], rows[0]["games"], rows[0]["wins"]),
                         ("Burn Warrior", 2, 1))

    def test_mulligan_excludes_battlegrounds_hero_picks(self) -> None:
        from hstracker import stats

        cards = {r["card_id"] for r in stats.mulligan(self.conn)}
        self.assertEqual(cards, {"CS2_106"})

    def test_bg_overall_uses_placement_not_result(self) -> None:
        from hstracker import stats

        row = stats.bg_overall(self.conn)[0]
        self.assertEqual((row["games"], row["avg_place"], row["top4_pct"]), (1, 2.0, 100.0))

    def test_bg_hero_picks_reads_hero_choice_rows(self) -> None:
        from hstracker import stats

        rows = {r["card_id"]: r["picked"] for r in stats.bg_hero_picks(self.conn)}
        self.assertEqual(rows, {"TB_BaconShop_HERO_23": 1, "TB_BaconShop_HERO_16": 0})


if __name__ == "__main__":
    unittest.main()
