---
name: hearthstone-deck-recommender
description: Figure out which current top competitive Hearthstone deck is easiest for a specific account to build, by comparing the user's card collection against current top Standard meta decks and ranking them by arcane dust needed to complete. Use whenever the user asks what deck they should build, which meta/competitive deck is cheapest or easiest to craft, what to spend dust on, which top-deck-site list they can afford, or wants deck recommendations based on the cards they already own.
---

# Hearthstone Deck Recommender

Recommend which competitive Standard deck a player should build, ranked by how little
arcane dust they need to complete it given the cards they already own.

There is **no official Blizzard API** for a player's collection, so getting the
collection is the part that needs care. The dust math and ranking are handled by
`scripts/rank_decks.py`.

## Workflow

1. **Get the collection** (see "Getting the collection" below). Save it to `collection.json`.
2. **Get current top Standard decks as deckstrings** (see "Getting current meta decks").
   Save them to `meta_decks.json` (or a text file of deck codes).
3. **Rank** with the bundled script:
   ```bash
   python3 <skill-dir>/scripts/rank_decks.py \
     --collection collection.json \
     --decks meta_decks.json
   ```
4. **Recommend.** Lead with the cheapest deck that is still competitive. Balance
   dust cost against win rate / tier: a 0-dust tier-3 deck may be worse advice than a
   small-craft tier-1 deck. Explain the tradeoff and list the exact missing cards.
5. To turn a chosen deck into an in-game import code, hand off to the
   `hearthstone-deck-builder` skill (or just give the deckstring, which imports directly).

## Getting the collection

Try these in order; stop at the first that works for the user.

1. **HSReplay collection JSON (most reliable).** The user connects Blizzard to a
   deck tracker (Hearthstone Deck Tracker on Windows, or Firestone) at least once so
   the collection uploads. Then, logged in at `https://hsreplay.net/collection/mine/`,
   open browser DevTools (F12) → Network, reload, and copy the JSON response from the
   request whose URL contains `account_lo=`. Save it as `collection.json`. It looks
   like `{"collection": {"<dbfId>": [normal, golden, diamond, signature], ...}, ...}`.
   The script reads this shape directly.
2. **Deck-tracker export.** Hearthstone Deck Tracker and Firestone can export the
   collection to JSON/CSV. Any JSON `{dbfId: count}` map, a list of
   `{"dbfId":..., "count":...}` / `{"dbfId":..., "ownedTotal":...}`, or a CSV with a
   `dbfId` column plus a count/`ownedTotal` column works.
3. **Manual.** If the user only knows a few key cards, build a small
   `{dbfId: count}` map by hand. Resolve names to DBF IDs via HearthstoneJSON.

Golden/diamond/signature copies count toward ownership — any finish fills the deck slot.

## Getting current meta decks

Card pools and the meta change constantly, so fetch **current** data; do not rely on
memorized lists. Browse current top-deck sources and collect each deck's name, class,
deckstring, and (if available) win rate or tier. Good sources include HSReplay meta,
Hearthstone Top Decks tier lists, HSGuru, Vicious Syndicate, and d0nkey. Prefer sources
that publish an importable deck code.

Save as JSON:

```json
{
  "decks": [
    {"name": "Aggro Hunter", "class": "Hunter", "tier": 1, "winrate": 54.2, "deckstring": "AAECAR8..."},
    {"name": "Control Warrior", "class": "Warrior", "tier": 2, "winrate": 52.1, "deckstring": "AAEBAQc..."}
  ]
}
```

`winrate` (or `win_rate`/`wr`) is optional but improves the recommendation: with
`--sort value` the script breaks dust ties by higher win rate. You can also pass a plain
text file with one deck code per line and an optional `# Deck Name` comment above each.

## Using the ranking script

Key options:

- `--collection PATH` and `--decks PATH` (required).
- `--cards-json PATH` uses a local HearthstoneJSON `cards.collectible.json` (needed for
  rarity/dust/names). Without it the script fetches the latest set; use `--no-fetch` to
  stay offline (dust costs then require the local file).
- `--sort value` (default: cheapest first, win-rate tiebreak) | `dust` | `completion`.
- `--budget N` shows only decks completable within N dust.
- `--max-results N`, `--top-missing N`, `--json` for machine-readable output.

Dust to craft a missing copy: Common 40, Rare 100, Epic 400, Legendary 1600. Core-set
cards can't be crafted (0 dust) and are flagged as free/leveling cards instead.

## Output

Give the user:

1. A short ranked list (cheapest-to-build competitive decks first) with dust needed,
   percent already owned, and missing legendaries/epics.
2. A clear top recommendation with the reasoning (dust vs. competitiveness).
3. The exact missing cards for the recommended deck, and the deckstring so they can
   import it once built.

See `references/data-formats.md` for exact input shapes and examples.
