# Hearthstone Live Coach

Real-time in-game strategic advice from the official Hearthstone game logs. Coach the user turn-by-turn during an active match by tailing the `Power.log` and parsing complete game state snapshots.

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ Hearthstone Client (Game)                                       │
│ Writes to: Power.log, Decks.log every turn                      │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 │ (packets: entity creation, tag changes, blocks)
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ hst live (FileTail + LiveGameTail)                              │
│ • Polls Power.log incrementally (offset tracking)               │
│ • Buffers only current game (resets on CREATE_GAME)             │
│ • Detects turn boundaries (TURN tag change)                     │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 │ (fresh LogParser per poll)
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ hslog (GameState parser)                                        │
│ • Rebuilds game tree from packet stream                         │
│ • Applies tag changes, entity creations, zone transitions       │
│ • Safe per-game isolation (fresh parser each poll)              │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 │ (game tree with up-to-date entity state)
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ snapshot_from_tree() — Live Snapshot Builder                   │
│ • Exports entity tree via EntityTreeExporter                    │
│ • Walks all entities by CONTROLLER + ZONE                       │
│ • Extracts: hand (with card type/text), board (flags), weapons  │
│ • Deck remaining (count), deck outs (cards not yet drawn)       │
│ • Opponent play history (what they've cast so far)              │
│ • Writes atomic JSON to live.json                               │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 │ (JSON: hand[], board[], hp, armor, mana, etc.)
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ Monitor + Print (hst live output)                               │
│ • Stdout: "== TURN 5 (your turn) — ME 28hp 5/5 mana vs OPP 14hp"
│ • Fired on: mulligan, your turn, game over, errors              │
│ • Stable path: ~/.local/share/hearthstone-tracker/live.json     │
└────────────────┬────────────────────────────────────────────────┘
                 │
                 │ (marker + JSON snapshot)
                 │
                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ hearthstone-live-coach SKILL.md                                 │
│ • Monitor fires "== TURN" on stdout → Agent resume              │
│ • Read live.json fresh (card type/text, not from memory)        │
│ • Follow checklist: damage both ways, respect flags, count outs  │
│ • Output: 1-2 why sentences + numbered move sequence            │
│ • Known traps: exhausted ≠ locked, discovers lag, deathrattle lag
└─────────────────────────────────────────────────────────────────┘
```

## Workflow: From Game to Advice

1. **Game starts.** Hearthstone writes to Power.log (packets arriving live).
2. **`hst live` polls** (default: every 3s). Detects new lines, buffers current game only.
3. **hslog parses buffer.** Fresh `LogParser()` each poll (safety: multi-game logs would corrupt a single parser).
4. **snapshot_from_tree() exports** the in-progress game state:
   - Entity tree → hand (card name, type, cost, rules text), board (atk/health/flags), weapons
   - Deck outs: decklist minus cards you've drawn (hunts in remaining deck)
   - Opponent history: every card they've cast so far
5. **live.json written atomically** (~/.local/share/hearthstone-tracker/live.json).
6. **Stdout marker fires:** `== TURN 5 (your turn) —` (or `== MULLIGAN`, `== GAME OVER`).
7. **Agent sees marker**, reads snapshot fresh, follows the skill checklist:
   - Count incoming damage (exhausted minions WILL attack next turn)
   - Count outgoing damage (Torch needs damaged targets, Erupting Volcano is random, etc.)
   - Respect card type (SPELL vs MINION vs LOCATION)
   - Use card text from snapshot, never from memory
8. **Advice:** why sentence + numbered moves. On lethal turns: **LETHAL** + arithmetic first.

## Known Limitations

### 1. **Discover and Deathrattle Lag (1 turn)**
- When you select from a Discover, the chosen card appears in your hand in the snapshot next turn (not the turn it was picked).
- Deathrattles resolve during death; by next snapshot they're done.
- **Workaround:** If your hand diverges from the snapshot by a discovered card, next turn's advice will be fully synced.

### 2. **Exhausted ≠ Locked Down**
- "Exhausted" means "can't act this turn". Next turn, exhausted minions reset and attack freely.
- **Gotcha (cost a game):** A 14/8 exhausted Ebyssian attacked twice (28 damage) the next turn.
- **Fix:** When counting incoming damage for stabilization, treat exhausted minions as full threats.

### 3. **Only Legal-Information Coaching**
- Opponent's hand is hidden-card count only (no cheating). What the client doesn't know, we can't advise around.
- No hand reconstruction from play patterns.

### 4. **Card Text Over Memory**
- Card mechanics change, sets rotate, and model memory drifts. Every card in the snapshot carries its current rules text.
- **Rule:** Always read `type` and `text` fields from the snapshot, never from model knowledge.

## Setup & Usage

### Prerequisites
- Hearthstone running with Power logging enabled (`log.config`: `[Power] FilePrinting=True, Verbose=True`)
- `hearthstone-tracker` CLI installed and in PATH
- This skill (symlinked into `~/.claude/skills/hearthstone-live-coach`)

### Running the Advice Loop

1. **Start the live tail** in the background:
   ```bash
   hst live
   ```
   Output will print `== MULLIGAN`, `== TURN ...`, `== GAME OVER` markers.

2. **In Claude Code**, watch for these markers:
   - Set up a Monitor on stdout: `^== TURN.*your turn|^== MULLIGAN|^== GAME OVER`
   - On each marker, Claude reads `~/.local/share/hearthstone-tracker/live.json` and advises.

3. **Play the game.** Advice arrives turn-by-turn.

### Scope
- **Constructed only.** Battlegrounds shop/combat is future work (snapshot is turn-end focused; shop is mid-turn).
- **Your turn only.** Advice fires on `== TURN.*your turn` and `== MULLIGAN`. Opponent turns are silent.

## The Checklist (From the Skill)

Before advising, verify:

1. **Fresh snapshot.** Read `live.json` from disk, never assume prior state.
2. **Card type/text, not memory.** SPELL needs targets, LOCATION has cooldown/charges, MINION is a body, WEAPON requires hero swing.
3. **Count damage both ways:**
   - Incoming: sum opponent board ATK + weapon. Treat exhausted minions as full threats (they attack next turn). Multiply windfury ×2.
   - Outgoing: your board + burn in hand. Check lethal every turn from ~turn 5 on.
4. **Respect flags:** `taunt` blocks attacks, `divine shield` pops first, `damaged` enables Torch-like effects, `exhausted` ≠ locked.
5. **Deck outs:** `deck_cards_left` shows remaining copy counts. "3 of 8 left = Torch" changes the race math.
6. **Opponent history:** `played` list shows every cast card. If removal is spent, commit; if not, hold.
7. **Deathrattle caution:** Eggs/tokens want to die; don't pop them without reason. Deathrattle payoffs change threat math.

## Output Format (Strict — You're on the Game's Turn Timer)

- **One why-paragraph.** 1–2 sentences of reasoning (threat math, race, stabilization).
- **Numbered moves.** One action per line, targets named, triggers noted (`→ draw`, `→ summon`).
- **Warnings as one bold line.** Not a paragraph; the user reads these in seconds.
- **Lethal turns:** Open with **LETHAL** followed by arithmetic (`**LETHAL: 5+3+2 = 10 ≥ their 10**`). Then numbered moves, attacks BEFORE spells (so burn can re-aim if a deathrattle changes the math mid-turn).
- **Mulligan:** Keep/toss per card with a few words reasoning each, before the user locks in.
- **Game over:** Post-mortem is welcome — this is the only time longer analysis is appropriate.

## Example: Turn Advice

```
They've emptied their hand and their 12-damage board is tapped. You're at 22 
HP with two Fireballs and a 4/3 on board. Race math: 4 + 8 + 8 = 20 < 22. 
Not quite lethal, but close — one more card draw and you're there.

1. Fireball their largest minion (8 damage)
2. Fireball face (8 damage) — drops them to 16
3. Swing with your 4/3 (4 damage)
4. Pass with Firewall in hand for next turn

You've dealt 12, need 6 more. If you top-deck a Bolt, you win next turn. If 
not, their top-deck matters.
```

## Example: Lethal Turn

```
**LETHAL: 12 + 8 + 1 = 21 ≥ their 21. Do not trade board, do not pass.**

1. Fireball their 5-health minion (dies, clears taunt)
2. Fireball face (8 damage) → 13 HP
3. Weapon swing + hero power (1 damage) → 12 HP
4. Second Fireball face (8 damage) → 4 HP
5. Attack face with your 4/3 board (4 damage) → 0 HP. Dead.

Do NOT attack their minions first — that wastes the 4/3 and drops you below 21.
```

## Testing & Iteration

Real-game validation is critical. Each coached game surfaces edge cases:
- Game 1–3: Happy path (turns, mulligan, basic trades)
- Game 4: Discovered card lag (hand diverges temporarily; next snapshot syncs)
- Game 5+: Lethal math edge cases, deathrattle timing, exhausted minion recovery

Found issues become traps in the skill's "Known traps" section (e.g., "Exhausted minions will attack next turn").

## Files

- **SKILL.md:** This skill file (register in `~/.claude/skills/`).
- **../hearthstone-tracker/hstracker/live.py:** Snapshot builder (`snapshot_from_tree`, `format_snapshot`).
- **../hearthstone-tracker/hstracker/cli.py:** `cmd_live` command (polling, JSON writes).
- **../hearthstone-tracker/README.md:** Tracker docs (backfill, watch, stats, live).
