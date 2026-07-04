from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hearthstone-deck-recommender" / "scripts"))

import fetch_meta_decks as f  # noqa: E402


class FetchHelperTests(unittest.TestCase):
    def test_guess_class_from_url(self) -> None:
        self.assertEqual(f.guess_class("https://x/dragon-warrior-1-legend/", ""), "Warrior")
        self.assertEqual(f.guess_class("https://x/broxigar-demon-hunter-7/", ""), "Demon Hunter")
        self.assertIsNone(f.guess_class("https://x/some-random-deck/", "Untitled"))

    def test_clean_title_strips_suffix(self) -> None:
        self.assertEqual(
            f.clean_title("Dragon Warrior #41 Legend - Hearthstone-Decks.net", "https://x/dragon-warrior-41/"),
            "Dragon Warrior #41 Legend",
        )

    def test_clean_title_falls_back_to_slug(self) -> None:
        self.assertEqual(f.clean_title("", "https://x/burn-warrior-129-legend/"), "Burn Warrior 129 Legend")

    def test_deckstring_regex_matches_real_code(self) -> None:
        code = "AAECAQcAD4agBI7UBJDUBOPmBuiHB4WVB9WmB+2sB/yvB4+xB9CyB9ayB5XCB5vCB5zCBwAA"
        found = f.DECKSTRING_RE.findall(f"junk before {code} junk after")
        self.assertIn(code, found)

    def test_deckstring_regex_ignores_short_blobs(self) -> None:
        self.assertEqual(f.DECKSTRING_RE.findall("AAEshort"), [])


if __name__ == "__main__":
    unittest.main()
