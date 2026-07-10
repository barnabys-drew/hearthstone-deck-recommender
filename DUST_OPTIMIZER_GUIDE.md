# Hearthstone Dust Optimizer — Guide

Skill: `/hearthstone-dust-optimizer` · Script: `hearthstone-deck-recommender/scripts/optimize_dust.py`

## What it does

Lists every extra card copy beyond the playable maximum (1x Legendary,
2x everything else) and the dust you'd gain. That set is exactly what the
in-game **Mass Disenchant** button clears.

## What it does NOT do (and why)

**It does not delete cards, and nothing external can.** Findings from the
2026-07-09 build session:

- battle.net's website has **no collection or disenchant UI** — we attached
  a browser to the live site and probed for it; it doesn't exist. Any
  "web automation" of disenchanting targets a page that isn't there.
- Disenchanting exists only inside the Hearthstone game client. Automating
  the client (synthetic clicks/input) violates Blizzard's EULA and risks
  account action. Don't.
- The good news: **Mass Disenchant already automates the safe part.**
  Collection → crafting mode (bottom-right toggle) → Mass Disenchant.
  One click claims everything this script flags.

It also does not flag "cards you never play." An earlier version tried,
with a stubbed-out meta-deck check, and recommended disenchanting ~900
legendaries (~360k phantom dust). Cutting non-duplicates is a card-by-card
human decision.

## Workflow

```bash
# 1. Export your collection (HSReplay: hsreplay.net/collection/mine/,
#    DevTools → Network → copy the account_lo= JSON response)

# 2. Preview the dust
python3 hearthstone-deck-recommender/scripts/optimize_dust.py \
  --collection collection.json --view summary

# 3. Optionally save the list
python3 hearthstone-deck-recommender/scripts/optimize_dust.py \
  --collection collection.json --output disenchants.json

# 4. In Hearthstone: Collection → crafting mode → Mass Disenchant
```

Accuracy: counts sum all finishes but dust is estimated at regular rates,
so golden extras are undervalued — the in-game number is ground truth.
Uncraftable sets (Core, Legacy-free, Vanilla) are excluded (0 dust).

## Appendix: WSL → Windows Chrome CDP setup

Built while investigating automation; the disenchant use case is dead, but
this recipe lets Playwright in WSL drive a real logged-in Windows Chrome —
useful for other automations (e.g. statement downloads).

1. **Chrome 136+ ignores `--remote-debugging-port` on the default
   profile** (security change). You must pass a dedicated user-data dir —
   which also means the debug Chrome runs alongside your normal Chrome,
   no need to kill anything:

   ```powershell
   & "C:\Program Files\Google\Chrome\Application\chrome.exe" `
     --remote-debugging-port=9222 `
     --user-data-dir=C:\Users\<you>\chrome-debug-profile
   ```

   (In PowerShell the leading `&` call operator is required.)

2. **WSL mirrored networking needs loopback access** to reach the Windows
   port. In `C:\Users\<you>\.wslconfig`:

   ```ini
   [experimental]
   hostAddressLoopback=true
   ```

   then `wsl --shutdown` and reopen the terminal.

3. **Verify from WSL**, then attach:

   ```bash
   curl -s http://localhost:9222/json/version   # should return Chrome JSON
   ```

   ```python
   from playwright.sync_api import sync_playwright
   p = sync_playwright().start()
   browser = p.chromium.connect_over_cdp("http://localhost:9222")
   page = browser.contexts[0].new_page()
   ```

Log into whatever site you're automating once in the debug profile; the
session persists in `chrome-debug-profile` for future runs.

## See Also

- `/hearthstone-deck-recommender` — pick the next deck to spend dust on
- `.claude/skills/hearthstone-dust-optimizer.md` — skill definition
