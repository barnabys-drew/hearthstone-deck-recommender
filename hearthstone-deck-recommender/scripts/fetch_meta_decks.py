#!/usr/bin/env python3
"""Fetch current Hearthstone deck candidates as deckstrings.

This gathers a batch of current decklists (name, class, deckstring) from a public
deck site so the recommender has real, up-to-date candidates to rank against a
collection. Deck codes are the stable, importable representation, so this scraper
only extracts them plus light metadata.

Sites change their HTML often. This uses conservative, well-documented patterns
and skips anything it can't parse cleanly rather than guessing. If the layout
changes and nothing is found, assemble meta_decks.json by hand (see the skill's
references) — the ranking script does not depend on this fetcher.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.request
from typing import Any

USER_AGENT = "Mozilla/5.0 hearthstone-ai-cli-skills/1.0 (+meta-deck-fetch)"

# Base64 Hearthstone deckstrings start with the reserved(0)+version(1) bytes and
# are long. Anchoring on "AAE" avoids matching short unrelated base64 blobs.
DECKSTRING_RE = re.compile(r"AAE[A-Za-z0-9+/]{40,}={0,2}")

CLASS_SLUGS = {
    "death-knight": "Death Knight",
    "demon-hunter": "Demon Hunter",
    "druid": "Druid",
    "hunter": "Hunter",
    "mage": "Mage",
    "paladin": "Paladin",
    "priest": "Priest",
    "rogue": "Rogue",
    "shaman": "Shaman",
    "warlock": "Warlock",
    "warrior": "Warrior",
}

DEFAULT_LISTINGS = [
    "https://hearthstone-decks.net/standard-decks/",
]
DETAIL_LINK_RE = re.compile(r"https://hearthstone-decks\.net/[a-z0-9%\-]+/")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def fetch(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def guess_class(url: str, title: str) -> str | None:
    haystack = f"{url} {title}".lower()
    for slug, name in CLASS_SLUGS.items():
        if slug in haystack or slug.replace("-", " ") in haystack:
            return name
    return None


def clean_title(raw: str, url: str) -> str:
    title = html.unescape(raw or "").strip()
    # Strip common site suffixes like " - Hearthstone-Decks.net".
    title = re.split(r"\s+[-|–]\s+", title)[0].strip()
    if title:
        return title
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").title()


def collect_detail_urls(listing_urls: list[str], limit: int) -> list[str]:
    seen: list[str] = []
    seen_set: set[str] = set()
    for listing in listing_urls:
        try:
            page = fetch(listing)
        except Exception as exc:
            print(f"WARNING: could not fetch listing {listing}: {exc}", file=sys.stderr)
            continue
        for link in DETAIL_LINK_RE.findall(page):
            # Detail pages have a descriptive slug; skip obvious non-decks.
            slug = link.rstrip("/").rsplit("/", 1)[-1]
            if not re.search(r"\d", slug) and "legend" not in slug:
                continue
            if any(bad in link for bad in ("/category/", "/standard-decks", "/wild-decks", "/tag/", "/author/")):
                continue
            if link in seen_set:
                continue
            seen_set.add(link)
            seen.append(link)
    return seen[: limit * 2]  # over-collect; some pages may fail to parse


def extract_deck(url: str) -> dict[str, Any] | None:
    try:
        page = fetch(url)
    except Exception as exc:
        print(f"WARNING: could not fetch {url}: {exc}", file=sys.stderr)
        return None
    codes = []
    for m in DECKSTRING_RE.finditer(page):
        code = html.unescape(m.group(0)).strip()
        if code not in codes:
            codes.append(code)
    if not codes:
        return None
    title_match = TITLE_RE.search(page)
    title = clean_title(title_match.group(1) if title_match else "", url)
    # Pick the longest code (full 30-card decks encode longer than snippets).
    code = max(codes, key=len)
    return {
        "name": title,
        "class": guess_class(url, title),
        "format": "standard",
        "source": url,
        "deckstring": code,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch current Standard deck candidates as deckstrings.")
    parser.add_argument("--out", default="meta_decks.json", help="Output JSON path")
    parser.add_argument("--limit", type=int, default=40, help="Max decks to collect")
    parser.add_argument("--listing", action="append", help="Listing URL(s) to crawl (repeatable)")
    parser.add_argument("--sleep", type=float, default=0.3, help="Delay between requests (be polite)")
    parser.add_argument("--one-per-class", action="store_true", help="Keep only the first deck per class for variety")
    args = parser.parse_args(argv)

    listings = args.listing or DEFAULT_LISTINGS
    detail_urls = collect_detail_urls(listings, args.limit)
    if not detail_urls:
        print("ERROR: no deck detail links found; site layout may have changed.", file=sys.stderr)
        return 2

    decks: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    seen_classes: set[str] = set()
    for url in detail_urls:
        if len(decks) >= args.limit:
            break
        deck = extract_deck(url)
        time.sleep(max(0.0, args.sleep))
        if not deck:
            continue
        if deck["deckstring"] in seen_codes:
            continue
        if args.one_per_class:
            cls = deck.get("class") or "?"
            if cls in seen_classes:
                continue
            seen_classes.add(cls)
        seen_codes.add(deck["deckstring"])
        decks.append(deck)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"decks": decks}, f, indent=2)
    print(f"Saved {len(decks)} decks to {args.out}")
    by_class: dict[str, int] = {}
    for d in decks:
        by_class[d.get("class") or "?"] = by_class.get(d.get("class") or "?", 0) + 1
    print("By class:", ", ".join(f"{k}={v}" for k, v in sorted(by_class.items())))
    return 0 if decks else 2


if __name__ == "__main__":
    raise SystemExit(main())
