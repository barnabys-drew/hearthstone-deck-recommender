const $ = (id) => document.getElementById(id);
const { escapeHtml, isValidCardId, cardRowHtml, isAdviceStale, groupLessons } = window.OverlayLogic;

// Which panel this window shows: advice | deck | opponent | lessons | all (browser mode).
const panel = new URLSearchParams(location.search).get('panel') || 'all';

let config = { overlayDir: '', pollMs: 250, staleAdviceSeconds: 75 };
let mtimes = new Map();
let live = null;
let advice = null;
let lessonsDoc = null;
let lessonStore = null;
let deckSeen = new Map(); // card key -> last seen copies-left, to flash changed rows

// Card art: resolved through the host (Electron disk cache / serve.py cache),
// falling back to the remote tile URL until the cached copy exists.
const ART_URL = (id) => `https://art.hearthstonejson.com/v1/tiles/${encodeURIComponent(id)}.png`;
const artCache = new Map(); // card id -> resolved url
let artRenderQueued = false;

function resolveArt(id) {
  if (artCache.has(id)) return artCache.get(id);
  artCache.set(id, ART_URL(id));
  Promise.resolve(window.overlayAPI.artPath(id)).then((resolved) => {
    if (resolved && resolved !== artCache.get(id)) {
      artCache.set(id, resolved);
      if (!artRenderQueued) {
        artRenderQueued = true;
        setTimeout(() => { artRenderQueued = false; render(); }, 120);
      }
    }
  }).catch(() => {});
  return artCache.get(id);
}

function setHidden(node, hidden) { node.classList.toggle('hidden', hidden); }

function cardRow(card, { left = null, remaining = 0 } = {}) {
  const key = `${card.name}|${card.cost}`;
  const artUrl = card.id && isValidCardId(card.id) ? resolveArt(card.id) : null;
  const { html, copies } = cardRowHtml(card, { left, remaining, prevLeft: deckSeen.get(key), artUrl });
  deckSeen.set(key, copies);
  return html;
}

function renderDeck() {
  if (!live || !live.me) return;
  const remaining = Number(live.me.deck_remaining || 0);
  const deck = (live.me.deck_full && live.me.deck_full.length) ? live.me.deck_full : (live.me.deck_cards_left || []);
  const extras = (live.me.deck_extra || []).filter((c) => c.cost != null);
  $('deck-count').textContent = remaining ? `${remaining} cards` : '';
  $('deck-left').innerHTML = deck.length || extras.length
    ? deck.map((c) => cardRow(c, { left: c.left ?? Number(c.count || 1), remaining })).join('')
      + (extras.length ? `<div class="deck-sep">generated / shuffled</div>${extras.map((c) => cardRow(c, { remaining })).join('')}` : '')
    : '<div class="empty">No deck list yet.</div>';
}

function renderOpponent() {
  if (!live || !live.opp) return;
  $('opp-title').textContent = live.opp.class ? `OPPONENT · ${live.opp.class}` : 'OPPONENT';
  const oppHand = Number(live.opp.hand_hidden || 0) + Number((live.opp.hand || []).length);
  const oppDeck = live.opp.deck_remaining ?? '—';
  const secrets = live.opp.secrets ? ` · ${live.opp.secrets} secrets` : '';
  $('opp-counts').textContent = `${oppHand} in hand · ${oppDeck} in deck${secrets}`;
  const played = (live.opp.played || []).slice().reverse();
  $('opp-played').innerHTML = played.length
    ? played.map((p) => cardRow(p)).join('')
    : '<div class="empty">No reveals yet.</div>';
}

function renderAdvice() {
  const current = advice || {};
  const kind = current.kind || 'idle';
  const isLethal = current.lethal?.is_lethal || kind === 'lethal';
  $('eyebrow').textContent = kind === 'idle' ? 'LIVE COACH' : kind.toUpperCase();
  $('headline').textContent = current.headline || (isLethal ? 'LETHAL' : 'Do this now');
  $('why').textContent = current.why || 'Waiting for the current turn plan.';
  $('turn-pill').textContent = `turn ${live?.turn ?? current.turn ?? '—'}${live ? ` · ${live.whose_turn === 'me' ? 'your turn' : 'opponent'}` : ''}`;

  const lethal = $('lethal');
  if (isLethal) {
    lethal.textContent = current.lethal?.math ? `LETHAL: ${current.lethal.math}` : 'LETHAL — do not trade first.';
  }
  setHidden(lethal, !isLethal);

  $('discover').textContent = current.discover ? `PICK: ${current.discover}` : '';
  setHidden($('discover'), !current.discover);

  const steps = current.steps || [];
  $('steps').innerHTML = steps.map((step) => `<li>${escapeHtml(step)}</li>`).join('');

  const mulligan = current.mulligan || [];
  $('mulligan').innerHTML = mulligan.map((row) => `<div class="mulligan-row"><span class="badge ${row.keep ? 'keep' : 'toss'}">${row.keep ? 'KEEP' : 'TOSS'}</span><div><strong>${escapeHtml(row.card)}</strong><br><span class="empty">${escapeHtml(row.reason || '')}</span></div></div>`).join('');
  setHidden($('mulligan'), !mulligan.length);

  $('warning').textContent = current.warning || '';
  setHidden($('warning'), !current.warning);

  setHidden($('stale'), !isAdviceStale(current, live?.turn, config.staleAdviceSeconds, Date.now() / 1000));
}

function renderLessons() {
  // Live trigger matches first (relevant to the CURRENT board), then general
  // principles, then a few points per deck from the structured store.
  const matched = (live?.lessons_matched || []).map((m) => m.cost ? `${m.lesson} — cost last time: ${m.cost}` : m.lesson);
  const grouped = groupLessons(lessonStore?.lessons || []);
  const row = (rec) => `<div class="lesson">${escapeHtml(rec.lesson)}</div>`;
  const sections = [];
  if (matched.length) {
    sections.push(matched.map((l) => `<div class="lesson matched">${escapeHtml(l)}</div>`).join(''));
  }
  if (grouped.general.length) {
    sections.push(`<div class="lessons-title">General</div>` + grouped.general.map(row).join(''));
  }
  for (const { deck, items } of grouped.decks) {
    sections.push(`<div class="lessons-title">${escapeHtml(deck)}</div>` + items.map(row).join(''));
  }
  $('lessons').innerHTML = sections.length ? sections.join('') : '<div class="empty">No lessons recorded yet.</div>';
}

function render() {
  const app = $('app');
  app.classList.toggle('waiting', !live || !live.me);
  if (panel === 'deck' || panel === 'all') renderDeck();
  if (panel === 'opponent' || panel === 'all') renderOpponent();
  if (panel === 'advice' || panel === 'all') renderAdvice();
  if (panel === 'lessons' || panel === 'all') renderLessons();
}

async function pollFile(fileName) {
  try {
    const result = await window.overlayAPI.readJson(fileName);
    if (mtimes.get(fileName) !== result.mtimeMs) {
      mtimes.set(fileName, result.mtimeMs);
      if (fileName === 'live.json') live = result.data;
      if (fileName === 'advice.json') advice = result.data;
      if (fileName === 'lessons.json') lessonsDoc = result.data;
      if (fileName === 'lesson_store.json') lessonStore = result.data;
      return true;
    }
  } catch (_error) {
    // Files do not exist until hst live / coach_publish creates them.
  }
  return false;
}

// Each panel polls only the files it renders from.
const FILES_BY_PANEL = {
  advice: ['advice.json', 'live.json'],
  deck: ['live.json'],
  opponent: ['live.json'],
  lessons: ['lesson_store.json', 'live.json'],
  all: ['live.json', 'advice.json', 'lessons.json', 'lesson_store.json'],
};

async function tick() {
  const files = FILES_BY_PANEL[panel] || FILES_BY_PANEL.all;
  let changed = false;
  for (const file of files) changed = (await pollFile(file)) || changed;
  if (changed) render();
}

async function boot() {
  document.body.dataset.panel = panel;
  config = await window.overlayAPI.config();
  const dataPath = $('data-path');
  if (dataPath) dataPath.textContent = config.overlayDir;
  window.overlayAPI.onState((state) => {
    for (const node of document.querySelectorAll('.overlay-state')) {
      node.textContent = state.clickThrough ? `click-through · ${Math.round(state.opacity * 100)}%` : `move/resize · ${Math.round(state.opacity * 100)}%`;
    }
    document.body.classList.toggle('movable', !state.clickThrough);
  });
  // Push-first: the main process watches the shared folder and nudges us on
  // writes; the interval is only a fallback (slow in push mode).
  window.overlayAPI.onFileChanged(async (fileName) => {
    if ((FILES_BY_PANEL[panel] || FILES_BY_PANEL.all).includes(fileName)) {
      if (await pollFile(fileName)) render();
    }
  });
  render();
  setInterval(tick, config.push ? 2000 : Number(config.pollMs || 250));
  tick();
}

boot();
