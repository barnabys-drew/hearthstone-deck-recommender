"""Extract per-card events (draws, plays, mulligan) from a game's packet tree.

Walks the hslog packets sequentially, tracking each entity's card id, zone,
and controller, so we can attribute events to cards even when the card is
revealed only later in the game. Opponent cards that are never revealed have
no card id and are skipped.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hearthstone.enums import BlockType, ChoiceType, GameTag, Step, Zone
from hslog import packets as pk
from hslog.export import coerce_to_entity_id


@dataclass
class CardStats:
    drawn: int = 0
    played: int = 0
    mull_offered: int = 0
    mull_kept: int = 0
    first_played_turn: int | None = None


@dataclass
class _EntityState:
    card_id: str | None = None
    zone: int | None = None
    controller: int | None = None
    drawn: int = 0
    played: int = 0
    mull_offered: bool = False
    mull_kept: bool = False
    first_played_turn: int | None = None


def _eid(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return coerce_to_entity_id(value)
    except Exception:
        return getattr(value, "entity_id", None)


def _tag_pairs(tags: Any):
    if isinstance(tags, dict):
        return tags.items()
    return tags or []


def extract_card_events(tree: Any, friendly_player_id: int | None) -> list[dict[str, Any]]:
    """Per-card event rows for one game: [{card_id, friendly, drawn, played, ...}]."""
    entities: dict[int, _EntityState] = {}
    game_entity_id: int | None = None
    in_mulligan = True
    turn = 1
    mulligan_choice_ids: dict[int, int] = {}  # choices-packet id -> player entity

    def ent(entity_id: int) -> _EntityState:
        return entities.setdefault(entity_id, _EntityState())

    def apply_tag(entity_id: int, tag: Any, value: Any) -> None:
        nonlocal in_mulligan, turn
        state = ent(entity_id)
        if entity_id == game_entity_id:
            if tag == GameTag.TURN and isinstance(value, int):
                turn = value
            if tag == GameTag.STEP and value in (Step.MAIN_READY, Step.MAIN_ACTION):
                in_mulligan = False
            return
        if tag == GameTag.CONTROLLER:
            state.controller = int(value)
        elif tag == GameTag.ZONE:
            new_zone = int(value)
            if (
                not in_mulligan
                and state.zone == int(Zone.DECK)
                and new_zone == int(Zone.HAND)
            ):
                state.drawn += 1
            state.zone = new_zone

    for packet in tree.recursive_iter():
        if isinstance(packet, pk.CreateGame):
            game_entity_id = _eid(packet.entity)
        elif isinstance(packet, (pk.FullEntity, pk.ShowEntity, pk.ChangeEntity)):
            entity_id = _eid(packet.entity)
            if entity_id is None:
                continue
            state = ent(entity_id)
            if getattr(packet, "card_id", None):
                state.card_id = packet.card_id
            for tag, value in _tag_pairs(getattr(packet, "tags", None)):
                apply_tag(entity_id, tag, value)
        elif isinstance(packet, pk.TagChange):
            entity_id = _eid(packet.entity)
            if entity_id is not None:
                apply_tag(entity_id, packet.tag, packet.value)
        elif isinstance(packet, pk.Block):
            if packet.type == BlockType.PLAY:
                entity_id = _eid(packet.entity)
                if entity_id is not None:
                    state = ent(entity_id)
                    state.played += 1
                    if state.first_played_turn is None:
                        # Raw TURN increments per player-turn; show game turns.
                        state.first_played_turn = (turn + 1) // 2
        elif isinstance(packet, pk.Choices):
            if packet.type == ChoiceType.MULLIGAN:
                mulligan_choice_ids[packet.id] = _eid(packet.player) or 0
                for choice in packet.choices:
                    choice_id = _eid(choice)
                    if choice_id is not None:
                        ent(choice_id).mull_offered = True
        elif isinstance(packet, pk.ChosenEntities):
            if packet.id in mulligan_choice_ids:
                for choice in packet.choices:
                    choice_id = _eid(choice)
                    if choice_id is not None:
                        ent(choice_id).mull_kept = True

    # Aggregate entity-level events up to (card_id, friendly) rows.
    by_card: dict[tuple[str, int], CardStats] = {}
    for state in entities.values():
        if not state.card_id or state.controller is None:
            continue
        if not (state.drawn or state.played or state.mull_offered):
            continue
        friendly = int(state.controller == friendly_player_id) if friendly_player_id else 0
        stats = by_card.setdefault((state.card_id, friendly), CardStats())
        stats.drawn += state.drawn
        stats.played += state.played
        stats.mull_offered += int(state.mull_offered)
        stats.mull_kept += int(state.mull_kept)
        if state.first_played_turn is not None:
            if stats.first_played_turn is None or state.first_played_turn < stats.first_played_turn:
                stats.first_played_turn = state.first_played_turn

    return [
        {
            "card_id": card_id,
            "friendly": friendly,
            "drawn": s.drawn,
            "played": s.played,
            "mull_offered": s.mull_offered,
            "mull_kept": s.mull_kept,
            "first_played_turn": s.first_played_turn,
        }
        for (card_id, friendly), s in sorted(by_card.items())
    ]
