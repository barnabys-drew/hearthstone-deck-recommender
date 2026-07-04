---
name: hearthstone-substitute-suggester
description: Suggest owned Hearthstone cards that could substitute for missing cards in a recommended deck
---

# Hearthstone Substitute Suggester

When a recommended deck requires cards you don't own, this skill finds owned cards that are mechanically similar and could serve as reasonable substitutes.

## When to Use

Use this skill whenever you want to explore alternatives to expensive or hard-to-craft missing cards. Enables smarter deckbuilding without immediate dust spend.

## How It Works

The suggester filters owned cards by:
1. **Legality** — must be NEUTRAL or match the deck's class
2. **Type match** — exact card type (MINION/SPELL/WEAPON)
3. **Mana cost window** — within ±N cost of the missing card (default ±1)
4. **Copy headroom** — not already at max copies in the deck (1 for Legendary, 2 for others)

Then scores by:
- `+2` for matching tribe/race (e.g., both BEAST)
- `+1` per shared mechanic keyword (e.g., both have TAUNT)
- Ties broken by closer mana cost, then alphabetical

Returns top N (default 3) candidates ranked by score.

## Command-Line Usage

```bash
# Via the main recommender (with substitutes enabled)
python3 hearthstone-deck-recommender/scripts/recommend_and_import.py \
  --collection collection.json \
  --decks meta_decks.json \
  --suggest-substitutes \
  --substitute-cost-window 2 \
  --max-substitutes 5

# Via rank_decks directly
python3 hearthstone-deck-recommender/scripts/rank_decks.py \
  --collection collection.json \
  --decks meta_decks.json \
  --suggest-substitutes \
  --view visual
```

## Important Caveats

**These are attribute matches only, not strategic guarantees.** Before adopting a substitute, verify:
- **Curve fit** — does it maintain the deck's mana curve?
- **Synergies** — does it trigger the same combos/triggers? (Reborn, Corrupt, Overheal, etc.)
- **Combo pieces** — is it part of a specific combo line?
- **Rarity/dust cost** — is crafting the substitute cheaper than the original?

**Known limitations**:
- Death Knight rune legality is not modeled
- Highlander singleton rules are not tracked per-deck
- Scores are purely mechanical, not meta-aware

## Flags

- `--suggest-substitutes` — enable suggestions (off by default)
- `--substitute-cost-window N` — mana window (default 1)
- `--max-substitutes N` — top N candidates per missing card (default 3)

## Output Format

In text reports:
```
  - 1x Sample Legendary (Legendary, 1600 dust)
      owned alternatives: Other Legendary (9-mana Legendary)
```

In import block (pasted into Hearthstone):
```
# - 1x Sample Legendary (LEGENDARY, 1600 dust)
#     substitutes you own (unverified — pick by curve/synergy): Other Legendary (9-mana Legendary)
```

## See Also

- `/hearthstone-deck-recommender` — main deck ranking skill
- `references/data-formats.md` — substitute data shapes and caveats
