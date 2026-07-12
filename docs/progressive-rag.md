# Progressive RAG: this repo as a learning lab

The live coach's lessons engine is a working retrieval-augmented system — just
not the embeddings-first kind most tutorials teach. This document names what
was built in RAG vocabulary, then lays out five phases that grow it into a
full progressive, cost-conscious RAG stack. Each phase says what it teaches
and maps it to the same pattern in a SOC context: a Tier-1 security-alert
triage agent whose knowledge base of past dispositions improves over time
without runaway cost.

**Thesis: RAG ≠ embeddings.** Retrieval starts with structure. Embeddings are
an escalation tier you adopt when measurement proves cheaper tiers miss —
not the foundation you start from.

## What we already built (named in RAG terms)

| This repo (file) | RAG concept | SOC triage equivalent |
|---|---|---|
| `lesson_store.json` + pydantic `Lesson`/`LessonTrigger` ([`hstracker/lessons.py`](../hearthstone-tracker/hstracker/lessons.py)) | Structured knowledge base with a typed metadata schema | Incident/disposition KB keyed by entities (host, user, hash, ASN) |
| `match_lessons()` — deterministic trigger matching inside `hst live` | **Tier-0 retrieval**: metadata filtering — exact, zero-cost, on the hot path | IOC/entity exact-match lookup at alert ingest |
| Lesson inlining into turn markers, capped at 3 (`live.py`) | Context assembly at decision time, under a budget | Enriching the alert with retrieved priors before the agent reasons |
| Post-game coach writing triggered records (`coach_publish.py --lesson-record`) | Offline ingestion/enrichment pipeline — LLM work stays off the hot path | Post-incident review producing structured dispositions |
| Headline record, newest wins (`headline: true`) | Periodic consolidation / distillation | Weekly playbook or threat-landscape synthesis |
| Retrieval itself never calls an LLM; LLM calls happen at boundaries (post-game, session start) | **The core cost pattern** | The dollar lever at alert volume |

The decision loop this feeds is latency-bound (~15s turn timer), which forced
the same discipline a high-volume alert queue forces: anything on the hot
path must be deterministic and effectively free; anything expensive runs at
boundaries and is cached.

## Phase 1 — Retrieval telemetry + eval harness ✅ BUILT (2026-07-12)

*The part everyone skips, and the part that matters most at work.*

Built (`hstracker/raglog.py`, `hstracker/ragreplay.py`):
- `retrieval_log.jsonl` — one event per your-turn snapshot: stable lesson ids
  (sha1 of normalized text, 12 hex chars), tiers ran, what matched (or that
  nothing did), weak game key (session + game_no) and turn. Events: `corpus`,
  `match`, `outcome`, `ingest` (new lesson recorded), `applied` (coach acked
  using a fired lesson via `coach_publish.py --applied-lesson "#<id>"`).
- Outcome joining — the live loop appends an `outcome` event at game over;
  cross-process `ingest`/`applied` events join by timestamp windows.
- `hst rag-report` — per-lesson firing rate; dead knowledge (records that
  never fire, untriggerable ones flagged); retrieval misses (games with a
  recorded misplay but zero fires — the evidence backlog that justifies or
  kills every later phase); a precision proxy (fired AND applied AND won,
  degrading to fired-AND-won when no applied events exist).
- `hst rag-replay <session-dir>` — runs the current store against historical
  Power.logs offline (reusing `LiveGameTail.snapshot`), deterministic
  `--json` output for diff-based regression tests. Never writes the live log.

First replay over a real session (13 games) already produced gate evidence:
several never-fired lessons and one lesson firing on 43 turns across 10
games — trigger specificity work before any new tier.

Teaches: retrieval evaluation, hit/miss telemetry, offline replay,
knowledge-decay detection.

SOC transfer: measure the KB before buying vector search. Replay historical
alerts through candidate retrieval configs. Find dispositions that never fire
(stale knowledge) and alerts that retrieve nothing (coverage gaps).

## Phase 2 — Tiered retrieval with escalation (lexical tier) 🧪 LAB-BUILT (2026-07-12), live-gated

**Entry gate:** Phase-1 report shows real misses — misplays where a relevant
lesson existed but its exact trigger didn't fire. *Gate not yet satisfied
(telemetry is hours old), so Tier 1 shipped as lab code: it always runs in
`rag-replay`; the live loop runs it only with `HS_RAG_T1=1`.*

Built (`hstracker/lexical.py`):
- Tier 1 runs only when Tier 0 returns nothing: pure-python BM25
  (k1=1.5, b=0.75) of lesson text against snapshot text (card names, rules
  text, flags, opponent class). Gated by score threshold AND ≥2-token
  informative overlap; headline records excluded (already always on the
  panel); trigger-less lessons ARE eligible — that's the tier's point.
- Fuzzy marker label `[T1 fuzzy]` + `#id`, so the coach weighs them below
  exact hits and can still ack with `--applied-lesson`.
- Tier usage feeds the Phase-1 log; `rag-report`/`rag-replay` show a "Tier
  earnings" section (turns each tier ran vs fired).
- Threshold tuned on session `Hearthstone_2026_07_12_04_50_10` (13 games,
  18 t0-miss turns): thresholds 2.0/5.5/6.5/7.5 fired on 18/12/8/5 miss
  turns → `SCORE_THRESHOLD = 7.5` (~28% of misses). Override per run with
  `HS_RAG_T1_MIN`; unthresholded scores via `rag-replay --candidates`.

**Acceptance evidence required to flip the live default ON** (all three):
1. ≥20 real telemetry games showing a miss backlog (`rag-report` misses, or
   dead trigger-less lessons that replay shows t1 firing on those games).
2. Replay over ≥2 sessions: user eyeballs every t1 fire (~70%+ judged
   relevant). First pass on the tuning session was MIXED — e.g. "Race swings
   go FACE, never into Lifesteal" vs Hunter looked right, but "Deny board
   vs Aura Paladin" fired vs Shaman (matchup mismatch) — so the threshold
   or query may need work before the flip. That is the lab doing its job.
3. `--tier0-only` A/B diff stays purely additive (verified once already).
If the evidence never materializes, t1 stays lab-only — also a valid outcome.

Teaches: escalation/fallback retrieval, precision-vs-recall tiering,
confidence labeling, cost gating.

SOC transfer: exact IOC match → keyword/sigma-style match → semantic search,
escalating only on miss, with evidence labeled by retrieval confidence so the
triage agent discounts fuzzier priors.

## Phase 3 — Embedding tier (deferred until data justifies)

**Entry gate:** the Phase-1 report shows misses that Tier 0+1 *cannot* cover
— lessons whose relevance is semantic, not lexical ("don't overextend into
AoE" with no shared card name). If that bucket stays empty, this phase never
gets built. That is itself the lesson: eval-driven adoption.

Build (when gated in):
- Embeddings computed at **write time** — each lesson embedded once when
  recorded — plus once per game (mulligan context), never per turn.
- Tier 2 runs only on Tier 0+1 miss: cosine top-k over the cached vectors.
- Local model (fastembed/ONNX MiniLM; zero per-call cost, keeps the repo's
  no-API property) vs API embeddings (pennies, teaches key/cost management)
  decided at build time with Phase-1 evidence in hand.

Teaches: write-time vs read-time cost asymmetry, embedding caching,
escalation economics — semantics only pays for the misses.

SOC transfer: embed dispositions at write time; embed each alert once at
ingest; only the fraction of alerts structured retrieval can't resolve ever
touches the semantic tier. At 10k alerts/day this is the difference between
a rounding error and a real bill.

## Phase 4 — Consolidation + decay (KB hygiene)

**Entry gate:** the store is big enough to have duplicates and dead weight
(Phase-1 report shows never-fired records or near-identical lessons).

Build:
- Post-game maintenance pass: merge near-duplicate lessons (lexical
  similarity), archive records that haven't fired in N games (decay),
  promote repeat-firers toward the headline.
- Per-lesson stats on the record itself: `times_fired`, `last_fired`,
  win correlation — provenance and confidence travel with the knowledge.

Teaches: memory consolidation, TTL/decay, provenance and confidence scoring,
dedupe.

SOC transfer: disposition dedupe, stale-IOC expiry, promoting recurring
false-positive patterns into suppression rules — with the evidence attached.

## Phase 5 — Context budgeting (progressive assembly)

**Entry gate:** retrieved context regularly exceeds what the decision needs
(more than the cap competes for the slot).

Build:
- An explicit token budget for retrieved context per decision; rank candidates
  by `specificity × recency × confidence` (Phase-4 stats); truncate to budget.
- A/B ranking functions through the Phase-1 replay harness — measure whether
  more context actually improves outcomes, or just costs more.

Teaches: context economics, ranking under a budget, measuring the marginal
value of context.

SOC transfer: a per-alert token budget is the primary cost lever for an LLM
triage agent at volume; ranking evidence under that budget is the craft.

## Standing constraints (apply to every phase)

Not phases of their own — invariants the whole stack must respect, recorded
here so they survive across sessions:

- **Deck tracking must stay accurate with no AI in the loop.** When the coach
  is out of credits (or simply not running), `hst live`/`hst watch` tracking,
  the overlay panels, and game recording must keep working correctly — the
  deterministic layer never depends on the LLM layer.
- **Make the model in use visible.** It should be easy to tell which AI
  model/CLI is currently coaching (e.g. surfaced in the advice payload or a
  panel footer), so behavior differences and credit burn are attributable.
- **Log every game for RAG, not just coached ones.** Telemetry and game
  capture should cover all games played — including sessions where nobody is
  actively "playing to learn" — so the eval corpus grows passively. If the
  live loop isn't running, backfill (`hst backfill`) plus replay
  (`hst rag-replay`) should be able to reconstruct the missing telemetry.

## Build order and the meta-lesson

Phase 1 first, always. Every later phase has an entry gate stated in terms of
Phase-1 evidence. Nothing gets built because it's the fashionable
architecture; everything gets built because the telemetry showed a gap it
closes. Carrying that discipline — *instrument retrieval before escalating
it* — into the work project is the whole point of this lab.
