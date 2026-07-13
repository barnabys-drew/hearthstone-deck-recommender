from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hearthstone-tracker"))

try:
    import hslog  # noqa: F401

    HAS_HSLOG = True
except ImportError:
    HAS_HSLOG = False


@unittest.skipUnless(HAS_HSLOG, "hslog not installed (pip install -r hearthstone-tracker/requirements.txt)")
class CardTextTests(unittest.TestCase):
    def test_strips_hearthstonejson_markup(self) -> None:
        from hstracker.live import card_text

        card = {"text": "[x]<b>Battlecry:</b> Deal $2 damage\nto a minion."}
        self.assertEqual(card_text(card), "Battlecry: Deal 2 damage to a minion.")

    def test_missing_or_empty_text_is_none(self) -> None:
        from hstracker.live import card_text

        self.assertIsNone(card_text({}))
        self.assertIsNone(card_text({"text": "<i></i>"}))

    def test_at_joined_variants_take_first_segment(self) -> None:
        """Live-session regression (2026-07-13): Broodwatcher's snapshot text
        showed the same Battlecry three times concatenated with "@". Cards
        with an in-hand progress counter store several complete "@"-joined
        text variants (in-progress/ready/static); we don't track the live
        counter needed to pick the right one, so take the first — it's
        always the complete, state-independent phrasing."""
        from hstracker.live import card_text

        card = {"text": ("[x]<b>Battlecry:</b> Get two 3/3 Whelps with "
                          "<b>Taunt</b>. If you spent 8 Mana while holding "
                          "this, summon them. <i>({0} left!)</i>"
                          "@[x]<b>Battlecry:</b> ...ready variant..."
                          "@[x]<b>Battlecry:</b> ...static variant...")}
        self.assertEqual(
            card_text(card),
            "Battlecry: Get two 3/3 Whelps with Taunt. If you spent 8 Mana "
            "while holding this, summon them. (X left!)")

    def test_unfilled_numbered_placeholder_becomes_x(self) -> None:
        """Live-session regression (2026-07-13): Scorching Ravager's snapshot
        text was "Battlecry: Herald {0}. Give the Soldier Rush." — a raw,
        never-filled HearthstoneJSON template placeholder leaking straight
        into the coach's advice input."""
        from hstracker.live import card_text

        card = {"text": "<b>Battlecry:</b> <b>Herald</b> {0}. Give the Soldier <b>Rush</b>."}
        self.assertEqual(card_text(card), "Battlecry: Herald X. Give the Soldier Rush.")


@unittest.skipUnless(HAS_HSLOG, "hslog not installed (pip install -r hearthstone-tracker/requirements.txt)")
class SnapshotDeltaTests(unittest.TestCase):
    """Mid-turn deltas must describe GAINED cards, not just name them.

    Live-session regression (2026-07-12, turn 2): the player cast Flashback and
    the feed printed only "board +Adaptive Amalgam, Crystalline Oracle" — no
    stats or text — so the coach had to ask what Flashback generated.
    """

    @staticmethod
    def _snap(hand, board, opp_board=()):
        return {
            "turn": 2,
            "me": {"hand": list(hand), "board": list(board)},
            "opp": {"hand": [], "hand_hidden": 5, "board": list(opp_board)},
        }

    def test_flashback_generated_minions_get_stats_and_text(self) -> None:
        from hstracker.live import snapshot_delta

        flashback = {"name": "Flashback", "cost": 2, "type": "SPELL",
                     "text": "Summon two random 1-Cost minions from the past.", "pos": 1}
        knight = {"name": "Bitterbloom Knight", "atk": 2, "health": 3, "pos": 1,
                  "flags": [], "location": False, "text": None}
        amalgam = {"name": "Adaptive Amalgam", "atk": 1, "health": 2, "pos": 2,
                   "flags": [], "location": False,
                   "text": "Deathrattle: Shuffle this into your deck. It keeps any enchantments."}
        oracle = {"name": "Crystalline Oracle", "atk": 1, "health": 2, "pos": 3,
                  "flags": [], "location": False,
                  "text": "Deathrattle: Copy a card from your opponent's deck and add it to your hand."}

        delta = snapshot_delta(
            self._snap([flashback], [knight]),
            self._snap([], [knight, amalgam, oracle]),
        )
        self.assertIsNotNone(delta)
        self.assertIn("Adaptive Amalgam 1/2 [Deathrattle: Shuffle this into your deck", delta)
        self.assertIn("Crystalline Oracle 1/2 [Deathrattle: Copy a card from your opponent's deck", delta)
        # The card that LEFT hand stays a bare name — the coach already saw it.
        self.assertIn("hand -Flashback", delta)

    def test_hand_generated_card_gets_cost_and_text(self) -> None:
        from hstracker.live import snapshot_delta

        swimmer = {"name": "Sewer Swimmer", "cost": 1, "type": "MINION",
                   "text": "Gains +2/+2 at the end of your turn.", "pos": 1}
        delta = snapshot_delta(self._snap([], []), self._snap([swimmer], []))
        self.assertIsNotNone(delta)
        self.assertIn("hand +Sewer Swimmer(1) [Gains +2/+2 at the end of your turn.]", delta)

    def test_opp_board_gain_gets_stats(self) -> None:
        from hstracker.live import snapshot_delta

        ghoul = {"name": "Frail Ghoul", "atk": 1, "health": 1, "pos": 1,
                 "flags": [], "location": False,
                 "text": "At the end of your turn, this minion dies."}
        delta = snapshot_delta(
            self._snap([], []),
            self._snap([], [], opp_board=[ghoul]),
        )
        self.assertIsNotNone(delta)
        self.assertIn("opp board +Frail Ghoul 1/1 [At the end of your turn, this minion dies.]", delta)

    def test_long_rules_text_is_truncated(self) -> None:
        from hstracker.live import snapshot_delta

        wall = {"name": "Wall of Words", "cost": 3, "type": "MINION",
                "text": "x" * 200, "pos": 1}
        delta = snapshot_delta(self._snap([], []), self._snap([wall], []))
        self.assertIsNotNone(delta)
        self.assertIn(f"Wall of Words(3) [{'x' * 90}]", delta)
        self.assertNotIn("x" * 91, delta)

    def test_no_change_returns_none(self) -> None:
        from hstracker.live import snapshot_delta

        snap = self._snap([], [])
        self.assertIsNone(snapshot_delta(snap, self._snap([], [])))
        self.assertIsNone(snapshot_delta(snap, snap))


if __name__ == "__main__":
    unittest.main()
