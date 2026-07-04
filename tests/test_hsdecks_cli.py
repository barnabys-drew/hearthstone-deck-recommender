from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


class HsdecksCliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [PYTHON, "hsdecks.py", *args],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_no_args_prints_usage(self) -> None:
        result = self.run_cli()
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage: hsdecks.py", result.stdout)
        for command in ("recommend", "rank", "fetch-decks", "build"):
            self.assertIn(command, result.stdout)

    def test_unknown_command_fails(self) -> None:
        result = self.run_cli("bogus")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown command 'bogus'", result.stderr)

    def test_build_dispatches_to_builder(self) -> None:
        result = self.run_cli("build", "--selftest")
        self.assertEqual(result.returncode, 0)
        self.assertIn("selftest ok", result.stdout)

    def test_recommend_dispatches_with_fixtures(self) -> None:
        result = self.run_cli(
            "recommend",
            "--collection", "examples/collection.sample.json",
            "--decks", "examples/meta_decks.sample.json",
            "--cards-json", "examples/cards.sample.json",
            "--no-fetch",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("COPY THIS INTO HEARTHSTONE", result.stdout)

    def test_subcommand_exit_code_passes_through(self) -> None:
        result = self.run_cli("rank", "--collection", "does-not-exist.json")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
