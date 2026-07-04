"""Live capture: tail the newest session's Power.log into the database."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from hslog import LogParser

from .capture import (
    _COMPLETE_RE,
    _META_RE,
    HeroClassResolver,
    GameRecord,
    _player_names,
    export_game,
    session_start,
)
from .config import session_dirs
from .decks import DeckEvent, DeckLogParser, attach_decks


class FileTail:
    """Incrementally parse one Power log file as it grows."""

    def __init__(self, path: Path, resolver: HeroClassResolver) -> None:
        self.path = path
        self.resolver = resolver
        self.base_dt: datetime | None = session_start(path.parent)
        self._reset()

    def _reset(self) -> None:
        self.offset = 0
        self.partial = ""
        self.parser = LogParser()
        self.metas: list[dict[str, Any]] = []
        self._meta_current: dict[str, Any] = {}
        self.exported = 0
        self.completions = 0
        self.last_dt: datetime | None = self.base_dt

    def _feed(self, line: str) -> None:
        m = _META_RE.search(line)
        if m:
            key, value = m.groups()
            if key == "BuildNumber" and self._meta_current:
                self.metas.append(self._meta_current)
                self._meta_current = {}
            self._meta_current[key] = int(value) if value.isdigit() else value
        if _COMPLETE_RE.search(line):
            self.completions += 1
        try:
            self.parser.read_line(line)
        except Exception:
            pass  # skip unparseable lines rather than dying mid-session

    def poll(self) -> list[GameRecord]:
        """Read any new bytes; return games that completed since the last poll."""
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return []
        if size < self.offset:
            self._reset()  # file was rotated/truncated
        if size == self.offset:
            return self._collect()

        with open(self.path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(self.offset)
            chunk = f.read()
            self.offset = f.tell()

        text = self.partial + chunk
        lines = text.split("\n")
        self.partial = lines.pop()  # tail may be a half-written line
        for line in lines:
            if line:
                self._feed(line + "\n")
        return self._collect()

    def _collect(self) -> list[GameRecord]:
        records: list[GameRecord] = []
        games = self.parser.games
        metas = self.metas + ([self._meta_current] if self._meta_current else [])
        names = _player_names(self.parser)
        base = (self.base_dt or datetime.now()).date()
        while self.exported < len(games):
            if self.exported >= self.completions:
                break  # newest game hasn't reached STATE=COMPLETE yet
            tree = games[self.exported]
            if tree.end_time is None:
                break
            meta = metas[self.exported] if self.exported < len(metas) else {}
            record = export_game(
                tree, meta, self.resolver, names=names,
                source_file=str(self.path), base=base, last_dt=self.last_dt,
            )
            self.exported += 1
            if record:
                self.last_dt = datetime.fromisoformat(record.end_time or record.start_time)
                records.append(record)
        return records


class DeckLogTail:
    """Incrementally parse Decks.log as it grows."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._reset()

    def _reset(self) -> None:
        self.offset = 0
        self.partial = ""
        self.parser = DeckLogParser(session_start(self.path.parent))

    @property
    def events(self) -> list[DeckEvent]:
        return self.parser.events

    def poll(self) -> None:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return
        if size < self.offset:
            self._reset()
        if size == self.offset:
            return
        with open(self.path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(self.offset)
            chunk = f.read()
            self.offset = f.tell()
        lines = (self.partial + chunk).split("\n")
        self.partial = lines.pop()
        for line in lines:
            if line:
                self.parser.feed(line)


def watch_loop(log_root: Path, on_games, *, interval: float = 2.0, resolver=None):
    """Poll the newest session folder forever, calling on_games(records) as games finish."""
    resolver = resolver or HeroClassResolver()
    tails: dict[Path, FileTail] = {}
    deck_tails: dict[Path, DeckLogTail] = {}
    current_dir: Path | None = None

    while True:
        dirs = session_dirs(log_root)
        newest = dirs[-1] if dirs else None
        if newest and newest != current_dir:
            current_dir = newest
            tails = {}
            deck_tails = {}
            print(f"watching {newest}", flush=True)
        if current_dir:
            for name in ("Decks_old.log", "Decks.log"):
                path = current_dir / name
                if path.exists() and path not in deck_tails:
                    deck_tails[path] = DeckLogTail(path)
            for deck_tail in deck_tails.values():
                deck_tail.poll()
            deck_events = [ev for t in deck_tails.values() for ev in t.events]

            for name in ("Power_old.log", "Power.log"):
                path = current_dir / name
                if path.exists() and path not in tails:
                    tails[path] = FileTail(path, resolver)
            for tail in tails.values():
                records = tail.poll()
                if records:
                    attach_decks(records, deck_events)
                    on_games(records)
        time.sleep(interval)
