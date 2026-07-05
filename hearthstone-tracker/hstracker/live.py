"""Live game-state snapshots from an in-progress Power.log.

Feeds real-time play advice: `hst live` tails the current game and emits a
snapshot every turn. Only information the client is allowed to see is in the
log — the opponent's hand shows up as hidden-card counts.

Two hard-won constraints shape the design (see git history / plan):
- A single LogParser fed a multi-game Power.log can raise
  InconsistentPlayerIdError when player ids shuffle between games, so each
  poll re-parses ONLY the current game's lines with a fresh parser.
- Player entities have no `card_id`; use getattr when walking entities.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from hearthstone.enums import CardType, GameTag, PlayState, Zone
from hslog import LogParser
from hslog.export import EntityTreeExporter, FriendlyPlayerExporter

from .capture import _player_names
from .cards import HeroClassResolver

_CREATE_GAME_MARKER = "GameState.DebugPrintPower() - CREATE_GAME"

_FLAG_TAGS = (
    (GameTag.TAUNT, "taunt"),
    (GameTag.DIVINE_SHIELD, "divine shield"),
    (GameTag.STEALTH, "stealth"),
    (GameTag.FROZEN, "frozen"),
    (GameTag.WINDFURY, "windfury"),
    (GameTag.EXHAUSTED, "exhausted"),
)


def _entity_flags(entity: Any) -> list[str]:
    return [label for tag, label in _FLAG_TAGS if entity.tags.get(tag)]


def snapshot_from_tree(
    tree: Any,
    resolver: HeroClassResolver,
    names: dict[int, str] | None = None,
) -> dict[str, Any] | None:
    """Current-game snapshot dict, or None if the game can't be exported yet."""
    names = names or {}
    try:
        friendly_id = FriendlyPlayerExporter(tree).export()
    except Exception:
        friendly_id = None
    try:
        game = EntityTreeExporter(tree).export().game
    except Exception:
        return None
    if not game.players:
        return None

    raw_turn = game.tags.get(GameTag.TURN, 0)
    snapshot: dict[str, Any] = {
        "turn": (raw_turn + 1) // 2,
        "raw_turn": raw_turn,
        "whose_turn": None,
        "game_over": None,
    }

    for player in game.players:
        side = "me" if player.player_id == friendly_id else "opp"
        pid = player.player_id
        if player.tags.get(GameTag.CURRENT_PLAYER):
            snapshot["whose_turn"] = side
        playstate = player.tags.get(GameTag.PLAYSTATE, 0)
        if side == "me" and playstate in (int(PlayState.WON), int(PlayState.LOST), int(PlayState.TIED)):
            snapshot["game_over"] = PlayState(playstate).name

        hero_hp = hero_armor = None
        hero_class = weapon = None
        hand: list[dict[str, Any]] = []
        board: list[dict[str, Any]] = []
        deck_remaining = hidden_in_hand = secrets = 0

        for entity in game.entities:
            if entity.tags.get(GameTag.CONTROLLER) != pid:
                continue
            card_id = getattr(entity, "card_id", None)
            card = resolver.card(card_id)
            card_type = entity.tags.get(GameTag.CARDTYPE)
            zone = entity.zone

            if card_type == CardType.HERO and zone == Zone.PLAY and entity.tags.get(GameTag.HEALTH):
                hero_hp = entity.tags.get(GameTag.HEALTH, 30) - entity.tags.get(GameTag.DAMAGE, 0)
                hero_armor = entity.tags.get(GameTag.ARMOR, 0)
                hero_class = resolver.player_class(card_id)
            elif card_type == CardType.WEAPON and zone == Zone.PLAY:
                weapon = {
                    "name": card.get("name", card_id),
                    "atk": entity.tags.get(GameTag.ATK, 0),
                    "durability": (entity.tags.get(GameTag.DURABILITY, 0)
                                   - entity.tags.get(GameTag.DAMAGE, 0)),
                }
            elif zone == Zone.HAND:
                if card_id:
                    hand.append({
                        "name": card.get("name", card_id),
                        "cost": entity.tags.get(GameTag.COST, card.get("cost")),
                        "pos": entity.tags.get(GameTag.ZONE_POSITION, 0),
                    })
                else:
                    hidden_in_hand += 1
            elif zone == Zone.PLAY and card_type in (CardType.MINION, CardType.LOCATION):
                board.append({
                    "name": card.get("name", card_id or "?"),
                    "atk": entity.tags.get(GameTag.ATK, 0),
                    "health": (entity.tags.get(GameTag.HEALTH, 0)
                               - entity.tags.get(GameTag.DAMAGE, 0)),
                    "pos": entity.tags.get(GameTag.ZONE_POSITION, 0),
                    "flags": _entity_flags(entity),
                    "location": card_type == CardType.LOCATION,
                })
            elif zone == Zone.DECK:
                deck_remaining += 1
            elif zone == Zone.SECRET and entity.tags.get(GameTag.SECRET):
                secrets += 1

        hand.sort(key=lambda c: c["pos"])
        board.sort(key=lambda c: c["pos"])
        resources = player.tags.get(GameTag.RESOURCES, 0) + player.tags.get(GameTag.TEMP_RESOURCES, 0)
        snapshot[side] = {
            "name": names.get(pid) or player.name,
            "class": hero_class,
            "hp": hero_hp,
            "armor": hero_armor,
            "mana": resources - player.tags.get(GameTag.RESOURCES_USED, 0),
            "mana_max": resources,
            "weapon": weapon,
            "hand": hand,
            "hand_hidden": hidden_in_hand,
            "board": board,
            "deck_remaining": deck_remaining,
            "secrets": secrets,
        }

    if "me" not in snapshot or "opp" not in snapshot:
        return None
    return snapshot


class LiveGameTail:
    """Tail one Power.log, keeping only the current game's lines buffered."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0
        self.partial = ""
        self.lines: list[str] = []
        self.names: dict[int, str] = {}

    def poll(self) -> bool:
        """Read new bytes; True if the current-game buffer changed."""
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return False
        if size < self.offset:
            self.offset = 0
            self.partial = ""
            self.lines = []
        if size == self.offset:
            return False
        with open(self.path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(self.offset)
            chunk = f.read()
            self.offset = f.tell()
        text = self.partial + chunk
        new_lines = text.split("\n")
        self.partial = new_lines.pop()
        changed = False
        for line in new_lines:
            if not line:
                continue
            if _CREATE_GAME_MARKER in line:
                self.lines = []  # a new game starts; drop the previous one
            self.lines.append(line + "\n")
            changed = True
        return changed

    def snapshot(self, resolver: HeroClassResolver) -> dict[str, Any] | None:
        if not self.lines:
            return None
        parser = LogParser()
        for line in self.lines:
            try:
                parser.read_line(line)
            except Exception:
                continue
        if not parser.games:
            return None
        return snapshot_from_tree(parser.games[-1], resolver, names=_player_names(parser))


def write_snapshot_json(snapshot: dict[str, Any], path: Path) -> None:
    """Atomic write so readers never see a torn file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _card_line(cards: list[dict[str, Any]]) -> str:
    parts = []
    for c in cards:
        flags = "".join(f" [{f}]" for f in c.get("flags", []) if f != "exhausted")
        if "cost" in c:
            parts.append(f"{c['name']}({c['cost']})")
        else:
            loc = " (location)" if c.get("location") else ""
            parts.append(f"{c['name']} {c['atk']}/{c['health']}{flags}{loc}")
    return ", ".join(parts) or "(empty)"


def format_snapshot(snap: dict[str, Any]) -> str:
    me, opp = snap["me"], snap["opp"]
    whose = "your turn" if snap.get("whose_turn") == "me" else "opponent's turn"
    armor = f"(+{me['armor']})" if me.get("armor") else ""
    opp_armor = f"(+{opp['armor']})" if opp.get("armor") else ""
    lines = [
        f"== TURN {snap['turn']} ({whose}) — ME {me['hp']}hp{armor} "
        f"{me['mana']}/{me['mana_max']} mana vs OPP {opp['hp']}hp{opp_armor}"
    ]
    weapon = f" | weapon: {me['weapon']['name']} {me['weapon']['atk']}/{me['weapon']['durability']}" if me.get("weapon") else ""
    lines.append(f"   my hand ({len(me['hand'])}): {_card_line(me['hand'])}")
    lines.append(f"   my board: {_card_line(me['board'])}{weapon}")
    opp_weapon = f" | weapon: {opp['weapon']['name']} {opp['weapon']['atk']}/{opp['weapon']['durability']}" if opp.get("weapon") else ""
    opp_extra = f" | opp hand: {opp['hand_hidden'] + len(opp['hand'])} cards"
    if opp["secrets"]:
        opp_extra += f", secrets: {opp['secrets']}"
    lines.append(f"   opp board: {_card_line(opp['board'])}{opp_weapon}{opp_extra}")
    if snap.get("game_over"):
        lines.append(f"== GAME OVER: {snap['game_over']}")
    return "\n".join(lines)
