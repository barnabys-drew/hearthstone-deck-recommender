"""Parse Hearthstone Power.log files into per-game records."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable

from hearthstone.enums import GameTag, PlayState, State
from hslog import LogParser
from hslog.export import EntityTreeExporter, FriendlyPlayerExporter
from hslog.exceptions import MissingPlayerData

from .bg import extract_bg_info, hero_choice_rows
from .cardevents import extract_card_events
from .cards import HeroClassResolver

_SESSION_DIR_RE = re.compile(
    r"Hearthstone_(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})$"
)
_META_RE = re.compile(
    r"DebugPrintGame\(\) - (BuildNumber|GameType|FormatType|ScenarioID)=(\S+)"
)
# A game only counts once the GameEntity reaches STATE=COMPLETE; hslog's
# end_time is merely the last packet seen, so it is set even mid-game.
_COMPLETE_RE = re.compile(
    r"GameState\.DebugPrintPower\(\) - TAG_CHANGE Entity=GameEntity tag=STATE value=COMPLETE"
)


@dataclass
class GameRecord:
    start_time: str
    end_time: str | None
    duration_seconds: int | None
    game_type: str | None
    format_type: str | None
    scenario_id: int | None
    build_number: int | None
    friendly_name: str | None
    friendly_class: str | None
    friendly_hero: str | None
    opponent_name: str | None
    opponent_class: str | None
    opponent_hero: str | None
    friendly_first: int | None
    result: str | None
    turns: int | None
    bg_place: int | None
    source_file: str
    deck_name: str | None = None
    deckstring: str | None = None
    bg_tech: int | None = None
    # Per-card events for this game; stored in game_cards, not the games row.
    cards: list[dict[str, Any]] = field(default_factory=list)


def session_start(session_dir: Path) -> datetime | None:
    m = _SESSION_DIR_RE.search(session_dir.name)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(g) for g in m.groups())
    return datetime(y, mo, d, h, mi, s)


def _scan_meta_blocks(path: Path) -> list[dict[str, Any]]:
    """Ordered per-game metadata (GameType etc.); one dict per game in the file."""
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _META_RE.search(line)
            if not m:
                continue
            key, value = m.groups()
            if key == "BuildNumber" and current:
                blocks.append(current)
                current = {}
            current[key] = int(value) if value.isdigit() else value
    if current:
        blocks.append(current)
    return blocks


def _combine_date(t: time, base: date, last: datetime | None) -> datetime:
    """Attach a calendar date to a log time-of-day, rolling past midnight."""
    dt = datetime.combine(base, t)
    while last is not None and dt < last - timedelta(minutes=5):
        dt += timedelta(days=1)
    return dt


def _as_time(value: Any) -> time | None:
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    return None


def _playstate(tags: dict) -> PlayState:
    try:
        return PlayState(tags.get(GameTag.PLAYSTATE, 0))
    except ValueError:
        return PlayState.INVALID


_RESULTS = {
    PlayState.WON: "WON",
    PlayState.LOST: "LOST",
    PlayState.TIED: "TIED",
    PlayState.CONCEDED: "LOST",
}


def parse_power_log(
    path: Path,
    resolver: HeroClassResolver,
    *,
    base_datetime: datetime | None = None,
) -> list[GameRecord]:
    """Parse one Power.log (or Power_old.log) into completed-game records."""
    base_datetime = base_datetime or session_start(path.parent)
    base = base_datetime.date() if base_datetime else date.today()

    parser = LogParser()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        parser.read(f)
    parser.flush()

    metas = _scan_meta_blocks(path)
    names = _player_names(parser)
    records: list[GameRecord] = []
    last_dt: datetime | None = base_datetime

    for i, tree in enumerate(parser.games):
        meta = metas[i] if i < len(metas) else {}
        record = export_game(
            tree,
            meta,
            resolver,
            names=names,
            source_file=str(path),
            base=base,
            last_dt=last_dt,
        )
        if record is None:
            continue
        last_dt = datetime.fromisoformat(record.end_time or record.start_time)
        records.append(record)
    return records


def _player_names(parser: LogParser) -> dict[int, str]:
    """{player_id: battletag/name} from the parser's PlayerManager."""
    manager = parser.player_manager
    by_player_id = getattr(manager, "_players_by_player_id", {})
    # Values are PlayerReference objects (or plain strings in older hslog).
    return {
        pid: str(getattr(ref, "name", ref))
        for pid, ref in by_player_id.items()
        if getattr(ref, "name", ref)
    }


def export_game(
    tree: Any,
    meta: dict[str, Any],
    resolver: HeroClassResolver,
    *,
    names: dict[int, str],
    source_file: str,
    base: date,
    last_dt: datetime | None,
) -> GameRecord | None:
    """Turn one hslog packet tree into a GameRecord; None if incomplete/broken."""
    if tree.end_time is None:
        return None
    try:
        game = EntityTreeExporter(tree).export().game
    except Exception:
        return None
    if game.tags.get(GameTag.STATE) != State.COMPLETE:
        return None  # truncated log or game still in progress

    try:
        friendly_id = FriendlyPlayerExporter(tree).export()
    except MissingPlayerData:
        friendly_id = None
    except Exception:
        friendly_id = None

    players = list(game.players)
    if not players:
        return None
    friendly = next((p for p in players if p.player_id == friendly_id), None)
    if friendly is None:
        # Fall back to whichever player is not the Battlegrounds innkeeper.
        friendly = next(
            (p for p in players if not (p.starting_hero and "BaconShopBob" in p.starting_hero.card_id)),
            players[0],
        )
    opponent = next((p for p in players if p is not friendly), None)

    start_t = _as_time(tree.start_time)
    end_t = _as_time(tree.end_time)
    if start_t is None:
        return None
    start_dt = _combine_date(start_t, base, last_dt)
    end_dt = _combine_date(end_t, start_dt.date(), start_dt) if end_t else None

    def hero_id(player: Any) -> str | None:
        hero = getattr(player, "starting_hero", None)
        return hero.card_id if hero else None

    fr_hero, op_hero = hero_id(friendly), hero_id(opponent) if opponent else None
    result = _RESULTS.get(_playstate(friendly.tags))
    bg_place = friendly.tags.get(GameTag.PLAYER_LEADERBOARD_PLACE) or None
    bg_tech = None

    game_type = meta.get("GameType")
    format_type = meta.get("FormatType")

    # BG/Mercs "mulligans" are hero picks and plays aren't deck cards; the
    # card views are about constructed decks, so skip extraction there.
    is_bg = "BATTLEGROUNDS" in str(game_type or "")
    no_deck_mode = is_bg or "MERCENARIES" in str(game_type or "")
    try:
        card_events = [] if no_deck_mode else extract_card_events(tree, friendly.player_id)
    except Exception:
        card_events = []

    if is_bg:
        try:
            bg = extract_bg_info(tree, friendly.player_id)
        except Exception:
            bg = None
        if bg:
            bg_place = bg.place or bg_place
            bg_tech = bg.max_tech
            fr_hero = bg.hero_card_id or fr_hero
            card_events = hero_choice_rows(bg)

    return GameRecord(
        start_time=start_dt.isoformat(sep=" ", timespec="seconds"),
        end_time=end_dt.isoformat(sep=" ", timespec="seconds") if end_dt else None,
        duration_seconds=int((end_dt - start_dt).total_seconds()) if end_dt else None,
        game_type=str(game_type) if game_type else None,
        format_type=str(format_type) if format_type else None,
        scenario_id=meta.get("ScenarioID"),
        build_number=meta.get("BuildNumber"),
        friendly_name=names.get(friendly.player_id) or friendly.name,
        friendly_class=resolver.player_class(fr_hero),
        friendly_hero=fr_hero,
        opponent_name=(names.get(opponent.player_id) or opponent.name) if opponent else None,
        opponent_class=resolver.player_class(op_hero),
        opponent_hero=op_hero,
        friendly_first=int(bool(friendly.tags.get(GameTag.FIRST_PLAYER, 0))),
        result=result,
        turns=game.tags.get(GameTag.TURN),
        bg_place=bg_place,
        source_file=source_file,
        bg_tech=bg_tech,
        cards=card_events,
    )


def power_logs(session_dir: Path) -> Iterable[Path]:
    for name in ("Power_old.log", "Power.log"):
        p = session_dir / name
        if p.exists():
            yield p


def record_dict(record: GameRecord) -> dict[str, Any]:
    d = asdict(record)
    d.pop("cards", None)
    return d
