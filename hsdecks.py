#!/usr/bin/env python3
"""Unified CLI for the Hearthstone deck tools in this repository.

One entry point, four subcommands, each dispatching to the underlying
dependency-free script:

    hsdecks.py recommend    -> hearthstone-deck-recommender/scripts/recommend_and_import.py
    hsdecks.py rank         -> hearthstone-deck-recommender/scripts/rank_decks.py
    hsdecks.py fetch-decks  -> hearthstone-deck-recommender/scripts/fetch_meta_decks.py
    hsdecks.py build        -> hearthstone-deck-builder/scripts/build_deck_code.py

All arguments after the subcommand are passed through unchanged, so each
subcommand accepts exactly the flags of its underlying script:

    python3 hsdecks.py recommend --collection collection.json
    python3 hsdecks.py recommend --help
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

SUBCOMMANDS = {
    "recommend": (
        REPO_ROOT / "hearthstone-deck-recommender" / "scripts" / "recommend_and_import.py",
        "Rank current meta decks by dust needed and print an import block (one-shot)",
    ),
    "rank": (
        REPO_ROOT / "hearthstone-deck-recommender" / "scripts" / "rank_decks.py",
        "Rank saved candidate decks against a collection (no deck fetching)",
    ),
    "fetch-decks": (
        REPO_ROOT / "hearthstone-deck-recommender" / "scripts" / "fetch_meta_decks.py",
        "Fetch current Standard meta decks to meta_decks.json",
    ),
    "build": (
        REPO_ROOT / "hearthstone-deck-builder" / "scripts" / "build_deck_code.py",
        "Build or verify a Hearthstone deckstring import code",
    ),
}


def usage() -> str:
    lines = [
        "usage: hsdecks.py <command> [args...]",
        "",
        "Hearthstone deck tools (dependency-free Python).",
        "",
        "commands:",
    ]
    for name, (_, help_text) in SUBCOMMANDS.items():
        lines.append(f"  {name:<12} {help_text}")
    lines += [
        "",
        "Run 'hsdecks.py <command> --help' for that command's options.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    command, rest = argv[0], argv[1:]
    if command not in SUBCOMMANDS:
        print(f"hsdecks.py: unknown command '{command}'", file=sys.stderr)
        print(usage(), file=sys.stderr)
        return 2
    script, _ = SUBCOMMANDS[command]
    return subprocess.call([sys.executable, str(script), *rest])


if __name__ == "__main__":
    raise SystemExit(main())
