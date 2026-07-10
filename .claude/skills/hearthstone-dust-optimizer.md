---
name: hearthstone-dust-optimizer
description: Preview how much dust Mass Disenchant would yield from extra card copies in your Hearthstone collection
---

# Hearthstone Dust Optimizer

Analyze your collection and list every extra card copy beyond the playable
maximum (1x Legendary, 2x everything else), with the dust you'd gain by
disenchanting them.

## The one thing to understand first

**Disenchanting can only be done inside the Hearthstone game client.**
There is no collection UI on battle.net's website (verified by probing the
live site), and automating the game client itself violates Blizzard's EULA
and risks account action. So this skill does not delete anything — it
computes the preview, and the in-game **Mass Disenchant** button
(Collection → crafting mode, bottom-right) clears exactly the set of cards
this script flags, in one click.

## Usage

```bash
python3 hearthstone-deck-recommender/scripts/optimize_dust.py \
  --collection collection.json \
  --view summary            # or json
```

Flags:

- `--collection PATH` — collection JSON: HSReplay export or `{dbfId: count}` map (required)
- `--cards-json PATH` — local HearthstoneJSON card data (auto-fetched if omitted)
- `--view summary|json` — output format
- `--threshold N` — minimum dust-per-copy to include (default 5 = everything)
- `--output PATH` — also save results as JSON

## What it flags (and deliberately doesn't)

Flags only **extra copies beyond playable max** — count minus 2 (minus 1
for Legendaries), skipping uncraftable sets (Core, Legacy-free, Vanilla)
which disenchant for 0 dust.

It does **not** flag "cards you never play" / "low meta relevance." A
previous version tried that with an unimplemented meta-deck protection stub
and recommended disenchanting ~900 legendaries (~360k phantom dust).
Which non-duplicate cards to cut is a judgment call — make it card by card,
never in bulk.

## Accuracy notes

- Counts sum all finishes (normal + golden + diamond + signature); dust is
  estimated at regular disenchant rates (5/20/100/400), so golden extras
  are undervalued. The in-game Mass Disenchant number is the ground truth
  and may be slightly higher.
- Verified against a real ~4,600-card collection: script said 3,800 dust.

## See Also

- `/hearthstone-deck-recommender` — pick your next deck (spend the dust)
- `../DUST_OPTIMIZER_GUIDE.md` — workflow guide + notes on the WSL→Windows
  Chrome CDP setup (reusable for other browser automations)
