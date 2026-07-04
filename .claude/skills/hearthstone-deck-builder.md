---
name: hearthstone-deck-builder
description: Build Hearthstone decks and produce verified import deck codes that the Hearthstone client can load
---

# Hearthstone Deck Builder

Create Hearthstone decks that are strategically coherent and importable by the game client.

## Quick Start

Provide a deck list (cards by name or DBF ID) and the script generates a verified deckstring:

```bash
python3 hearthstone-deck-builder/scripts/build_deck_code.py --input deck.json
```

Copy the import block into your clipboard, open Hearthstone, create a deck, and paste.

## Core Workflow

1. **Clarify deck intent** — Standard/Wild/Twist, class, archetype, budget. Prefer reasonable defaults.
2. **Use current data** — card pools, balance patches, and legality change often. Browse current sources unless user asks for off-meta/theorycraft.
3. **Draft the deck** — 30 cards (or valid alternate size). Respect class, copy limits (1 Legendary, 2 others), and format legality.
4. **Generate the code** — use `build_deck_code.py`, never hand-invent deckstrings. It validates constraints and resolves card names to DBF IDs.
5. **Verify** — re-run with `--decode` to check the output. If card names are ambiguous, fix by DBF ID.
6. **Present in clipboard-ready form** — import block + instructions.

## Input Format

JSON deck file:
```json
{
  "name": "Elemental Mage",
  "class": "Mage",
  "format": "standard",
  "cards": [
    {"name": "Example Card", "count": 2},
    {"dbfId": 12345, "count": 1}
  ],
  "sideboard_cards": [
    {"name": "Sideboard Card", "count": 1, "owner": "E.T.C., Band Manager"}
  ]
}
```

Mix names and DBF IDs freely. The script resolves names via HearthstoneJSON or a local `--cards-json` file.

## Flags

- `--input deck.json` — deck to encode
- `--cards-json path/to/cards.collectible.json` — local card data (avoids network)
- `--no-fetch` — offline mode (requires DBF IDs for all cards)
- `--decode AAECA...` — decode and verify a deckstring
- `--copy` — copy import block to clipboard (if available)
- `--deck-size 30|40|none` — validate deck size (default 30)

## Handling Ambiguous Cards

Many card names have multiple printings. If the script reports ambiguity:
- Check a current database and add `dbfId` to that card entry
- Or decode a known-good deck from another source and compare DBF IDs
- Don't guess — import correctness depends on exact IDs

## Output

Print:
1. Deck name, class, format, one-paragraph game plan
2. Import block (exact from script, unmodified)
3. Note that the deckstring is what Hearthstone reads

## See Also

- `/hearthstone-deck-recommender` — rank decks by dust cost
- `/hearthstone-substitute-suggester` — find alternatives to missing cards
- `references/deck-json-examples.md` — example deck shapes
