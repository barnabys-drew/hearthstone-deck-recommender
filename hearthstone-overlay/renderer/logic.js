// Pure, DOM-free logic shared by the renderer (browser global) and the
// node:test suite (CommonJS). No Electron, no window, no fetch in here.
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.OverlayLogic = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  const CARD_ID_RE = /^[A-Za-z0-9_.-]+$/;

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  }

  function isValidCardId(id) {
    return CARD_ID_RE.test(String(id));
  }

  // HTML for one deck/opponent row. Pure: previous count and the resolved
  // art URL are passed in; the caller owns state and async art resolution.
  function cardRowHtml(card, { left = null, remaining = 0, prevLeft, artUrl = null } = {}) {
    const copies = Number(left ?? card.count ?? 1);
    const gone = copies === 0;
    const flash = prevLeft !== undefined && prevLeft !== copies;
    const odds = !gone && remaining ? `${Math.round((copies / remaining) * 100)}%` : '';
    const art = (artUrl && card.id && isValidCardId(card.id))
      ? ` style="background-image: linear-gradient(90deg, rgba(24,25,30,.96) 38%, rgba(24,25,30,.55) 70%, rgba(24,25,30,.25)), url('${artUrl}')"`
      : '';
    const html = `<div class="deck-card${artUrl && art ? ' art' : ''}${gone ? ' gone' : ''}${flash ? ' flash' : ''}"${art}>`
      + `<span class="cost">${escapeHtml(card.cost ?? '?')}</span>`
      + `<span class="deck-name">${escapeHtml(card.name)}</span>`
      + `${copies > 1 ? `<span class="copies">×${copies}</span>` : ''}`
      + `<span class="odds">${odds}</span></div>`;
    return { html, copies };
  }

  // idle/gameover cards sit on screen indefinitely by design — never stale.
  function isAdviceStale(advice, liveTurn, staleSeconds, nowSeconds) {
    const kind = advice?.kind || 'idle';
    if (kind === 'idle' || kind === 'gameover') return false;
    const age = advice?.ts ? nowSeconds - Number(advice.ts) : Infinity;
    const wrongTurn = Boolean(liveTurn) && advice?.turn != null
      && Number(advice.turn) !== Number(liveTurn);
    return wrongTurn || age > Number(staleSeconds || 75);
  }

  // Lessons panel structure: general principles first (no deck), then a few
  // points per deck, newest first, capped so the panel stays scannable.
  function groupLessons(records, { perGroup = 4 } = {}) {
    const general = [];
    const byDeck = new Map();
    for (const rec of records || []) {
      if (!rec || !rec.lesson) continue;
      const deck = (rec.deck || '').trim();
      if (!deck) {
        general.push(rec);
      } else {
        if (!byDeck.has(deck)) byDeck.set(deck, []);
        byDeck.get(deck).push(rec);
      }
    }
    return {
      general: general.slice(0, perGroup),
      decks: [...byDeck.entries()].map(([deck, items]) => ({ deck, items: items.slice(0, perGroup) })),
    };
  }

  // Deep-merge saved config over defaults, per-panel and per-hotkey, so a
  // partial config.json never loses fields added in newer versions.
  function mergeConfig(defaults, saved, panels) {
    const cfg = { ...defaults, ...(saved || {}) };
    cfg.windows = { ...defaults.windows };
    for (const name of panels) {
      cfg.windows[name] = { ...defaults.windows[name], ...(((saved || {}).windows || {})[name] || {}) };
    }
    cfg.hotkeys = { ...defaults.hotkeys, ...((saved || {}).hotkeys || {}) };
    return cfg;
  }

  return { escapeHtml, isValidCardId, cardRowHtml, isAdviceStale, mergeConfig, groupLessons };
});
