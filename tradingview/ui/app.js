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
    if (tab === 'trade') { startPositionsPoll(); refreshChartMeta(); } else stopPositionsPoll();
    if (tab === 'watchlist') loadWatchlist();
    if (tab === 'alerts') loadAlerts();
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

function renderAnalysisResult(r) {
  hideAnalyzeProgress();
  clearAnalyzeError();
  $('analyze-result').classList.remove('hidden');

  const sig = String(r.signal || 'Skip');
  const sigCls = sig.toLowerCase();
  const pill = $('analyze-signal-pill');
  pill.textContent = sig;
  pill.className = `analyze-signal ${sigCls}`;

  const conf = Math.max(0, Math.min(100, +r.confidence || 0));
  $('analyze-confidence-val').textContent = `${conf}%`;
  $('analyze-confidence-fill').style.width = `${conf}%`;

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
  const pineBtn = $('analyze-apply-pine');
  if (r.pine_path) {
    pineBtn.disabled = false;
    pineBtn.onclick = async () => {
      if (!confirm('Paste this analysis pine script into TradingView? Takes ~20s and takes over the chart view briefly.')) return;
      setBusy(pineBtn, true);
      try {
        const ar = await api('/api/analyze/apply-pine', { method: 'POST', body: { path: r.pine_path } });
        if (ar.ok) toast('pine applied to chart', 'ok');
        else toast(`pine apply failed: ${(ar.stderr || 'see server log').slice(-200)}`, 'err');
      } catch (e) { toast(`apply-pine: ${e.message}`, 'err'); }
      finally { setBusy(pineBtn, false, 'Apply pine to chart'); }
    };
  } else {
    pineBtn.disabled = true;
    pineBtn.onclick = null;
  }

  $('analyze-rationale').textContent = r.rationale || '';

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
      } else if (ev === 'analyze.done') {
        phase = 'done';
      } else if (ev === 'analyze.fail' || ev === 'analyze.parse_fail') {
        phase = `failed: ${e.error || e.raw_head || ''}`;
      }
    }

    const done = doneTfs.size;
    const isDeep = total > 1;

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

    if (status.state === 'running') {
      setAnalyzeProgress(phase, detail, pct);
    } else if (status.state === 'done') {
      stopAnalyzePoll();
      renderAnalysisResult(status.result || {});
      setAnalyzeBusy(null);
    } else if (status.state === 'failed') {
      stopAnalyzePoll();
      showAnalyzeError(`${status.error || 'analysis failed'}`);
      setAnalyzeBusy(null);
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

// Deep analysis — captures all 9 timeframes and asks the LLM to pick
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

// Provider → model control swap. Ollama has an open-ended model zoo
// (text input) while claude.ai exposes a fixed three-tier dropdown. We
// show exactly one at a time and read from the visible one at submit.
function _syncAnalyzeModelControl() {
  const isClaudeWeb = $('analyze-provider').value === 'claude_web';
  $('analyze-model').classList.toggle('hidden', isClaudeWeb);
  $('analyze-model-claude').classList.toggle('hidden', !isClaudeWeb);
}
function _analyzeModelValue() {
  if ($('analyze-provider').value === 'claude_web') {
    return $('analyze-model-claude').value || null;
  }
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
// Initial load
// ----------------------------------------------------------------------
refreshChartMeta();
setupCombo('trade-symbol');
setupCombo('alert-symbol');
populateSymbolCombos();  // fire-and-forget — fills all three combos from watchlist
