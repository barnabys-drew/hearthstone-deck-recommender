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


if __name__ == "__main__":
    unittest.main()
