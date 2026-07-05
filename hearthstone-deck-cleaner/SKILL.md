---
name: hearthstone-deck-cleaner
description: Analyze a deck and identify which cards to cut. Use this when a deck's win rate has been sliding or the user asks "what should I remove from this deck?"
---

# Hearthstone Deck Cleaner

Identify which cards are dragging down your deck's win rate and should be cut. The cleaner analyzes historical game data to surface underperforming cards, then pairs with the deck recommender's substitute-suggestion logic to propose replacements.

Unlike the post-game coach (analyzing one game ex post facto), this skill looks across many games to identify deck-wide weaknesses.

## When to Use

When a deck's win rate has been sliding, or the user asks: "what should I cut?", "clean up my deck", "this deck feels off", or "which cards are hurting me?"

The analysis requires at least 5 games (default `min_games=5`); decks with fewer games will show "insufficient data" rather than unreliable recommendations.

## What the Skill Does

### 1. Identify Cut Candidates (Ranked)
Compares each card's win rate (when drawn) against the deck's own baseline. Cards with the worst delta (wr_drawn - baseline_wr) surface first. For example:
```
Erupting Volcano: 34% win rate when drawn vs 58% deck baseline over 12 games → -24% delta
```

### 2. Flag Dead Draws
Cards drawn often but rarely played clog the hand even if their win rate isn't obviously bad. For example:
```
Sanguine Depths: drawn 8 times, played 2 times → 75% dead draw rate
```

### 3. Suggest Replacements
Hand off the worst cards to the deck recommender's `--suggest-substitutes` logic (reuses existing scoring from `hearthstone-deck-recommender`). The cleaner identifies *what to cut*, the recommender proposes *what to play instead*.

### 4. Flag Insufficient-Data Cards
Cards in your current deck list with fewer than `min_games` draws are explicitly marked as "can't judge yet" rather than silently ignored.

## Input Data

The skill accesses:
- **`hst stats cut --deck "<name>" --min-games <N>`** (new command) for per-card win-rate deltas
- **`hearthstone-deck-builder/scripts/build_deck_code.py --decode <deckstring>`** to parse the current deck list
- **Tracker database** (`~/.local/share/hearthstone-tracker/games.db`): game metadata, card draws/plays, win rates

## Output Format

### Header
```
== DECK CLEANER: [Deck Name] — [game_type] [format] [overall deckwin rate]
```

### Section 1: Cut Candidates (Ranked by Delta)
```
Cut Candidates (worst first):
—
1. Erupting Volcano: 34% win rate when drawn (12 games) vs 58% deck baseline → -24% delta
   → Cards with negative deltas are dragging the deck down.

2. Rockskipper: 42% win rate when drawn (8 games) vs 58% deck baseline → -16% delta

3. Shield Block: 68% win rate when drawn (4 games) vs 58% deck baseline → +10% delta
   → Positive deltas are performing above deck baseline; don't cut these.
```

### Section 2: Dead Draws (High Clog Rate)
```
Dead Draws (drawn but rarely played):
—
Sanguine Depths: 75% dead draw rate (drawn 8 times, played 2 times)
→ This card is clogging your hand even if its win rate isn't low. Consider cutting or adding cheaper plays.

Precursory Strike: 50% dead draw rate (drawn 4 times, played 2 times)
→ Conditional effect (needs 5+ cost minion) — can be hard to play on curve.
```

### Section 3: Suggested Replacements
```
Suggested Replacements (if you remove the worst cuts):
—
If you cut -1 Erupting Volcano, -1 Rockskipper:
  Option A: +2 Searing Fissure (cheaper AoE, would've cleared their wide boards turns 4-5)
  Option B: +1 Searing Fissure +1 Shield Block (stabilize + removal)
  Option C: +1 Searing Fissure +1 Eternal Toil (removal + draw)

Run: ./hsdecks recommend --collection <collection.json> --deck-outs "Erupting Volcano,Rockskipper"
     to see full substitute scoring from your collection.
```

### Section 4: Insufficient-Data Cards
```
Insufficient Data (< min_games in history):
—
Bloodmage Thalnos: 1 game recorded
Deathborne: 0 games recorded

These haven't been tested enough to judge. Play a few more games with them
before cutting; they might be tech choices for your meta.
```

## The Checklist: What to Analyze

1. **Cut candidates:** Cards with negative `wr_delta` (below deck baseline) are hurting you.
2. **Dead draws:** Cards with high `dead_draw_pct` are clogging your hand.
3. **Missing types:** Are you missing card types the cut candidates would've provided? (e.g., cutting a spell and losing all AoE).
4. **Replacement cost:** Cutting a 3-drop means you need a 3-drop replacement, not a 10-drop.
5. **Matchup bias:** A card might look bad against THIS deck's meta (specific opponents faced) without being bad in general.

## Examples

### Example 1: Burn Warrior Cleaner

```
== DECK CLEANER: Burn Warrior — GT_RANKED FT_STANDARD — 58.5% win rate (42 games)

Cut Candidates (worst first):
—
1. Erupting Volcano: 34% when drawn (12 games) vs 58% baseline → -24% delta
   Likely too slow for your early-game pressure role. You're a tempo deck, not a control one.

2. Rockskipper: 42% when drawn (8 games) vs 58% baseline → -16% delta
   Generates rocks but they're 1-cost — on turn 3+ they're redundant with your burn hand.

3. Precursory Strike: 46% when drawn (6 games) vs 58% baseline → -12% delta
   Conditional draw (needs 5+ cost minion) makes it slow. Only played when you already had a big body.

4. Sanguine Depths: 52% when drawn (7 games) vs 58% baseline → -6% delta
   Location costs a turn to set up damage; you're already damaging with spells/weapons.

5. Shield Block: 68% when drawn (4 games) vs 58% baseline → +10% delta
   KEEP — performing above baseline. Your stabilization is working.

Dead Draws (hand clog):
—
Sanguine Depths: 71% dead draw rate (drawn 7 times, played 2 times)
→ Location setup is clunky mid-game. When you draw it turns 4+, you can't always justify the setup turn.

Rockskipper: 50% dead draw rate (drawn 8 times, played 4 times)
→ Synergy card — it needs specific follow-ups to shine. Often sits in hand.

Suggested Replacements:
—
If you cut -1 Erupting Volcano, -1 Rockskipper:
  Option A: +2 Searing Fissure (1 mana cheaper than Volcano, immediate AoE, gets combo bonus)
  Option B: +1 Searing Fissure +1 Eternal Toil (AoE + draw, fixes your card advantage)

Run: ./hsdecks recommend --collection collection.json --deck-outs "Erupting Volcano,Rockskipper"
     for full scoring from your collection.

Insufficient Data:
—
Bloodmage Thalnos: 1 game recorded
Wisp: 0 games recorded

Play more games before cutting these; they may be meta-dependent tech.
```

### Example 2: Control Mage Cleaner

```
== DECK CLEANER: Control Mage — GT_RANKED FT_STANDARD — 42% win rate (25 games)

Cut Candidates (worst first):
—
1. Flamestrike: 15% when drawn (6 games) vs 42% baseline → -27% delta
   By the time you can cast it (turn 7+), the game is often decided. Opponent has already outpaced you.

2. Frost Nova: 25% when drawn (8 games) vs 42% baseline → -17% delta
   Defensive only; doesn't advance your game plan. Cut for proactive pressure.

3. Arcane Intellect: 38% when drawn (8 games) vs 42% baseline → -4% delta
   Draw is good, but you're a control deck and you're losing to tempo. Draw isn't your problem.

4. Flameburst: 48% when drawn (6 games) vs 42% baseline → +6% delta
   KEEP — performing above baseline. Early removal is what's keeping you in games.

Dead Draws:
—
Flamestrike: 67% dead draw rate (drawn 6 times, played 2 times)
→ A 7+ mana card that costs ~6 turns to play is often a clog by the time you can cast it.

Suggested Replacements:
—
If you cut -1 Flamestrike, -1 Frost Nova:
  Option A: +2 Searing Fissure (cheaper AoE, punishes aggro boards early)
  Option B: +1 Searing Fissure +1 Firewall (early removal + proactive tempo)

Your 42% win rate suggests you're losing to tempo/burn decks. Early removal and proactive plays will help more than late-game swing cards.
```

## Limitations

- **Small sample size noise:** Min_games=5 helps but doesn't eliminate noise. A card with 5 games and 0% win rate might just have had bad luck, not be bad.
- **Matchup-specific bias:** A card can look bad against THIS deck's meta (specific opponents faced) without being bad in general.
- **Dead-draw ambiguity:** High dead_draw_pct doesn't explain WHY (could be correct sequencing that played around the card, not a bad card).
- **Deck synergy:** The skill sees individual card performance, not multi-card synergies. A card might be weak alone but strong with one key card you always have.
- **Meta shift:** Recommendations are only as good as your recent game history. If the meta shifts, old data becomes stale.

## Invoking the Skill

```bash
# Check your recent games:
./hst stats recent --limit 3

# Get cut suggestions for a specific deck:
./hst stats cut --deck "Burn Warrior" --min-games 5

# For a stricter threshold (ignore cards with < 10 games):
./hst stats cut --deck "Burn Warrior" --min-games 10
```

Then ask the skill:

```
"Clean up my Burn Warrior deck. I have 42 games on it and my win rate is sliding.
What should I cut?"
```

The skill will query the tracker database, identify the worst performers, and suggest replacements.

## See Also

- **[hearthstone-deck-recommender](../hearthstone-deck-recommender/)** — what to craft/build (use the results of this skill to inform substitute suggestions)
- **[hearthstone-post-game-coach](../hearthstone-post-game-coach/)** — analyze a single game (this skill aggregates across many games)
- **[hearthstone-tracker](../hearthstone-tracker/)** — game history and stats database
