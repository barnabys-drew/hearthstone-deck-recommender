# Input data formats

## Collection

The script normalizes several shapes into `{dbfId: owned_count}`. Owned count sums all
finishes (normal + golden + diamond + signature) because any copy fills a deck slot.

You can load collections from disk with `--collection collection.json` or directly from a
JSON URL with `--collection-url`. Private HSReplay URLs may require copying the JSON from
DevTools, or passing a `--collection-cookie` header copied from your browser session. Do
not commit Cookie headers or paste them into shared logs.

### HSReplay collection/mine JSON (preferred)

```json
{
  "collection": {
    "1234": [2, 0, 0, 0],
    "5678": [0, 1, 0, 0]
  },
  "dust": 3200
}
```

The top-level `collection` object is used; other keys are ignored.

### Simple maps and lists

```json
{"1234": 2, "5678": 1}
```

```json
[
  {"dbfId": 1234, "count": 2},
  {"dbfId": 5678, "ownedTotal": 1},
  {"dbfId": 4321, "normal": 1, "golden": 1}
]
```

### CSV

Needs a `dbfId` column and a count column (`ownedTotal`, `owned`, `count`, `total`, or `normal`).

```csv
dbfId,ownedTotal
1234,2
5678,1
```

## Meta decks

```json
{
  "decks": [
    {"name": "Aggro Hunter", "class": "Hunter", "tier": 1, "winrate": 54.2, "deckstring": "AAECAR8..."}
  ]
}
```

Or a plain-text file:

```text
# Aggro Hunter
AAECAR8...
# Control Warrior
AAEBAQc...
```

## How dust is computed

For each deck the script decodes the deckstring, and for every card computes
`missing = required_copies - min(owned, required_copies)`, multiplies by the rarity's
craft cost (Common 40, Rare 100, Epic 400, Legendary 1600), and sums. Core-set cards are
0 dust (uncraftable / earned by leveling) and reported separately as free cards.

## One-shot import flow

Use `scripts/recommend_and_import.py` when you want the skills to work together:

```bash
python3 scripts/recommend_and_import.py \
  --collection collection.json \
  --decks meta_decks.json \
  --budget 4000
```

The wrapper prints the ranked report and then a `COPY THIS INTO HEARTHSTONE` block for
the chosen deck. Copy the block or just the deckstring line, open Hearthstone, create a
new deck, and accept the detected clipboard deck.
