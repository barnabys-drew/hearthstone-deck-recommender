from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hearthstone-tracker"))

from hstracker.hygiene import (  # noqa: E402
    compute_stats, decay_candidates, headline_candidates, maintain,
    near_duplicates,
)
from hstracker.lessons import Lesson, load_store  # noqa: E402
from hstracker.raglog import lesson_id  # noqa: E402


def make_lesson(text: str, **fields) -> Lesson:
    trigger = fields.pop("trigger", {})
    return Lesson.model_validate({"lesson": text, "trigger": trigger, **fields})


def match_ev(lids, session="S", game_no=1, raw_turn=3, ts=1000.0):
    return {"ev": "match", "session": session, "game_no": game_no,
            "raw_turn": raw_turn, "tiers": ["t0"],
            "matched": [{"id": lid, "tier": "t0", "conds": 1} for lid in lids],
            "ts": ts}


def corpus_ev(lids, session="S", game_no=1, ts=999.0):
    return {"ev": "corpus", "session": session, "game_no": game_no,
            "ids": list(lids), "count": len(lids), "untriggered": [], "ts": ts}


def outcome_ev(result, session="S", game_no=1, ts=2000.0):
    return {"ev": "outcome", "session": session, "game_no": game_no,
            "result": result, "deck": None, "opp_class": "MAGE", "turns": 9,
            "ts": ts}


class StatsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fired = make_lesson("spend every weapon charge")
        self.dead = make_lesson("never popped seismopod")
        self.store = [self.fired, self.dead]
        self.fid = lesson_id(self.fired.lesson)
        self.did = lesson_id(self.dead.lesson)

    def test_counts_turns_games_wins_and_corpus(self) -> None:
        events = [
            corpus_ev([self.fid, self.did], game_no=1),
            match_ev([self.fid], game_no=1, raw_turn=3),
            match_ev([self.fid], game_no=1, raw_turn=5, ts=1100.0),
            outcome_ev("WON", game_no=1),
            corpus_ev([self.fid, self.did], game_no=2, ts=3000.0),
            match_ev([self.fid], game_no=2, raw_turn=7, ts=3100.0),
            outcome_ev("LOST", game_no=2, ts=4000.0),
        ]
        stats = compute_stats(events, self.store)
        s = stats[self.fid]
        self.assertEqual((s.times_fired, s.games_fired, s.won_when_fired,
                          s.games_in_corpus), (3, 2, 1, 2))
        self.assertIsNotNone(s.last_fired)
        d = stats[self.did]
        self.assertEqual((d.times_fired, d.games_in_corpus), (0, 2))
        self.assertIsNone(d.last_fired)

    def test_replay_events_do_not_count(self) -> None:
        events = [corpus_ev([self.fid]),
                  dict(match_ev([self.fid]), replay=True),
                  outcome_ev("WON")]
        self.assertEqual(compute_stats(events, self.store)[self.fid].times_fired, 0)


class DedupeTests(unittest.TestCase):
    def test_near_identical_pair_found_and_keeper_is_more_specific(self) -> None:
        vague = make_lesson("kill bloodhoof brave in one hit or leave it alone")
        specific = make_lesson(
            "kill bloodhoof brave in ONE hit or leave it alone entirely",
            trigger={"enemy_board": ["Bloodhoof Brave"]})
        pairs = near_duplicates([vague, specific])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["keep"].lesson, specific.lesson)
        self.assertEqual(pairs[0]["drop"].lesson, vague.lesson)

    def test_unrelated_lessons_not_paired(self) -> None:
        a = make_lesson("spend every weapon charge every turn")
        b = make_lesson("never trade big minions into poisonous bodies")
        self.assertEqual(near_duplicates([a, b]), [])

    def test_different_opp_class_never_merges(self) -> None:
        a = make_lesson("deny the board every single early turn",
                        trigger={"opp_class": "PALADIN"})
        b = make_lesson("deny the board every single early turn always",
                        trigger={"opp_class": "SHAMAN"})
        self.assertEqual(near_duplicates([a, b]), [])

    def test_headline_never_participates(self) -> None:
        a = make_lesson("deny the board every single early turn")
        b = make_lesson("deny the board every single early turn always",
                        headline=True)
        self.assertEqual(near_duplicates([a, b]), [])

    def test_deterministic(self) -> None:
        a = make_lesson("coin only when it converts into an extra play")
        b = make_lesson("coin only when it converts into an extra play now")
        p1, p2 = near_duplicates([a, b]), near_duplicates([b, a])
        self.assertEqual(p1[0]["keep"].lesson, p2[0]["keep"].lesson)


class DecayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rec = make_lesson("never popped seismopod")
        self.lid = lesson_id(self.rec.lesson)

    def events(self, games: int):
        evs = []
        for n in range(1, games + 1):
            evs.append(corpus_ev([self.lid], game_no=n, ts=n * 100.0))
            evs.append(outcome_ev("LOST", game_no=n, ts=n * 100.0 + 50))
        return evs

    def test_archives_only_past_the_game_floor(self) -> None:
        store = [self.rec]
        below = compute_stats(self.events(14), store)
        at = compute_stats(self.events(15), store)
        self.assertEqual(decay_candidates(store, below, min_games=15), [])
        self.assertEqual(decay_candidates(store, at, min_games=15), [self.rec])

    def test_headline_exempt(self) -> None:
        head = make_lesson("never popped seismopod", headline=True)
        stats = compute_stats(self.events(20), [head])
        self.assertEqual(decay_candidates([head], stats, min_games=15), [])


class HeadlineCandidateTests(unittest.TestCase):
    def test_repeat_firers_ranked(self) -> None:
        hot = make_lesson("spend every weapon charge")
        cold = make_lesson("never popped seismopod")
        hid = lesson_id(hot.lesson)
        events = []
        for n in (1, 2, 3):
            events += [corpus_ev([hid], game_no=n, ts=n * 100.0),
                       match_ev([hid], game_no=n, ts=n * 100.0 + 10),
                       outcome_ev("WON", game_no=n, ts=n * 100.0 + 50)]
        stats = compute_stats(events, [hot, cold])
        cands = headline_candidates([hot, cold], stats)
        self.assertEqual([c["id"] for c in cands], [hid])
        self.assertEqual(cands[0]["games_fired"], 3)


class MaintainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.store_path = Path(self.dir.name) / "lesson_store.json"
        self.log_path = Path(self.dir.name) / "retrieval_log.jsonl"
        self.archive_path = Path(self.dir.name) / "lesson_archive.json"
        self.keep = make_lesson("kill bloodhoof brave in one hit or leave it",
                                trigger={"enemy_board": ["Bloodhoof Brave"]})
        self.dupe = make_lesson("kill bloodhoof brave in one hit or leave it be")
        self.dead = make_lesson("never popped seismopod")
        self._write_store([self.keep, self.dupe, self.dead])
        dead_id = lesson_id(self.dead.lesson)
        keep_id = lesson_id(self.keep.lesson)
        events = []
        for n in range(1, 16):
            events.append(corpus_ev([dead_id, keep_id], game_no=n, ts=n * 100.0))
            events.append(match_ev([keep_id], game_no=n, ts=n * 100.0 + 10))
            events.append(outcome_ev("WON", game_no=n, ts=n * 100.0 + 50))
        self.log_path.write_text(
            "\n".join(json.dumps(ev) for ev in events) + "\n", encoding="utf-8")

    def _write_store(self, lessons) -> None:
        self.store_path.write_text(json.dumps(
            {"ts": 0, "lessons": [rec.model_dump(mode="json") for rec in lessons]}),
            encoding="utf-8")

    def run_maintain(self, apply: bool):
        return maintain(self.store_path, self.log_path, self.archive_path,
                        apply=apply, decay_games=15)

    def test_dry_run_reports_but_writes_nothing(self) -> None:
        before = self.store_path.read_text()
        report = self.run_maintain(apply=False)
        self.assertEqual(len(report["duplicates"]), 1)
        self.assertEqual(len(report["decayed"]), 1)
        self.assertEqual(self.store_path.read_text(), before)
        self.assertFalse(self.archive_path.exists())

    def test_apply_stamps_merges_archives(self) -> None:
        report = self.run_maintain(apply=True)
        self.assertEqual(report["archived_count"], 2)  # dupe + decayed
        remaining = load_store(self.store_path)
        self.assertEqual([rec.lesson for rec in remaining], [self.keep.lesson])
        self.assertEqual(remaining[0].stats.games_fired, 15)
        archived = json.loads(self.archive_path.read_text())["lessons"]
        reasons = sorted(e["archived"]["reason"] for e in archived)
        self.assertIn("decay", reasons[0])
        self.assertIn("merged into", reasons[1])

    def test_stats_survive_store_roundtrip(self) -> None:
        self.run_maintain(apply=True)
        rec = load_store(self.store_path)[0]
        self.assertIsNotNone(rec.stats)
        self.assertEqual(rec.stats.won_when_fired, 15)
