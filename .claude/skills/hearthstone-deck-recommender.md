---
name: hearthstone-deck-recommender
description: Rank competitive Hearthstone decks by dust cost based on your collection, with optional substitute card suggestions
---

# Hearthstone Deck Recommender

Recommend which competitive Standard deck you should build, ranked by how little arcane dust you need to complete it given the cards you already own.

## Quick Start

```bash
python3 hearthstone-deck-recommender/scripts/recommend_and_import.py \
  --collection collection.json \
  --view visual \
  --suggest-substitutes
```

This will:
1. Load your card collection
2. Fetch current meta decks (or use `--decks meta_decks.json` to provide your own)
3. Rank by dust cost
4. Print a recommendation with substitute suggestions for missing cards
5. Output an importable deck code

## Getting Your Collection

**HSReplay (easiest)**: Log into [hsreplay.net/collection/mine/](https://hsreplay.net/collection/mine/), open DevTools (F12) → Network, reload, copy the JSON response from `account_lo=` request, save as `collection.json`.

**Deck Tracker**: Export from Hearthstone Deck Tracker or Firestone as JSON/CSV.

**Manual**: Build a small `{dbfId: count}` map by hand.

## Key Flags

- `--suggest-substitutes` — find owned cards that could replace missing ones
- `--substitute-cost-window 1` — mana cost matching window (default 1)
- `--max-substitutes 3` — max suggestions per missing card (default 3)
- `--view visual|table|both` — output style (default: visual)
- `--pick-policy close|affordable|overall|cheapest|rank` — which deck to import (default: close)
- `--available-dust N` — if you have dust to spend, narrows recommendations
- `--budget N` — only show decks costing ≤ N dust

## Understanding Output

The visual report shows four picks:
- **Best overall** — highest-rated deck by meta consensus
- **Best affordable** — strongest deck within your available dust (if provided)
- **Best close/easy craft** — strongest deck within ~3200 dust (default threshold)
- **Cheapest** — lowest dust cost, regardless of strength

The **suggested first build** is the one chosen for import; use `--pick-policy` to change which one.

**Substitute suggestions** are raw attribute matches (same class, type, cost window, tribe/mechanics overlap) — NOT strategic recommendations. Use your Hearthstone knowledge to judge curve fit, synergies (Reborn/Corrupt tags), and combos before adopting one.

## See Also

- `/hearthstone-deck-builder` — build decks with verified import codes
- `/hearthstone-substitute-suggester` — deep dive into substitute matching
- `references/data-formats.md` — exact input/output shapes, caveats
