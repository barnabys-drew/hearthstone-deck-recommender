#!/usr/bin/env python3
"""
Hearthstone Dust Optimizer

Analyzes your collection and lists extra card copies beyond the playable
maximum (1x Legendary, 2x everything else) with the dust you'd gain.

This is the same set the in-game "Mass Disenchant" button clears —
disenchanting can ONLY be done inside the Hearthstone client (there is no
web collection UI on battle.net, and automating the game client violates
Blizzard's EULA). Use this script to preview the number, then press the
button in game: Collection -> crafting mode -> Mass Disenchant.
"""

import json
import sys
import argparse
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import defaultdict
import requests


@dataclass
class CardRec:
    """Single disenchant recommendation."""
    card_id: int
    name: str
    count: int
    rarity: str
    dust_per_copy: int
    total_dust: int
    reason: str
    priority: str  # "high", "medium", "low"
    is_golden: bool = False


@dataclass
class OptimizeResult:
    """Results of dust optimization analysis."""
    recommendations: List[CardRec] = field(default_factory=list)
    total_dust_available: int = 0
    protected_cards: Dict[str, int] = field(default_factory=dict)
    approval_status: str = "pending"  # "pending", "approved", "completed"


def get_card_name(card: Dict) -> str:
    """Extract English card name from card data (handles multilingual format)."""
    if isinstance(card.get("name"), dict):
        return card["name"].get("enUS", "Unknown")
    return card.get("name", "Unknown")


def get_dust_value(rarity: str) -> int:
    """Return dust value for a given rarity."""
    rarity_map = {
        "COMMON": 5,
        "RARE": 20,
        "EPIC": 100,
        "LEGENDARY": 400,
    }
    return rarity_map.get(rarity, 0)


def load_collection(path: str) -> Dict[str, int]:
    """Load collection from JSON (dbfId -> count map)."""
    with open(path) as f:
        data = json.load(f)

    # Handle HSReplay format
    if "collection" in data:
        collection = defaultdict(int)
        for dbf_id_str, counts in data["collection"].items():
            # counts might be [normal, golden, diamond, signature]
            if isinstance(counts, list):
                collection[int(dbf_id_str)] = sum(c for c in counts if c)
            else:
                collection[int(dbf_id_str)] = counts
        return dict(collection)

    # Handle simple {dbfId: count} format
    return {int(k): v for k, v in data.items()}


def load_cards_json(path: Optional[str] = None) -> Dict[int, Dict]:
    """Load card database (dbfId -> card data map)."""
    if path:
        with open(path) as f:
            cards = json.load(f)
            if "cards" in cards:
                cards = cards["cards"]
    else:
        # Fetch from HearthstoneJSON
        print("Fetching latest card data from HearthstoneJSON...", file=sys.stderr)
        try:
            resp = requests.get("https://api.hearthstonejson.com/v1/latest/all/cards.json")
            resp.raise_for_status()
            cards = resp.json()
        except Exception as e:
            print(f"Error fetching cards: {e}", file=sys.stderr)
            return {}

    # Index by dbfId
    indexed = {}
    for card in cards:
        if "dbfId" in card:
            indexed[card["dbfId"]] = card
    return indexed


def analyze_collection(
    collection: Dict[str, int],
    cards_db: Dict[int, Dict],
    threshold: int = 5,
) -> OptimizeResult:
    """
    Analyze collection and recommend disenchants.

    Only flags EXTRA COPIES beyond the playable maximum (1 for Legendary,
    2 for everything else) — the same set the in-game "Mass Disenchant"
    button clears. Anything beyond that (e.g. "you never play this card")
    is a judgment call this script deliberately does not make: an earlier
    version flagged every non-meta minion and recommended disenchanting
    ~900 legendaries, which was dangerously wrong.

    Note: counts sum all finishes (normal + golden + diamond + signature),
    and dust is estimated at the regular disenchant rate, so golden extras
    are undervalued — the real number can only be higher.

    Args:
        collection: {dbfId: count} of owned cards
        cards_db: {dbfId: card_data} card database
        threshold: Minimum dust-per-copy to include

    Returns:
        OptimizeResult with ranked recommendations
    """
    result = OptimizeResult()
    recommendations = []

    for card_id_str, count in collection.items():
        try:
            card_id = int(card_id_str)
        except ValueError:
            continue

        if card_id not in cards_db:
            continue

        card = cards_db[card_id]
        name = get_card_name(card)
        rarity = card.get("rarity", "COMMON")

        # Core/free cards can't be disenchanted (0 dust)
        if card.get("set") in ("CORE", "LEGACY_FREE", "HERO_SKINS", "VANILLA"):
            continue

        dust_value = get_dust_value(rarity)
        if dust_value < threshold:
            continue

        max_playable = 1 if rarity == "LEGENDARY" else 2
        extra_copies = count - max_playable

        if extra_copies > 0:
            recommendations.append(CardRec(
                card_id=card_id,
                name=name,
                count=extra_copies,
                rarity=rarity,
                dust_per_copy=dust_value,
                total_dust=dust_value * extra_copies,
                reason="extra_copies",
                priority="high",
            ))

    # Sort by priority, then by dust value
    priority_order = {"high": 0, "medium": 1, "low": 2}
    recommendations.sort(
        key=lambda r: (priority_order[r.priority], -r.total_dust)
    )

    result.recommendations = recommendations
    result.total_dust_available = sum(r.total_dust for r in recommendations)

    return result


def format_summary(result: OptimizeResult) -> str:
    """Format results as human-readable summary."""
    output = ["DISENCHANT RECOMMENDATIONS", "=" * 40, ""]

    if not result.recommendations:
        output.append("No recommendations at this time.")
        return "\n".join(output)

    by_priority = {"high": [], "medium": [], "low": []}
    for rec in result.recommendations:
        by_priority[rec.priority].append(rec)

    for priority in ["high", "medium", "low"]:
        if by_priority[priority]:
            title = f"{priority.upper()} PRIORITY"
            output.append(f"\n{title}:")
            for rec in by_priority[priority]:
                output.append(
                    f"  - {rec.count}x {rec.name} ({rec.rarity}, {rec.dust_per_copy} dust each = {rec.total_dust} total)"
                )
                output.append(f"      reason: {rec.reason}")

    output.append("")
    output.append(f"TOTAL DUST AVAILABLE: {result.total_dust_available}")

    return "\n".join(output)


def format_json(result: OptimizeResult) -> str:
    """Format results as JSON."""
    return json.dumps({
        "recommendations": [
            {
                "card_id": r.card_id,
                "name": r.name,
                "count": r.count,
                "rarity": r.rarity,
                "dust_per_copy": r.dust_per_copy,
                "total_dust": r.total_dust,
                "reason": r.reason,
                "priority": r.priority,
            }
            for r in result.recommendations
        ],
        "total_dust_available": result.total_dust_available,
        "approval_status": result.approval_status,
    }, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="List extra Hearthstone card copies and the dust Mass Disenchant would yield"
    )
    parser.add_argument(
        "--collection",
        required=True,
        help="Path to collection JSON (dbfId -> count map, or HSReplay export)",
    )
    parser.add_argument(
        "--cards-json",
        help="Path to cards.collectible.json (auto-fetched if omitted)",
    )
    parser.add_argument(
        "--view",
        choices=["summary", "json"],
        default="summary",
        help="Output format",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=5,
        help="Minimum dust-per-copy to include (default: 5, i.e. everything)",
    )
    parser.add_argument(
        "--output",
        help="Save results to JSON file",
    )

    args = parser.parse_args()

    # Load data
    print("Loading collection...", file=sys.stderr)
    collection = load_collection(args.collection)

    print("Loading card database...", file=sys.stderr)
    cards_db = load_cards_json(args.cards_json)

    # Analyze
    print("Analyzing collection...", file=sys.stderr)
    result = analyze_collection(
        collection,
        cards_db,
        threshold=args.threshold,
    )

    # Output results
    if args.view == "json":
        output = format_json(result)
    else:
        output = format_summary(result)

    print(output)

    if args.output:
        with open(args.output, "w") as f:
            f.write(format_json(result))
        print(f"\nResults saved to {args.output}", file=sys.stderr)

    print(
        "\nTo claim this dust: Hearthstone -> Collection -> crafting mode -> Mass Disenchant.",
        file=sys.stderr,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
