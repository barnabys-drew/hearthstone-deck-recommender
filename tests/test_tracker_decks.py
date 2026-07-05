from __future__ import annotations

import base64
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hearthstone-tracker"))

try:
    import hslog  # noqa: F401

    HAS_HSLOG = True
except ImportError:
    HAS_HSLOG = False

# A syntactically valid deckstring: reserved byte 0, version 1.
CODE = base64.b64encode(bytes([0, 1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14])).decode()

# Real Decks.log format: 'I ' severity prefix, and one "Deck Contents
# Received" block listing several decks back to back.
DECKS_LOG = f"""I 16:23:39.7656255 Deck Contents Received:
I 16:23:39.7656255 ### Ladder Ready Warrior
I 16:23:39.7656255 # Deck ID: 3367724703
I 16:23:39.7656255 {CODE}
I 16:23:39.7656255 ### Burn Warrior
I 16:23:39.7656255 # Deck ID: 3367803731
I 16:23:39.7656255 {CODE}
I 16:24:13.4576007 Finding Game With Deck:
I 16:24:13.4576007 ### Burn Warrior
I 16:24:13.4576007 # Deck ID: 3367803731
I 16:24:13.4576007 {CODE}
"""


@unittest.skipUnless(HAS_HSLOG, "hslog not installed (pip install -r hearthstone-tracker/requirements.txt)")
class DeckLogParserTests(unittest.TestCase):
    def parse(self, text: str):
        from hstracker.decks import DeckLogParser

        parser = DeckLogParser(datetime(2026, 7, 4, 16, 23, 20))
        for line in text.splitlines():
            parser.feed(line)
        return parser.events

    def test_multi_deck_contents_block_yields_every_deck(self) -> None:
        events = self.parse(DECKS_LOG)
        self.assertEqual(
            [e.name for e in events],
            ["Ladder Ready Warrior", "Burn Warrior", "Burn Warrior"],
        )

    def test_deckstring_and_timestamp_captured(self) -> None:
        events = self.parse(DECKS_LOG)
        self.assertEqual(events[-1].deckstring, CODE)
        self.assertEqual(events[-1].when.replace(microsecond=0),
                         datetime(2026, 7, 4, 16, 24, 13))

    def test_non_deckstring_base64_lines_are_ignored(self) -> None:
        from hstracker.decks import _looks_like_deckstring

        self.assertTrue(_looks_like_deckstring(CODE))
        # Valid base64, but does not start with the 0x00 0x01 deckstring header.
        self.assertFalse(_looks_like_deckstring(base64.b64encode(b"hello hearthstone!").decode()))
        self.assertFalse(_looks_like_deckstring("### not base64 at all"))


@unittest.skipUnless(HAS_HSLOG, "hslog not installed (pip install -r hearthstone-tracker/requirements.txt)")
class MatchDeckTests(unittest.TestCase):
    def events(self):
        from hstracker.decks import DeckEvent

        return [
            DeckEvent(datetime(2026, 7, 4, 16, 5, 0), "Old Deck", CODE),
            DeckEvent(datetime(2026, 7, 4, 16, 24, 13), "Burn Warrior", CODE),
        ]

    def test_latest_event_before_game_start_wins(self) -> None:
        from hstracker.decks import match_deck

        match = match_deck(self.events(), datetime(2026, 7, 4, 16, 24, 22))
        self.assertEqual(match.name, "Burn Warrior")

    def test_events_after_game_start_are_not_matched(self) -> None:
        from hstracker.decks import match_deck

        match = match_deck(self.events(), datetime(2026, 7, 4, 16, 10, 0))
        self.assertEqual(match.name, "Old Deck")

    def test_stale_events_outside_window_do_not_match(self) -> None:
        from hstracker.decks import match_deck

        self.assertIsNone(match_deck(self.events(), datetime(2026, 7, 4, 18, 0, 0)))

    def test_attach_decks_skips_battlegrounds(self) -> None:
        from hstracker.decks import attach_decks

        bg = SimpleNamespace(game_type="GT_BATTLEGROUNDS", start_time="2026-07-04 16:24:22",
                             deck_name=None, deckstring=None)
        ranked = SimpleNamespace(game_type="GT_RANKED", start_time="2026-07-04 16:24:22",
                                 deck_name=None, deckstring=None)
        attach_decks([bg, ranked], self.events())
        self.assertIsNone(bg.deck_name)
        self.assertEqual(ranked.deck_name, "Burn Warrior")


if __name__ == "__main__":
    unittest.main()
