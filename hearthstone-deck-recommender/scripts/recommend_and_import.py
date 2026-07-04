#!/usr/bin/env python3
"""One-shot Hearthstone recommendation -> import block.

This is the tandem workflow between the recommender and deck-builder skills:

1. Load the user's collection from a file or collection JSON URL.
2. Rank current meta deckstrings by dust needed to complete.
3. Pick the top recommendation.
4. Print the ranked summary plus a Hearthstone clipboard/import block.

It intentionally still requires a meta-deck input file. Top-deck sites change HTML
frequently; the surrounding AI skill should browse current sites and save
`meta_decks.json`, then this deterministic wrapper does the math and output.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Import rank_decks.py from the same directory regardless of cwd.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from rank_decks import (  # type: ignore  # noqa: E402
    evaluate_deck,
    format_report,
    index_cards,
    load_cards,
    load_collection_source,
    load_decks,
    rank,
)


def _deckstring(deck: dict[str, Any]) -> str:
    code = deck.get("deckstring") or deck.get("code")
    if not code:
        raise ValueError(f"Recommended deck {deck.get('name')!r} has no deckstring")
    return str(code).strip()


def format_import_block(deck: dict[str, Any], *, top_missing: int) -> str:
    name = deck.get("name", "Recommended Hearthstone Deck")
    deck_class = deck.get("class") or deck.get("hero_class")
    fmt = deck.get("format") or deck.get("decoded_format") or "Standard"
    code = _deckstring(deck)

    lines = [f"### {name}"]
    if deck_class:
        lines.append(f"# Class: {deck_class}")
    if fmt:
        lines.append(f"# Format: {str(fmt).title()}")
    if "dust_needed" in deck:
        lines.append(f"# Dust needed from your collection: {deck['dust_needed']}")
    if "percent_owned" in deck:
        lines.append(f"# Collection completion: {deck['percent_owned']}%")
    lines.append("#")

    missing = list(deck.get("missing", []))[:top_missing]
    if missing:
        lines.append("# Missing to craft / unlock:")
        for m in missing:
            dust = f"{m['dust']} dust" if m.get("dust") else "free/Core"
            lines.append(f"# - {m.get('need', 1)}x {m.get('name', 'Unknown')} ({m.get('rarity', 'UNKNOWN')}, {dust})")
        lines.append("#")

    lines.append(code)
    lines.append("#")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rank Hearthstone meta decks for your collection and print the best deck's import block.",
    )
    parser.add_argument("--collection", help="Path to collection JSON/CSV")
    parser.add_argument("--collection-url", help="URL returning collection JSON, such as HSReplay's account_lo JSON response")
    parser.add_argument("--collection-cookie", help="Optional Cookie header for private collection URLs")
    parser.add_argument("--decks", required=True, help="Meta decks JSON/text containing deckstrings")
    parser.add_argument("--cards-json", help="Local HearthstoneJSON cards.collectible.json")
    parser.add_argument("--no-fetch", action="store_true", help="Do not fetch HearthstoneJSON card data")
    parser.add_argument("--sort", choices=["value", "dust", "completion"], default="value")
    parser.add_argument("--budget", type=int, help="Only recommend decks completable within this much dust")
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument("--top-missing", type=int, default=10)
    parser.add_argument("--pick", type=int, default=1, help="1-based ranked deck to output as the import block")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON with ranked decks and chosen import block")
    args = parser.parse_args(argv)

    try:
        owned = load_collection_source(args.collection, args.collection_url, cookie=args.collection_cookie)
        decks = load_decks(args.decks)
        if not decks:
            raise ValueError("No decks found in --decks input")
        by_dbf = index_cards(load_cards(args.cards_json, allow_fetch=not args.no_fetch))
        if not by_dbf:
            print("WARNING: no card data; dust costs/names unavailable. Provide --cards-json or allow fetch.", file=sys.stderr)

        ranked = [evaluate_deck(d, owned, by_dbf) for d in decks]
        if args.budget is not None:
            ranked = [d for d in ranked if d["dust_needed"] <= args.budget]
        ranked = rank(ranked, args.sort)
        if not ranked:
            raise ValueError("No decks matched the budget/filter")
        if args.pick < 1 or args.pick > len(ranked):
            raise ValueError(f"--pick must be between 1 and {len(ranked)}")

        shown = ranked[: args.max_results]
        chosen = ranked[args.pick - 1]
        import_block = format_import_block(chosen, top_missing=args.top_missing)

        if args.json:
            print(json.dumps({"chosen": chosen, "import_block": import_block, "ranked": shown}, indent=2))
        else:
            print(format_report(shown, top_missing=args.top_missing))
            print("\n" + "=" * 72)
            print("COPY THIS INTO HEARTHSTONE")
            print("=" * 72)
            print(import_block)
            print("\nHow to use: copy the deck code/import block, open Hearthstone, create a new deck, and accept the detected clipboard deck.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
