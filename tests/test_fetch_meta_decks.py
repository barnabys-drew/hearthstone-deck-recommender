from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class SensitiveOutPathTests(unittest.TestCase):
    def test_system_paths_are_sensitive(self) -> None:
        for path in ("/etc/meta_decks.json", "/usr/local/share/x.json", "/var/tmp/x.json"):
            self.assertTrue(f.is_sensitive_out_path(path), path)

    def test_home_dotfiles_are_sensitive(self) -> None:
        home = Path.home()
        self.assertTrue(f.is_sensitive_out_path(str(home / ".bashrc")))
        self.assertTrue(f.is_sensitive_out_path(str(home / ".ssh" / "meta_decks.json")))

    def test_ordinary_paths_are_fine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(f.is_sensitive_out_path(str(Path(tmp) / "meta_decks.json")))
        self.assertFalse(f.is_sensitive_out_path(str(Path.home() / "decks" / "meta.json")))
        self.assertFalse(f.is_sensitive_out_path("meta_decks.json"))

    def test_dot_segments_do_not_bypass_guard(self) -> None:
        self.assertTrue(f.is_sensitive_out_path("/tmp/../etc/meta_decks.json"))

    def test_main_refuses_sensitive_out_without_force(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(f, "fetch_decks") as fetch_mock, \
                contextlib.redirect_stderr(stderr):
            code = f.main(["--out", "/etc/meta_decks.json"])
        self.assertEqual(code, 2)
        self.assertIn("refusing to write", stderr.getvalue())
        fetch_mock.assert_not_called()


class FetchSizeLimitTests(unittest.TestCase):
    def test_fetch_rejects_oversized_page(self) -> None:
        class FakeResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        oversized = FakeResponse(b"x" * (f.MAX_PAGE_BYTES + 1))
        with mock.patch.object(f.urllib.request, "urlopen", return_value=oversized):
            with self.assertRaises(ValueError):
                f.fetch("https://example.com/huge")


if __name__ == "__main__":
    unittest.main()
