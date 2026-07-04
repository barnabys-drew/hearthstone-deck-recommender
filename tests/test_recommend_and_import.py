from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hearthstone-deck-recommender" / "scripts"))

import recommend_and_import as rai  # noqa: E402

BASE_ARGS = [
    "--collection", str(ROOT / "examples" / "collection.sample.json"),
    "--cards-json", str(ROOT / "examples" / "cards.sample.json"),
]

FAKE_FETCHED = [
    {
        "name": "Fetched Tempo",
        "class": "Warrior",
        "format": "standard",
        "deckstring": "AAEBAQcBBQEBAAA=",
        "source_rank": 1,
    }
]


class AutoFetchTests(unittest.TestCase):
    def run_main(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = rai.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_omitting_decks_fetches_live(self) -> None:
        with mock.patch.object(rai, "fetch_decks", return_value=FAKE_FETCHED) as fetcher:
            rc, out, err = self.run_main(BASE_ARGS)
        self.assertEqual(rc, 0)
        fetcher.assert_called_once()
        self.assertIn("Fetched Tempo", out)
        self.assertIn("COPY THIS INTO HEARTHSTONE", out)
        self.assertIn("fetching current Standard meta decks", err)

    def test_no_fetch_without_decks_errors(self) -> None:
        with mock.patch.object(rai, "fetch_decks") as fetcher:
            rc, _, err = self.run_main([*BASE_ARGS, "--no-fetch"])
        self.assertEqual(rc, 2)
        fetcher.assert_not_called()
        self.assertIn("--decks is required when --no-fetch is set", err)

    def test_empty_live_fetch_errors_with_guidance(self) -> None:
        with mock.patch.object(rai, "fetch_decks", return_value=[]):
            rc, _, err = self.run_main(BASE_ARGS)
        self.assertEqual(rc, 2)
        self.assertIn("assemble meta_decks.json by hand", err)

    def test_explicit_decks_skips_live_fetch(self) -> None:
        with mock.patch.object(rai, "fetch_decks") as fetcher:
            rc, out, _ = self.run_main(
                [*BASE_ARGS, "--decks", str(ROOT / "examples" / "meta_decks.sample.json"), "--no-fetch"]
            )
        self.assertEqual(rc, 0)
        fetcher.assert_not_called()
        self.assertIn("COPY THIS INTO HEARTHSTONE", out)


if __name__ == "__main__":
    unittest.main()
