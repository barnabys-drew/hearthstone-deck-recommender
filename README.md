# Hearthstone AI CLI Skills

Portable [Agent Skills](https://SKILL.md) for building and choosing Hearthstone decks,
designed to work across multiple AI coding CLIs (Codex, Claude Code, Cursor, Gemini)
from a single shared source.

Each skill is a self-contained folder with a `SKILL.md`, a deterministic Python script
(dependency-free, standard library only), and reference docs.

## Skills

### `hearthstone-deck-builder`
Build a Hearthstone deck and produce a verified **import deck code (deckstring)** the
game can load from the clipboard.

- Encodes/decodes the Hearthstone deckstring format (varint + base64).
- Resolves card names to DBF IDs via HearthstoneJSON (or a local card file).
- Handles sideboards (e.g. E.T.C., Band Manager), heroes, and formats.
- Validates copy/legendary limits and round-trips the code for correctness.

```bash
python3 hearthstone-deck-builder/scripts/build_deck_code.py --input deck.json --copy
```

### `hearthstone-deck-recommender`
Given your **collection** and a set of **current top Standard decks**, rank them by the
arcane dust needed to complete each one — so you can see which competitive deck is
easiest for your account to build.

- Normalizes many collection export shapes (HSReplay `collection/mine` JSON,
  Hearthstone Deck Tracker / Firestone exports, `{dbfId: count}` maps, CSV).
- Decodes each deck's deckstring and computes dust-to-complete per card
  (Common 40 / Rare 100 / Epic 400 / Legendary 1600; Core cards are free).
- Ranks cheapest-first with a win-rate tiebreak; supports `--budget`.
- Can load a collection from a local export (`--collection`) or JSON URL (`--collection-url`).
- Includes a one-shot wrapper that ranks decks, picks the best one, and prints a
  Hearthstone clipboard/import block.

```bash
python3 hearthstone-deck-recommender/scripts/rank_decks.py \
  --collection collection.json --decks meta_decks.json

python3 hearthstone-deck-recommender/scripts/recommend_and_import.py \
  --collection-url "https://...account_lo=..." --decks meta_decks.json --budget 4000
```

The recommender and builder work in tandem: the recommender picks the best deck for your
collection; the wrapper prints the deckstring in a Hearthstone import block.

## Installing into an AI CLI

These skills use the standard `SKILL.md` format. Point each CLI at the same shared
folder so encoder fixes stay in one place (see
`hearthstone-deck-builder/references/ai-cli-install.md`):

- **Codex / Claude Code / Cursor** — symlink each skill folder into the tool's skills
  directory, e.g.:
  ```bash
  ln -s "$PWD/hearthstone-deck-builder"     ~/.codex/skills/hearthstone-deck-builder
  ln -s "$PWD/hearthstone-deck-recommender" ~/.cursor/skills/hearthstone-deck-recommender
  ```
- **Gemini / CLIs without native skills** — add an `AGENTS.md` / `GEMINI.md` pointer
  telling the agent to read the relevant `SKILL.md`.

## Notes

- There is no official Blizzard API for a player's collection; the recommender documents
  the practical ways to obtain it. See `hearthstone-deck-recommender/references/data-formats.md`.
- Card data comes from the community [HearthstoneJSON](https://hearthstonejson.com) project.
