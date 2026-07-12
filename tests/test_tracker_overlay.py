from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACKER = ROOT / "hearthstone-tracker"
sys.path.insert(0, str(TRACKER))


class OverlayBridgeTests(unittest.TestCase):
    def test_normalize_advice_shapes_payload(self) -> None:
        from hstracker.overlay import normalize_advice

        advice = normalize_advice({
            "kind": "lethal",
            "turn": "8",
            "headline": "Kill them",
            "why": "5+5 beats their 10.",
            "steps": "Swing face\nFireball face",
            "warning": "Do not trade.",
            "lethal": {"math": "5+5 = 10 ≥ 10"},
        })
        self.assertEqual(advice["kind"], "lethal")
        self.assertEqual(advice["turn"], 8)
        self.assertEqual(advice["steps"], ["Swing face", "Fireball face"])
        self.assertTrue(advice["lethal"]["is_lethal"])
        self.assertEqual(advice["lethal"]["math"], "5+5 = 10 ≥ 10")
        self.assertIn("ts", advice)

    def test_write_advice_and_mirror_live_are_atomic_json_files(self) -> None:
        from hstracker.overlay import mirror_live_snapshot, write_advice

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            advice_path = write_advice({"kind": "turn", "turn": 3, "steps": ["Trade first"]}, out)
            live_path = mirror_live_snapshot({"turn": 3, "me": {"hp": 30}, "opp": {"hp": 12}}, out)

            self.assertEqual(advice_path.name, "advice.json")
            self.assertEqual(live_path.name, "live.json")
            self.assertEqual(json.loads(advice_path.read_text())["steps"], ["Trade first"])
            self.assertEqual(json.loads(live_path.read_text())["opp"]["hp"], 12)
            self.assertFalse(list(out.glob("*.tmp")))

    def test_coach_publish_cli_accepts_stdin_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"kind": "mulligan", "turn": 0, "mulligan": [{"card": "The Coin", "keep": False, "reason": "not a keep"}]}
            proc = subprocess.run(
                [sys.executable, str(TRACKER / "coach_publish.py"), "--overlay-dir", tmp],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("advice.json", proc.stdout)
            advice = json.loads((Path(tmp) / "advice.json").read_text())
            self.assertEqual(advice["kind"], "mulligan")
            self.assertEqual(advice["mulligan"][0]["card"], "The Coin")

            subprocess.run(
                [sys.executable, str(TRACKER / "coach_publish.py"), "--overlay-dir", tmp, "--clear"],
                capture_output=True,
                text=True,
                check=True,
            )
            cleared = json.loads((Path(tmp) / "advice.json").read_text())
            self.assertEqual(cleared["kind"], "idle")


if __name__ == "__main__":
    unittest.main()
