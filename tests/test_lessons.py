"""Tests for the trigger-matched lessons engine."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hearthstone-tracker"))

from hstracker.lessons import (  # noqa: E402
    Lesson, LessonTrigger, StoreWatcher, append_lesson, load_store, match_lessons,
)


def snap(**overrides):
    base = {
        "me": {
            "board": [{"name": "Amber Warden", "flags": ["taunt"]}],
            "hand": [{"name": "Fan of Knives"}],
        },
        "opp": {
            "class": "WARRIOR",
            "hand_hidden": 5,
            "hand": [],
            "board": [
                {"name": "Bloodhoof Brave", "flags": ["taunt"]},
                {"name": "Blob of Tar", "flags": ["taunt", "poisonous"]},
            ],
        },
    }
    base.update(overrides)
    return base


class MatchTests(unittest.TestCase):
    def test_enemy_board_card_name_fires_case_insensitively(self):
        lesson = Lesson(lesson="one-hit or leave it",
                        trigger=LessonTrigger(enemy_board=["bloodhoof brave"]))
        self.assertEqual(match_lessons(snap(), [lesson]), [lesson])

    def test_enemy_flag_fires(self):
        lesson = Lesson(lesson="never trade a big minion into poisonous",
                        trigger=LessonTrigger(enemy_flags=["Poisonous"]))
        self.assertEqual(match_lessons(snap(), [lesson]), [lesson])

    def test_all_conditions_must_hold(self):
        lesson = Lesson(lesson="x", trigger=LessonTrigger(
            enemy_board=["Bloodhoof Brave"], opp_class="MAGE"))
        self.assertEqual(match_lessons(snap(), [lesson]), [])

    def test_opp_hand_min_boundary(self):
        at = Lesson(lesson="at", trigger=LessonTrigger(opp_class="WARRIOR", opp_hand_min=5))
        above = Lesson(lesson="above", trigger=LessonTrigger(opp_class="WARRIOR", opp_hand_min=6))
        matched = match_lessons(snap(), [at, above])
        self.assertEqual(matched, [at])

    def test_untriggered_lessons_never_match(self):
        lesson = Lesson(lesson="general wisdom")
        self.assertEqual(match_lessons(snap(), [lesson]), [])

    def test_most_specific_first_and_capped(self):
        broad = Lesson(lesson="broad", trigger=LessonTrigger(opp_class="WARRIOR"))
        narrow = Lesson(lesson="narrow", trigger=LessonTrigger(
            opp_class="WARRIOR", enemy_board=["Bloodhoof Brave"], enemy_flags=["taunt"]))
        extra1 = Lesson(lesson="e1", trigger=LessonTrigger(enemy_flags=["taunt"]))
        extra2 = Lesson(lesson="e2", trigger=LessonTrigger(enemy_flags=["poisonous"]))
        matched = match_lessons(snap(), [broad, extra1, narrow, extra2], cap=3)
        self.assertEqual(len(matched), 3)
        self.assertEqual(matched[0], narrow)

    def test_my_hand_and_my_board_zones(self):
        hand = Lesson(lesson="h", trigger=LessonTrigger(my_hand=["Fan of Knives"]))
        board = Lesson(lesson="b", trigger=LessonTrigger(my_board=["Amber Warden"]))
        wrong_zone = Lesson(lesson="w", trigger=LessonTrigger(my_hand=["Amber Warden"]))
        matched = match_lessons(snap(), [hand, board, wrong_zone])
        self.assertIn(hand, matched)
        self.assertIn(board, matched)
        self.assertNotIn(wrong_zone, matched)


class StoreTests(unittest.TestCase):
    def test_append_load_roundtrip_and_dedupe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.json"
            append_lesson({"lesson": "A", "trigger": {"enemy_board": ["X"]}}, path)
            append_lesson({"lesson": "B"}, path)
            append_lesson({"lesson": "A", "trigger": {"enemy_board": ["X"]}}, path)  # dupe
            store = load_store(path)
            self.assertEqual([rec.lesson for rec in store], ["B", "A"])

    def test_bad_record_does_not_poison_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.json"
            path.write_text(json.dumps({"lessons": [
                {"lesson": "good"},
                {"trigger": "not-a-dict-and-no-lesson"},
            ]}))
            store = load_store(path)
            self.assertEqual([rec.lesson for rec in store], ["good"])

    def test_watcher_reloads_only_on_mtime_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "store.json"
            watcher = StoreWatcher(path)
            self.assertEqual(watcher.lessons(), [])
            append_lesson({"lesson": "fresh"}, path)
            self.assertEqual([rec.lesson for rec in watcher.lessons()], ["fresh"])


if __name__ == "__main__":
    unittest.main()
