// ----------------------------------------------------------------------
// UI_TOKEN handoff — if the URL carries "#token=<value>" (share-friendly
// onboarding), stash it in localStorage and clean the fragment so the
// token doesn't linger in browser history or referrers.
// ----------------------------------------------------------------------
(function () {
  try {
    const m = (location.hash || '').match(/(?:^#|&)token=([^&]+)/);
    if (m) {
      localStorage.setItem('ios-ui-token', decodeURIComponent(m[1]));
      history.replaceState(null, '', location.pathname + location.search);
    }
  } catch (e) {}
})();

// ----------------------------------------------------------------------
// Tiny API wrapper + UI helpers
// ----------------------------------------------------------------------
async function api(path, opts = {}) {
  const init = { method: opts.method || 'GET', headers: {} };
  if (init.method !== 'GET') {
    // CSRF: custom header makes same-origin XHR work but blocks any
    // cross-origin attacker (they can't set custom headers without a
    // CORS preflight, which the server never allows).
    init.headers['X-UI'] = '1';
  }
  // Optional shared-secret token — stash via DevTools if UI_TOKEN is set
  // server-side: localStorage.setItem('ios-ui-token', '<value>').
  let token = null;
  try { token = localStorage.getItem('ios-ui-token'); } catch (e) {}
  if (token) init.headers['X-UI-Token'] = token;

  if (opts.body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  }
  const r = await fetch(path, init);
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = { raw: text }; }
  if (!r.ok) {
    const msg = (data && (data.detail || data.error)) || `HTTP ${r.status}`;
    throw new Error(msg);
  }
  return data;
}

const $ = (id) => document.getElementById(id);
const toastEl = $('toast');
let toastTimer = null;

// Error-hint table — pattern → actionable advice. The automation layer
// produces a lot of opaque failure modes (paper-trading disconnects,
// session modals, login expiries); surface the fix, not just the symptom.
const _ERROR_HINTS = [
  [/broker picker|Paper Trading isn't connected|not paper trading/i,
    'Reconnect Paper Trading: `.venv/bin/python activate_paper.py`'],
  [/not logged in|sessionid|NotLoggedInError/i,
    'Sign in again: `.venv/bin/python login.py`'],
  [/Session disconnected|session_modal/i,
    'Dismiss the TV reconnect modal: `tv chart reconnect`'],
  [/LimitViolationError/i,
    'Edit `tv_automation/limits.yaml` to adjust allowlist / caps.'],
  [/ChartNotReadyError|canvas.*visible/i,
    'Chart still loading — retry in a few seconds, or verify the TV tab is open.'],
  [/CSRF/i,
    'Hard-refresh the page (Cmd+Shift+R) — the client is missing the X-UI header.'],
  [/auth: bad or missing X-UI-Token/i,
    'UI_TOKEN is set server-side. Stash via DevTools: localStorage.setItem("ios-ui-token", "<value>")'],
];
function _withHint(msg) {
  for (const [re, hint] of _ERROR_HINTS) {
    if (re.test(msg)) return { msg, hint };
  }
  return { msg, hint: null };
}

function toast(msg, kind = 'ok') {
  const { hint } = kind === 'err' ? _withHint(msg) : { hint: null };
  toastEl.innerHTML = hint
    ? `<div>${escapeHtml(msg)}</div><div class="muted" style="margin-top: 4px; font-size: 12px;">→ ${escapeHtml(hint)}</div>`
    : escapeHtml(msg);
  toastEl.className = `toast ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.add('hidden'), hint ? 7000 : 3500);
}

function setBusy(btn, busy, originalText) {
  if (busy) {
    btn.dataset.origText = btn.innerHTML;
    btn.innerHTML = '<span class="spinner"></span>';
    btn.disabled = true;
  } else {
    btn.innerHTML = originalText || btn.dataset.origText || btn.innerHTML;
    btn.disabled = false;
  }
}

// ----------------------------------------------------------------------
// Theme (dark ↔ light) — persisted in localStorage
// ----------------------------------------------------------------------
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  const btn = $('theme-toggle');
  if (btn) btn.textContent = t === 'light' ? '☾' : '☀';
  // ☾ (moon) = "switch to dark"; ☀ (sun) = "switch to light". Icon shows
  // the *destination* of a click, not the current state.
  // Keep the iOS status-bar color in sync with the chosen theme. Safari
  // reads <meta name="theme-color"> whenever it changes — this is what
  // makes the native status-bar backdrop match our sidebar on iPhone.
  const meta = document.getElementById('theme-color-meta');
  if (meta) meta.setAttribute('content', t === 'light' ? '#ffffff' : '#0d1117');
}
$('theme-toggle').addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = cur === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  try { localStorage.setItem('ios-theme', next); } catch (e) {}
});
// applyTheme(…) was called synchronously in <head> below to avoid a
// theme-flash on first paint; here we just sync the button icon to the
// already-applied class.
applyTheme(document.documentElement.getAttribute('data-theme') || 'dark');

// ----------------------------------------------------------------------
// Sidebar collapse (mobile) — show/hide the tabs + status strip. Desktop
// ignores the state via CSS, so stored "collapsed" never breaks desktop.
// ----------------------------------------------------------------------
const _sidebar = document.querySelector('.sidebar');
const _sidebarToggle = $('sidebar-toggle');
const _mobileMQ = window.matchMedia('(max-width: 768px)');

function applySidebarCollapsed(collapsed) {
  _sidebar.classList.toggle('collapsed', collapsed);
  // Icon shows the destination of a tap (same convention as theme toggle).
  _sidebarToggle.textContent = collapsed ? '☰' : '✕';
  _sidebarToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
}

try {
  applySidebarCollapsed(localStorage.getItem('ios-sidebar-collapsed') === '1');
} catch (e) {
  applySidebarCollapsed(false);
}

_sidebarToggle.addEventListener('click', () => {
  const next = !_sidebar.classList.contains('collapsed');
  applySidebarCollapsed(next);
  try { localStorage.setItem('ios-sidebar-collapsed', next ? '1' : '0'); } catch (e) {}
});

// ----------------------------------------------------------------------
// Tab switching
// ----------------------------------------------------------------------
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.nav-item').forEach(x => x.classList.toggle('active', x === btn));
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('hidden', t.id !== `tab-${tab}`));
    // Mobile: auto-collapse so the user sees content after picking a tab.
    if (_mobileMQ.matches) {
      applySidebarCollapsed(true);
      try { localStorage.setItem('ios-sidebar-collapsed', '1'); } catch (e) {}
    }
    // Tab-specific on-enter hooks
    if (tab === 'audit') startAuditPoll(); else stopAuditPoll();
    if (tab === 'trade') { startPositionsPoll(); refreshChartMeta(); refreshSessionStrip(); } else stopPositionsPoll();
    if (tab === 'watchlist') loadWatchlist();
    if (tab === 'alerts') loadAlerts();
    if (tab === 'journal') loadJournal();
  });
});

// ----------------------------------------------------------------------
// Health
// ----------------------------------------------------------------------
// Sidebar dot reflects both UI-server and browser CDP health.
//   green  = UI server up AND browser attachable
//   yellow = UI server up, browser not reachable (CDP down / Chrome killed)
//   red    = UI server down
async function checkHealth() {
  try {
    await api('/api/health');
    // Server is up — now check browser (cached server-side to 30s).
    let browserOk = true, browserErr = null;
    try {
      const b = await api('/api/health/browser');
      browserOk = b.ok !== false;
      browserErr = b.err;
    } catch (e) { /* browser probe itself failed — treat as degraded */
      browserOk = false; browserErr = e.message;
    }
    $('health-dot').className = browserOk ? 'status-dot ok' : 'status-dot warn';
    $('health-text').textContent = browserOk ? 'connected' : 'browser offline';
    $('health-text').title = browserErr || '';
  } catch (e) {
    $('health-dot').className = 'status-dot err';
    $('health-text').textContent = 'offline';
    $('health-text').title = e.message || '';
  }
}
setInterval(checkHealth, 15000);
checkHealth();

// ----------------------------------------------------------------------
// Custom combobox — input with clickable ▾ dropdown backed by the watchlist.
// Used for both the Chart and Trade symbol fields. Plain <datalist> was
// invisible in Chrome without an affordance arrow, and filtered by prefix
// only, so typing a bare ticker against exchange-prefixed options showed
// nothing. This is a small, purpose-built combo.
// ----------------------------------------------------------------------
const _combos = {};  // inputId → { setSymbols(list) }

function setupCombo(inputId) {
  const input = $(inputId);
  const arrow = document.querySelector(`[data-combo-target="${inputId}"]`);
  const menu = document.querySelector(`[data-combo-for="${inputId}"]`);
  if (!input || !arrow || !menu) return null;

  let symbols = [];   // [{symbol, exchange, active}]
  let activeIdx = -1;

  function matches(filter) {
    const f = (filter || '').toLowerCase().trim();
    if (!f) return symbols;
    return symbols.filter(s =>
      s.symbol.toLowerCase().includes(f) ||
      (s.exchange || '').toLowerCase().includes(f)
    );
  }

  function render(filter) {
    const list = matches(filter);
    activeIdx = list.length ? 0 : -1;
    if (!list.length) {
      menu.innerHTML = symbols.length
        ? '<div class="combo-option empty">No matches</div>'
        : '<div class="combo-option empty">Watchlist not loaded</div>';
      return list;
    }
    menu.innerHTML = list.map((s, i) => `
      <div class="combo-option${i === 0 ? ' active' : ''}" data-val="${escapeHtml(s.symbol)}" data-idx="${i}">
        <span class="sym">${escapeHtml(s.symbol)}${s.active ? ' <span class="side-pill long" style="margin-left: 4px; padding: 1px 6px; font-size: 10px;">active</span>' : ''}</span>
        <span class="exch">${escapeHtml(s.exchange || '')}</span>
      </div>
    `).join('');
    return list;
  }

  function open() { menu.classList.remove('hidden'); }
  function close() { menu.classList.add('hidden'); activeIdx = -1; }
  function isOpen() { return !menu.classList.contains('hidden'); }

  function pickByIndex(i) {
    const list = matches(input.value);
    if (i < 0 || i >= list.length) return;
    input.value = list[i].symbol;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    close();
    input.focus();
  }

  arrow.addEventListener('click', (e) => {
    e.preventDefault(); e.stopPropagation();
    if (isOpen()) { close(); return; }
    render('');  // show full list when opened via arrow
    open();
    input.focus();
  });

  input.addEventListener('input', () => { render(input.value); open(); });
  input.addEventListener('focus', () => { if (symbols.length) { render(input.value); open(); } });
  input.addEventListener('keydown', (e) => {
    if (!isOpen() && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      render(input.value); open(); e.preventDefault(); return;
    }
    if (!isOpen()) return;
    const opts = menu.querySelectorAll('.combo-option[data-val]');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      activeIdx = Math.min(activeIdx + 1, opts.length - 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      activeIdx = Math.max(activeIdx - 1, 0);
    } else if (e.key === 'Enter') {
      if (activeIdx >= 0) { e.preventDefault(); pickByIndex(activeIdx); }
      return;
    } else if (e.key === 'Escape') {
      close(); return;
    } else {
      return;
    }
    opts.forEach((o, i) => o.classList.toggle('active', i === activeIdx));
    if (opts[activeIdx]) opts[activeIdx].scrollIntoView({ block: 'nearest' });
  });

  menu.addEventListener('mousedown', (e) => {
    // mousedown (not click) — otherwise input blur fires first, closing the menu.
    const opt = e.target.closest('.combo-option[data-val]');
    if (!opt) return;
    e.preventDefault();
    input.value = opt.dataset.val;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    close();
    input.focus();
  });

  document.addEventListener('click', (e) => {
    if (!menu.contains(e.target) && e.target !== arrow && e.target !== input &&
        !arrow.contains(e.target)) {
      close();
    }
  });

  const api = {
    setSymbols(list) {
      symbols = list || [];
      if (isOpen()) render(input.value);
    },
  };
  _combos[inputId] = api;
  return api;
}

async function populateSymbolCombos(preFetched) {
  try {
    const r = preFetched || await api('/api/watchlist');
    const list = (r.contents?.symbols || []).map(s => ({
      symbol: s.symbol,
      exchange: s.exchange || '',
      active: !!s.active,
    }));
    Object.values(_combos).forEach(c => c.setSymbols(list));
  } catch (e) {
    // Silent — combo shows "Watchlist not loaded" until watchlist tab is visited.
  }
}

// ----------------------------------------------------------------------
// Trade deck — unified chart + order entry.
//
// One symbol field drives the live TradingView chart AND the trade panel.
// Picking from the combo or pressing Enter commits the symbol, and we
// auto-capture so the UI screenshot never goes stale relative to the
// live chart. Timeframe pills do the same.
//
// The position-context strip surfaces any open position in the selected
// symbol right above the quick-trade bar — the highest-value piece of
// info for a day trader about to fire another order in a name they're
// already in.
// ----------------------------------------------------------------------
let _currentChartSymbol = '';

// TradingView's URL-param interval format → our friendly pill format.
// Kept in sync with _TIMEFRAME_MAP in tv_automation/chart.py. Without
// this reverse map the pill bar drifts from the actual chart on every
// intraday TF (pill data-tf="5m" vs meta.interval="5"), which in turn
// makes Analyze run on whatever pill stayed stuck-active (usually 1D).
const TV_INTERVAL_TO_PILL = {
  '30S': '30s', '45S': '45s',
  '1': '1m', '2': '2m', '3': '3m', '5': '5m', '15': '15m', '30': '30m',
  '60': '1h', '120': '2h', '240': '4h',
  'D': '1D', 'W': '1W', 'M': '1M',
};

function intervalToPill(iv) {
  if (!iv) return null;
  return TV_INTERVAL_TO_PILL[iv] || iv;  // pass-through if already friendly
}

function renderChartMeta(meta) {
  const fullSym = meta.symbol || '';
  const idx = fullSym.indexOf(':');
  const sym = idx < 0 ? fullSym : fullSym.slice(idx + 1);
  const exch = idx < 0 ? '' : fullSym.slice(0, idx);
  const pillTf = intervalToPill(meta.interval);
  const parts = [];
  parts.push(`<span class="sym">${escapeHtml(sym || '—')}</span>`);
  if (exch) parts.push(`<span class="sep">·</span><span>${escapeHtml(exch)}</span>`);
  parts.push(`<span class="sep">·</span><span>${escapeHtml(pillTf || meta.interval || '—')}</span>`);
  if (meta.title) parts.push(`<span class="sep">·</span><span>${escapeHtml(meta.title)}</span>`);
  $('trade-chart-meta').innerHTML = parts.join('');
  if (pillTf) {
    document.querySelectorAll('#trade-tf-bar .tf-pill').forEach(p => {
      p.classList.toggle('active', p.dataset.tf === pillTf);
    });
  }
  _currentChartSymbol = fullSym || _currentChartSymbol;
  refreshPositionContext();
}

async function refreshChartMeta() {
  try {
    const meta = await api('/api/chart/metadata');
    renderChartMeta(meta);
  } catch (e) { /* silent — fires on initial load when browser may be offline */ }
}

// Position context — match chart symbol against any open position and
// render a compact strip above the quick-trade bar. Symbols from TV
// positions come exchange-prefixed ("CME_MINI:MNQ1!"); chart symbols may
// or may not be. Compare on the bare ticker to handle both shapes.
function refreshPositionContext() {
  const card = $('position-context-card');
  const ctx = $('position-context');
  const chartSym = _currentChartSymbol || $('trade-symbol').value.trim();
  const bare = s => {
    const c = String(s || '').replace(/\s*\n\s*/g, ' ').trim();
    const i = c.indexOf(':');
    return i < 0 ? c : c.slice(i + 1);
  };
  const target = bare(chartSym);
  if (!target || !_lastPositions.length) { card.classList.add('hidden'); return; }
  const match = _lastPositions.find(p => bare(p.symbol) === target);
  if (!match) { card.classList.add('hidden'); return; }

  const clean = v => String(v ?? '').replace(/\s*\n\s*/g, ' ').trim();
  const isNeg = s => /^[−-]/.test(s);
  const side = clean(match.side);
  const sideCls = side.toLowerCase() === 'short' ? 'short' : 'long';
  const pl = clean(match.pl).replace(/\s*USD$/, '');
  const plPct = clean(match.plPercent);
  const plCls = pl ? (isNeg(pl) ? 'pnl-neg' : 'pnl-pos') : '';
  ctx.innerHTML = `
    <span class="position-context__label">Current</span>
    <span class="side-pill ${sideCls}">${escapeHtml(side)}</span>
    <span class="position-context__qty">${escapeHtml(clean(match.qty))}</span>
    <span class="position-context__price">@ ${escapeHtml(clean(match.avgPrice))}</span>
    <span class="position-context__price muted">last ${escapeHtml(clean(match.lastPrice))}</span>
    <span class="position-context__pnl ${plCls}">${escapeHtml(pl)}${plPct ? ` (${escapeHtml(plPct)})` : ''}</span>
    <span class="position-context__actions">
      <button class="danger icon-btn" data-close="${escapeHtml(target)}">Close</button>
    </span>`;
  ctx.querySelector('[data-close]').addEventListener('click', async (e) => {
    const sym = e.currentTarget.dataset.close;
    if (!confirm(`Close position on ${sym}?`)) return;
    setBusy(e.currentTarget, true);
    try {
      await api('/api/trade/close', { method: 'POST', body: { symbol: sym } });
      toast(`closed ${sym}`);
      loadPositions();
    } catch (err) {
      toast(`close ${sym}: ${err.message}`, 'err');
      setBusy(e.currentTarget, false, 'Close');
    }
  });
  card.classList.remove('hidden');
}

async function captureChart() {
  const btn = $('trade-capture');
  setBusy(btn, true);
  try {
    const r = await api('/api/chart/screenshot', { method: 'POST', body: { area: 'chart' } });
    const src = r.data_url || r.url;
    const file = (r.path || '').split('/').pop();
    $('trade-chart-shot').innerHTML = `
      <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px; font-size: 12px;">
        <span class="badge ${r.fell_back ? 'yellow' : ''}">${escapeHtml(r.area)}${r.fell_back ? ' · fallback' : ''}</span>
        <span class="muted mono" style="margin-left: auto; font-size: 11px;" title="${escapeHtml(r.path)}">${escapeHtml(file)}</span>
      </div>
      <img class="screenshot" src="${src}" alt="chart screenshot" />`;
    renderChartMeta({ symbol: r.symbol, interval: r.interval });
  } catch (e) { toast(`screenshot: ${e.message}`, 'err'); }
  finally { setBusy(btn, false, 'Capture'); }
}

// commitSymbol — called when user picks from combo, hits Enter, or clicks
// a timeframe pill. Sets the live TV chart, then auto-captures so the UI
// screenshot matches the new state. Toast on failure only.
async function commitSymbol(symbol, interval) {
  if (!symbol) return toast('symbol required', 'err');
  try {
    const meta = await api('/api/chart/set-symbol', { method: 'POST', body: { symbol, interval: interval || null } });
    renderChartMeta(meta);
    toast(`set to ${meta.symbol} ${meta.interval}`);
    captureChart();
  } catch (e) { toast(`set-symbol: ${e.message}`, 'err'); }
}

$('trade-capture').addEventListener('click', captureChart);

// Symbol combo: picking from dropdown dispatches 'change' (see setupCombo).
// Typing + Enter commits as well. Blur doesn't commit — prevents accidental
// chart switches from tabbing through the form.
$('trade-symbol').addEventListener('change', () => {
  const sym = $('trade-symbol').value.trim();
  const tf = document.querySelector('#trade-tf-bar .tf-pill.active')?.dataset.tf || null;
  commitSymbol(sym, tf);
});
$('trade-symbol').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    const sym = $('trade-symbol').value.trim();
    const tf = document.querySelector('#trade-tf-bar .tf-pill.active')?.dataset.tf || null;
    commitSymbol(sym, tf);
  }
});

// Timeframe pills — immediate visual update then apply + capture.
document.querySelectorAll('#trade-tf-bar .tf-pill').forEach(pill => {
  pill.addEventListener('click', () => {
    const tf = pill.dataset.tf;
    const sym = $('trade-symbol').value.trim();
    document.querySelectorAll('#trade-tf-bar .tf-pill').forEach(p => p.classList.toggle('active', p === pill));
    commitSymbol(sym, tf);
  });
});

// ----------------------------------------------------------------------
// Single-timeframe analysis
//
// Captures the chart at the selected timeframe, sends one vision-LLM
// turn, then renders a Long/Short/Skip signal + saved pine script.
// Task-based: POST returns a task_id, we poll /api/analyze/{task_id}
// every 1.5s while listening to the audit stream for capture/LLM phases.
// ----------------------------------------------------------------------
let analyzeCurrent = null;  // {task_id, request_id, pollTimer}
let _analyzeStartAt = 0;
let _analyzeElapsedTimer = null;

function startElapsedTicker() {
  _analyzeStartAt = Date.now();
  stopElapsedTicker();
  _analyzeElapsedTimer = setInterval(() => {
    const el = $('analyze-progress-elapsed');
    if (!el) return;
    const s = Math.round((Date.now() - _analyzeStartAt) / 1000);
    el.textContent = s < 60 ? `${s}s` : `${Math.floor(s/60)}m ${s%60}s`;
  }, 500);
}

function stopElapsedTicker() {
  if (_analyzeElapsedTimer) {
    clearInterval(_analyzeElapsedTimer);
    _analyzeElapsedTimer = null;
  }
}

// setAnalyzeProgress — phase = top-line status, detail = supporting line,
// pct = 0..100 for the bar (pass null for the LLM "thinking" shimmer).
function setAnalyzeProgress(phase, detail, pct) {
  $('analyze-progress').classList.remove('hidden');
  $('analyze-progress-phase').textContent = phase;
  $('analyze-progress-detail').textContent = detail || '';
  const bar = document.querySelector('.analyze-progress-bar');
  if (pct === null) {
    bar.classList.add('thinking');
  } else {
    bar.classList.remove('thinking');
    $('analyze-progress-fill').style.width = `${Math.max(0, Math.min(100, pct))}%`;
  }
}

function hideAnalyzeProgress() {
  $('analyze-progress').classList.add('hidden');
  document.querySelector('.analyze-progress-bar')?.classList.remove('thinking');
  stopElapsedTicker();
  const stop = $('analyze-stop-btn');
  if (stop) { stop.disabled = false; stop.textContent = 'Stop'; }
}

function showAnalyzeError(msg) {
  $('analyze-error').textContent = msg;
  $('analyze-error').classList.remove('hidden');
  $('analyze-result').classList.add('hidden');
}

function clearAnalyzeError() {
  $('analyze-error').classList.add('hidden');
  $('analyze-error').textContent = '';
}

// When *any* analyze run is in flight, disable BOTH Analyze and Deep so
// the user can't kick off a second (which the server would 409 anyway,
// but a disabled button communicates intent more clearly than an error
// toast). The `primary` arg picks which button visually spins; the
// other is just greyed. Re-enable both in one call when the run ends.
function setAnalyzeBusy(primary) {
  const a = $('trade-analyze'), d = $('trade-analyze-deep');
  if (primary === 'analyze') {
    setBusy(a, true);
    d.disabled = true;
  } else if (primary === 'deep') {
    setBusy(d, true);
    a.disabled = true;
  } else {  // done
    setBusy(a, false, 'Analyze');
    setBusy(d, false, 'Deep');
    a.disabled = false;
    d.disabled = false;
  }
}

function dismissAnalysis() {
  stopAnalyzePoll();
  $('analyze-card').classList.add('hidden');
  $('analyze-result').classList.add('hidden');
  hideAnalyzeProgress();
  clearAnalyzeError();
}
$('analyze-dismiss').addEventListener('click', dismissAnalysis);

// Export menu — toggles visibility, click on format triggers download
// via a hidden <a>. Using a link rather than fetch so the browser's
// download dialog fires naturally with the server-sent filename.
(() => {
  const btn = $('analyze-export-btn');
  const menu = $('analyze-export-menu');
  if (!btn || !menu) return;
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    menu.classList.toggle('hidden');
  });
  document.addEventListener('click', (e) => {
    if (!menu.classList.contains('hidden') &&
        !menu.contains(e.target) && e.target !== btn) {
      menu.classList.add('hidden');
    }
  });
  menu.querySelectorAll('button[data-fmt]').forEach(opt => {
    opt.addEventListener('click', () => {
      const fmt = opt.dataset.fmt;
      const tid = btn.dataset.taskId || analyzeCurrent?.task_id;
      if (!tid) {
        showAnalyzeError('No analysis to export — run one first.');
        return;
      }
      menu.classList.add('hidden');
      // Show a transient loading state on the button for slow formats (PDF).
      const prevText = btn.textContent;
      if (fmt === 'pdf') {
        btn.textContent = 'Rendering…';
        btn.disabled = true;
      }
      const url = `/api/analyze/export/${encodeURIComponent(tid)}?fmt=${encodeURIComponent(fmt)}`;
      // Use fetch so we can surface server errors inline rather than
      // dropping the user onto a raw JSON error page.
      fetch(url)
        .then(r => {
          if (!r.ok) return r.text().then(t => { throw new Error(t || r.statusText); });
          const cd = r.headers.get('Content-Disposition') || '';
          const m = cd.match(/filename="([^"]+)"/);
          const fname = m ? m[1] : `analysis.${fmt}`;
          return r.blob().then(blob => ({ blob, fname }));
        })
        .then(({ blob, fname }) => {
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = fname;
          document.body.appendChild(a);
          a.click();
          setTimeout(() => {
            URL.revokeObjectURL(a.href);
            a.remove();
          }, 1000);
        })
        .catch(err => {
          showAnalyzeError(`Export failed: ${err.message || err}`);
        })
        .finally(() => {
          if (fmt === 'pdf') {
            btn.textContent = prevText;
            btn.disabled = false;
          }
        });
    });
  });
})();

function renderAnalysisResult(r) {
  hideAnalyzeProgress();
  clearAnalyzeError();
  $('analyze-result').classList.remove('hidden');
  // Hide any stale pressure-test section from a prior run — this
  // result is for a regular Analyze/Deep, not a consensus check.
  $('analyze-pressure').classList.add('hidden');

  // Timestamp — anchors accuracy-over-time comparisons. Shows when the
  // analysis completed so a later review can see "this call was made
  // when price was X; here's what happened after." Falls back to
  // "just now" if the result predates the iso_ts field.
  const tsEl = $('analyze-ts');
  if (r.iso_ts) {
    try {
      const dt = new Date(r.iso_ts);
      // Local time, compact — e.g. "Apr 20, 10:14:32"
      tsEl.textContent = dt.toLocaleString('en-US', {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false,
      });
      tsEl.title = r.iso_ts;
    } catch (_) {
      tsEl.textContent = r.iso_ts;
    }
  } else {
    tsEl.textContent = 'just now';
    tsEl.title = '';
  }
  // Stash the task_id on the Export button so the menu knows which
  // analysis to export. The current running task_id lives in
  // analyzeCurrent — when renderAnalysisResult is called from replay
  // of a completed task, that's still the right task_id.
  const exportBtn = $('analyze-export-btn');
  if (exportBtn && analyzeCurrent?.task_id) {
    exportBtn.dataset.taskId = analyzeCurrent.task_id;
  }

  const sig = String(r.signal || 'Skip');
  const sigCls = sig.toLowerCase();
  const pill = $('analyze-signal-pill');
  pill.textContent = sig;
  pill.className = `analyze-signal ${sigCls}`;

  const conf = Math.max(0, Math.min(100, +r.confidence || 0));
  $('analyze-confidence-val').textContent = `${conf}%`;
  $('analyze-confidence-fill').style.width = `${conf}%`;

  // Calibration chip — renders the historical track for this exact
  // (provider, model, confidence-bucket). Three display states:
  //   • n >= 5 and hit_rate known → "Sonnet: 67% hit @ 70-79% (n=12)"
  //   • 1 <= n < 5 → "Sonnet: pending (n=2)" — the model has a record
  //     but too few samples to trust the number yet
  //   • n == 0 or bucket missing → hidden entirely (don't clutter the
  //     UI on a truly-cold-start for this bucket)
  // This is the thesis's central discipline: no confidence number
  // without its earnable track. When track is absent, we say so
  // explicitly rather than hiding the question.
  const chipEl = $('analyze-cal-chip');
  const cal = r.calibration;
  const modelShort = String(r.model || '').split(' ')[0] || r.model || '';
  if (cal && cal.n >= 5 && cal.hit_rate !== null && cal.hit_rate !== undefined) {
    const hit = Math.round(cal.hit_rate * 100);
    chipEl.textContent = `${modelShort}: ${hit}% hit @ ${cal.bucket} (n=${cal.n})`;
    chipEl.className = 'analyze-cal-chip';
    // Tint tracks calibration quality: green when hit-rate >= 60%,
    // amber 40-59%, red <40%. Not about the specific trade — about
    // whether this provider/model/bucket has *earned* trust.
    if (hit >= 60) chipEl.classList.add('cal-good');
    else if (hit >= 40) chipEl.classList.add('cal-mid');
    else chipEl.classList.add('cal-bad');
  } else if (cal && cal.n > 0) {
    chipEl.textContent = `${modelShort}: pending (n=${cal.n})`;
    chipEl.className = 'analyze-cal-chip cal-pending';
  } else {
    chipEl.className = 'analyze-cal-chip hidden';
    chipEl.textContent = '';
  }

  // Thousand-separator commas on numeric values. Non-numeric → em-dash.
  // Up to 2 decimals so tick-sized instruments (ES 0.25, MNQ 0.25) read
  // correctly while clean integer levels like 26836 stay integer.
  const fmt = v => {
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v);
    if (!Number.isFinite(n)) return String(v);
    return n.toLocaleString('en-US', { maximumFractionDigits: 2 });
  };
  $('analyze-entry').textContent = fmt(r.entry);
  $('analyze-stop').textContent = fmt(r.stop);
  $('analyze-tp').textContent = fmt(r.tp);

  // Risk/Reward ratio — (reward / risk) given the consolidated side.
  // Only meaningful when all three levels are numeric AND signal is a
  // direction (Long/Short). Skip signals or missing levels → hide.
  const e = Number(r.entry), s = Number(r.stop), t = Number(r.tp);
  const rrEl = $('analyze-rr');
  if (rrEl) {
    rrEl.className = 'value mono';
    if (sigCls === 'long' && Number.isFinite(e) && Number.isFinite(s) && Number.isFinite(t) && e > s) {
      const rr = (t - e) / (e - s);
      rrEl.textContent = `${rr.toFixed(2)}:1`;
      rrEl.classList.add(rr >= 2 ? 'rr-good' : rr >= 1 ? 'rr-ok' : 'rr-bad');
    } else if (sigCls === 'short' && Number.isFinite(e) && Number.isFinite(s) && Number.isFinite(t) && s > e) {
      const rr = (e - t) / (s - e);
      rrEl.textContent = `${rr.toFixed(2)}:1`;
      rrEl.classList.add(rr >= 2 ? 'rr-good' : rr >= 1 ? 'rr-ok' : 'rr-bad');
    } else {
      rrEl.textContent = '—';
    }
  }

  // Apply-to-order: pre-populate Quick Order bracket fields + pre-select
  // side based on the consolidated signal. Skip disables the button so
  // the trader doesn't accidentally fire a no-edge trade.
  const applyBtn = $('analyze-apply-order');
  applyBtn.disabled = (sigCls === 'skip');
  applyBtn.onclick = () => {
    if (r.entry !== null && r.entry !== undefined) {
      // Entry is informational — the UI fires market orders, not limits.
      // Setting it visually via trade-symbol/qty isn't meaningful; the
      // bracket fields below carry the real impact.
    }
    if (r.stop !== null && r.stop !== undefined) $('trade-sl').value = r.stop;
    if (r.tp !== null && r.tp !== undefined) $('trade-tp').value = r.tp;
    refreshBracketArmed();
    toast(`applied ${sig.toLowerCase()} brackets to order`, 'ok');
    $('trade-sl').scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  // Apply-pine button — enabled only if the backend saved a pine script.
  // We pass `request_id` so the server can tie the post-apply screenshot
  // (chart with Entry/Stop/TP drawn on it) to this decision in
  // decisions.db. The Journal tab can later show that image when
  // reviewing accuracy.
  const pineBtn = $('analyze-apply-pine');
  if (r.pine_path) {
    pineBtn.disabled = false;
    pineBtn.onclick = async () => {
      if (!confirm('Paste this analysis pine script into TradingView? Takes ~20s and takes over the chart view briefly.')) return;
      setBusy(pineBtn, true);
      try {
        const ar = await api('/api/analyze/apply-pine', {
          method: 'POST',
          body: {
            path: r.pine_path,
            request_id: analyzeCurrent?.request_id || null,
          },
        });
        if (ar.ok) {
          const shot = ar.applied_screenshot;
          if (shot) {
            toast(`pine applied · screenshot saved: ${shot.split('/').slice(-2).join('/')}`, 'ok');
          } else {
            toast('pine applied to chart', 'ok');
          }
        } else {
          toast(`pine apply failed: ${(ar.stderr || 'see server log').slice(-200)}`, 'err');
        }
      } catch (e) { toast(`apply-pine: ${e.message}`, 'err'); }
      finally { setBusy(pineBtn, false, 'Apply pine to chart'); }
    };
  } else {
    pineBtn.disabled = true;
    pineBtn.onclick = null;
  }

  $('analyze-rationale').textContent = r.rationale || '';

  // Unknowns — "What could change my mind." Rendered only when the
  // model returned at least one material unknown. An empty array means
  // "setup is clear" and we don't want to clutter the card with an
  // empty section. Each entry has `what` (required) and an optional
  // `resolves_how` hint which renders as faint supporting text.
  // Future: wire up one-click resolvers (econ calendar, vol term
  // curve, options flow) keyed off resolves_how patterns.
  const unknowns = Array.isArray(r.unknowns) ? r.unknowns : [];
  const unknownsEl = $('analyze-unknowns');
  if (unknowns.length === 0) {
    unknownsEl.classList.add('hidden');
    $('analyze-unknowns-list').innerHTML = '';
  } else {
    unknownsEl.classList.remove('hidden');
    $('analyze-unknowns-list').innerHTML = unknowns.map(u => {
      const what = escapeHtml(u.what || '');
      const how = u.resolves_how
        ? `<span class="analyze-unknowns__how">${escapeHtml(u.resolves_how)}</span>`
        : '';
      return `<li><span class="analyze-unknowns__what">${what}</span>${how}</li>`;
    }).join('');
  }

  // Deep-mode extras: optimal-TF badge above the verdict + per-TF
  // breakdown table below the rationale. Both hidden for single-TF.
  const isDeep = r.mode === 'deep' || Array.isArray(r.per_tf) && r.per_tf.length > 0;
  const optimalBox = $('analyze-optimal-tf');
  if (isDeep && r.optimal_tf) {
    $('analyze-optimal-tf-val').textContent = String(r.optimal_tf);
    optimalBox.classList.remove('hidden');
    // Auto-switch the chart to the optimal TF so "Apply to order" and
    // "Apply pine to chart" hit the same timeframe the analysis is
    // calibrated for. Only navigate if the optimal TF is one we have
    // a pill for (guards against LLM hallucinating a TF outside the
    // 9-set) and it's different from the current chart TF.
    const pills = Array.from(document.querySelectorAll('#trade-tf-bar .tf-pill'));
    const match = pills.find(p => p.dataset.tf === r.optimal_tf);
    const currentActive = document.querySelector('#trade-tf-bar .tf-pill.active')?.dataset.tf;
    if (match && match.dataset.tf !== currentActive) {
      const sym = $('trade-symbol').value.trim() || r.symbol;
      commitSymbol(sym, match.dataset.tf);
      toast(`chart → ${match.dataset.tf} (optimal)`, 'ok');
    }
  } else {
    optimalBox.classList.add('hidden');
  }

  const pertfWrap = $('analyze-pertf');
  if (isDeep && Array.isArray(r.per_tf) && r.per_tf.length) {
    const rows = r.per_tf.map(row => {
      const s = String(row.signal || 'Skip');
      const cls = s.toLowerCase();
      const isOpt = row.tf === r.optimal_tf;
      return `<tr class="${isOpt ? 'optimal' : ''}">
        <td class="tf">${escapeHtml(row.tf || '—')}${isOpt ? ' ★' : ''}</td>
        <td class="sig"><span class="pill ${cls}">${escapeHtml(s)}</span></td>
        <td class="conf">${Math.max(0, Math.min(100, +row.confidence || 0))}%</td>
        <td>${escapeHtml(row.rationale || '')}</td>
      </tr>`;
    }).join('');
    $('analyze-pertf-body').innerHTML = `<table>
      <thead><tr>
        <th>TF</th><th>Signal</th><th class="num">Conf</th><th>Rationale</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
    pertfWrap.classList.remove('hidden');
  } else {
    pertfWrap.classList.add('hidden');
  }

  // Meta strip — provider/model/timeframe/cost/elapsed for transparency
  const meta = [];
  if (r.timeframe) meta.push(`<span>tf: ${escapeHtml(r.timeframe)}</span>`);
  if (isDeep && r.optimal_tf) meta.push(`<span>optimal: ${escapeHtml(r.optimal_tf)}</span>`);
  if (r.provider) meta.push(`<span>provider: ${escapeHtml(r.provider)}</span>`);
  if (r.model) meta.push(`<span>model: ${escapeHtml(r.model)}</span>`);
  // Only show cost when it's actually nonzero — local providers return 0
  // and a "cost: $0.0000" line is just noise when you're running for free.
  if (r.cost_usd !== undefined && r.cost_usd !== null && +r.cost_usd > 0) {
    meta.push(`<span>cost: $${(+r.cost_usd).toFixed(4)}</span>`);
  }
  if (r.elapsed_s) meta.push(`<span>total: ${r.elapsed_s}s</span>`);
  if (r.llm_elapsed_s) meta.push(`<span>llm: ${r.llm_elapsed_s}s</span>`);
  if (r.pine_path) {
    const name = String(r.pine_path).split('/').pop();
    meta.push(`<span>pine: ${escapeHtml(name)}</span>`);
  }
  $('analyze-meta').innerHTML = meta.join('<span class="sep"> · </span>');
}

async function pollAnalyzeStatus() {
  if (!analyzeCurrent) return;
  const { task_id, request_id } = analyzeCurrent;
  try {
    const [status, auditTail] = await Promise.all([
      api(`/api/analyze/${task_id}`),
      api(`/api/audit/tail?n=100&request_id=${request_id}`),
    ]);

    // Stream progress from the audit log. analyze_mtf emits:
    //   analyze.start         { symbol, timeframe?, timeframes?[], mode? }
    //   analyze.capture_start { symbol, tf, index?, total? }
    //   analyze.captured      { symbol, tf, path, index?, total? }
    //   analyze.llm_request   { provider, model }
    //   analyze.done | analyze.fail | analyze.parse_fail
    //
    // Progress shape varies by mode:
    //   single-TF: 1 capture → LLM → done. Phases map cleanly to %.
    //   deep: N=9 captures → LLM → done. We count done vs total so the
    //     bar moves smoothly through the ~45s capture phase instead of
    //     sitting at 10% until the last capture lands.
    const events = auditTail.entries || [];
    let phase = 'starting', detail = '', pct = 0;
    let llmStarted = false, activeTf = null;
    let symbol = '', tf = '', model = '', total = 1;
    const doneTfs = new Set();
    // Pressure-test state — counts providers done vs total expected.
    let ptTotal = 0, ptDone = 0, ptActive = null, ptMode = false;

    for (const e of events) {
      const ev = e.event || '';
      if (ev === 'analyze.start') {
        symbol = e.symbol || symbol;
        tf = e.timeframe || tf;
        if (Array.isArray(e.timeframes)) total = e.timeframes.length;
      } else if (ev === 'analyze.capture_start') {
        activeTf = e.tf || activeTf;
        if (e.total) total = e.total;
      } else if (ev === 'analyze.captured') {
        if (e.tf) doneTfs.add(e.tf);
        if (activeTf === e.tf) activeTf = null;
        if (e.total) total = e.total;
      } else if (ev === 'analyze.llm_request') {
        llmStarted = true;
        model = e.model || model;
      } else if (ev === 'pressure_test.start') {
        ptMode = true;
        if (Array.isArray(e.combos)) ptTotal = e.combos.length;
        symbol = e.symbol || symbol;
        tf = e.timeframe || tf;
      } else if (ev === 'pressure_test.provider_start') {
        ptActive = `${e.provider}/${e.model}`;
        if (e.total) ptTotal = e.total;
      } else if (ev === 'pressure_test.provider_done'
              || ev === 'pressure_test.provider_fail') {
        ptDone += 1;
        if (ptActive && ptActive === `${e.provider}/${e.model}`) ptActive = null;
      } else if (ev === 'pressure_test.done') {
        phase = 'done';
      } else if (ev === 'analyze.done') {
        phase = 'done';
      } else if (ev === 'analyze.fail' || ev === 'analyze.parse_fail') {
        phase = `failed: ${e.error || e.raw_head || ''}`;
      }
    }

    // Pressure-test progress overrides the single/deep progress path
    // because the same `analyze.*` capture events fire early, then
    // the pressure_test.provider_* events take over.
    if (ptMode && phase !== 'done' && !phase.startsWith('failed')) {
      if (ptActive) {
        phase = `Pressure test — ${ptDone + 1} of ${ptTotal}`;
        detail = `${ptActive} thinking…`;
        pct = null;
      } else if (ptDone > 0 && ptDone < ptTotal) {
        phase = `Pressure test — ${ptDone} of ${ptTotal} done`;
        detail = 'next provider…';
        pct = Math.round((ptDone / ptTotal) * 100);
      } else if (ptDone === 0) {
        phase = 'Pressure test starting';
        detail = `capturing ${symbol} ${tf || ''}…`;
        pct = 10;
      }
    }

    const done = doneTfs.size;
    const isDeep = total > 1;

    // Only run the single/deep progress branching when NOT in pressure-
    // test mode — the pressure-test block above has already set phase/
    // detail/pct correctly for this path.
    if (!ptMode) {
      if (llmStarted) {
        phase = isDeep ? `Integrating ${total} timeframes` : `Analyzing ${tf || 'chart'}`;
        detail = model ? `${model} reading chart${isDeep ? 's' : ''}…` : 'model reading chart…';
        pct = null;  // indeterminate shimmer
      } else if (done >= total && total > 0) {
        phase = isDeep ? `All ${total} timeframes captured` : 'Chart captured';
        detail = 'handing off to model…';
        pct = 50;
      } else if (activeTf) {
        phase = isDeep
          ? `Capturing ${activeTf} (${done + 1} of ${total})`
          : `Capturing ${activeTf}`;
        detail = symbol ? `symbol: ${symbol}` : '';
        pct = isDeep ? Math.round((done / total) * 50) : 10;
      } else if (done > 0 && isDeep) {
        phase = `Captured ${done} of ${total}`;
        detail = 'next timeframe…';
        pct = Math.round((done / total) * 50);
      } else if (symbol) {
        phase = `Starting — ${symbol} ${tf || ''}`.trim();
        detail = isDeep ? `preparing ${total} captures…` : 'preparing capture…';
        pct = 0;
      }
    }

    if (status.state === 'running') {
      setAnalyzeProgress(phase, detail, pct);
    } else if (status.state === 'done') {
      stopAnalyzePoll();
      hideAnalyzeProgress();
      const result = status.result || {};
      // Branch render on mode: pressure test has a different shape
      // (array of per-provider results, no single signal/entry/etc),
      // so it rides the polling infra but gets its own renderer.
      if (result.mode === 'pressure_test') {
        renderPressureTest(result);
      } else {
        renderAnalysisResult(result);
      }
      setAnalyzeBusy(null);
      setBusy($('analyze-pressure-test'), false, 'Pressure test');
      refreshSessionStrip();
    } else if (status.state === 'failed') {
      stopAnalyzePoll();
      showAnalyzeError(`${status.error || 'analysis failed'}`);
      setAnalyzeBusy(null);
      setBusy($('analyze-pressure-test'), false, 'Pressure test');
    } else if (status.state === 'cancelled') {
      // User hit Stop. The server already flipped state; we just tidy up
      // the UI — no error banner (not a failure), no result card.
      stopAnalyzePoll();
      hideAnalyzeProgress();
      setAnalyzeBusy(null);
      setBusy($('analyze-pressure-test'), false, 'Pressure test');
      toast('analysis stopped', 'ok');
    }
  } catch (e) {
    // transient — keep polling
  }
}

function stopAnalyzePoll() {
  if (analyzeCurrent && analyzeCurrent.pollTimer) {
    clearInterval(analyzeCurrent.pollTimer);
    analyzeCurrent.pollTimer = null;
  }
}

// User hit Stop while analysis was in flight. Fire-and-forget the cancel
// request — the next poll tick will see state=cancelled and tidy the UI.
// Disable the button immediately so double-click doesn't spam the server.
async function cancelAnalysis() {
  if (!analyzeCurrent) return;
  const { task_id } = analyzeCurrent;
  const btn = $('analyze-stop-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Stopping…'; }
  try {
    await api(`/api/analyze/${task_id}/cancel`, { method: 'POST' });
  } catch (e) {
    toast(`stop failed: ${e.message}`, 'err');
    if (btn) { btn.disabled = false; btn.textContent = 'Stop'; }
  }
}
$('analyze-stop-btn').addEventListener('click', cancelAnalysis);

async function startAnalysis() {
  const symbol = $('trade-symbol').value.trim();
  if (!symbol) return toast('symbol required', 'err');
  const tf = document.querySelector('#trade-tf-bar .tf-pill.active')?.dataset.tf || null;

  setAnalyzeBusy('analyze');

  // Reveal the card and reset transient UI: hide any prior result, clear
  // any prior error, start the elapsed ticker. Only these pieces change
  // per run — the provider/model selectors in the card head persist
  // intentionally.
  $('analyze-card').classList.remove('hidden');
  $('analyze-result').classList.add('hidden');
  clearAnalyzeError();
  startElapsedTicker();
  setAnalyzeProgress(`Starting — ${symbol} ${tf || ''}`.trim(), 'preparing capture…', 0);

  try {
    const r = await api('/api/analyze', {
      method: 'POST',
      body: {
        symbol,
        timeframe: tf,
        provider: $('analyze-provider').value,
        model: _analyzeModelValue(),
      },
    });
    stopAnalyzePoll();
    analyzeCurrent = {
      task_id: r.task_id,
      request_id: r.request_id,
      pollTimer: setInterval(pollAnalyzeStatus, 1500),
    };
    pollAnalyzeStatus();
  } catch (e) {
    hideAnalyzeProgress();
    showAnalyzeError(e.message);
    toast(`analyze: ${e.message}`, 'err');
    setAnalyzeBusy(null);
  }
  // Note: on success we leave the spinner spinning — pollAnalyzeStatus will
  // re-enable the button when status.state flips to done/failed.
}
$('trade-analyze').addEventListener('click', startAnalysis);

// ----------------------------------------------------------------------
// Reversibility-aware commitment — dollar risk per trade + daily
// budget tracking. The Quick Order bar shows "$N risk · X% of budget"
// tinted green/amber/red so the UX weight of clicking BUY scales with
// how much money is actually at stake. A small scalp and a swing-size
// position can't look the same in the UI.
// ----------------------------------------------------------------------

// Point values for common futures. When a symbol isn't in this map
// (stocks, crypto, unknown futures), dollar-risk falls back to 1:1
// price terms ($1 per point) and the display is labeled accordingly.
// CME contract specs — values are USD per 1.00 price point.
const POINT_VALUES = {
  // Micro equity index futures
  'MNQ1!': 2.0,   'MNQ': 2.0,        // Micro Nasdaq-100
  'MES1!': 5.0,   'MES': 5.0,        // Micro S&P 500
  'M2K1!': 5.0,   'M2K': 5.0,        // Micro Russell 2000
  'MYM1!': 0.5,   'MYM': 0.5,        // Micro Dow
  // Full-size equity index futures
  'NQ1!':  20.0,  'NQ':  20.0,       // E-mini Nasdaq-100
  'ES1!':  50.0,  'ES':  50.0,       // E-mini S&P 500
  'RTY1!': 50.0,  'RTY': 50.0,       // E-mini Russell 2000
  'YM1!':  5.0,   'YM':  5.0,        // E-mini Dow
  // Micro metals / energy
  'MCL1!': 100.0, 'MCL': 100.0,      // Micro crude ($1/bbl × 100bbl? TV conventions vary)
  'MGC1!': 10.0,  'MGC': 10.0,       // Micro gold
};

// Return the point-value dollars/point for the currently-selected
// symbol, or null if we don't know. Tries exact match, then strips
// exchange prefix ("CME_MINI:MNQ1!" → "MNQ1!"), then strips the front-
// month continuous marker ("MNQ1!" → "MNQ").
function _pointValueFor(symbol) {
  if (!symbol) return null;
  const bare = symbol.includes(':') ? symbol.split(':').pop() : symbol;
  if (POINT_VALUES[bare] != null) return POINT_VALUES[bare];
  const root = bare.replace(/[!0-9]+$/, '');
  if (POINT_VALUES[root] != null) return POINT_VALUES[root];
  return null;
}

const BUDGET_STORAGE_KEY = 'ios-daily-risk-budget';

function _getDailyBudget() {
  try {
    const v = localStorage.getItem(BUDGET_STORAGE_KEY);
    const n = v ? Number(v) : NaN;
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch (e) {
    return null;
  }
}

function _setDailyBudget(v) {
  try {
    if (v && v > 0) localStorage.setItem(BUDGET_STORAGE_KEY, String(v));
    else localStorage.removeItem(BUDGET_STORAGE_KEY);
  } catch (e) { /* private mode / quota — non-fatal */ }
}

// Recompute and render the risk bar. Called on every change to qty,
// stop, entry, or symbol. Hidden when we lack enough info to compute
// (no stop, no qty, or unknown symbol AND no fallback). Uses entry
// from either an explicit field or the latest analyze result.
function refreshRiskBar() {
  const bar = $('trade-risk-bar');
  const qty = parseFloat($('trade-qty').value);
  const sl = parseFloat($('trade-sl').value);
  const symbol = $('trade-symbol').value.trim();

  if (!Number.isFinite(qty) || qty <= 0 || !Number.isFinite(sl)) {
    bar.classList.add('hidden');
    return;
  }

  // Entry reference: use the last analysis's entry if present, else
  // fall back to the last chart meta's price (from the capture). If
  // neither, we can't compute a meaningful risk distance.
  const lastEntry = parseFloat($('analyze-entry').textContent.replace(/,/g, ''));
  const entry = Number.isFinite(lastEntry) ? lastEntry : null;
  if (entry === null) {
    bar.classList.add('hidden');
    return;
  }

  const distance = Math.abs(entry - sl);
  if (distance <= 0) {
    bar.classList.add('hidden');
    return;
  }

  const pv = _pointValueFor(symbol);
  const dollarRisk = qty * distance * (pv != null ? pv : 1);
  const symKnown = pv != null;

  $('risk-dollars').textContent = symKnown
    ? `$${dollarRisk.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
    : `${dollarRisk.toLocaleString('en-US', { maximumFractionDigits: 2 })} pts`;

  // The small math breakdown makes the number auditable — "where did
  // $310 come from?" answers itself. Hidden on mobile via CSS.
  const pvLabel = symKnown ? `$${pv}/pt` : 'unknown pt value';
  $('risk-math').textContent = `(${qty} × ${distance.toFixed(2)} × ${pvLabel})`;

  const budget = _getDailyBudget();
  let pctStr = '—';
  let tint = '';
  if (budget && symKnown) {
    const pct = (dollarRisk / budget) * 100;
    pctStr = `${pct.toFixed(1)}% of $${budget.toLocaleString()} budget`;
    tint = pct < 10 ? 'risk-ok'
         : pct < 30 ? 'risk-warn'
         : pct < 50 ? 'risk-high'
         : 'risk-over';
  } else if (!symKnown) {
    pctStr = 'pt value unknown — can\'t convert to $';
  } else {
    pctStr = 'set a daily budget above for % context';
  }
  $('risk-pct').textContent = pctStr;

  bar.classList.remove('hidden', 'risk-ok', 'risk-warn', 'risk-high', 'risk-over');
  if (tint) bar.classList.add(tint);

  // Friction messaging: at risk-high flag it, at risk-over suggest
  // shrinking. Traders can still click BUY/SELL — this is UI weight,
  // not a hard block. Hard blocks belong on a settings toggle, not
  // here where a single bad click costs keystrokes.
  const hint = $('risk-hint');
  if (tint === 'risk-over') {
    hint.textContent = `⚠ This trade would risk >${Math.round(100 - (budget / dollarRisk) * 100)}% over your daily budget.`;
  } else if (tint === 'risk-high') {
    hint.textContent = 'Heavy size for this budget — consider half.';
  } else {
    hint.textContent = '';
  }
}

function wireRiskBar() {
  const recompute = () => refreshRiskBar();
  ['trade-qty', 'trade-sl', 'trade-symbol'].forEach(id => {
    const el = $(id);
    if (!el) return;
    el.addEventListener('input', recompute);
    el.addEventListener('change', recompute);
  });
  // Re-run after analyze finishes (new entry/stop appear)
  const obs = new MutationObserver(recompute);
  obs.observe($('analyze-entry'), { childList: true, characterData: true, subtree: true });

  // Budget field — load, persist, recompute
  const budgetEl = $('daily-risk-budget');
  const stored = _getDailyBudget();
  if (stored) budgetEl.value = stored;
  budgetEl.addEventListener('input', () => {
    _setDailyBudget(parseFloat(budgetEl.value));
    recompute();
  });
}
wireRiskBar();

// ----------------------------------------------------------------------
// Session rollup — today's scorecard strip at the top of Trade.
// ----------------------------------------------------------------------
async function refreshSessionStrip() {
  // Outer strip always visible (hosts the daily budget input); only the
  // scorecard cells portion hides when there's no data yet today.
  const cells = $('session-strip-cells');
  try {
    const s = await api('/api/decisions/session');
    if (!s || !s.total) {
      cells.classList.add('hidden');
      cells.innerHTML = '';
      return;
    }
    // Realized R formatting: explicit sign, 2 decimals. Red/green color
    // by total direction — at a glance, "am I up or down today?"
    const r = Number(s.realized_r_sum || 0);
    const rStr = (r >= 0 ? '+' : '') + r.toFixed(2) + 'R';
    const rCls = r > 0 ? 'pos' : r < 0 ? 'neg' : '';
    // Win rate only meaningful if there were directional closes. Skip
    // rendering when both wins and losses are 0 (all no_fill / expired).
    const closes = (s.wins || 0) + (s.losses || 0);
    const winRate = closes > 0 ? Math.round((s.wins / closes) * 100) : null;

    const cellsHtml = [
      `<div class="cell"><span class="n">${s.total}</span><span class="label">decisions</span></div>`,
      `<div class="cell"><span class="n ${rCls}">${rStr}</span><span class="label">realized</span></div>`,
    ];
    if (winRate !== null) {
      cellsHtml.push(`<div class="cell"><span class="n">${s.wins}–${s.losses}</span><span class="label">W–L (${winRate}%)</span></div>`);
    }
    if (s.unreconciled > 0) {
      cellsHtml.push(`<div class="cell"><span class="n warn">${s.unreconciled}</span><span class="label">to tag</span></div>`);
    }
    if (s.skips > 0) {
      cellsHtml.push(`<div class="cell"><span class="n muted">${s.skips}</span><span class="label">skipped</span></div>`);
    }
    if (s.overrides > 0) {
      cellsHtml.push(`<div class="cell"><span class="n muted">${s.overrides}</span><span class="label">overrode AI</span></div>`);
    }
    cells.innerHTML = cellsHtml.join('');
    cells.classList.remove('hidden');
  } catch (e) {
    // Silent — transient DB/network hiccup shouldn't drop a banner on
    // the user. Cells stay in whatever state they were in.
  }
}

// Initial load + on tab-enter is hooked in the tab switcher below.
refreshSessionStrip();

// Deep analysis — captures all 10 timeframes and asks the LLM to pick
// the optimal one, then produces a backtestable Pine strategy. Same
// task shape as single-TF, so we reuse pollAnalyzeStatus unchanged —
// the only differences are the endpoint and a note in the phase label.
async function startDeepAnalysis() {
  const symbol = $('trade-symbol').value.trim();
  if (!symbol) return toast('symbol required', 'err');

  setAnalyzeBusy('deep');

  $('analyze-card').classList.remove('hidden');
  $('analyze-result').classList.add('hidden');
  clearAnalyzeError();
  startElapsedTicker();
  setAnalyzeProgress(`Deep analyzing — ${symbol}`, 'preparing 9 captures…', 0);

  try {
    const r = await api('/api/analyze/deep', {
      method: 'POST',
      body: {
        symbol,
        provider: $('analyze-provider').value,
        model: _analyzeModelValue(),
      },
    });
    stopAnalyzePoll();
    analyzeCurrent = {
      task_id: r.task_id,
      request_id: r.request_id,
      mode: 'deep',
      pollTimer: setInterval(pollAnalyzeStatus, 1500),
    };
    pollAnalyzeStatus();
  } catch (e) {
    hideAnalyzeProgress();
    showAnalyzeError(e.message);
    toast(`deep analyze: ${e.message}`, 'err');
    setAnalyzeBusy(null);
  }
}
$('trade-analyze-deep').addEventListener('click', startDeepAnalysis);

// ----------------------------------------------------------------------
// Pressure test — run the same chart through 2-3 providers for a
// consensus check. Expensive in Claude quota + time, so it's a
// user-initiated second-opinion flow, not automatic.
// ----------------------------------------------------------------------
async function startPressureTest() {
  const symbol = $('trade-symbol').value.trim();
  if (!symbol) return toast('symbol required', 'err');
  const tf = document.querySelector('#trade-tf-bar .tf-pill.active')?.dataset.tf || null;

  const btn = $('analyze-pressure-test');
  setAnalyzeBusy('analyze');  // co-disable both Analyze buttons too
  setBusy(btn, true);
  $('analyze-card').classList.remove('hidden');
  clearAnalyzeError();
  startElapsedTicker();
  setAnalyzeProgress(`Pressure test — ${symbol}`, 'capturing once + querying 3 providers…', 0);

  try {
    const r = await api('/api/analyze/pressure-test', {
      method: 'POST',
      body: { symbol, timeframe: tf },
    });
    stopAnalyzePoll();
    analyzeCurrent = {
      task_id: r.task_id,
      request_id: r.request_id,
      mode: 'pressure_test',
      pollTimer: setInterval(pollAnalyzeStatus, 1500),
    };
    pollAnalyzeStatus();
  } catch (e) {
    hideAnalyzeProgress();
    showAnalyzeError(e.message);
    toast(`pressure test: ${e.message}`, 'err');
    setAnalyzeBusy(null);
    setBusy(btn, false, 'Pressure test');
  }
}
$('analyze-pressure-test').addEventListener('click', startPressureTest);

function renderPressureTest(r) {
  const wrap = $('analyze-pressure');
  const body = $('analyze-pressure-body');
  const badge = $('analyze-pressure-badge');

  wrap.classList.remove('hidden');
  const c = r.consensus || {};
  const agree = c.agree || 0;
  const total = c.total || 0;
  // Consensus badge: all-agree green, majority amber, split red. "0/0"
  // means every provider errored — badge says so explicitly.
  let badgeCls = 'split', badgeText = '';
  if (total === 0) {
    badgeCls = 'empty';
    badgeText = 'all providers errored';
  } else if (c.all_agree) {
    badgeCls = 'agree';
    badgeText = `✓ ${agree}/${total} agree: ${c.direction}`;
  } else if (agree / total >= 0.67) {
    badgeCls = 'majority';
    badgeText = `◐ ${agree}/${total} lean ${c.direction}`;
  } else {
    badgeCls = 'split';
    badgeText = `✗ split — ${agree}/${total} on ${c.direction}`;
  }
  badge.className = `analyze-pressure__badge pressure-${badgeCls}`;
  badge.textContent = badgeText;

  // Per-provider rows. Errored providers render in a muted row with
  // the error message instead of signal/levels.
  const rows = (r.results || []).map(p => {
    if (p.error) {
      return `<tr class="errored">
        <td class="mono">${escapeHtml((p.provider || '').split('_')[0])}/${escapeHtml(String(p.model || '').split(' ')[0])}</td>
        <td colspan="5" class="muted">error: ${escapeHtml(p.error)}</td>
        <td class="mono muted num">${p.elapsed_s || 0}s</td>
      </tr>`;
    }
    const sig = String(p.signal || 'Skip');
    const cls = sig.toLowerCase();
    const conf = p.confidence != null ? `${p.confidence}%` : '—';
    const rr = _calcRR(p.signal, p.entry, p.stop, p.tp);
    const rrStr = rr !== null ? `${rr.toFixed(2)}:1` : '—';
    return `<tr>
      <td class="mono">${escapeHtml((p.provider || '').split('_')[0])}/<strong>${escapeHtml(String(p.model || '').split(' ')[0])}</strong></td>
      <td><span class="pill ${cls}">${escapeHtml(sig)}</span></td>
      <td class="mono num">${conf}</td>
      <td class="mono num">${p.entry != null ? (+p.entry).toLocaleString() : '—'}</td>
      <td class="mono num">${p.stop != null ? (+p.stop).toLocaleString() : '—'}</td>
      <td class="mono num">${p.tp != null ? (+p.tp).toLocaleString() : '—'}</td>
      <td class="mono num">${rrStr}</td>
      <td class="mono num muted">${p.elapsed_s || 0}s</td>
    </tr>`;
  }).join('');

  // Spread row — shows max-min across agreeing providers for each
  // level. Only rendered when at least one spread number exists.
  let spreadRow = '';
  if (c.entry_spread != null || c.stop_spread != null || c.tp_spread != null) {
    const fmt = v => v == null ? '—' : `±${Number(v).toLocaleString()}`;
    spreadRow = `<tr class="spread-row">
      <td colspan="3" class="muted">agreeing-provider spread</td>
      <td class="mono num muted">${fmt(c.entry_spread)}</td>
      <td class="mono num muted">${fmt(c.stop_spread)}</td>
      <td class="mono num muted">${fmt(c.tp_spread)}</td>
      <td colspan="2"></td>
    </tr>`;
  }

  body.innerHTML = `<table class="pressure-table">
    <thead><tr>
      <th>Model</th><th>Signal</th><th class="num">Conf</th>
      <th class="num">Entry</th><th class="num">Stop</th><th class="num">TP</th>
      <th class="num">R:R</th><th class="num">Time</th>
    </tr></thead>
    <tbody>${rows}${spreadRow}</tbody>
  </table>`;
}

// Provider → model control swap. Each provider has its own model
// affordance: Ollama uses an open-ended text input (many models,
// custom names), claude.ai uses a fixed 3-tier dropdown, ChatGPT uses
// a fixed 2-option dropdown (Instant / Thinking). Show exactly one
// control at a time and read from whichever is visible at submit.
function _syncAnalyzeModelControl() {
  const p = $('analyze-provider').value;
  $('analyze-model').classList.toggle('hidden', p !== 'ollama');
  $('analyze-model-claude').classList.toggle('hidden', p !== 'claude_web');
  $('analyze-model-chatgpt').classList.toggle('hidden', p !== 'chatgpt_web');
}
function _analyzeModelValue() {
  const p = $('analyze-provider').value;
  if (p === 'claude_web')  return $('analyze-model-claude').value || null;
  if (p === 'chatgpt_web') return $('analyze-model-chatgpt').value || null;
  return $('analyze-model').value.trim() || null;
}
$('analyze-provider').addEventListener('change', _syncAnalyzeModelControl);
_syncAnalyzeModelControl();  // initialize on page load

// ----------------------------------------------------------------------
// Act tab
// ----------------------------------------------------------------------
let actCurrent = null;  // {task_id, request_id, pollTimer}

function renderSteps(entries) {
  const box = $('act-steps');
  if (!entries || !entries.length) {
    box.innerHTML = '<div class="empty">Waiting for first step…</div>';
    return;
  }
  const out = [];
  for (const e of entries) {
    const event = e.event || '';
    if (event === 'act.start') {
      out.push(`<div class="step terminal">
        <span class="step-num">—</span>
        <div class="step-main">
          <div class="step-head"><span class="act-pill describe_only">start</span></div>
          <div class="step-reason">${escapeHtml(e.goal || '')}</div>
        </div>
      </div>`);
    } else if (event === 'act.decision') {
      const action = e.action || '?';
      const cost = e.cost_usd != null ? `<span class="step-cost">$${(+e.cost_usd).toFixed(4)}</span>` : '';
      out.push(`<div class="step">
        <span class="step-num">${e.step}</span>
        <div class="step-main">
          <div class="step-head">
            <span class="act-pill ${escapeHtml(action)}">${escapeHtml(action)}</span>
            ${cost}
          </div>
          <div class="step-reason">${escapeHtml(e.reason || '')}</div>
        </div>
      </div>`);
    } else if (event === 'act.done') {
      out.push(`<div class="step terminal">
        <span class="step-num">✓</span>
        <div class="step-main">
          <div class="step-head">
            <span class="act-pill done">done</span>
            <span class="step-cost">${e.steps} steps · $${(+e.total_cost_usd || 0).toFixed(4)}</span>
          </div>
          ${e.result ? `<div class="step-reason">${escapeHtml(e.result)}</div>` : ''}
        </div>
      </div>`);
    } else if (event === 'act.fail') {
      out.push(`<div class="step terminal">
        <span class="step-num">✗</span>
        <div class="step-main">
          <div class="step-head"><span class="act-pill fail">fail</span></div>
          <div class="step-reason">${escapeHtml(e.reason || '')}</div>
        </div>
      </div>`);
    } else if (event === 'act.budget_exceeded') {
      out.push(`<div class="step terminal">
        <span class="step-num">⚠</span>
        <div class="step-main">
          <div class="step-head"><span class="act-pill budget">budget</span></div>
          <div class="step-reason">${escapeHtml(e.reason || '')}</div>
        </div>
      </div>`);
    } else if (event === 'act.read_only_refused') {
      out.push(`<div class="step terminal">
        <span class="step-num">⚠</span>
        <div class="step-main">
          <div class="step-head">
            <span class="act-pill budget">refused</span>
            <span class="step-cost">${escapeHtml(e.action || '')}</span>
          </div>
          <div class="step-reason">${escapeHtml(e.query || '')}</div>
        </div>
      </div>`);
    }
  }
  box.innerHTML = out.join('') || '<div class="empty">Waiting…</div>';
  box.scrollTop = box.scrollHeight;
}

function escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

async function pollActStatus() {
  if (!actCurrent) return;
  try {
    const [status, audit] = await Promise.all([
      api(`/api/act/${actCurrent.task_id}`),
      api(`/api/audit/tail?n=100&request_id=${actCurrent.request_id}`),
    ]);
    renderSteps(audit.entries);
    const strip = $('act-status-strip');
    const steps = audit.entries.filter(e => e.event === 'act.decision').length;
    const lastCost = audit.entries.slice().reverse().find(e => e.total_cost_usd != null);
    const cost = lastCost ? (+lastCost.total_cost_usd).toFixed(4) : '0.0000';
    if (status.state === 'running') {
      strip.innerHTML = `
        <div><span class="label">State</span><span class="value small"><span class="spinner"></span> running</span></div>
        <div><span class="label">Steps</span><span class="value">${steps}</span></div>
        <div><span class="label">Cost</span><span class="value">$${cost}</span></div>`;
    } else if (status.state === 'done') {
      const r = status.result || {};
      strip.innerHTML = `
        <div><span class="label">State</span><span class="value small pnl-pos">✓ done</span></div>
        <div><span class="label">Steps</span><span class="value">${r.steps || steps}</span></div>
        <div><span class="label">Cost</span><span class="value">$${(+r.total_cost_usd || 0).toFixed(4)}</span></div>`;
      $('act-run').disabled = false;
      stopActPoll();
    } else if (status.state === 'failed') {
      strip.innerHTML = `
        <div><span class="label">State</span><span class="value small pnl-neg">✗ failed</span></div>
        <div style="flex: 1; min-width: 0;"><span class="label">Error</span><span class="value small" style="word-break: break-word;">${escapeHtml(status.error || '')}</span></div>`;
      $('act-run').disabled = false;
      stopActPoll();
    }
  } catch (e) {
    // transient — keep polling
  }
}

function stopActPoll() {
  if (actCurrent && actCurrent.pollTimer) {
    clearInterval(actCurrent.pollTimer);
    actCurrent.pollTimer = null;
  }
}

$('act-run').addEventListener('click', async (e) => {
  const btn = e.target;
  const goal = $('act-goal').value.trim();
  if (!goal) return toast('goal required', 'err');
  const payload = {
    goal,
    provider: $('act-provider').value,
    model: $('act-model').value.trim() || null,
    max_steps: +$('act-max-steps').value,
    max_cost_usd: +$('act-max-cost').value,
    vision: $('act-vision').checked,
    text_only: $('act-text-only').checked,
    read_only: $('act-read-only').checked,
    dry_run: $('act-dry-run').checked,
  };
  btn.disabled = true;
  $('act-status-strip').innerHTML = `<div><span class="label">State</span><span class="value small"><span class="spinner"></span> starting</span></div>`;
  $('act-steps').innerHTML = '<div class="empty">Waiting for first step…</div>';
  try {
    const r = await api('/api/act', { method: 'POST', body: payload });
    stopActPoll();
    actCurrent = { task_id: r.task_id, request_id: r.request_id, pollTimer: null };
    actCurrent.pollTimer = setInterval(pollActStatus, 1500);
    pollActStatus();
  } catch (e) {
    toast(`act: ${e.message}`, 'err');
    btn.disabled = false;
    $('act-status-strip').innerHTML = '';
  }
});

// ----------------------------------------------------------------------
// Trade tab — order placement, bracket arming, flatten
// ----------------------------------------------------------------------

// Reflect TP/SL field state into the "bracket armed" badge + button glow.
// Run on every input change so the trader sees exactly which order shape
// (market vs. bracket) their next BUY/SELL click will fire.
function refreshBracketArmed() {
  const tp = $('trade-tp').value.trim();
  const sl = $('trade-sl').value.trim();
  const armed = !!(tp || sl);
  $('trade-bracket-armed').classList.toggle('hidden', !armed);
  $('trade-quick').classList.toggle('bracket-armed-state', armed);
}
$('trade-tp').addEventListener('input', refreshBracketArmed);
$('trade-sl').addEventListener('input', refreshBracketArmed);

async function placeOrder(side) {
  const symbol = $('trade-symbol').value.trim();
  const qty = +$('trade-qty').value;
  const dry_run = $('trade-dry-run').checked;
  const tpRaw = $('trade-tp').value.trim();
  const slRaw = $('trade-sl').value.trim();
  const take_profit = tpRaw ? +tpRaw : null;
  const stop_loss = slRaw ? +slRaw : null;
  if (!symbol || !qty) return toast('symbol + qty required', 'err');
  if (take_profit !== null && !isFinite(take_profit)) return toast('take profit must be numeric', 'err');
  if (stop_loss !== null && !isFinite(stop_loss)) return toast('stop loss must be numeric', 'err');

  const bracketNote = (take_profit !== null || stop_loss !== null)
    ? ` · bracket TP ${take_profit ?? '—'} / SL ${stop_loss ?? '—'}`
    : '';
  const confirmMsg = dry_run
    ? `DRY-RUN: ${side.toUpperCase()} ${qty} ${symbol}${bracketNote}?`
    : `Confirm ${side.toUpperCase()} ${qty} ${symbol} (paper)${bracketNote}?`;
  if (!confirm(confirmMsg)) return;

  const btn = side === 'buy' ? $('trade-buy') : $('trade-sell');
  setBusy(btn, true);
  try {
    const body = { symbol, side, qty, dry_run };
    if (take_profit !== null) body.take_profit = take_profit;
    if (stop_loss !== null) body.stop_loss = stop_loss;
    const r = await api('/api/trade/order', { method: 'POST', body });
    const tag = (take_profit !== null || stop_loss !== null) ? ' (bracket)' : '';
    toast(`${r.ok ? '✓' : '✗'} ${side.toUpperCase()} ${qty} ${symbol}${tag}${dry_run ? ' (dry-run)' : ''}`, r.ok ? 'ok' : 'err');
    // Clear brackets after a successful fire — avoids the footgun of a
    // subsequent market order carrying last trade's SL/TP unintentionally.
    if (r.ok) {
      $('trade-tp').value = '';
      $('trade-sl').value = '';
      refreshBracketArmed();
    }
    loadPositions();
  } catch (e) { toast(`order: ${e.message}`, 'err'); }
  finally { setBusy(btn, false, side === 'buy' ? 'BUY market' : 'SELL market'); }
}
$('trade-buy').addEventListener('click', () => placeOrder('buy'));
$('trade-sell').addEventListener('click', () => placeOrder('sell'));

// Flatten — close every open position. Blast-radius button; gated by an
// explicit count confirmation and auto-disables when no positions are open.
async function flattenAll() {
  const count = _lastPositions.length;
  if (!count) return toast('no open positions', 'ok');
  if (!confirm(`Close ALL ${count} open position${count === 1 ? '' : 's'}? This can't be undone.`)) return;
  const btn = $('pos-flatten');
  setBusy(btn, true);
  try {
    const r = await api('/api/trade/flatten', { method: 'POST', body: {} });
    const msg = r.failed
      ? `flatten: closed ${r.closed}/${r.total} · ${r.failed} failed`
      : `flattened ${r.closed}/${r.total}`;
    toast(msg, r.failed ? 'err' : 'ok');
    loadPositions();
  } catch (e) { toast(`flatten: ${e.message}`, 'err'); }
  finally { setBusy(btn, false, 'Flatten'); }
}
$('pos-flatten').addEventListener('click', flattenAll);

let _lastPositions = [];

async function loadPositions() {
  const body = $('positions-body');
  body.innerHTML = '<div class="empty"><span class="spinner"></span> loading…</div>';
  try {
    const r = await api('/api/trade/positions');
    const positions = r.positions || [];
    _lastPositions = positions;
    $('pos-flatten').disabled = positions.length === 0;
    refreshPositionContext();
    if (!positions.length) {
      body.innerHTML = '<div class="empty">No open positions.</div>';
      return;
    }

    // TV renders "number\nUSD" inside cells and uses Unicode minus (U+2212).
    const clean = v => String(v ?? '').replace(/\s*\n\s*/g, ' ').trim();
    const isNeg = s => /^[−-]/.test(s);
    const parseNum = v => {
      const s = clean(v);
      const m = s.match(/([−-])?([\d,]*\.?\d+)/);
      if (!m) return 0;
      return (m[1] ? -1 : 1) * parseFloat(m[2].replace(/,/g, ''));
    };
    const splitSym = v => {
      const s = clean(v);
      const i = s.indexOf(':');
      return i < 0 ? { exchange: '', symbol: s } : { exchange: s.slice(0, i), symbol: s.slice(i + 1) };
    };
    const fmtUsd = n => {
      const sign = n < 0 ? '−' : (n > 0 ? '+' : '');
      return sign + '$' + Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    };

    // Totals — unrealized P&L + gross market value.
    const totalPnl = positions.reduce((s, p) => s + parseNum(p.pl), 0);
    const totalMV = positions.reduce((s, p) => s + parseNum(p.marketValue), 0);
    const totalCls = totalPnl < 0 ? 'pnl-neg' : (totalPnl > 0 ? 'pnl-pos' : '');

    const rows = positions.map(p => {
      const { exchange, symbol } = splitSym(p.symbol);
      const pl = clean(p.pl).replace(/\s*USD$/, '');
      const plPct = clean(p.plPercent);
      const plCls = pl ? (isNeg(pl) ? 'pnl-neg' : 'pnl-pos') : '';
      const side = clean(p.side);
      const sideCls = side.toLowerCase() === 'short' ? 'short' : 'long';
      return `<tr class="pos-row">
        <td class="sym-cell">
          <div class="sym-primary">${escapeHtml(symbol)}</div>
          ${exchange ? `<div class="sym-exchange">${escapeHtml(exchange)}</div>` : ''}
        </td>
        <td><span class="side-pill ${sideCls}">${escapeHtml(side)}</span></td>
        <td class="num-col num-primary">${escapeHtml(clean(p.qty))}</td>
        <td class="num-col">
          <div class="num-primary">${escapeHtml(clean(p.avgPrice))}</div>
          <div class="num-secondary">last ${escapeHtml(clean(p.lastPrice))}</div>
        </td>
        <td class="num-col">
          <div class="num-primary ${plCls}">${escapeHtml(pl)}</div>
          ${plPct ? `<div class="num-secondary ${plCls}">${escapeHtml(plPct)}</div>` : ''}
        </td>
        <td class="num-col num-primary">${escapeHtml(clean(p.marketValue).replace(/\s*USD$/, ''))}</td>
        <td style="text-align: right; white-space: nowrap;">
          <button class="danger icon-btn" data-close="${escapeHtml(symbol)}">Close</button>
        </td>
      </tr>`;
    }).join('');

    body.innerHTML = `
      <div class="summary-strip">
        <div><span class="label">Open</span><span class="value">${positions.length}</span></div>
        <div><span class="label">Unrealized P&amp;L</span><span class="value ${totalCls}">${escapeHtml(fmtUsd(totalPnl))}</span></div>
        <div><span class="label">Market value</span><span class="value">${escapeHtml(fmtUsd(totalMV).replace(/^\+/, ''))}</span></div>
      </div>
      <table>
        <thead><tr>
          <th>Symbol</th>
          <th>Side</th>
          <th class="num-col">Qty</th>
          <th class="num-col">Avg / Last</th>
          <th class="num-col">P&amp;L</th>
          <th class="num-col">Market value</th>
          <th></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;

    body.querySelectorAll('[data-close]').forEach(b => {
      b.addEventListener('click', async () => {
        const sym = b.dataset.close;
        if (!confirm(`Close position on ${sym}?`)) return;
        setBusy(b, true);
        try {
          const r = await api('/api/trade/close', { method: 'POST', body: { symbol: sym } });
          toast(r.ok !== false ? `closed ${sym}` : `${sym}: ${r.reason || 'no-op'}`, r.ok !== false ? 'ok' : 'err');
          loadPositions();
        } catch (e) {
          toast(`close ${sym}: ${e.message}`, 'err');
          setBusy(b, false, 'Close');
        }
      });
    });
  } catch (e) {
    body.innerHTML = `<div class="empty" style="color: var(--red);">error: ${escapeHtml(e.message)}</div>`;
  }
}
$('pos-refresh').addEventListener('click', loadPositions);

// Positions auto-refresh — only while Trade tab is visible. 8s cadence
// balances freshness of P&L against the cost of opening CDP each time.
// In-flight guard prevents stacking when a refresh runs longer than the
// interval (slow CDP attach / network). Dropped ticks are fine — the
// next tick already carries fresh data.
let _posPollTimer = null;
let _posInFlight = false;
async function loadPositionsGuarded() {
  if (_posInFlight) return;
  _posInFlight = true;
  try { await loadPositions(); }
  finally { _posInFlight = false; }
}
function startPositionsPoll() {
  loadPositionsGuarded();
  if (!_posPollTimer) _posPollTimer = setInterval(loadPositionsGuarded, 8000);
}
function stopPositionsPoll() {
  if (_posPollTimer) { clearInterval(_posPollTimer); _posPollTimer = null; }
}

// ----------------------------------------------------------------------
// Watchlist tab
// ----------------------------------------------------------------------
async function loadWatchlist() {
  const body = $('watchlist-body');
  body.innerHTML = '<div class="empty"><span class="spinner"></span> loading…</div>';
  try {
    const r = await api('/api/watchlist');
    const name = r.current?.name || '—';
    $('watchlist-current').textContent = `Active list: ${name}`;
    populateSymbolCombos(r);
    const symbols = r.contents?.symbols || [];
    if (!symbols.length) { body.innerHTML = '<div class="empty">List is empty.</div>'; return; }

    const activeCount = symbols.filter(s => s.active).length;
    const exchanges = new Set(symbols.map(s => s.exchange).filter(Boolean));
    // Only show Status column if any row has a status (usually empty).
    const anyStatus = symbols.some(s => (s.status || '').trim());

    body.innerHTML = `
      <div class="summary-strip">
        <div><span class="label">Symbols</span><span class="value">${symbols.length}</span></div>
        <div><span class="label">Exchanges</span><span class="value">${exchanges.size}</span></div>
        <div><span class="label">Active</span><span class="value">${activeCount}</span></div>
      </div>
      <table>
        <thead><tr>
          <th>Symbol</th>
          ${anyStatus ? '<th>Status</th>' : ''}
          <th></th>
        </tr></thead>
        <tbody>${symbols.map(s => `<tr class="pos-row">
          <td class="sym-cell">
            <div class="sym-primary">${escapeHtml(s.symbol)}${s.active ? ' <span class="side-pill long" style="margin-left: 4px;">active</span>' : ''}</div>
            ${s.exchange ? `<div class="sym-exchange">${escapeHtml(s.exchange)}</div>` : ''}
          </td>
          ${anyStatus ? `<td class="muted">${escapeHtml(s.status || '')}</td>` : ''}
          <td style="text-align: right;"><button class="danger icon-btn" data-remove="${escapeHtml(s.symbol)}">Remove</button></td>
        </tr>`).join('')}</tbody>
      </table>`;
    body.querySelectorAll('[data-remove]').forEach(b => {
      b.addEventListener('click', async () => {
        const sym = b.dataset.remove;
        if (!confirm(`Remove ${sym} from watchlist?`)) return;
        setBusy(b, true);
        try {
          await api('/api/watchlist/remove', { method: 'POST', body: { symbol: sym } });
          toast(`removed ${sym}`);
          loadWatchlist();
        } catch (e) { toast(`remove: ${e.message}`, 'err'); setBusy(b, false, 'Remove'); }
      });
    });
  } catch (e) {
    body.innerHTML = `<div class="empty" style="color: var(--red);">error: ${escapeHtml(e.message)}</div>`;
  }
}
$('watchlist-refresh').addEventListener('click', loadWatchlist);
$('watchlist-add-btn').addEventListener('click', async (e) => {
  const btn = e.target;
  const sym = $('watchlist-add-symbol').value.trim();
  if (!sym) return toast('symbol required', 'err');
  setBusy(btn, true);
  try {
    await api('/api/watchlist/add', { method: 'POST', body: { symbol: sym } });
    toast(`added ${sym}`);
    $('watchlist-add-symbol').value = '';
    loadWatchlist();
  } catch (e) { toast(`add: ${e.message}`, 'err'); }
  finally { setBusy(btn, false, 'Add'); }
});

// ----------------------------------------------------------------------
// Alerts tab
// ----------------------------------------------------------------------
async function loadAlerts() {
  const body = $('alerts-body');
  body.innerHTML = '<div class="empty"><span class="spinner"></span> loading…</div>';
  try {
    const r = await api('/api/alerts');
    const alerts = r.alerts || [];
    if (!alerts.length) { body.innerHTML = '<div class="empty">No alerts configured.</div>'; return; }

    const splitSym = v => {
      const s = String(v || '').trim();
      const i = s.indexOf(':');
      return i < 0 ? { exchange: '', symbol: s } : { exchange: s.slice(0, i), symbol: s.slice(i + 1) };
    };
    const activeCount = alerts.filter(a => a.active !== false).length;

    body.innerHTML = `
      <div class="summary-strip">
        <div><span class="label">Alerts</span><span class="value">${alerts.length}</span></div>
        <div><span class="label">Active</span><span class="value pnl-pos">${activeCount}</span></div>
        <div><span class="label">Paused</span><span class="value">${alerts.length - activeCount}</span></div>
      </div>
      <table>
        <thead><tr>
          <th>Name</th>
          <th>Symbol</th>
          <th>Condition</th>
          <th>State</th>
          <th></th>
        </tr></thead>
        <tbody>${alerts.map(a => {
          const active = a.active !== false;
          const { exchange, symbol } = splitSym(a.symbol);
          const id = a.id || '';
          return `<tr class="pos-row">
            <td>
              <div>${escapeHtml(a.name || '—')}</div>
              ${id ? `<div class="sym-exchange" title="alert id">${escapeHtml(id)}</div>` : ''}
            </td>
            <td class="sym-cell">
              <div class="sym-primary">${escapeHtml(symbol)}</div>
              ${exchange ? `<div class="sym-exchange">${escapeHtml(exchange)}</div>` : ''}
            </td>
            <td class="muted" style="font-size: 12px;">${escapeHtml(a.condition || '')}</td>
            <td>${active ? '<span class="side-pill long">active</span>' : '<span class="side-pill short" style="background: rgba(139,148,158,0.15); color: var(--muted); border-color: var(--border);">paused</span>'}</td>
            <td style="text-align: right; white-space: nowrap;">
              <button class="icon-btn" data-toggle="${escapeHtml(id)}" data-active="${active}">${active ? 'Pause' : 'Resume'}</button>
              <button class="danger icon-btn" data-del="${escapeHtml(id)}" style="margin-left: 4px;">Delete</button>
            </td>
          </tr>`;
        }).join('')}</tbody>
      </table>`;
    body.querySelectorAll('[data-toggle]').forEach(b => {
      b.addEventListener('click', async () => {
        const id = b.dataset.toggle;
        const action = b.dataset.active === 'true' ? 'pause' : 'resume';
        setBusy(b, true);
        try {
          await api(`/api/alerts/${action}`, { method: 'POST', body: { id } });
          toast(`${action}d ${id}`);
          loadAlerts();
        } catch (e) { toast(`${action}: ${e.message}`, 'err'); setBusy(b, false); }
      });
    });
    body.querySelectorAll('[data-del]').forEach(b => {
      b.addEventListener('click', async () => {
        const id = b.dataset.del;
        if (!confirm(`Delete alert ${id}?`)) return;
        setBusy(b, true);
        try {
          await api('/api/alerts/delete', { method: 'POST', body: { id } });
          toast(`deleted ${id}`);
          loadAlerts();
        } catch (e) { toast(`delete: ${e.message}`, 'err'); setBusy(b, false, 'Delete'); }
      });
    });
  } catch (e) {
    body.innerHTML = `<div class="empty" style="color: var(--red);">error: ${escapeHtml(e.message)}</div>`;
  }
}
$('alerts-refresh').addEventListener('click', loadAlerts);

$('alert-create').addEventListener('click', async (e) => {
  const btn = e.target;
  const payload = {
    symbol: $('alert-symbol').value.trim(),
    op: $('alert-op').value,
    value: parseFloat($('alert-value').value),
    name: $('alert-name').value.trim() || null,
    message: $('alert-message').value.trim() || null,
    webhook_url: $('alert-webhook').value.trim() || null,
    notify_app: $('alert-notify-app').checked,
    notify_toast: $('alert-notify-toast').checked,
    notify_email: $('alert-notify-email').checked,
    notify_sound: $('alert-notify-sound').checked,
  };
  if (!payload.symbol || !payload.op || isNaN(payload.value)) {
    return toast('symbol, condition, value required', 'err');
  }
  setBusy(btn, true);
  try {
    const r = await api('/api/alerts/create', { method: 'POST', body: payload });
    toast(`created alert${r.id ? ' #' + r.id : ''}`);
    // Clear the form for the next entry (keep symbol — often batched).
    $('alert-value').value = '';
    $('alert-name').value = '';
    $('alert-message').value = '';
    loadAlerts();
  } catch (e) {
    toast(`create: ${e.message}`, 'err');
  } finally { setBusy(btn, false, 'Create alert'); }
});

// ----------------------------------------------------------------------
// Audit tab
// ----------------------------------------------------------------------
let auditTimer = null;
const _KNOWN_NS = ['chart', 'act', 'trading', 'alerts', 'watchlist'];
async function fetchAudit() {
  const prefix = $('audit-filter').value.trim();
  try {
    const q = new URLSearchParams({ n: '100' });
    if (prefix) q.set('event_prefix', prefix);
    const r = await api('/api/audit/tail?' + q.toString());
    const box = $('audit-log');
    const entries = r.entries || [];
    if (!entries.length) { box.innerHTML = '<div class="empty">No entries yet today.</div>'; return; }

    // Build summary: count per namespace.
    const counts = {};
    for (const e of entries) {
      const ns = (e.event || '').split('.')[0] || 'default';
      counts[ns] = (counts[ns] || 0) + 1;
    }

    const rows = entries.slice().reverse().map(e => {
      const ts = (e.ts || '').slice(11, 19);
      const event = e.event || '';
      const ns = event.split('.')[0] || 'default';
      const nsClass = _KNOWN_NS.includes(ns) ? ns : 'default';
      const rest = {};
      for (const k of Object.keys(e)) {
        if (!['ts','pid','request_id','event'].includes(k)) rest[k] = e[k];
      }
      const kind = event.endsWith('.failed') || event.endsWith('.fail') ? 'err'
                 : event.endsWith('.done') || event.endsWith('.complete') ? 'done' : '';
      return `<div class="audit-entry">
        <span class="t">${ts}</span>
        <div class="main">
          <div class="head">
            <span class="ns-pill ${nsClass}">${escapeHtml(ns)}</span>
            <span class="evname ${kind}">${escapeHtml(event.slice(ns.length + 1) || event)}</span>
            ${e.request_id ? `<span class="rid">${escapeHtml(e.request_id).slice(0, 8)}</span>` : ''}
          </div>
          ${Object.keys(rest).length ? `<div class="fields">${escapeHtml(JSON.stringify(rest))}</div>` : ''}
        </div>
      </div>`;
    }).join('');

    const summary = `<div class="summary-strip">
      <div><span class="label">Entries</span><span class="value">${entries.length}</span></div>
      ${_KNOWN_NS.filter(ns => counts[ns]).map(ns =>
        `<div><span class="label">${ns}</span><span class="value small"><span class="ns-pill ${ns}" style="min-width: 0;">${counts[ns]}</span></span></div>`
      ).join('')}
    </div>`;
    // Scroll preservation — auto-scroll to top (newest) only when the
    // user is already near the top; otherwise keep their current view
    // so they can read old entries without being yanked back.
    const nearTop = box.scrollTop < 40;
    const prevTop = box.scrollTop;
    box.innerHTML = summary + rows;
    box.scrollTop = nearTop ? 0 : prevTop;
  } catch (e) {
    // silent — keep polling
  }
}
function startAuditPoll() {
  fetchAudit();
  if ($('audit-autorefresh').checked && !auditTimer) {
    auditTimer = setInterval(fetchAudit, 2000);
  }
}
function stopAuditPoll() {
  if (auditTimer) { clearInterval(auditTimer); auditTimer = null; }
}
$('audit-autorefresh').addEventListener('change', () => {
  if ($('audit-autorefresh').checked) startAuditPoll();
  else stopAuditPoll();
});
$('audit-filter').addEventListener('input', () => fetchAudit());

// ----------------------------------------------------------------------
// Journal tab — decision log + inline reconciliation. Complement to the
// CLI: users who prefer the browser can tag outcomes without leaving.
// Shares the exact outcome taxonomy with tv_automation/reconcile.py —
// if you add a new outcome, update both here and server-side valid set.
// ----------------------------------------------------------------------
let _journalCache = [];  // last loaded list, so refresh after reconcile doesn't need a full roundtrip for the unchanged rows

function _calcRR(signal, entry, stop, tp) {
  const e = Number(entry), s = Number(stop), t = Number(tp);
  if (!Number.isFinite(e) || !Number.isFinite(s) || !Number.isFinite(t)) return null;
  if (signal === 'Long' && e > s) return (t - e) / (e - s);
  if (signal === 'Short' && s > e) return (e - t) / (s - e);
  return null;
}

function _rAutoFromOutcome(outcome, signal, entry, stop, tp) {
  if (outcome === 'hit_tp') return _calcRR(signal, entry, stop, tp);
  if (outcome === 'hit_stop') return -1.0;
  if (outcome === 'expired' || outcome === 'no_fill' || outcome === 'skip_right') return 0.0;
  return null;  // manual_close / skip_wrong — user enters
}

function _fmtR(r) {
  if (r === null || r === undefined) return '—';
  const n = Number(r);
  if (!Number.isFinite(n)) return '—';
  return (n >= 0 ? '+' : '') + n.toFixed(2) + 'R';
}

function _fmtDateShort(iso_ts) {
  // "2026-04-19T10:47:21-0400" → "04-19 10:47"
  if (!iso_ts) return '—';
  const m = iso_ts.match(/(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : iso_ts.slice(0, 16);
}

function _outcomeChoicesFor(signal) {
  // Directional signals and Skip have semantically different choices.
  // Mirrors the CLI's branch logic. Each entry: [code, label, takesR]
  // where takesR is true if we need to prompt for a manual R number.
  if (signal === 'Long' || signal === 'Short') {
    return [
      ['hit_tp',       'Hit TP',        false],
      ['hit_stop',     'Hit stop',      false],
      ['manual_close', 'Manual close',  true],
      ['expired',      'Expired',       false],
      ['no_fill',      'No fill',       false],
    ];
  }
  return [
    ['skip_right', 'Skip right',  false],
    ['skip_wrong', 'Skip wrong',  true],
  ];
}

function renderJournalRow(d) {
  const rr = _calcRR(d.signal, d.entry, d.stop, d.tp);
  const rrStr = rr !== null ? `R:R ${rr.toFixed(2)}:1` : '';
  const tf = d.optimal_tf || d.tf || '?';
  const modeTag = d.mode === 'deep' ? '<span class="pill-mini deep">deep</span>' : '';
  const sigCls = String(d.signal || 'skip').toLowerCase();
  const conf = d.confidence != null ? `${d.confidence}%` : '—';

  // Link to the post-apply chart screenshot (pine overlay drawn on
  // the chart) when the user applied this decision's pine script.
  // Clicking opens the PNG in a new tab — the "what the trader saw
  // after applying levels" image, useful for rating setups later.
  const chartLink = d.applied_screenshot_path
    ? ` <a class="journal-chart-link" target="_blank"
           href="/api/chart/image?path=${encodeURIComponent(d.applied_screenshot_path)}"
           title="Open chart screenshot (Entry/Stop/TP drawn)">chart ↗</a>`
    : '';

  const levels = (d.entry != null)
    ? `<span class="mono">E ${(+d.entry).toLocaleString()} / S ${(+d.stop).toLocaleString()} / T ${(+d.tp).toLocaleString()}</span>  <span class="muted">${rrStr}</span>${chartLink}`
    : `<span class="muted">no levels</span>${chartLink}`;

  const outcomeCell = d.outcome
    ? `<span class="outcome-tag out-${d.outcome}">${d.outcome.replace('_', ' ')}</span> <span class="mono">${_fmtR(d.realized_r)}</span>`
    : _reconcileButtonsHtml(d);

  // Learning-note row — only for reconciled decisions. Click to edit,
  // blur to save. Empty note shows a muted prompt; filled shows the
  // text. No submit button — blur-save keeps the flow frictionless.
  const noteRow = d.outcome ? `<tr class="note-row" data-request-id="${escapeHtml(d.request_id)}">
    <td colspan="2" class="muted" style="text-align: right; vertical-align: middle; font-size: var(--fs-xs);">What I learned:</td>
    <td colspan="5">
      <input type="text" class="learning-note-input"
             data-request-id="${escapeHtml(d.request_id)}"
             value="${escapeHtml(d.learning_note || '')}"
             placeholder="one-line takeaway for next time…"
             maxlength="500" />
    </td>
  </tr>` : '';

  return `<tr data-request-id="${escapeHtml(d.request_id)}" class="${d.outcome ? 'reconciled' : 'unreconciled'}">
    <td class="mono muted">${_fmtDateShort(d.iso_ts)}</td>
    <td class="mono">${escapeHtml(d.symbol || '—')}</td>
    <td class="mono">${escapeHtml(tf)} ${modeTag}</td>
    <td><span class="pill ${sigCls}">${escapeHtml(d.signal || 'Skip')}</span> <span class="mono muted">${conf}</span></td>
    <td>${levels}</td>
    <td class="mono muted">${escapeHtml((d.provider || '').split('_')[0])}/${escapeHtml(String(d.model || '').split(' ')[0])}</td>
    <td class="journal-outcome">${outcomeCell}</td>
  </tr>${noteRow}`;
}

function _reconcileButtonsHtml(d) {
  const choices = _outcomeChoicesFor(d.signal);
  return choices.map(([code, label, takesR]) => {
    const title = takesR ? `${label} (enter R)` : label;
    return `<button class="reconcile-btn" data-outcome="${code}" data-takes-r="${takesR ? 1 : 0}" title="${title}">${label}</button>`;
  }).join('');
}

async function loadJournal() {
  const unreconciledOnly = $('journal-unreconciled-only').checked;
  const endpoint = unreconciledOnly ? '/api/decisions/unreconciled?limit=100' : '/api/decisions/recent?limit=100';
  try {
    const r = await api(endpoint);
    _journalCache = r.decisions || [];
    renderJournalList();
  } catch (e) {
    $('journal-list').innerHTML = `<div class="empty">Load failed: ${escapeHtml(e.message)}</div>`;
  }
  // Parallel, fire-and-forget — calibration + rollup reloads
  // shouldn't block decision-list render. A failure in either just
  // hides its card without affecting the decision list below.
  loadCalibration();
  loadRollup();
}

// Range toggle wiring — 7d / 30d / 90d. On click, swap active class
// and reload the rollup. Defaulting to 30d because a week is too
// short for meaningful per-provider attribution (~5-10 decisions per
// provider) at typical usage.
document.querySelectorAll('#rollup-range-toggle .range-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#rollup-range-toggle .range-btn').forEach(b =>
      b.classList.toggle('active', b === btn));
    _rollupDays = parseInt(btn.dataset.days, 10) || 30;
    loadRollup();
  });
});

let _rollupDays = 30;  // default window; user toggles to 7/30/90

async function loadRollup() {
  const card = $('journal-rollup-card');
  try {
    const r = await api(`/api/decisions/rollup?days=${_rollupDays}`);
    if (!r || !r.current || r.current.total === 0) {
      // No decisions in the window — hide the card. The Journal's
      // decision list below still renders; this is just the rollup.
      card.classList.add('hidden');
      return;
    }
    card.classList.remove('hidden');
    renderRollup(r);
  } catch (e) {
    card.classList.add('hidden');
  }
}

function _deltaPill(cur, prior) {
  // Small ± pill showing week-over-week delta. Muted when either
  // period has no data. Colored by direction only when both are
  // non-zero — a new metric from 0 → 5 would mislead a % change.
  if (!prior) return '<span class="rollup-delta muted">new</span>';
  const d = cur - prior;
  if (d === 0) return '<span class="rollup-delta muted">±0</span>';
  const sign = d > 0 ? '+' : '';
  const cls = d > 0 ? 'pos' : 'neg';
  return `<span class="rollup-delta ${cls}">${sign}${d.toFixed(d % 1 === 0 ? 0 : 2)}</span>`;
}

function renderRollup(r) {
  const c = r.current, p = r.prior;
  const closes = (c.wins || 0) + (c.losses || 0);
  const winRate = closes > 0 ? Math.round((c.wins / closes) * 100) : null;
  const priorCloses = (p.wins || 0) + (p.losses || 0);
  const priorWinRate = priorCloses > 0 ? Math.round((p.wins / priorCloses) * 100) : null;

  const rSum = Number(c.realized_r_sum || 0);
  const priorRSum = Number(p.realized_r_sum || 0);
  const rCls = rSum > 0 ? 'pos' : rSum < 0 ? 'neg' : '';

  // Top-row metrics — the summary cards. Each has current value +
  // week-over-week delta so drift is immediately visible.
  const topCells = `<div class="rollup-cells">
    <div class="cell">
      <div class="n">${c.total}</div>
      <div class="label">decisions</div>
      <div class="row">${_deltaPill(c.total, p.total)}</div>
    </div>
    <div class="cell">
      <div class="n ${rCls}">${(rSum >= 0 ? '+' : '') + rSum.toFixed(2)}R</div>
      <div class="label">realized</div>
      <div class="row">${_deltaPill(rSum, priorRSum)}</div>
    </div>
    <div class="cell">
      <div class="n">${c.wins}–${c.losses}${winRate !== null ? `  <span class="muted">(${winRate}%)</span>` : ''}</div>
      <div class="label">W–L</div>
      <div class="row">${priorWinRate !== null && winRate !== null ? _deltaPill(winRate, priorWinRate) + '<span class="muted" style="font-size:var(--fs-xs);"> pp</span>' : '<span class="rollup-delta muted">—</span>'}</div>
    </div>
    <div class="cell">
      <div class="n pos">${c.best_r != null ? '+' + Number(c.best_r).toFixed(2) + 'R' : '—'}</div>
      <div class="label">best trade</div>
    </div>
    <div class="cell">
      <div class="n neg">${c.worst_r != null && c.worst_r < 0 ? Number(c.worst_r).toFixed(2) + 'R' : '—'}</div>
      <div class="label">worst trade</div>
    </div>
    ${c.overrides > 0 ? `<div class="cell">
      <div class="n muted">${c.overrides}</div>
      <div class="label">overrode AI</div>
    </div>` : ''}
  </div>`;

  // Per-provider attribution. Who made you money, who lost you money?
  // Ordered by r_sum desc so the most profitable appears first. Skip
  // rendering if only one provider was used (no attribution value).
  let providerSection = '';
  if (Array.isArray(r.per_provider) && r.per_provider.length > 1) {
    const rows = r.per_provider.map(pp => {
      const rSum = Number(pp.r_sum || 0);
      const rAvg = Number(pp.r_avg || 0);
      const rCls = rSum > 0 ? 'pos' : rSum < 0 ? 'neg' : '';
      const closes = (pp.wins || 0) + (pp.losses || 0);
      const winPct = closes > 0 ? Math.round((pp.wins / closes) * 100) : null;
      return `<tr>
        <td class="mono">${escapeHtml((pp.provider || '').split('_')[0])}/<strong>${escapeHtml(String(pp.model || '').split(' ')[0])}</strong></td>
        <td class="mono num">${pp.total}</td>
        <td class="mono num">${pp.closed}</td>
        <td class="mono num">${winPct !== null ? `${pp.wins}–${pp.losses} (${winPct}%)` : '—'}</td>
        <td class="mono num ${rCls}">${(rSum >= 0 ? '+' : '') + rSum.toFixed(2)}R</td>
        <td class="mono num muted">${rAvg ? (rAvg >= 0 ? '+' : '') + rAvg.toFixed(2) + 'R' : '—'}</td>
      </tr>`;
    }).join('');
    providerSection = `<div class="rollup-providers">
      <div class="rollup-section-head">Per-provider attribution</div>
      <table class="rollup-table">
        <thead><tr>
          <th>Model</th><th class="num">Decisions</th><th class="num">Closed</th>
          <th class="num">W–L</th><th class="num">R sum</th><th class="num">R avg</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }

  // Period label so it's unambiguous what window the numbers cover.
  const cur_date = new Date(r.cur_start_ts * 1000);
  const periodLabel = `last ${r.days} day${r.days === 1 ? '' : 's'} — since ${cur_date.toISOString().slice(0, 10)}`;

  $('rollup-body').innerHTML = `<div class="rollup-period muted">${periodLabel}</div>
    ${topCells}
    ${providerSection}`;
}

async function loadCalibration() {
  const card = $('journal-calibration-card');
  try {
    const r = await api('/api/decisions/calibration');
    const summary = r.summary || [];
    if (!summary.length) {
      // No reconciled directional decisions yet — hide the card entirely.
      // The Decision list below will still show with its empty-state
      // message; surfacing an empty calibration card would be noise.
      card.classList.add('hidden');
      return;
    }
    card.classList.remove('hidden');
    renderCalibration(summary);
  } catch (e) {
    card.classList.add('hidden');
  }
}

function renderCalibration(summary) {
  // Sort: biggest sample sizes first — most-trusted rows float to top.
  // Ties broken by avg_r so good performers outrank bad ones at same n.
  const rows = summary.slice().sort((a, b) => {
    if (b.n !== a.n) return b.n - a.n;
    return (b.avg_r || 0) - (a.avg_r || 0);
  });

  const totalN = rows.reduce((s, r) => s + r.n, 0);
  const distinctModels = new Set(rows.map(r => `${r.provider}/${r.model}`)).size;
  $('calibration-stats').textContent =
    `${totalN} reconciled · ${distinctModels} model${distinctModels === 1 ? '' : 's'}`;

  // Confidence-bucket ordering for the visual bar position — not the
  // row order. Higher buckets render at the right end of their
  // per-model strip.
  const bucketOrder = ['low (<50)', '50-59', '60-69', '70-79', '80+'];

  const tbody = rows.map(r => {
    const hitPct = r.hit_rate != null ? Math.round(r.hit_rate * 100) : null;
    const trustable = r.n >= 5;
    const hitCell = hitPct === null
      ? '<span class="muted">—</span>'
      : `<span class="mono ${_hitRateClass(hitPct, trustable)}">${hitPct}%</span>${!trustable ? ' <span class="muted" style="font-style:italic;">pending</span>' : ''}`;
    const rStr = r.avg_r != null ? _fmtR(r.avg_r) : '—';
    const bar = _calibrationBar(hitPct, trustable);

    // Override cell — "how often I chose NOT to follow this AI's call."
    // High override rate isn't inherently bad (the AI might be wrong
    // about *this setup* even if it's generally right), but it's worth
    // seeing. Color scale: >40% override = amber signal (are you
    // actually trusting this AI?), >60% = red (consider switching).
    // Rendered muted when sample is small, same convention as hit rate.
    const overridePct = r.override_rate != null ? Math.round(r.override_rate * 100) : null;
    const overrideTrustable = r.n_total >= 5;
    const overrideCell = overridePct === null
      ? '<span class="muted">—</span>'
      : `<span class="mono ${_overrideRateClass(overridePct, overrideTrustable)}">${overridePct}%</span> <span class="muted">(${r.n_overrides}/${r.n_total})</span>`;

    return `<tr>
      <td class="mono">${escapeHtml(r.provider.split('_')[0])}/<strong>${escapeHtml(String(r.model).split(' ')[0])}</strong></td>
      <td class="mono">${escapeHtml(r.bucket)}</td>
      <td class="mono">n=${r.n}</td>
      <td>${bar}</td>
      <td class="num">${hitCell}</td>
      <td class="num mono ${(r.avg_r || 0) >= 0 ? 'pos' : 'neg'}">${rStr}</td>
      <td class="num">${overrideCell}</td>
    </tr>`;
  }).join('');

  $('calibration-body').innerHTML = `<table class="calibration-table">
    <thead><tr>
      <th>Model</th><th>Bucket</th><th class="num">Sample</th>
      <th>Hit rate</th><th class="num">Rate</th><th class="num">Avg R</th>
      <th class="num" title="How often you skipped this AI's actionable Long/Short signal">Override</th>
    </tr></thead>
    <tbody>${tbody}</tbody>
  </table>`;
}

function _overrideRateClass(overridePct, trustable) {
  // Lower override rate = more trust in the AI = neutral/positive.
  // Higher override rate = warning. Scale inverts the hit-rate scale
  // because "high override" is what we're flagging, not rewarding.
  if (!trustable) return 'muted';
  if (overridePct <= 20) return '';       // default color — you trust it
  if (overridePct <= 40) return 'muted';  // middle — mild flag
  if (overridePct <= 60) return 'warn';   // amber — are you trusting this AI?
  return 'neg';                            // red — why is it in the dropdown?
}

function _hitRateClass(hitPct, trustable) {
  if (!trustable) return 'muted';
  if (hitPct >= 60) return 'pos';
  if (hitPct >= 40) return 'warn';
  return 'neg';
}

// Horizontal progress-bar visual for hit rate. CSS handles the color
// so this just emits the markup. Rendered as two overlaid divs so
// the filled portion can tint independently from the track.
function _calibrationBar(hitPct, trustable) {
  if (hitPct === null) {
    return '<div class="cal-bar cal-bar--empty"></div>';
  }
  const fillClass = !trustable
    ? 'cal-bar-fill cal-pending'
    : hitPct >= 60 ? 'cal-bar-fill cal-good'
    : hitPct >= 40 ? 'cal-bar-fill cal-mid'
    : 'cal-bar-fill cal-bad';
  return `<div class="cal-bar">
    <div class="${fillClass}" style="width: ${hitPct}%"></div>
  </div>`;
}

function renderJournalList() {
  const rows = _journalCache;
  const total = rows.length;
  const unreconciled = rows.filter(d => !d.outcome).length;
  $('journal-stats').textContent = total
    ? `${total} shown · ${unreconciled} unreconciled`
    : '';

  if (!total) {
    $('journal-list').innerHTML = '<div class="empty">No decisions yet. Run an Analyze or Deep to start the log.</div>';
    return;
  }

  $('journal-list').innerHTML = `<table class="journal-table">
    <thead><tr>
      <th>When</th><th>Sym</th><th>TF</th>
      <th>Signal</th><th>Levels</th><th class="muted">Model</th>
      <th>Outcome</th>
    </tr></thead>
    <tbody>${rows.map(renderJournalRow).join('')}</tbody>
  </table>`;

  // Learning-note inputs — blur to save. Only fires a PATCH when the
  // value actually changed, so a user tabbing past an unchanged note
  // doesn't trigger a roundtrip. Enter also blurs to save.
  document.querySelectorAll('.learning-note-input').forEach(input => {
    const original = input.value;
    const commit = async () => {
      const rid = input.dataset.requestId;
      const val = input.value.trim();
      if (val === (original || '').trim()) return;  // no-op on unchanged
      try {
        await api(`/api/decisions/learning/${encodeURIComponent(rid)}`, {
          method: 'POST',
          body: { note: val },
        });
        // Update the local cache so future re-renders keep the note.
        const d = _journalCache.find(x => x.request_id === rid);
        if (d) d.learning_note = val || null;
        toast(val ? 'note saved' : 'note cleared', 'ok');
      } catch (e) {
        toast(`save failed: ${e.message}`, 'err');
      }
    };
    input.addEventListener('blur', commit);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') input.blur();
      if (e.key === 'Escape') { input.value = original; input.blur(); }
    });
  });

  // Wire up reconcile buttons per row. Delegation would save event
  // listeners but each button needs access to its row's request_id
  // and its own data-takes-r — inline binding is clearer and the
  // rowcount is bounded (≤100).
  document.querySelectorAll('.reconcile-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const tr = btn.closest('tr');
      const rid = tr.dataset.requestId;
      const outcome = btn.dataset.outcome;
      const takesR = btn.dataset.takesR === '1';
      let realizedR = null;
      if (takesR) {
        const prompt_label = outcome === 'skip_wrong'
          ? 'Missed opportunity in R (positive):'
          : 'Realized R (e.g. 1.5 or -0.3):';
        const raw = prompt(prompt_label);
        if (raw === null) return;  // user cancelled
        const parsed = parseFloat(raw);
        if (!Number.isFinite(parsed)) {
          toast(`not a number: ${raw}`, 'err');
          return;
        }
        realizedR = parsed;
      } else {
        const d = _journalCache.find(x => x.request_id === rid);
        realizedR = _rAutoFromOutcome(outcome, d?.signal, d?.entry, d?.stop, d?.tp);
      }
      setBusy(btn, true);
      try {
        await api(`/api/decisions/reconcile/${encodeURIComponent(rid)}`, {
          method: 'POST',
          body: { outcome, realized_r: realizedR },
        });
        // Optimistic local update — avoid a full re-fetch for one row.
        const d = _journalCache.find(x => x.request_id === rid);
        if (d) {
          d.outcome = outcome;
          d.realized_r = realizedR;
        }
        toast(`tagged: ${outcome} ${_fmtR(realizedR)}`, 'ok');
        renderJournalList();
        // Update the calibration card (new data point landed) + the
        // session strip if the Trade tab peeks at it.
        loadCalibration();
        refreshSessionStrip();
      } catch (e) {
        toast(`reconcile failed: ${e.message}`, 'err');
        setBusy(btn, false, btn.textContent);
      }
    });
  });
}

$('journal-refresh').addEventListener('click', loadJournal);
$('journal-unreconciled-only').addEventListener('change', loadJournal);

// End-of-day reconciliation — grades all today's unreconciled
// decisions against real OHLCV bars (yfinance) and writes outcomes
// back to the DB. First-touch of stop vs TP; pessimistic tie-break.
$('journal-reconcile-eod').addEventListener('click', async () => {
  const btn = $('journal-reconcile-eod');
  if (!confirm("Grade today's unreconciled decisions against real price bars? This will write outcomes + realized R to the journal.")) return;
  setBusy(btn, true);
  try {
    const r = await api('/api/decisions/reconcile-eod', {
      method: 'POST', body: {},
    });
    const c = r.counts || {};
    const win = r.win_rate !== null && r.win_rate !== undefined
        ? `${(r.win_rate * 100).toFixed(1)}%` : '—';
    const totalR = r.total_r !== undefined ? r.total_r.toFixed(2) : '?';
    const msg = `reconciled ${c.total} · ${c.hit_tp}W/${c.hit_stop}L · `
              + `win ${win} · ${totalR > 0 ? '+' : ''}${totalR}R`
              + (c.expired ? ` · ${c.expired} expired` : '')
              + (c.ungraded ? ` · ${c.ungraded} ungraded` : '');
    toast(msg, c.hit_tp + c.expired >= c.hit_stop ? 'ok' : 'warn');
    loadJournal();
  } catch (e) {
    toast(`reconcile-eod: ${e.message}`, 'err');
  } finally {
    setBusy(btn, false, 'Reconcile today');
  }
});

// CSV export — bypass api() because we want the raw text response
// (not JSON-parsed) and to trigger a file download. Reuses the
// existing auth token from localStorage; same trust boundary as any
// other authenticated request.
$('journal-export-csv').addEventListener('click', async () => {
  const btn = $('journal-export-csv');
  setBusy(btn, true);
  try {
    const headers = { 'X-UI': '1' };
    try {
      const token = localStorage.getItem('ios-ui-token');
      if (token) headers['X-UI-Token'] = token;
    } catch (e) { /* private mode */ }
    const r = await fetch('/api/decisions/export.csv', { headers });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const blob = await r.blob();

    // Pull the server-suggested filename out of Content-Disposition
    // so "repeated exports same day" gets the right date-stamped name.
    // Falls back to a generic name if the header is missing or malformed.
    const cd = r.headers.get('content-disposition') || '';
    const match = cd.match(/filename="?([^";]+)"?/i);
    const fname = match ? match[1] : 'intelligenceos-decisions.csv';

    // Object-URL + <a download> is the canonical Blob-to-file pattern.
    // Revoking the URL after the click releases the memory.
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fname;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    toast(`exported ${fname}`, 'ok');
  } catch (e) {
    toast(`export failed: ${e.message}`, 'err');
  } finally {
    setBusy(btn, false, 'Export CSV');
  }
});

// ----------------------------------------------------------------------
// Initial load
// ----------------------------------------------------------------------
refreshChartMeta();
setupCombo('trade-symbol');
setupCombo('alert-symbol');
populateSymbolCombos();  // fire-and-forget — fills all three combos from watchlist
