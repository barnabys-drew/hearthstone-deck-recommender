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
3. **Rank** with the bundled script, or use the one-shot wrapper:
   ```bash
   python3 <skill-dir>/scripts/rank_decks.py \
     --collection collection.json \
     --decks meta_decks.json

   # One-shot: rank, choose the best deck, and print a Hearthstone import block
   python3 <skill-dir>/scripts/recommend_and_import.py \
     --collection collection.json \
     --decks meta_decks.json \
     --view visual \
     --pick-policy close
   ```
4. **Recommend.** Prefer the visual output. It separates the best overall deck,
   best affordable deck, best close/easy craft, and cheapest deck, then groups
   candidates into dust tiers. Use that to explain the tradeoff instead of
   presenting a flat table as the only answer.
5. The one-shot wrapper is the tandem flow with `hearthstone-deck-builder`: it uses
   the recommender's math, then prints the chosen deck's deckstring in an import block
   the Hearthstone client can read from the clipboard.

## Getting the collection

Try these in order; stop at the first that works for the user.

1. **HSReplay collection JSON (most reliable).** The user connects Blizzard to a
   deck tracker (Hearthstone Deck Tracker on Windows, or Firestone) at least once so
   the collection uploads. Then, logged in at `https://hsreplay.net/collection/mine/`,
   open browser DevTools (F12) → Network, reload, and copy the JSON response from the
   request whose URL contains `account_lo=`. Save it as `collection.json`. It looks
   like `{"collection": {"<dbfId>": [normal, golden, diamond, signature], ...}, ...}`.
   The script reads this shape directly. If the copied request URL returns JSON directly,
   use `--collection-url "https://...account_lo=..."`; if it is private to your browser
   session, paste/save the JSON manually or pass `--collection-cookie` with a Cookie
   header copied from DevTools. Avoid saving Cookie headers in shell history.
2. **Deck-tracker export.** Hearthstone Deck Tracker and Firestone can export the
   collection to JSON/CSV. Any JSON `{dbfId: count}` map, a list of
   `{"dbfId":..., "count":...}` / `{"dbfId":..., "ownedTotal":...}`, or a CSV with a
   `dbfId` column plus a count/`ownedTotal` column works.
3. **Manual.** If the user only knows a few key cards, build a small
   `{dbfId: count}` map by hand. Resolve names to DBF IDs via HearthstoneJSON.

Golden/diamond/signature copies count toward ownership — any finish fills the deck slot.

## Getting current meta decks (automatic)

`scripts/fetch_meta_decks.py` collects a batch of current Standard decks (name,
class, deckstring) from a public deck site and writes `meta_decks.json`:

```bash
python3 <skill-dir>/scripts/fetch_meta_decks.py --out meta_decks.json --limit 40
```

Deck sites change their HTML and their front-page decks constantly, so treat this
as a convenience: if it returns nothing, or you want a specific curated meta,
assemble `meta_decks.json` by hand or from other sources (below). The ranking
scripts never depend on the fetcher.

## Getting current meta decks (manual / other sources)

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

- `--collection PATH` **or** `--collection-url URL`, plus `--decks PATH` (required).
- `--collection-cookie COOKIE` can be used with private browser-session collection URLs.
- `--cards-json PATH` uses a local HearthstoneJSON `cards.collectible.json` (needed for
  rarity/dust/names). Without it the script fetches the latest set; use `--no-fetch` to
  stay offline (dust costs then require the local file).
- `--sort value` (default: cheapest first, win-rate tiebreak) | `dust` | `completion`.
- `--budget N` shows only decks completable within N dust.
- `--max-results N`, `--top-missing N`, `--json` for machine-readable output.
- `scripts/recommend_and_import.py` accepts the same collection/deck/card options, plus
  `--view visual|table|both`, `--pick-policy close|affordable|overall|cheapest|rank`,
  `--available-dust`, and `--close-dust`. The wrapper detects `dust` from HSReplay
  collection JSON when present.

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
