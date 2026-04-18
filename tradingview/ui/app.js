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
    if (tab === 'trade') startPositionsPoll(); else stopPositionsPoll();
    if (tab === 'chart') refreshMetadata();
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
// Chart tab
// ----------------------------------------------------------------------
function renderMetadata(meta) {
  // Split "CME_MINI:MNQ1!" → "MNQ1!" + "CME_MINI" muted. Interval as a badge.
  const fullSym = meta.symbol || '';
  const idx = fullSym.indexOf(':');
  const sym = idx < 0 ? fullSym : fullSym.slice(idx + 1);
  const exch = idx < 0 ? '' : fullSym.slice(0, idx);
  $('chart-meta').innerHTML = `
    <div>
      <span class="label">Symbol</span>
      <span class="value">${escapeHtml(sym || '—')}</span>
      ${exch ? `<span class="muted mono" style="font-size: 11px; margin-left: 6px;">${escapeHtml(exch)}</span>` : ''}
    </div>
    <div><span class="label">Interval</span><span class="value">${escapeHtml(meta.interval || '—')}</span></div>
    ${meta.title ? `<div class="grow" style="flex: 1; min-width: 0;"><span class="label">Title</span><span class="value small" style="word-break: break-word;">${escapeHtml(meta.title)}</span></div>` : ''}
  `;
  $('chart-meta-url').textContent = meta.url || '—';
}
async function refreshMetadata() {
  try {
    const meta = await api('/api/chart/metadata');
    renderMetadata(meta);
  } catch (e) { toast(`metadata: ${e.message}`, 'err'); }
}
$('chart-meta-refresh').addEventListener('click', refreshMetadata);

$('chart-set').addEventListener('click', async (e) => {
  const btn = e.target;
  const symbol = $('chart-symbol').value.trim();
  const interval = $('chart-tf').value || null;
  if (!symbol) return toast('symbol required', 'err');
  setBusy(btn, true);
  try {
    const meta = await api('/api/chart/set-symbol', { method: 'POST', body: { symbol, interval } });
    renderMetadata(meta);
    toast(`set to ${meta.symbol} ${meta.interval}`);
  } catch (e) { toast(`set-symbol: ${e.message}`, 'err'); }
  finally { setBusy(btn, false, 'Set symbol'); }
});

$('chart-shoot').addEventListener('click', async (e) => {
  const btn = e.target;
  const area = $('chart-area').value;
  setBusy(btn, true);
  try {
    const r = await api('/api/chart/screenshot', { method: 'POST', body: { area } });
    const box = $('chart-shot');
    const file = (r.path || '').split('/').pop();
    box.innerHTML = `
      <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px; font-size: 12px;">
        <span class="badge ${r.fell_back ? 'yellow' : ''}">${escapeHtml(r.area)}${r.fell_back ? ' · fallback' : ''}</span>
        <span class="mono">${escapeHtml(r.symbol)} ${escapeHtml(r.interval)}</span>
        <span class="muted mono" style="margin-left: auto; font-size: 11px;" title="${escapeHtml(r.path)}">${escapeHtml(file)}</span>
      </div>
      <img class="screenshot" src="${r.url}" alt="chart screenshot" />
    `;
  } catch (e) { toast(`screenshot: ${e.message}`, 'err'); }
  finally { setBusy(btn, false, 'Capture'); }
});

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
// Trade tab
// ----------------------------------------------------------------------
async function placeOrder(side) {
  const symbol = $('trade-symbol').value.trim();
  const qty = +$('trade-qty').value;
  const dry_run = $('trade-dry-run').checked;
  if (!symbol || !qty) return toast('symbol + qty required', 'err');
  const confirmMsg = dry_run
    ? `DRY-RUN: ${side.toUpperCase()} ${qty} ${symbol}?`
    : `Confirm ${side.toUpperCase()} ${qty} ${symbol} (paper)?`;
  if (!confirm(confirmMsg)) return;
  const btn = side === 'buy' ? $('trade-buy') : $('trade-sell');
  setBusy(btn, true);
  try {
    const r = await api('/api/trade/order', { method: 'POST', body: { symbol, side, qty, dry_run } });
    toast(`${r.ok ? '✓' : '✗'} ${side.toUpperCase()} ${qty} ${symbol}${dry_run ? ' (dry-run)' : ''}`, r.ok ? 'ok' : 'err');
    loadPositions();
  } catch (e) { toast(`order: ${e.message}`, 'err'); }
  finally { setBusy(btn, false, side === 'buy' ? 'BUY market' : 'SELL market'); }
}
$('trade-buy').addEventListener('click', () => placeOrder('buy'));
$('trade-sell').addEventListener('click', () => placeOrder('sell'));

async function loadPositions() {
  const body = $('positions-body');
  body.innerHTML = '<div class="empty"><span class="spinner"></span> loading…</div>';
  try {
    const r = await api('/api/trade/positions');
    const positions = r.positions || [];
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
refreshMetadata();
setupCombo('chart-symbol');
setupCombo('trade-symbol');
setupCombo('alert-symbol');
populateSymbolCombos();  // fire-and-forget — fills all three combos from watchlist
