#!/usr/bin/env python3
"""Rank current Hearthstone meta decks by how easy they are to complete.

Given (1) your collection and (2) a set of current top Standard decks as
deckstrings, this computes the arcane dust needed to finish each deck and ranks
them cheapest-first, so you can see which competitive deck is easiest to build.

The script is dependency-free. It reuses the deckstring decoder from the sibling
`hearthstone-deck-builder` skill when available, and otherwise falls back to a
built-in decoder so it still works if copied on its own.
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

HJSON_LATEST_COLLECTIBLE = "https://api.hearthstonejson.com/v1/latest/enUS/cards.collectible.json"
USER_AGENT = "hearthstone-deck-recommender-skill/1.0 (+https://hearthstonejson.com)"

# Arcane dust to CRAFT a standard (non-golden) copy, by rarity.
CRAFT_COST = {
    "FREE": 0,
    "COMMON": 40,
    "RARE": 100,
    "EPIC": 400,
    "LEGENDARY": 1600,
}
# Core-set cards can't be crafted; they are granted for free by leveling.
UNCRAFTABLE_SETS = {"CORE"}


# --------------------------------------------------------------------------- #
# Deckstring decoding (imported from sibling skill, with a local fallback).
# --------------------------------------------------------------------------- #
def _load_sibling_decoder():
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent.parent / "hearthstone-deck-builder" / "scripts",
    ]
    for cand in candidates:
        script = cand / "build_deck_code.py"
        if script.exists():
            sys.path.insert(0, str(cand))
            try:
                from build_deck_code import decode_deckstring  # type: ignore

                return decode_deckstring
            except Exception:
                pass
    return None


def _fallback_read_varint(data: bytes, offset: int) -> tuple[int, int]:
    shift = 0
    value = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return value, offset
        shift += 7


def _fallback_decode(code: str) -> dict[str, Any]:
    data = base64.b64decode("".join(code.strip().split()))
    off = 0
    _, off = _fallback_read_varint(data, off)   # reserved
    _, off = _fallback_read_varint(data, off)   # version
    fmt, off = _fallback_read_varint(data, off)
    hero_count, off = _fallback_read_varint(data, off)
    heroes = []
    for _ in range(hero_count):
        h, off = _fallback_read_varint(data, off)
        heroes.append(h)
    cards: list[tuple[int, int]] = []
    for fixed in (1, 2):
        n, off = _fallback_read_varint(data, off)
        for _ in range(n):
            dbf, off = _fallback_read_varint(data, off)
            cards.append((dbf, fixed))
    n, off = _fallback_read_varint(data, off)
    for _ in range(n):
        dbf, off = _fallback_read_varint(data, off)
        cnt, off = _fallback_read_varint(data, off)
        cards.append((dbf, cnt))
    return {"format_id": fmt, "heroes": heroes, "cards": sorted(cards)}


_DECODE = _load_sibling_decoder() or _fallback_decode


def decode_deckstring(code: str) -> dict[str, Any]:
    return _DECODE(code)


# --------------------------------------------------------------------------- #
# Card data
# --------------------------------------------------------------------------- #
def fetch_text(url: str, *, cookie: str | None = None) -> str:
    """Fetch text with a browser-like User-Agent.

    Some HSReplay collection URLs are private to the signed-in browser session.
    If a direct URL returns login HTML or 403, export/copy the JSON manually or
    pass a Cookie header copied from the browser with --collection-cookie.
    """
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json,text/plain,*/*"}
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def load_json_from_url(url: str, *, cookie: str | None = None) -> Any:
    text = fetch_text(url, cookie=cookie)
    stripped = text.lstrip()
    if not stripped.startswith(("{", "[")):
        preview = stripped[:120].replace("\n", " ")
        raise ValueError(
            "URL did not return JSON. If this is a private HSReplay page/API, "
            "copy the JSON response manually or pass --collection-cookie. "
            f"Response started with: {preview!r}"
        )
    return json.loads(text)


def load_cards(path: str | None, *, allow_fetch: bool) -> list[dict[str, Any]]:
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    if not allow_fetch:
        return []
    return load_json_from_url(HJSON_LATEST_COLLECTIBLE)


def index_cards(cards: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    by_dbf: dict[int, dict[str, Any]] = {}
    for card in cards:
        dbf = card.get("dbfId")
        if isinstance(dbf, int):
            by_dbf[dbf] = card
    return by_dbf


# --------------------------------------------------------------------------- #
# Collection normalization
# --------------------------------------------------------------------------- #
def _owned_from_value(value: Any) -> int:
    """A collection entry can be an int, or a list like [normal, golden, ...].

    Any premium copy (golden/diamond/signature) still satisfies the deck slot,
    so owned = sum of all copies across finishes.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, list):
        return sum(int(x) for x in value if isinstance(x, (int, float)))
    if isinstance(value, dict):
        keys = ("count", "owned", "ownedTotal", "total", "normal")
        total = 0
        for k in ("normal", "golden", "diamond", "signature"):
            if isinstance(value.get(k), (int, float)):
                total += int(value[k])
        if total:
            return total
        for k in keys:
            if isinstance(value.get(k), (int, float)):
                return int(value[k])
    return 0


def normalize_collection(raw: Any) -> dict[int, int]:
    """Return {dbfId: owned_count} from many collection export shapes."""
    owned: dict[int, int] = defaultdict(int)

    # HSReplay "collection/mine" JSON: {"collection": {"<dbf>": [n,g,d,s]}}
    if isinstance(raw, dict) and isinstance(raw.get("collection"), dict):
        raw = raw["collection"]

    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                dbf = int(key)
            except (TypeError, ValueError):
                # Skip non-card keys (e.g. metadata).
                continue
            owned[dbf] += _owned_from_value(value)
        return dict(owned)

    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            dbf = item.get("dbfId") or item.get("dbf_id") or item.get("dbf")
            if dbf is None:
                continue
            owned[int(dbf)] += _owned_from_value(item if "dbfId" not in item else item.get("count", item))
        return dict(owned)

    raise ValueError("Unrecognized collection format")


def normalize_collection_text(text: str) -> dict[int, int]:
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return normalize_collection(json.loads(text))
    # CSV fallback: needs a dbfId column and a count/owned column.
    owned: dict[int, int] = defaultdict(int)
    reader = csv.DictReader(text.splitlines())
    fields = {f.lower(): f for f in (reader.fieldnames or [])}
    dbf_key = next((fields[k] for k in ("dbfid", "dbf_id", "dbf") if k in fields), None)
    if not dbf_key:
        raise ValueError("CSV collection needs a dbfId column")
    count_key = next(
        (fields[k] for k in ("ownedtotal", "owned", "count", "total", "normal") if k in fields),
        None,
    )
    for row in reader:
        try:
            dbf = int(row[dbf_key])
        except (TypeError, ValueError):
            continue
        owned[dbf] += int(float(row.get(count_key, 1) or 0)) if count_key else 1
    return dict(owned)


def load_collection(path: str) -> dict[int, int]:
    return normalize_collection_text(Path(path).read_text(encoding="utf-8"))


def load_collection_url(url: str, *, cookie: str | None = None) -> dict[int, int]:
    return normalize_collection(load_json_from_url(url, cookie=cookie))


def load_collection_source(path: str | None, url: str | None, *, cookie: str | None = None) -> dict[int, int]:
    if bool(path) == bool(url):
        raise ValueError("Provide exactly one of --collection or --collection-url")
    if url:
        return load_collection_url(url, cookie=cookie)
    assert path is not None
    return load_collection(path)


# --------------------------------------------------------------------------- #
# Meta deck loading
# --------------------------------------------------------------------------- #
def load_decks(path: str) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(text)
        decks = data.get("decks", data) if isinstance(data, dict) else data
        return list(decks)
    # Plain text: lines of deckstrings, optional "# Name" comment before each.
    decks: list[dict[str, Any]] = []
    pending_name: str | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            pending_name = line.lstrip("#").strip() or pending_name
            continue
        decks.append({"name": pending_name or f"Deck {len(decks) + 1}", "deckstring": line})
        pending_name = None
    return decks


# --------------------------------------------------------------------------- #
# Core ranking
# --------------------------------------------------------------------------- #
def rarity_cost(card: dict[str, Any]) -> int:
    if str(card.get("set", "")).upper() in UNCRAFTABLE_SETS:
        return 0
    return CRAFT_COST.get(str(card.get("rarity", "")).upper(), 0)


def evaluate_deck(
    deck: dict[str, Any],
    owned: dict[int, int],
    by_dbf: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    code = deck.get("deckstring") or deck.get("code")
    if not code:
        raise ValueError(f"Deck {deck.get('name')!r} has no deckstring")
    decoded = decode_deckstring(code)

    total_cards = 0
    owned_cards = 0
    dust = 0
    free_missing = 0
    missing: list[dict[str, Any]] = []
    missing_by_rarity: dict[str, int] = defaultdict(int)

    for dbf, count in decoded["cards"]:
        total_cards += count
        have = min(owned.get(dbf, 0), count)
        owned_cards += have
        need = count - have
        if need <= 0:
            continue
        card = by_dbf.get(dbf, {})
        name = card.get("name", f"dbfId {dbf}")
        rarity = str(card.get("rarity", "UNKNOWN")).upper()
        cost = rarity_cost(card)
        if cost == 0:
            free_missing += need
        line_dust = cost * need
        dust += line_dust
        missing_by_rarity[rarity] += need
        missing.append(
            {
                "dbfId": dbf,
                "name": name,
                "rarity": rarity,
                "need": need,
                "cost_each": cost,
                "dust": line_dust,
                "cost": card.get("cost"),
            }
        )

    missing.sort(key=lambda m: (-m["dust"], m["name"]))
    result = dict(deck)
    result.update(
        {
            "decoded_cards": decoded["cards"],
            "decoded_format": decoded.get("format") or decoded.get("format_id"),
            "total_cards": total_cards,
            "owned_cards": owned_cards,
            "percent_owned": round(100 * owned_cards / total_cards, 1) if total_cards else 0.0,
            "dust_needed": dust,
            "free_cards_missing": free_missing,
            "missing_by_rarity": dict(missing_by_rarity),
            "missing_legendaries": missing_by_rarity.get("LEGENDARY", 0),
            "missing_epics": missing_by_rarity.get("EPIC", 0),
            "missing": missing,
        }
    )
    return result


def _winrate(deck: dict[str, Any]) -> float:
    for key in ("winrate", "win_rate", "wr"):
        v = deck.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    return -1.0


def rank(results: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    if sort == "value":
        # Cheapest, then highest winrate. Fully-owned decks float up.
        return sorted(results, key=lambda d: (d["dust_needed"], -_winrate(d)))
    if sort == "completion":
        return sorted(results, key=lambda d: (-d["percent_owned"], d["dust_needed"]))
    return sorted(results, key=lambda d: (d["dust_needed"], -_winrate(d)))


def format_report(results: list[dict[str, Any]], *, top_missing: int) -> str:
    lines: list[str] = []
    lines.append(f"{'#':>2}  {'Dust':>7}  {'Own%':>5}  {'Leg':>3} {'Epic':>4}  Deck")
    lines.append("-" * 72)
    for i, deck in enumerate(results, 1):
        wr = _winrate(deck)
        wr_str = f"  ({wr:.1f}% WR)" if wr >= 0 else ""
        cls = deck.get("class") or deck.get("hero_class") or ""
        cls_str = f" [{cls}]" if cls else ""
        lines.append(
            f"{i:>2}  {deck['dust_needed']:>7}  {deck['percent_owned']:>4.0f}%  "
            f"{deck['missing_legendaries']:>3} {deck['missing_epics']:>4}  "
            f"{deck.get('name', 'Deck')}{cls_str}{wr_str}"
        )
    lines.append("")
    lines.append("Legend: Dust = arcane dust to complete, Own% = cards you already have,")
    lines.append("        Leg/Epic = missing legendaries/epics.")

    if results:
        best = results[0]
        lines.append("")
        lines.append(f"Easiest to build: {best.get('name', 'Deck')} "
                     f"({best['dust_needed']} dust, {best['percent_owned']:.0f}% owned).")
        if best.get("free_cards_missing"):
            lines.append(f"  Note: {best['free_cards_missing']} missing card(s) are Core/free "
                         f"(earned by leveling, not crafting).")
        shown = best["missing"][:top_missing]
        if shown:
            lines.append("  Missing cards:")
            for m in shown:
                cost = f"{m['dust']} dust" if m["dust"] else "free (Core)"
                lines.append(f"    - {m['need']}x {m['name']} ({m['rarity'].title()}, {cost})")
            if len(best["missing"]) > top_missing:
                lines.append(f"    ... and {len(best['missing']) - top_missing} more")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rank current Hearthstone meta decks by dust needed to complete.",
    )
    parser.add_argument("--collection", help="Path to your collection (HSReplay/HDT/Firestone export, or {dbfId: count})")
    parser.add_argument("--collection-url", help="URL returning collection JSON, such as the HSReplay account_lo JSON response")
    parser.add_argument("--collection-cookie", help="Optional Cookie header for private collection URLs (avoid saving this in shell history)")
    parser.add_argument("--decks", required=True, help="Meta decks: JSON list of {name,class,deckstring,winrate?} or a text file of deck codes")
    parser.add_argument("--cards-json", help="Local HearthstoneJSON cards.collectible.json (avoids network)")
    parser.add_argument("--no-fetch", action="store_true", help="Do not fetch HearthstoneJSON")
    parser.add_argument("--sort", choices=["value", "dust", "completion"], default="value",
                        help="value/dust: cheapest first; completion: most-owned first")
    parser.add_argument("--budget", type=int, help="Only show decks completable within this much dust")
    parser.add_argument("--max-results", type=int, default=15)
    parser.add_argument("--top-missing", type=int, default=8, help="How many missing cards to list for the top deck")
    parser.add_argument("--json", action="store_true", help="Emit full JSON instead of the text report")
    args = parser.parse_args(argv)

    try:
        owned = load_collection_source(args.collection, args.collection_url, cookie=args.collection_cookie)
        decks = load_decks(args.decks)
        if not decks:
            raise ValueError("No decks found in --decks input")
        by_dbf = index_cards(load_cards(args.cards_json, allow_fetch=not args.no_fetch))
        if not by_dbf:
            print("WARNING: no card data; dust costs/names unavailable. Provide --cards-json or allow fetch.", file=sys.stderr)

        results = [evaluate_deck(d, owned, by_dbf) for d in decks]
        if args.budget is not None:
            results = [d for d in results if d["dust_needed"] <= args.budget]
        results = rank(results, args.sort)[: args.max_results]

        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(format_report(results, top_missing=args.top_missing))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
