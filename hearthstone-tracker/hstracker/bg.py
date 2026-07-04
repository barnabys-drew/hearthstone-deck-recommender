"""Extract Battlegrounds-specific info (placement, hero pick, tavern tier).

Same packet-walking approach as cardevents.py: PLAYER_LEADERBOARD_PLACE and
PLAYER_TECH_LEVEL are TagChanges on hero entities keyed by CONTROLLER, and the
hero selection is a MULLIGAN-type Choices/ChosenEntities pair.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hearthstone.enums import ChoiceType, GameTag, PlayState
from hslog import packets as pk
from hslog.export import coerce_to_entity_id


@dataclass
class BgInfo:
    place: int | None = None
    hero_card_id: str | None = None
    offered_hero_card_ids: list[str] = field(default_factory=list)
    max_tech: int | None = None


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


def extract_bg_info(tree: Any, friendly_player_id: int | None) -> BgInfo:
    controller: dict[int, int] = {}
    card: dict[int, str] = {}
    place_by_controller: dict[int | None, int] = {}
    tech_by_controller: dict[int | None, int] = {}
    friendly_playstate: int | None = None
    offered_entities: list[int] = []
    picked_entities: list[int] = []
    mulligan_choice_ids: set[int] = set()

    def apply_tag(entity_id: int, tag: Any, value: Any, *, live: bool) -> None:
        nonlocal friendly_playstate
        if tag == GameTag.CONTROLLER:
            controller[entity_id] = int(value)
        elif tag == GameTag.PLAYER_LEADERBOARD_PLACE:
            place_by_controller[controller.get(entity_id)] = int(value)
        elif tag == GameTag.PLAYER_TECH_LEVEL and live:
            # Only live TagChanges: FullEntity snapshots of ghost boards carry
            # OTHER players' tech levels on entities we'd misattribute.
            c = controller.get(entity_id)
            tech_by_controller[c] = max(tech_by_controller.get(c, 0), int(value))
        elif tag == GameTag.PLAYSTATE and controller.get(entity_id) == friendly_player_id:
            friendly_playstate = int(value)

    for packet in tree.recursive_iter():
        if isinstance(packet, (pk.FullEntity, pk.ShowEntity, pk.ChangeEntity)):
            entity_id = _eid(packet.entity)
            if entity_id is None:
                continue
            if getattr(packet, "card_id", None):
                card[entity_id] = packet.card_id
            for tag, value in _tag_pairs(getattr(packet, "tags", None)):
                apply_tag(entity_id, tag, value, live=False)
        elif isinstance(packet, pk.TagChange):
            entity_id = _eid(packet.entity)
            if entity_id is not None:
                apply_tag(entity_id, packet.tag, packet.value, live=True)
        elif isinstance(packet, pk.Choices):
            if packet.type == ChoiceType.MULLIGAN:
                mulligan_choice_ids.add(packet.id)
                offered_entities = [e for e in (_eid(c) for c in packet.choices) if e is not None]
        elif isinstance(packet, pk.ChosenEntities):
            if packet.id in mulligan_choice_ids:
                picked_entities.extend(e for e in (_eid(c) for c in packet.choices) if e is not None)

    info = BgInfo()
    info.place = place_by_controller.get(friendly_player_id)
    if info.place is None and friendly_playstate == int(PlayState.WON):
        info.place = 1
    info.max_tech = tech_by_controller.get(friendly_player_id) or None
    info.offered_hero_card_ids = [card[e] for e in offered_entities if e in card]
    picked_ids = [card[e] for e in picked_entities if e in card]
    # The hero pick is the chosen entity from the offer; duos or odd logs may
    # record several ChosenEntities, so prefer one that was actually offered.
    offered_set = set(info.offered_hero_card_ids)
    info.hero_card_id = next(
        (c for c in picked_ids if c in offered_set), picked_ids[0] if picked_ids else None
    )
    return info


def hero_choice_rows(info: BgInfo) -> list[dict[str, Any]]:
    """game_cards-shaped rows recording the hero offer and pick."""
    return [
        {
            "card_id": hero,
            "friendly": 1,
            "drawn": 0,
            "played": 0,
            "mull_offered": 1,
            "mull_kept": int(hero == info.hero_card_id),
            "first_played_turn": None,
        }
        for hero in dict.fromkeys(info.offered_hero_card_ids)
    ]
