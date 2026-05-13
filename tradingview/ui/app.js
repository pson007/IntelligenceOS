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
    // Mirror the token into a same-origin cookie so plain browser
    // requests (<img>, <a href>) authenticate under Tailscale Serve.
    // fetch() still sets X-UI-Token explicitly; this only covers the
    // requests JS can't attach a header to. SameSite=Strict blocks CSRF.
    const tok = localStorage.getItem('ios-ui-token');
    if (tok) {
      const secure = location.protocol === 'https:' ? '; Secure' : '';
      document.cookie = `ios-ui-token=${encodeURIComponent(tok)}; path=/; SameSite=Strict; max-age=31536000${secure}`;
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
    let msg = (data && (data.detail || data.error)) || `HTTP ${r.status}`;
    // FastAPI's HTTPException(status, {dict}) wraps the dict under
    // {"detail": <dict>} — surface the inner "detail" string when present
    // so toasts show "kill-switch engaged" instead of "[object Object]".
    if (msg && typeof msg === 'object') {
      msg = msg.detail || msg.error || JSON.stringify(msg);
    }
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
  [/kill-switch engaged/i,
    'Workspace is paused. Click the red PAUSED pill in the sidebar to resume.'],
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
// Mobile detection — combines four signals so we pick the right UI
// regardless of how the app was opened (Electron, desktop browser,
// phone browser, narrow window, iPad in desktop-mode):
//
//   1. Viewport ≤ 768px → mobile. Catches real phones AND any browser
//      window someone resized down (responsive design).
//   2. User-agent contains iPhone|iPad|iPod|Android|Mobile → mobile,
//      even on wide viewports. Catches iPad in portrait split-view.
//   3. iPad-in-desktop-mode trick — iPadOS ≥ 13 reports a Mac UA by
//      default. We sniff `Macintosh` UA + `maxTouchPoints > 1` (Macs
//      with magic trackpads report 0; only true touchscreen Macs +
//      iPads have this). Avoids false-positives on regular Macs.
//   4. Otherwise → desktop. Includes Electron, desktop Chrome,
//      desktop Safari/Firefox on real Macs.
//
// The class is set on `<html>` (documentElement), not <body>: the
// pre-paint inline script in <head> needs a target, and <body>
// doesn't exist at head-parse time. The pre-paint script eliminates
// the desktop→mobile flash on first iPhone load.
//
// CSS consumes `html.is-mobile` selectors for all mobile styles.
// One toggle, four triggers, zero FOUC.
// ----------------------------------------------------------------------
const _mobileMQ = window.matchMedia('(max-width: 768px)');
const _MOBILE_UA_RX = /\b(iPhone|iPad|iPod|Android|Mobile)\b/i;
const _IPAD_DESKTOP_MODE = /\bMacintosh\b/.test(navigator.userAgent)
  && navigator.maxTouchPoints > 1;
const _IS_MOBILE_DEVICE = _MOBILE_UA_RX.test(navigator.userAgent)
  || _IPAD_DESKTOP_MODE;
function _applyMobileClass(narrowViewport) {
  const shouldBeMobile = !!narrowViewport || _IS_MOBILE_DEVICE;
  document.documentElement.classList.toggle('is-mobile', shouldBeMobile);
}
_applyMobileClass(_mobileMQ.matches);
_mobileMQ.addEventListener('change', e => _applyMobileClass(e.matches));

// ----------------------------------------------------------------------
// Navigation icons — inline SVG (feather-style) replacing the old Unicode
// glyph spans. Swapped at page-load into every [data-tab] button's icon
// slot (both sidebar .nav-item and bottom tab bar .mtab).
// ----------------------------------------------------------------------
const _NAV_ICONS = {
  today: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>',
  plan: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"/></svg>',
  journal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>',
  setup: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
};
document.querySelectorAll('.nav-item[data-tab]').forEach(btn => {
  const slot = btn.querySelector('.ico');
  const svg = _NAV_ICONS[btn.dataset.tab];
  if (slot && svg) slot.innerHTML = svg;
});
document.querySelectorAll('.mtab[data-tab]').forEach(btn => {
  const slot = btn.querySelector('.mtab__ico');
  const svg = _NAV_ICONS[btn.dataset.tab];
  if (slot && svg) slot.innerHTML = svg;
});
// Delegated handler for mobile drill-in back buttons (Forecasts, Profiles).
// Clicking removes the `mobile-view-detail` class from the named layout
// container, returning the user to the list. Works after innerHTML
// replacements because we re-emit the back button each render.
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.mobile-back-btn');
  if (!btn) return;
  const layoutId = btn.dataset.target;
  const layout = layoutId ? document.getElementById(layoutId) : null;
  if (layout) layout.classList.remove('mobile-view-detail');
});

// ----------------------------------------------------------------------
// Sidebar collapse (mobile) — show/hide the tabs + status strip. Desktop
// ignores the state via CSS, so stored "collapsed" never breaks desktop.
// ----------------------------------------------------------------------
const _sidebar = document.querySelector('.sidebar');
const _sidebarToggle = $('sidebar-toggle');

function applySidebarCollapsed(collapsed) {
  _sidebar.classList.toggle('collapsed', collapsed);
  // Icon shows the destination of a tap (same convention as theme toggle).
  _sidebarToggle.textContent = collapsed ? '☰' : '✕';
  _sidebarToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
}

// Mobile starts collapsed — the bottom .mobile-tabbar already exposes the
// same primary nav, so the expanded sidebar strip is just duplicated nav
// + a "connected" status row eating ~120pt of precious vertical space on a
// phone. Desktop still starts expanded since there's no replacement nav.
// Session-only either way; the toggle button flips it within a tab.
applySidebarCollapsed(_mobileMQ.matches || _IS_MOBILE_DEVICE);
try { localStorage.removeItem('ios-sidebar-collapsed'); } catch (e) {}

_sidebarToggle.addEventListener('click', () => {
  const next = !_sidebar.classList.contains('collapsed');
  applySidebarCollapsed(next);
});

// ----------------------------------------------------------------------
// Tab switching — 4 primary groups (Today / Plan / Journal / Setup). Some
// groups are aliases for a default sub-tab plus an in-page sub-tab bar
// that reveals the other members of the group. The sub-tab rendering
// stays outside .tab sections so the existing sections (tab-forecasts,
// tab-profiles, tab-audit, tab-watchlist, tab-alerts, tab-act) don't
// need to be physically restructured — the group layer only reroutes.
// ----------------------------------------------------------------------
// Setup's default sub depends on whether the user has finished the
// onboarding wizard. First-time users land on 'onboarding'; returning
// users (flag set) land on 'audit'. A dedicated 'Wizard' sub-tab stays
// available so power users can re-run setup any time.
function _onboardingDone() {
  try { return localStorage.getItem('onboarding-complete') === '1'; }
  catch (e) { return false; }
}
function _setupDefault() {
  return _onboardingDone() ? 'audit' : 'onboarding';
}
const TAB_GROUPS = {
  today:   { default: 'today',     subs: [] },
  plan:    { default: 'forecasts', subs: [
              { id: 'forecasts', label: 'Forecast' },
              { id: 'coach',     label: 'Coach' },
              { id: 'profiles',  label: 'Profile' },
            ] },
  journal: { default: 'journal',   subs: [] },
  setup:   { get default() { return _setupDefault(); }, subs: [
              { id: 'onboarding', label: 'Wizard' },
              { id: 'audit',      label: 'Activity' },
              { id: 'watchlist',  label: 'Watchlist' },
              { id: 'alerts',     label: 'Alerts' },
              { id: 'act',        label: 'Act' },
            ] },
};

// Last-active sub per group — so returning to a group after leaving lands
// back on the same sub-tab the user was on (iOS-style recency memory).
const _groupLastSub = {};

function _syncMobileTabbarActive(group) {
  document.querySelectorAll('.mtab').forEach(m => {
    m.classList.toggle('active', m.dataset.tab === group);
  });
}

function _renderSubtabBar(group, activeSub) {
  const bar = document.getElementById('subtab-bar');
  if (!bar) return;
  const grp = TAB_GROUPS[group];
  if (!grp || grp.subs.length === 0) {
    bar.classList.add('hidden');
    bar.innerHTML = '';
    return;
  }
  bar.classList.remove('hidden');
  bar.innerHTML = grp.subs.map(s =>
    `<button type="button" class="subtab${s.id === activeSub ? ' active' : ''}" data-sub="${s.id}" role="tab">${s.label}</button>`
  ).join('');
  bar.querySelectorAll('.subtab').forEach(btn => {
    btn.addEventListener('click', () => activateGroup(group, btn.dataset.sub));
  });
}

function _fireTabHook(sub) {
  if (sub === 'audit') startAuditPoll(); else stopAuditPoll();
  if (sub === 'today') { startPositionsPoll(); refreshChartMeta(); refreshSessionStrip(); loadTradeLessons(); renderTodayArc(); loadTodayDecisions(); } else stopPositionsPoll();
  if (sub === 'watchlist') loadWatchlist();
  if (sub === 'alerts') loadAlerts();
  if (sub === 'journal') { loadJournal(); initDayArc(); }
  if (sub === 'profiles') { loadProfiles(); initProfileRun(); }
  if (sub === 'forecasts') { loadForecasts(); initForecastRun(); }
  if (sub === 'coach') { initCoachTab(); refreshSketchpad(); }
  if (sub === 'onboarding') initWizard();
}

function activateGroup(group, sub = null) {
  const grp = TAB_GROUPS[group];
  if (!grp) return;
  const targetSub = sub || _groupLastSub[group] || grp.default;
  _groupLastSub[group] = targetSub;

  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === group);
  });

  document.querySelectorAll('.tab').forEach(t => {
    t.classList.toggle('hidden', t.id !== `tab-${targetSub}`);
  });

  const activeTab = document.getElementById(`tab-${targetSub}`);
  if (activeTab) {
    activeTab.classList.remove('tab-entering');
    void activeTab.offsetWidth;
    activeTab.classList.add('tab-entering');
    setTimeout(() => activeTab.classList.remove('tab-entering'), 300);
  }

  _syncMobileTabbarActive(group);
  _renderSubtabBar(group, targetSub);

  document.querySelectorAll('.mobile-view-detail').forEach(el => el.classList.remove('mobile-view-detail'));

  _fireTabHook(targetSub);
}

document.querySelectorAll('.nav-item[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => activateGroup(btn.dataset.tab));
});

document.querySelectorAll('.mtab[data-tab]').forEach(btn => {
  btn.addEventListener('click', () => activateGroup(btn.dataset.tab));
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

// Kill-switch — single sidebar control that pauses every CDP-bound
// workflow + scheduled run. State polled every 8s; UI swaps the
// "Pause" button for a red "PAUSED" pill when engaged.
async function refreshKillSwitch() {
  try {
    const r = await fetch('/api/admin/state', { headers: { 'X-UI': '1' } });
    if (!r.ok) return;
    const data = await r.json();
    const paused = !!data.paused;
    $('kill-switch-pause').classList.toggle('hidden', paused);
    $('kill-switch-resume').classList.toggle('hidden', !paused);
    if (paused && data.state) {
      const since = data.state.since || '';
      const reason = data.state.reason || '';
      $('kill-switch-resume').title =
        `Paused since ${since}${reason ? ' — ' + reason : ''}. Click to resume.`;
    }
    // Mirror to topbar — same data, two surfaces.
    const tPause = document.getElementById('topbar-kill-pause');
    const tResume = document.getElementById('topbar-kill-resume');
    if (tPause)  tPause.classList.toggle('hidden', paused);
    if (tResume) tResume.classList.toggle('hidden', !paused);
    if (tResume && paused && data.state) {
      const since = data.state.since || '';
      const reason = data.state.reason || '';
      tResume.title =
        `Paused since ${since}${reason ? ' — ' + reason : ''}. Click to resume.`;
    }
  } catch (e) { /* silent — health poll will surface server-down */ }
}
async function _killPause() {
  const reason = (prompt('Pause every workflow. Reason (optional):') ?? '').trim();
  if (reason === null) return;
  try {
    const r = await api('/api/admin/pause', { method: 'POST', body: { reason } });
    if (r.ok) { toast('workspace paused', 'ok'); refreshKillSwitch(); }
  } catch (e) { toast(`pause failed: ${e.message}`, 'err'); }
}
async function _killResume() {
  try {
    const r = await api('/api/admin/resume', { method: 'POST', body: {} });
    if (r.ok) { toast('workspace resumed', 'ok'); refreshKillSwitch(); }
  } catch (e) { toast(`resume failed: ${e.message}`, 'err'); }
}
$('kill-switch-pause')?.addEventListener('click', _killPause);
$('kill-switch-resume')?.addEventListener('click', _killResume);
document.getElementById('topbar-kill-pause')?.addEventListener('click', _killPause);
document.getElementById('topbar-kill-resume')?.addEventListener('click', _killResume);
setInterval(refreshKillSwitch, 8000);
refreshKillSwitch();

// ----------------------------------------------------------------------
// Recording — wire the topbar Record / Stop / Note buttons. Polls
// /api/recording/status every 5s while idle so the UI reflects state
// even if recording was started from another surface (CLI, another
// tab). While active, the counter on the Stop button shows live event
// + note totals.
// ----------------------------------------------------------------------
let _recPollTimer = null;

function _setRecUI(active, info) {
  const start = document.getElementById('topbar-rec-start');
  const stop  = document.getElementById('topbar-rec-stop');
  const note  = document.getElementById('topbar-rec-note');
  const lbl   = document.getElementById('topbar-rec-counter');
  if (!start || !stop || !note) return;
  start.classList.toggle('hidden', active);
  stop .classList.toggle('hidden', !active);
  note .classList.toggle('hidden', !active);
  if (active && info) {
    const ev = info.events ?? 0, n = info.notes ?? 0;
    if (lbl) lbl.textContent = `REC · ${ev}e · ${n}n`;
    stop.title = `Recording → ${info.path || ''}\n${ev} events, ${n} notes — click to stop.`;
  }
}

async function refreshRecording() {
  try {
    const r = await api('/api/recording/status', { method: 'GET' });
    _setRecUI(!!r.active, r);
  } catch (e) { /* silent */ }
}

async function _recStart() {
  try {
    const r = await api('/api/recording/start', { method: 'POST', body: {} });
    if (r.ok) {
      toast(`recording → ${r.path.split('/').pop()}`, 'ok');
      _setRecUI(true, { events: 0, notes: 0, path: r.path });
      // Tighter cadence while active so the counter feels live.
      if (_recPollTimer) clearInterval(_recPollTimer);
      _recPollTimer = setInterval(refreshRecording, 1500);
    }
  } catch (e) { toast(`record start failed: ${e.message}`, 'err'); }
}

async function _recStop() {
  try {
    const r = await api('/api/recording/stop', { method: 'POST', body: {} });
    if (r.ok) {
      toast(`stopped · ${r.events} events, ${r.notes} notes`, 'ok');
      _setRecUI(false, null);
      if (_recPollTimer) { clearInterval(_recPollTimer); _recPollTimer = null; }
      // Resume the lazy poll so the next external start is reflected.
      setTimeout(refreshRecording, 1000);
    }
  } catch (e) { toast(`stop failed: ${e.message}`, 'err'); }
}

async function _recNote() {
  const text = (prompt('Intent note (what are you about to do, or just did?):') || '').trim();
  if (!text) return;
  try {
    const r = await api('/api/recording/note', { method: 'POST', body: { text } });
    if (r.ok) toast(`note added (${r.notes} total)`, 'ok');
  } catch (e) { toast(`note failed: ${e.message}`, 'err'); }
}

document.getElementById('topbar-rec-start')?.addEventListener('click', _recStart);
document.getElementById('topbar-rec-stop' )?.addEventListener('click', _recStop);
document.getElementById('topbar-rec-note' )?.addEventListener('click', _recNote);

// Cmd/Ctrl+Shift+N — quick-note shortcut while a recording is active.
document.addEventListener('keydown', (ev) => {
  if (!ev.shiftKey) return;
  if (!(ev.metaKey || ev.ctrlKey)) return;
  if (ev.key !== 'N' && ev.key !== 'n') return;
  if (document.getElementById('topbar-rec-stop')?.classList.contains('hidden')) return;
  ev.preventDefault();
  _recNote();
});

setInterval(refreshRecording, 5000);
refreshRecording();

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
      if (!confirm('Apply this Pine to a NEW TradingView layout? '
                 + 'A fresh layout (named "Pine — TS") will be created '
                 + 'and the script attached there — your active layout '
                 + 'is left untouched. Takes ~30s.')) return;
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
            toast(`pine applied · screenshot: ${shot.split('/').slice(-2).join('/')}`, 'ok');
          } else {
            toast('pine applied to chart', 'ok');
          }
        } else {
          toast(`pine apply failed: ${(ar.stderr || ar.error || 'see server log').slice(-200)}`, 'err');
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
// affordance: Ollama gets a dynamic dropdown populated from
// /api/analyze/local_models (curated × installed) plus a free-text
// fallback for custom model names not in the curated list; claude.ai
// uses a fixed 3-tier dropdown; ChatGPT uses a fixed 2-option dropdown
// (Instant / Thinking). Show exactly one primary control at a time and
// read from whichever is visible at submit.
let _ollamaModelsLoaded = false;
async function _loadOllamaModels() {
  if (_ollamaModelsLoaded) return;
  _ollamaModelsLoaded = true;
  const sel = $('analyze-model');
  const txt = $('analyze-model-ollama-text');
  try {
    const r = await api('/api/analyze/local_models');
    const installed = (r && r.installed) || [];
    if (!installed.length) {
      // Ollama unreachable or no curated models installed — fall back
      // to a free-text input so the user isn't blocked.
      sel.classList.add('hidden'); sel.hidden = true;
      txt.classList.remove('hidden'); txt.hidden = false;
      return;
    }
    sel.innerHTML = installed.map((m, i) => {
      const selected = (m.id === r.default || (i === 0 && !r.default)) ? ' selected' : '';
      const note = m.note ? ` — ${m.note}` : '';
      return `<option value="${m.id}"${selected}>${m.label}${note}</option>`;
    }).join('');
  } catch (e) {
    // API failed (server down, etc) — fall back to free text.
    sel.classList.add('hidden'); sel.hidden = true;
    txt.classList.remove('hidden'); txt.hidden = false;
  }
}

function _syncAnalyzeModelControl() {
  const p = $('analyze-provider').value;
  const sel = $('analyze-model');
  const txt = $('analyze-model-ollama-text');
  // Ollama branch: select OR text fallback (decided by _loadOllamaModels).
  // We reveal whichever is currently in the populated state.
  if (p === 'ollama') {
    _loadOllamaModels();
    if (sel.options.length > 0) {
      sel.classList.remove('hidden'); sel.hidden = false;
      txt.classList.add('hidden'); txt.hidden = true;
    } else {
      sel.classList.add('hidden'); sel.hidden = true;
      txt.classList.remove('hidden'); txt.hidden = false;
    }
  } else {
    sel.classList.add('hidden'); sel.hidden = true;
    txt.classList.add('hidden'); txt.hidden = true;
  }
  $('analyze-model-claude').classList.toggle('hidden', p !== 'claude_web');
  $('analyze-model-chatgpt').classList.toggle('hidden', p !== 'chatgpt_web');
}
function _analyzeModelValue() {
  const p = $('analyze-provider').value;
  if (p === 'claude_web')  return $('analyze-model-claude').value || null;
  if (p === 'chatgpt_web') return $('analyze-model-chatgpt').value || null;
  // Ollama: prefer the curated select if visible/populated; otherwise
  // the free-text fallback.
  const sel = $('analyze-model');
  if (sel.options.length > 0 && !sel.hidden) return sel.value || null;
  return $('analyze-model-ollama-text').value.trim() || null;
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
  const noteInput = $('trade-note');
  const note = (noteInput?.value || '').trim();
  setBusy(btn, true);
  try {
    const body = { symbol, side, qty, dry_run };
    if (take_profit !== null) body.take_profit = take_profit;
    if (stop_loss !== null) body.stop_loss = stop_loss;
    if (note) body.note = note;
    const r = await api('/api/trade/order', { method: 'POST', body });
    const tag = (take_profit !== null || stop_loss !== null) ? ' (bracket)' : '';
    toast(`${r.ok ? '✓' : '✗'} ${side.toUpperCase()} ${qty} ${symbol}${tag}${dry_run ? ' (dry-run)' : ''}`, r.ok ? 'ok' : 'err');
    // Clear brackets + note after a successful fire — avoids stale state
    // (e.g. last trade's SL/TP or yesterday's reasoning) carrying forward.
    if (r.ok) {
      $('trade-tp').value = '';
      $('trade-sl').value = '';
      if (noteInput) noteInput.value = '';
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

// ----------------------------------------------------------------------
// Day arc — forecast → reality timeline for one day. Reads
// /api/journal/{symbol}/{date}, renders pre-session + 10/12/14 + pivot
// stages with deterministic per-stage grading. Date defaults to today.
// ----------------------------------------------------------------------
let _dayArcInitialized = false;
function initDayArc() {
  if (_dayArcInitialized) return;
  _dayArcInitialized = true;
  const dateInput = $('day-arc-date');
  if (dateInput && !dateInput.value) {
    const today = new Date();
    const iso = today.toISOString().slice(0, 10);
    dateInput.value = iso;
  }
  $('day-arc-load')?.addEventListener('click', loadDayArc);
}

function _stageStatusClass(grading) {
  if (!grading) return '';
  const score = grading.axes_score;
  if (!score || !score.includes('/')) return '';
  const [p, t] = score.split('/').map(Number);
  if (!t) return '';
  const ratio = p / t;
  if (ratio >= 0.8) return 'pass';
  if (ratio >= 0.4) return 'partial';
  return 'miss';
}

function _renderBandRow(b) {
  if (b.predicted_lo == null && b.predicted_hi == null) {
    return `<span class="day-arc__chip">${b.label}: <i>not predicted</i></span>`;
  }
  const lo = b.predicted_lo?.toLocaleString() ?? '?';
  const hi = b.predicted_hi?.toLocaleString() ?? '?';
  const actual = b.actual?.toLocaleString() ?? '?';
  if (b.hit === true) {
    return `<span class="day-arc__chip pass">${b.label} ✓ <span class="muted">${actual} ∈ [${lo}, ${hi}]</span></span>`;
  }
  if (b.hit === false) {
    const dir = b.side === 'over' ? '↑' : '↓';
    return `<span class="day-arc__chip miss">${b.label} ✗ ${dir}${b.miss_pts} pts <span class="muted">${actual} vs [${lo}, ${hi}]</span></span>`;
  }
  return `<span class="day-arc__chip">${b.label}: n/a</span>`;
}

function _renderStage(s) {
  const klass = _stageStatusClass(s.grading);
  const score = s.grading?.axes_score
    ? `<span class="day-arc__stage-score">${s.grading.axes_score}</span>`
    : '<span class="day-arc__stage-score muted">—</span>';
  let body = '';
  const g = s.grading;
  if (g) {
    const dir = g.direction || {};
    if (dir.predicted || dir.actual) {
      const m = dir.match === true ? '<span class="day-arc__chip pass">dir ✓</span>'
              : dir.match === false ? '<span class="day-arc__chip miss">dir ✗</span>'
              : '<span class="day-arc__chip">dir n/a</span>';
      const pct = dir.confidence_pct != null ? ` <span class="muted">@${dir.confidence_pct}%</span>` : '';
      body += `<div class="day-arc__row">${m}<span><b>predicted</b> ${escapeHtml(dir.predicted || '—')}${pct} → <b>actual</b> ${escapeHtml(dir.actual || '—')}</span></div>`;
    }
    if (s.key === 'pre_session') {
      // Pre-session has span_pts + net_pct + tags blocks.
      const pre = g;
      if (pre.span_pts && (pre.span_pts.predicted_lo || pre.span_pts.predicted_hi)) {
        body += `<div class="day-arc__row">${_renderBandRow({ ...pre.span_pts, label: 'span(pts)' })}</div>`;
      }
      if (pre.net_pct && (pre.net_pct.predicted_lo != null || pre.net_pct.predicted_hi != null)) {
        body += `<div class="day-arc__row">${_renderBandRow({ ...pre.net_pct, label: 'net%' })}</div>`;
      }
      const tags = pre.tags || [];
      if (tags.length) {
        const chips = tags.map(t => {
          if (t.match === true) return `<span class="day-arc__chip pass">${escapeHtml(t.key)}: ${escapeHtml(t.predicted)}</span>`;
          if (t.match === false) return `<span class="day-arc__chip miss">${escapeHtml(t.key)}: ${escapeHtml(t.predicted)}≠${escapeHtml(t.actual)}</span>`;
          return `<span class="day-arc__chip">${escapeHtml(t.key)}: n/a</span>`;
        }).join(' ');
        body += `<div class="day-arc__row">${chips}</div>`;
      }
      if (pre.tags_score) body += `<div class="day-arc__row muted">tags ${escapeHtml(pre.tags_score)}</div>`;
    } else if (g.bands) {
      body += `<div class="day-arc__row">${g.bands.map(_renderBandRow).join('')}</div>`;
    }
  } else {
    body = '<div class="day-arc__row muted">No daily profile yet — grading n/a until 16:00 ET capture.</div>';
  }
  const time = s.made_at ? `<span class="day-arc__stage-time">${escapeHtml(s.made_at)}</span>` : '';
  return `<div class="day-arc__stage ${klass}">
    <div class="day-arc__stage-head">
      <span class="day-arc__stage-label">${escapeHtml(s.label)}</span>
      ${time}
      ${score}
    </div>
    <div class="day-arc__stage-body">${body}</div>
  </div>`;
}

async function loadDayArc() {
  const date = $('day-arc-date')?.value;
  if (!date) { toast('pick a date first', 'err'); return; }
  const body = $('day-arc-body');
  body.innerHTML = '<div class="empty">Loading…</div>';
  $('day-arc-score').textContent = '—';
  try {
    const data = await api(`/api/journal/MNQ1/${encodeURIComponent(date)}`);
    if (data.rollup?.score) {
      $('day-arc-score').textContent = `${data.rollup.score} axes`;
      $('day-arc-score').classList.remove('muted');
    } else {
      $('day-arc-score').textContent = `${data.rollup?.stages_count || 0} stages · grading pending`;
      $('day-arc-score').classList.add('muted');
    }
    let html = '';
    if (data.profile?.available) {
      const sm = data.profile.summary || {};
      const tags = data.profile.tags || {};
      html += `<div class="day-arc__profile">
        <h3>Daily profile · ${escapeHtml(data.date)}</h3>
        <div class="day-arc__takeaway">${escapeHtml(data.profile.takeaway || '')}</div>
        <div class="day-arc__summary">
          <div><b>direction</b> ${escapeHtml(sm.direction || '—')}</div>
          <div><b>open</b> ${sm.open_approx?.toLocaleString() ?? '—'}</div>
          <div><b>close</b> ${sm.close_approx?.toLocaleString() ?? '—'}</div>
          <div><b>HOD</b> ${sm.hod_approx?.toLocaleString() ?? '—'}</div>
          <div><b>LOD</b> ${sm.lod_approx?.toLocaleString() ?? '—'}</div>
          <div><b>span</b> ${sm.intraday_span_pts ?? '—'} pts</div>
          <div><b>net%</b> ${sm.net_range_pct_open_to_close != null ? sm.net_range_pct_open_to_close.toFixed(2) : '—'}</div>
          <div><b>structure</b> ${escapeHtml(tags.structure || '—')}</div>
        </div>
      </div>`;
    } else {
      html += `<div class="day-arc__profile muted"><h3>Daily profile</h3><div>No profile for ${escapeHtml(data.date)} — grading is unavailable until the 16:00 ET capture runs.</div></div>`;
    }
    if (!data.stages?.length) {
      html += '<div class="empty">No forecasts for this date.</div>';
    } else {
      html += data.stages.map(_renderStage).join('');
    }
    if (data.applied_screenshots?.length) {
      const items = data.applied_screenshots.map(s => `<li>${escapeHtml(s.name)}</li>`).join('');
      html += `<div class="day-arc__appshots">Applied-Pine snapshots (${data.applied_screenshots.length}):<ul>${items}</ul></div>`;
    }
    if (data.decisions?.length) {
      html += `<div class="day-arc__appshots">Decisions logged: ${data.decisions.length}</div>`;
    }
    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = `<div class="empty">Load failed: ${escapeHtml(e.message)}</div>`;
  }
}

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
// Profiles tab — reference-day DB + live comparator
// ----------------------------------------------------------------------
let _profilesCache = null;
let _profilesSelectedKey = null;

async function loadProfiles() {
  const list = document.getElementById('profiles-list');
  try {
    const r = await api('/api/profiles');
    _profilesCache = r.profiles || [];
    renderProfilesList();
  } catch (e) {
    list.innerHTML = `<div class="empty err">failed to load: ${e.message}</div>`;
  }
}

// ----------------------------------------------------------------------
// Profile-run card — calendar + mode toggle + override modal + run stream
// ----------------------------------------------------------------------
let _profileRunInited = false;
let _profileRunPollTimer = null;
let _profileRunSeenEvents = 0;

function initProfileRun() {
  if (_profileRunInited) return;
  _profileRunInited = true;

  document.getElementById('profile-date-select').addEventListener('change', _refreshSelectionSummary);
  document.getElementById('profile-run-go').addEventListener('click', onProfileRunClick);

  document.getElementById('profile-run-modal-cancel').addEventListener('click', _hideProfileModal);
  document.getElementById('profile-run-modal-skip').addEventListener('click', () => _confirmProfileModal('skip'));
  document.getElementById('profile-run-modal-override').addEventListener('click', () => _confirmProfileModal('override'));

  _populateDateDropdown();
  _refreshSelectionSummary();
}

function _fmtDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function _profiledDates() {
  const out = new Set();
  (_profilesCache || []).forEach(p => { if (p.date) out.add(p.date); });
  return out;
}

function _populateDateDropdown() {
  const select = document.getElementById('profile-date-select');
  const profiledSet = _profiledDates();
  const todayStr = _fmtDate(new Date());
  const dates = [];
  const d = new Date();
  while (dates.length < 20) {
    const ds = _fmtDate(d);
    const dow = d.getDay();
    if (dow >= 1 && dow <= 5 && ds <= todayStr) dates.push(ds);
    d.setDate(d.getDate() - 1);
  }
  select.innerHTML = '<option value="">— select date —</option>';
  dates.forEach(ds => {
    const profiled = profiledSet.has(ds);
    const opt = document.createElement('option');
    opt.value = ds;
    const dayName = new Date(ds + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'short' });
    opt.textContent = `${ds}  ${dayName}${profiled ? '  ✓' : ''}`;
    select.appendChild(opt);
  });
}

function _refreshSelectionSummary() {
  const go = document.getElementById('profile-run-go');
  const ds = document.getElementById('profile-date-select').value;
  go.disabled = !ds || !!_profileRunPollTimer;
}

// ------- Override modal -------
let _pendingRun = null;

function _showProfileModal() {
  const ds = document.getElementById('profile-date-select').value;
  const body = document.getElementById('profile-run-modal-body');
  const modal = document.getElementById('profile-run-modal');
  body.textContent = `${ds} is already profiled. Override re-profiles the day (~3–5 min + one ChatGPT Thinking call).`;
  modal.classList.remove('hidden');
}

function _hideProfileModal() {
  document.getElementById('profile-run-modal').classList.add('hidden');
  _pendingRun = null;
}

function _confirmProfileModal(choice) {
  if (!_pendingRun) { _hideProfileModal(); return; }
  const pending = _pendingRun;
  _pendingRun = null;
  document.getElementById('profile-run-modal').classList.add('hidden');
  _dispatchProfileRun({ ...pending, resume: choice === 'skip' });
}

async function onProfileRunClick() {
  const ds = document.getElementById('profile-date-select').value;
  if (!ds) return;
  const payload = { dates: [ds], symbol: 'MNQ1', resume: true };
  if (_profiledDates().has(ds)) {
    _pendingRun = payload;
    _showProfileModal();
    return;
  }
  _dispatchProfileRun(payload);
}

async function _dispatchProfileRun(payload) {
  const goEl = document.getElementById('profile-run-go');
  const statusEl = document.getElementById('profile-run-status');
  const progressEl = document.getElementById('profile-run-progress');
  const phaseEl = document.getElementById('profile-run-phase');
  const eventsEl = document.getElementById('profile-run-events');

  goEl.disabled = true;
  statusEl.textContent = 'starting…';
  progressEl.classList.remove('hidden');
  let label;
  if (payload.dates && payload.dates.length) {
    label = payload.dates.length === 1
      ? payload.dates[0]
      : `${payload.dates.length} days (${payload.dates[0]} … ${payload.dates[payload.dates.length - 1]})`;
  } else {
    label = payload.end ? `${payload.start} → ${payload.end}` : payload.start;
  }
  phaseEl.textContent = `Starting run for ${label} (resume=${payload.resume})`;
  eventsEl.innerHTML = '';
  _profileRunSeenEvents = 0;

  let task_id, request_id;
  try {
    const r = await api('/api/profiles/run', { method: 'POST', body: payload });
    task_id = r.task_id; request_id = r.request_id;
  } catch (e) {
    statusEl.textContent = 'failed to start';
    phaseEl.textContent = `Error: ${e.message}`;
    goEl.disabled = false;
    return;
  }

  statusEl.textContent = `running (task ${task_id.slice(0, 6)})`;
  _profileRunPollTimer = setInterval(() => _pollProfileRun(task_id, request_id), 1500);
  _pollProfileRun(task_id, request_id);
}

async function _pollProfileRun(task_id, request_id) {
  const statusEl = document.getElementById('profile-run-status');
  const phaseEl = document.getElementById('profile-run-phase');
  const eventsEl = document.getElementById('profile-run-events');
  const goEl = document.getElementById('profile-run-go');

  let status, entries = [];
  try {
    [status, entries] = await Promise.all([
      api(`/api/profiles/runs/${task_id}`),
      api(`/api/audit/tail?n=200&request_id=${encodeURIComponent(request_id)}`)
        .then(r => r.entries || []).catch(() => []),
    ]);
  } catch (e) {
    statusEl.textContent = `poll error: ${e.message}`;
    return;
  }

  // Render any new events (entries come newest-last from the server).
  const newEntries = entries.slice(_profileRunSeenEvents);
  _profileRunSeenEvents = entries.length;
  newEntries.forEach(ent => {
    const li = document.createElement('li');
    const t = (ent.ts || '').slice(11, 19);
    const ev = ent.event || '';
    let line = `${t}  ${ev}`;
    let cls = '';
    if (ev === 'daily_profile.gate') {
      line += `  attempt=${ent.attempt} ${ent.ok ? 'ok' : 'fail'} ${ent.reason || ''}`.trimEnd();
      cls = ent.ok ? 'ev-pass' : 'ev-fail';
    } else if (ev === 'daily_profile.run_day.complete') {
      line += `  ${ent.date} gate=${ent.gate_ok ? 'ok' : 'fail'}`;
      cls = 'ev-done';
    } else if (ev === 'daily_profile.parse_fail') {
      cls = 'ev-fail';
    } else if (ev === 'daily_profile.skip_existing') {
      line += `  ${ent.date}`;
      cls = 'ev-done';
    } else if (ent.date) {
      line += `  ${ent.date}`;
    }
    if (cls) li.className = cls;
    li.textContent = line;
    eventsEl.prepend(li);  // newest on top
  });

  // Derive a phase line from the latest event.
  const latest = entries[entries.length - 1];
  if (latest) {
    const d = latest.date || '';
    phaseEl.textContent = d ? `${d} · ${latest.event}` : latest.event;
  }

  if (status.state === 'done' || status.state === 'failed') {
    clearInterval(_profileRunPollTimer);
    _profileRunPollTimer = null;
    if (status.state === 'done') {
      const n = (status.results || []).length;
      statusEl.textContent = `done — ${n} day(s)`;
      phaseEl.textContent = `Complete: ${n} day(s) processed. Refreshing list…`;
      await loadProfiles();
      _populateDateDropdown();
    } else {
      statusEl.textContent = 'failed';
      phaseEl.textContent = `Error: ${status.error || 'unknown'}`;
    }
    // Re-enable Run per current selection state (also re-renders overlap).
    _refreshSelectionSummary();
  }
}

function renderProfilesList() {
  const list = document.getElementById('profiles-list');
  if (!_profilesCache || _profilesCache.length === 0) {
    list.innerHTML = '<div class="empty">No profiles yet. Run a profile flow first.</div>';
    return;
  }
  const html = _profilesCache.map(p => {
    const dir = (p.summary && p.summary.direction) || '?';
    const box = (p.summary && p.summary.box_color) || '';
    const pct = p.summary && p.summary.net_range_pct;
    const pctStr = (pct != null) ? `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%` : '';
    const shape = (p.summary && p.summary.shape_sentence) || '';
    const boxCls = box === 'green' ? 'badge-green' : (box === 'red' ? 'badge-red' : 'badge-neutral');
    const sel = p.key === _profilesSelectedKey ? ' selected' : '';
    return `
      <div class="profile-card${sel}" data-key="${p.key}">
        <div class="profile-card__row">
          <span class="profile-card__date">${p.date || p.key}</span>
          <span class="profile-card__dow">${p.dow || ''}</span>
          <span class="badge ${boxCls}">${dir}</span>
          <span class="profile-card__pct mono small">${pctStr}</span>
        </div>
        <div class="profile-card__shape small muted">${shape}</div>
      </div>
    `;
  }).join('');
  list.innerHTML = html;
  list.querySelectorAll('.profile-card').forEach(el => {
    el.addEventListener('click', () => selectProfile(el.dataset.key));
  });
}

async function selectProfile(key) {
  _profilesSelectedKey = key;
  renderProfilesList();  // re-render to update selected styling
  const title = document.getElementById('compare-profile-title');
  const meta = document.getElementById('compare-profile-meta');
  const img = document.getElementById('compare-profile-img');
  const tags = document.getElementById('compare-profile-tags');
  const nar = document.getElementById('compare-profile-narrative');
  title.textContent = 'Loading…';
  img.innerHTML = '<div class="empty">Loading…</div>';
  tags.innerHTML = '';
  nar.innerHTML = '';
  try {
    const r = await api(`/api/profiles/${encodeURIComponent(key)}`);
    const j = r.json || {};
    title.textContent = `${j.date || key} ${j.dow ? '· ' + j.dow : ''}`;
    const sum = j.summary || {};
    const metaBits = [];
    if (sum.open_approx) metaBits.push(`O ${sum.open_approx}`);
    if (sum.close_approx) metaBits.push(`C ${sum.close_approx}`);
    if (sum.hod_approx) metaBits.push(`H ${sum.hod_approx}`);
    if (sum.lod_approx) metaBits.push(`L ${sum.lod_approx}`);
    meta.textContent = metaBits.join('  ');
    img.innerHTML = `<img src="/api/profiles/${encodeURIComponent(key)}/screenshot" alt="profile screenshot" onerror="this.parentNode.innerHTML='<div class=empty>Screenshot not available</div>';" />`;
    tags.innerHTML = renderProfileTags(j.tags || {});
    nar.innerHTML = renderProfileMarkdown(r.markdown || '');
  } catch (e) {
    title.textContent = 'Error';
    img.innerHTML = `<div class="empty err">${e.message}</div>`;
  }
}

function renderProfileTags(tags) {
  const entries = Object.entries(tags).filter(([_, v]) => v != null && v !== '');
  if (!entries.length) return '';
  return entries.map(([k, v]) =>
    `<span class="tag-pill"><span class="tag-k">${k}</span><span class="tag-v">${String(v)}</span></span>`
  ).join('');
}

// Minimal markdown-to-HTML. Handles headings (##, ###), **bold**, *italic*,
// bullet lists (- item), pipe-tables, and fenced paragraphs. Good enough
// for the profile narratives we generate — no external lib needed.
function renderProfileMarkdown(md) {
  if (!md) return '<div class="empty">No narrative.</div>';
  // Strip frontmatter
  md = md.replace(/^---[\s\S]*?---\s*/, '');
  const lines = md.split('\n');
  const out = [];
  let i = 0;
  let inList = false;
  while (i < lines.length) {
    const ln = lines[i];
    // Table: a row that starts with | and the next row is | --- | ---
    if (ln.trim().startsWith('|') && i + 1 < lines.length && /^\|[\s\-:|]+\|$/.test(lines[i+1].trim())) {
      const header = ln.trim().split('|').slice(1, -1).map(c => c.trim());
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(lines[i].trim().split('|').slice(1, -1).map(c => c.trim()));
        i++;
      }
      let tbl = '<table class="profile-table"><thead><tr>';
      header.forEach(h => tbl += `<th>${escapeHTML(h)}</th>`);
      tbl += '</tr></thead><tbody>';
      rows.forEach(r => {
        tbl += '<tr>';
        r.forEach(c => tbl += `<td>${renderInline(c)}</td>`);
        tbl += '</tr>';
      });
      tbl += '</tbody></table>';
      out.push(tbl);
      continue;
    }
    if (/^#{1,6} /.test(ln)) {
      if (inList) { out.push('</ul>'); inList = false; }
      const m = ln.match(/^(#+) (.*)$/);
      const level = Math.min(m[1].length + 1, 6);  // bump one level so our h1 stays the page title
      out.push(`<h${level}>${renderInline(m[2])}</h${level}>`);
    } else if (/^\s*-\s+/.test(ln)) {
      if (!inList) { out.push('<ul>'); inList = true; }
      out.push(`<li>${renderInline(ln.replace(/^\s*-\s+/, ''))}</li>`);
    } else if (ln.trim() === '') {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push('');
    } else {
      if (inList) { out.push('</ul>'); inList = false; }
      out.push(`<p>${renderInline(ln)}</p>`);
    }
    i++;
  }
  if (inList) out.push('</ul>');
  return out.join('\n');
}

function renderInline(s) {
  s = escapeHTML(s);
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  return s;
}

function escapeHTML(s) {
  return String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
}

// "Capture" button — grabs a fresh chart screenshot and shows it in the top pane.
document.getElementById('compare-capture')?.addEventListener('click', async (ev) => {
  const btn = ev.currentTarget;
  const img = document.getElementById('compare-today-img');
  setBusy(btn, true, 'Capture');
  img.innerHTML = '<div class="empty">Capturing…</div>';
  try {
    const r = await api('/api/chart/screenshot', { method: 'POST', body: {} });
    const src = r.data_url || r.url;
    if (src) {
      img.innerHTML = `<img src="${src}" alt="today's chart" />`;
    } else {
      img.innerHTML = '<div class="empty err">Screenshot returned no image</div>';
    }
  } catch (e) {
    img.innerHTML = `<div class="empty err">${e.message}</div>`;
  } finally {
    setBusy(btn, false, 'Capture');
  }
});

// ----------------------------------------------------------------------
// Forecasts tab — replay-forecast run browser
// ----------------------------------------------------------------------
let _forecastsCache = null;
let _forecastsSelectedKey = null;  // `${symbol}|${date}`

async function loadForecasts() {
  const list = document.getElementById('forecasts-list');
  try {
    const r = await api('/api/forecasts');
    _forecastsCache = r.days || [];
    renderForecastsList();
    if (_forecastRunInited) {
      renderForecastCalendar();
      // Re-sync the summary + Run-button enabled state in case the
      // initial render raced with the fetch or the user changed selection
      // before the cache arrived.
      _refreshForecastSummary();
    }
  } catch (e) {
    list.innerHTML = `<div class="empty err">failed to load: ${e.message}</div>`;
  }
  // Lessons + calibration run independently — failures shouldn't block the day list.
  loadLessons();
  loadCalibration();
}

// ----------------------------------------------------------------------
// Forecast-run card — pick a day, kick off daily_forecast, stream events.
// Mirrors the profile-run card but single-day (CLI runs one date at a time).
// ----------------------------------------------------------------------
let _forecastRunInited = false;
let _forecastRunPollTimer = null;
let _forecastRunSeenEvents = 0;
let _forecastRunElapsedTimer = null;
let _forecastRunStartedAt = 0;
let _forecastRunActiveKind = null;
const _forecastCal = {
  viewYear: 0, viewMonth: 0,
  selected: null,  // single YYYY-MM-DD or null
};

// Labels for the status bar — short human-facing tag per kind. Mirrors
// the `data-kind` attribute on each .forecast-run-btn so the bar reads
// the same dialect as the buttons.
const _FORECAST_KIND_LABEL = {
  pre_session: 'Pre-session',
  live_f1: 'F1 (live 10:00)',
  live_f2: 'F2 (live 12:00)',
  live_f3: 'F3 (live 14:00)',
  adhoc: 'Ad-hoc (Bar Replay)',
};

function initForecastRun() {
  if (_forecastRunInited) return;
  _forecastRunInited = true;
  const today = new Date();
  _forecastCal.viewYear = today.getFullYear();
  _forecastCal.viewMonth = today.getMonth();

  document.getElementById('forecast-cal-prev').addEventListener('click', () => _forecastGotoMonth(-1));
  document.getElementById('forecast-cal-next').addEventListener('click', () => _forecastGotoMonth(+1));
  document.getElementById('forecast-run-go').addEventListener('click', onForecastRunClick);
  document.getElementById('forecast-run-pre-session').addEventListener('click', () => onTypedForecastClick('pre_session'));
  document.getElementById('forecast-run-f1').addEventListener('click', () => onTypedForecastClick('live_f1'));
  document.getElementById('forecast-run-f2').addEventListener('click', () => onTypedForecastClick('live_f2'));
  document.getElementById('forecast-run-f3').addEventListener('click', () => onTypedForecastClick('live_f3'));

  // Calendar collapse toggle — user preference persists in localStorage so
  // the minimize state survives reloads. Defaults to expanded.
  const toggleBtn = document.getElementById('forecast-cal-toggle');
  const cal = document.getElementById('forecast-cal');
  const applyCalCollapsed = (collapsed) => {
    cal.classList.toggle('collapsed', collapsed);
    toggleBtn.textContent = collapsed ? '▸' : '▾';
    toggleBtn.setAttribute('aria-label', collapsed ? 'Expand calendar' : 'Minimize calendar');
    toggleBtn.title = collapsed ? 'Expand calendar' : 'Minimize calendar';
  };
  applyCalCollapsed(localStorage.getItem('ios-forecast-cal-collapsed') === '1');
  toggleBtn.addEventListener('click', () => {
    const next = !cal.classList.contains('collapsed');
    localStorage.setItem('ios-forecast-cal-collapsed', next ? '1' : '0');
    applyCalCollapsed(next);
  });

  document.getElementById('forecast-run-modal-cancel').addEventListener('click', _hideForecastModal);
  document.getElementById('forecast-run-modal-skip').addEventListener('click', () => _confirmForecastModal('skip'));
  document.getElementById('forecast-run-modal-override').addEventListener('click', () => _confirmForecastModal('override'));

  // Default: today if it's a weekday, else most-recent weekday.
  const d = new Date();
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() - 1);
  _forecastCal.selected = _fmtDate(d);

  renderForecastCalendar();
  _refreshForecastSummary();
}

function _forecastedDates() {
  // Set of YYYY-MM-DD strings that already have ANY forecast stage on disk.
  const out = new Set();
  (_forecastsCache || []).forEach(d => { if (d.date) out.add(d.date); });
  return out;
}

function _forecastAccuracyByDate() {
  // Map YYYY-MM-DD → {best_score, avg_score, overall_max} for reconciled days.
  const out = new Map();
  (_forecastsCache || []).forEach(d => {
    if (d.date && d.accuracy && d.accuracy.best_score != null) {
      out.set(d.date, d.accuracy);
    }
  });
  return out;
}

function _accuracyTier(score, max) {
  // Semantic color tier for a /7 score. Tuned for the 7-point scale — if max
  // changes, proportions stay the same (≥85% = strong, ≥57% = ok, else weak).
  if (score == null || !max) return '';
  const pct = score / max;
  if (pct >= 0.85) return 'acc-strong';
  if (pct >= 0.57) return 'acc-ok';
  return 'acc-weak';
}

function _forecastGotoMonth(delta) {
  let m = _forecastCal.viewMonth + delta;
  let y = _forecastCal.viewYear;
  while (m < 0) { m += 12; y -= 1; }
  while (m > 11) { m -= 12; y += 1; }
  _forecastCal.viewYear = y;
  _forecastCal.viewMonth = m;
  renderForecastCalendar();
}

function renderForecastCalendar() {
  const grid = document.getElementById('forecast-cal-grid');
  const title = document.getElementById('forecast-cal-title');
  const y = _forecastCal.viewYear;
  const m = _forecastCal.viewMonth;
  title.textContent = new Date(y, m, 1).toLocaleDateString(undefined, { year: 'numeric', month: 'long' });

  const firstOfMonth = new Date(y, m, 1);
  const firstDow = (firstOfMonth.getDay() + 6) % 7;
  const gridStart = new Date(y, m, 1 - firstDow);

  const forecastedSet = _forecastedDates();
  const accuracyMap = _forecastAccuracyByDate();
  const todayStr = _fmtDate(new Date());
  const sel = _forecastCal.selected;

  const cells = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    const ds = _fmtDate(d);
    const otherMonth = (d.getMonth() !== m);
    const dow = (d.getDay() + 6) % 7;
    const isWeekend = dow >= 5;
    const isFuture = ds > todayStr;
    const disabled = isFuture || isWeekend;  // forecasts are single-day weekdays only

    const acc = accuracyMap.get(ds);
    const tier = acc ? _accuracyTier(acc.best_score, acc.overall_max) : '';

    const classes = ['cal-day'];
    if (otherMonth) classes.push('other-month');
    if (disabled) classes.push('disabled');
    if (isWeekend) classes.push('weekend');
    if (ds === todayStr) classes.push('today');
    if (forecastedSet.has(ds)) classes.push('profiled');  // reuse profiled styling
    if (acc) classes.push('reconciled');
    if (tier) classes.push(tier);
    if (ds === sel) classes.push('selected');

    const scoreChip = acc
      ? `<span class="cal-score">${acc.best_score}/${acc.overall_max}</span>`
      : '';
    cells.push(`<div class="${classes.join(' ')}" data-date="${ds}"><span class="cal-day-num">${d.getDate()}</span>${scoreChip}</div>`);
  }
  grid.innerHTML = cells.join('');
  grid.querySelectorAll('.cal-day:not(.disabled)').forEach(el => {
    el.addEventListener('click', () => {
      _forecastCal.selected = el.dataset.date;
      renderForecastCalendar();
      _refreshForecastSummary();
    });
  });
}

function _refreshForecastSummary() {
  const summary = document.getElementById('forecast-run-summary');
  const go = document.getElementById('forecast-run-go');
  const sel = _forecastCal.selected;
  if (!sel) {
    summary.textContent = 'Pick a day to run F1 → F2 → F3 → reconciliation';
    go.disabled = true;
    return;
  }
  const existing = _forecastedDates().has(sel);
  // Look up partial-stage detail so the summary tells the user what's already done.
  let stageBits = '';
  if (existing) {
    const day = (_forecastsCache || []).find(d => d.date === sel);
    const stages = (day && day.stages) || {};
    const has = k => !!stages[k];
    const parts = [];
    if (has('1000')) parts.push('F1');
    if (has('1200')) parts.push('F2');
    if (has('1400')) parts.push('F3');
    if (day && day.has_reconciliation) parts.push('recon');
    stageBits = parts.length
      ? `<span class="overlap">Existing stages: ${parts.join(', ')}. Run will ask: skip or override.</span>`
      : '<span class="overlap">Forecast exists. Run will ask: skip or override.</span>';
  }
  const isToday = (sel === _fmtDate(new Date()));
  const adhocBadge = isToday
    ? ' <span class="session-bar__chip" title="Ad-hoc mode: stages whose cursor time hasn\'t arrived will be skipped; reconciliation waits for the profile + RTH close.">adhoc</span>'
    : '';
  summary.innerHTML = `${sel}${adhocBadge}${stageBits}`;
  if (!_forecastRunPollTimer) go.disabled = false;
}

// ------- Forecast override modal -------
let _pendingForecastRun = null;

function _showForecastModal(date) {
  const body = document.getElementById('forecast-run-modal-body');
  const modal = document.getElementById('forecast-run-modal');
  body.textContent = `${date} already has forecast stages on disk. `
    + `Skip existing = continue from where the prior run left off (cheap). `
    + `Override all = re-run every stage from scratch (~15–20 min + four ChatGPT Thinking calls).`;
  modal.classList.remove('hidden');
}

function _hideForecastModal() {
  document.getElementById('forecast-run-modal').classList.add('hidden');
  _pendingForecastRun = null;
}

function _confirmForecastModal(choice) {
  if (!_pendingForecastRun) { _hideForecastModal(); return; }
  const pending = _pendingForecastRun;
  _pendingForecastRun = null;
  document.getElementById('forecast-run-modal').classList.add('hidden');
  _dispatchForecastRun({ ...pending, resume: choice === 'skip' });
}

async function onForecastRunClick() {
  const sel = _forecastCal.selected;
  if (!sel) return;
  const existing = _forecastedDates().has(sel);
  // Auto-enable adhoc mode when the target date is today — makes the run
  // time-aware so stages whose cursor time hasn't arrived get skipped
  // cleanly instead of writing gate-failed artifacts, and reconciliation
  // waits for the profile + RTH close. For historical dates adhoc is a
  // no-op so it's safe to always leave it off there.
  const adhoc = (sel === _fmtDate(new Date()));
  const payload = { date: sel, symbol: 'MNQ1', resume: true, adhoc };
  if (existing) {
    _pendingForecastRun = payload;
    _showForecastModal(sel);
    return;
  }
  _dispatchForecastRun({ kind: 'adhoc', endpoint: '/api/forecasts/run', body: payload });
}

// Resolve which trading day a pre-session run should target right now.
// Before 16:00 ET on a weekday → today. After 16:00 ET (or weekend) →
// the next weekday. Lets the operator press Pre-session in the evening
// and have it forecast tomorrow without any date picker.
function _preSessionTargetDate() {
  const now = new Date();
  const etParts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: 'numeric', hour12: false, weekday: 'short',
  }).formatToParts(now);
  const etHour = parseInt(etParts.find(p => p.type === 'hour').value, 10);
  const etDow  = etParts.find(p => p.type === 'weekday').value;
  const isWeekend = (etDow === 'Sat' || etDow === 'Sun');
  const afterClose = (etHour >= 16);
  if (!isWeekend && !afterClose) return _fmtDate(now);
  const cursor = new Date(now);
  for (let i = 0; i < 5; i++) {
    cursor.setDate(cursor.getDate() + 1);
    const dow = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', weekday: 'short',
    }).format(cursor);
    if (dow !== 'Sat' && dow !== 'Sun') return _fmtDate(cursor);
  }
  return _fmtDate(cursor);
}

// Update Pre-session button hints (Plan tab + Today quick-strip) so a
// press's target date is visible at-a-glance. Called on load and every
// minute so the label flips automatically when the clock crosses
// 16:00 ET. Both hint spans share the same logic; either may be absent
// (Today quick-strip wasn't always there).
function _refreshPreSessionHint() {
  const target = _preSessionTargetDate();
  const today = _fmtDate(new Date());
  let label;
  if (target === today) {
    label = 'today';
  } else {
    const [y, m, d] = target.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    const dow = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][dt.getDay()];
    label = `${dow} ${m}/${d}`;
  }
  for (const id of ['forecast-run-pre-session-hint', 'today-quick-pre-session-hint']) {
    const el = document.getElementById(id);
    if (el) el.textContent = label;
  }
}
_refreshPreSessionHint();
setInterval(_refreshPreSessionHint, 60_000);

// Today tab Quick-run strip — surfaces the most-fired actions at the
// top of the run surface. Pre-session reuses the typed-forecast click
// path, Analyze pops the Trade desk and synthesises a click on its
// Capture button (the user always wants a fresh frame for an analysis),
// and Plan › switches tabs.
document.getElementById('today-quick-pre-session')?.addEventListener('click', () => {
  onTypedForecastClick('pre_session');
});
document.getElementById('today-quick-analyze')?.addEventListener('click', () => {
  const desk = document.getElementById('trade-desk');
  if (desk && !desk.open) desk.open = true;
  // Defer the click so the panel layout settles first; without this,
  // the trade-bar inputs may not be ready when Capture fires.
  setTimeout(() => document.getElementById('trade-capture')?.click(), 50);
});
document.getElementById('today-quick-open-plan')?.addEventListener('click', () => {
  activateGroup('plan');
});

// Today tab Recent decisions strip — last 3 entries from the decision
// log. Hidden when the response is empty so a clean repo doesn't show
// a stub card. Pulls from /api/decisions/recent which already returns
// the shape we need (signal / confidence / outcome / realized_r).
async function loadTodayDecisions() {
  const card = document.getElementById('today-decisions-card');
  const rows = document.getElementById('today-decisions-rows');
  if (!card || !rows) return;
  try {
    const r = await api('/api/decisions/recent?limit=3', { method: 'GET' });
    const list = (r && r.decisions) || [];
    if (!list.length) { card.classList.add('hidden'); return; }
    card.classList.remove('hidden');
    rows.innerHTML = list.map(d => {
      const t = (d.iso_ts || '').slice(11, 16);
      const sigCls = (d.signal || '').toLowerCase();   // long/short/skip
      const sig = (d.signal || '—').toUpperCase();
      const conf = d.confidence != null ? `${d.confidence}%` : '—';
      const out = d.outcome
        ? (d.outcome === 'win' ? '✓' : d.outcome === 'loss' ? '✗' : '·')
        : '—';
      const r_text = d.realized_r != null
        ? `${d.realized_r >= 0 ? '+' : ''}${(+d.realized_r).toFixed(2)}R`
        : '';
      return `<button type="button" class="today-decisions__row" data-rid="${escapeHTML(d.request_id)}">
        <span class="today-decisions__time mono">${t}</span>
        <span class="today-decisions__sig today-decisions__sig--${sigCls}">${sig}</span>
        <span class="today-decisions__conf mono muted">${conf}</span>
        <span class="today-decisions__out mono">${out}</span>
        <span class="today-decisions__r mono">${r_text}</span>
      </button>`;
    }).join('');
    rows.querySelectorAll('.today-decisions__row').forEach(btn => {
      btn.addEventListener('click', () => {
        const rid = btn.dataset.rid;
        // Same target as the Journal tab uses for a single decision.
        if (rid) location.hash = `#journal/${rid}`;
        activateGroup('journal');
      });
    });
  } catch (e) {
    card.classList.add('hidden');
  }
}
document.getElementById('today-decisions-refresh')?.addEventListener('click', loadTodayDecisions);

// Typed forecast runs: pre-session targets today (before 16:00 ET) or
// the next trading day (after). Live F1/F2/F3 always target today.
async function onTypedForecastClick(kind) {
  if (_forecastRunPollTimer) return;  // a run is already in flight
  const today = _fmtDate(new Date());
  if (kind === 'pre_session') {
    _dispatchForecastRun({
      kind, endpoint: '/api/forecasts/pre_session',
      body: { date: _preSessionTargetDate(), symbol: 'MNQ1' },
    });
    return;
  }
  const stageMap = { live_f1: 'F1', live_f2: 'F2', live_f3: 'F3' };
  const stage = stageMap[kind];
  if (!stage) return;
  _dispatchForecastRun({
    kind, endpoint: '/api/forecasts/live',
    body: { stage, date: today, symbol: 'MNQ1', force: true },
  });
}

function _setForecastButtonsDisabled(disabled) {
  const ids = ['forecast-run-go', 'forecast-run-pre-session',
               'forecast-run-f1', 'forecast-run-f2', 'forecast-run-f3'];
  ids.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    if (disabled) {
      el.disabled = true;
    } else if (id === 'forecast-run-go') {
      // Ad-hoc button's enabled state depends on calendar selection.
      _refreshForecastSummary();
    } else {
      el.disabled = false;
    }
  });
}

function _showForecastStatusBar(kind) {
  const bar = document.getElementById('forecast-status-bar');
  const kindEl = document.getElementById('forecast-status-kind');
  const stateEl = document.getElementById('forecast-status-state');
  const fillEl = document.getElementById('forecast-status-fill');
  const elapsedEl = document.getElementById('forecast-status-elapsed');
  bar.classList.remove('hidden', 'done', 'failed');
  bar.classList.add('running');
  kindEl.textContent = _FORECAST_KIND_LABEL[kind] || kind;
  stateEl.textContent = 'running…';
  fillEl.style.width = '';  // CSS drives the stripe animation while .running
  elapsedEl.textContent = '0s';
  _forecastRunStartedAt = Date.now();
  if (_forecastRunElapsedTimer) clearInterval(_forecastRunElapsedTimer);
  _forecastRunElapsedTimer = setInterval(() => {
    const s = Math.floor((Date.now() - _forecastRunStartedAt) / 1000);
    const mm = Math.floor(s / 60), ss = s % 60;
    elapsedEl.textContent = mm > 0 ? `${mm}m${ss.toString().padStart(2, '0')}s` : `${s}s`;
  }, 1000);
}

function _finishForecastStatusBar(state, detail = '') {
  const bar = document.getElementById('forecast-status-bar');
  const stateEl = document.getElementById('forecast-status-state');
  const fillEl = document.getElementById('forecast-status-fill');
  bar.classList.remove('running');
  bar.classList.add(state);  // 'done' or 'failed'
  stateEl.textContent = state === 'done' ? `done${detail ? ' · ' + detail : ''}` : `failed${detail ? ' · ' + detail : ''}`;
  fillEl.style.width = '100%';
  if (_forecastRunElapsedTimer) { clearInterval(_forecastRunElapsedTimer); _forecastRunElapsedTimer = null; }
}

async function _dispatchForecastRun(spec) {
  // Legacy callers pass a raw payload object (ad-hoc). Normalize to
  // the new {kind, endpoint, body} shape so both flows share one path.
  if (!spec.endpoint) {
    spec = { kind: 'adhoc', endpoint: '/api/forecasts/run', body: spec };
  }
  const { kind, endpoint, body } = spec;
  const statusEl = document.getElementById('forecast-run-status');
  const progressEl = document.getElementById('forecast-run-progress');
  const phaseEl = document.getElementById('forecast-run-phase');
  const eventsEl = document.getElementById('forecast-run-events');

  _forecastRunActiveKind = kind;
  _setForecastButtonsDisabled(true);
  _showForecastStatusBar(kind);
  statusEl.textContent = 'starting…';
  progressEl.classList.remove('hidden');
  const date = body.date || _fmtDate(new Date());
  phaseEl.textContent = `Starting ${_FORECAST_KIND_LABEL[kind] || kind} for ${date}`;
  eventsEl.innerHTML = '';
  _forecastRunSeenEvents = 0;

  let task_id, request_id;
  try {
    const r = await api(endpoint, { method: 'POST', body });
    task_id = r.task_id; request_id = r.request_id;
  } catch (e) {
    statusEl.textContent = 'failed to start';
    phaseEl.textContent = `Error: ${e.message}`;
    _finishForecastStatusBar('failed', e.message);
    _setForecastButtonsDisabled(false);
    _forecastRunActiveKind = null;
    return;
  }

  statusEl.textContent = `running (task ${task_id.slice(0, 6)})`;
  _forecastRunPollTimer = setInterval(() => _pollForecastRun(task_id, request_id), 1500);
  _pollForecastRun(task_id, request_id);
}

async function _pollForecastRun(task_id, request_id) {
  const statusEl = document.getElementById('forecast-run-status');
  const phaseEl = document.getElementById('forecast-run-phase');
  const eventsEl = document.getElementById('forecast-run-events');
  const goEl = document.getElementById('forecast-run-go');

  let status, entries = [];
  try {
    [status, entries] = await Promise.all([
      api(`/api/forecasts/runs/${task_id}`),
      api(`/api/audit/tail?n=200&request_id=${encodeURIComponent(request_id)}`)
        .then(r => r.entries || []).catch(() => []),
    ]);
  } catch (e) {
    statusEl.textContent = `poll error: ${e.message}`;
    return;
  }

  const newEntries = entries.slice(_forecastRunSeenEvents);
  _forecastRunSeenEvents = entries.length;
  newEntries.forEach(ent => {
    const li = document.createElement('li');
    const t = (ent.ts || '').slice(11, 19);
    const ev = ent.event || '';
    let line = `${t}  ${ev}`;
    let cls = '';
    if (ev === 'daily_forecast.stage.skip_existing') {
      line += `  ${ent.stage || ''}`;
      cls = 'ev-done';
    } else if (ev === 'daily_forecast.stage.gate_fail') {
      line += `  ${ent.stage || ''} ${ent.reason || ''}`;
      cls = 'ev-fail';
    } else if (ev.endsWith('.complete')) {
      cls = 'ev-done';
    } else if (ev.endsWith('.parse_fail') || ev.endsWith('.error')) {
      cls = 'ev-fail';
    }
    if (cls) li.className = cls;
    li.textContent = line;
    eventsEl.prepend(li);
  });

  const latest = entries[entries.length - 1];
  if (latest) phaseEl.textContent = latest.event;

  if (status.state === 'done' || status.state === 'failed') {
    clearInterval(_forecastRunPollTimer);
    _forecastRunPollTimer = null;
    if (status.state === 'done') {
      statusEl.textContent = 'done';
      phaseEl.textContent = `Complete. Refreshing list…`;
      _finishForecastStatusBar('done');
      await loadForecasts();
      renderForecastCalendar();
    } else {
      statusEl.textContent = 'failed';
      phaseEl.textContent = `Error: ${status.error || 'unknown'}`;
      _finishForecastStatusBar('failed', status.error || 'unknown');
    }
    _forecastRunActiveKind = null;
    _setForecastButtonsDisabled(false);
    _refreshForecastSummary();
  }
}

function _renderLessonsInto(meta, body, r, { topN = null, emptyMsg = '' } = {}) {
  const ls = (r.lessons || []).slice(0, topN || (r.lessons || []).length);
  if (ls.length === 0) {
    meta.textContent = '';
    body.innerHTML = `<div class="empty muted">${emptyMsg || 'Lessons will appear here once you have reconciled a few forecasts.'}</div>`;
    return;
  }
  meta.textContent = `${r.count_unique} unique · ${r.count_reconciliations} reconciliations`;
  body.innerHTML = '<ul class="lesson-list">' + ls.map(l => {
    const badge = l.count > 1
      ? `<span class="lesson-count">${l.count}× across ${l.sources.length} day${l.sources.length !== 1 ? 's' : ''}</span>`
      : `<span class="lesson-source mono small">${l.sources.join(', ')}</span>`;
    return `<li><span class="lesson-text">${escapeHTML(l.text)}</span> ${badge}</li>`;
  }).join('') + '</ul>';
}

async function loadLessons() {
  const meta = document.getElementById('lessons-meta');
  const body = document.getElementById('lessons-body');
  try {
    const r = await api('/api/forecasts/lessons');
    _renderLessonsInto(meta, body, r);
  } catch (e) {
    meta.textContent = '';
    body.innerHTML = `<div class="empty err">${e.message}</div>`;
  }
}

async function loadCalibration() {
  // Note: `forecast-calibration-*` IDs (not bare `calibration-*`) because
  // the Journal tab already owns `#calibration-body` for its trade-outcome
  // calibration card — duplicate IDs would silently redirect updates.
  const meta = document.getElementById('forecast-calibration-meta');
  const body = document.getElementById('forecast-calibration-body');
  if (!meta || !body) return;
  try {
    const r = await api('/api/forecasts/calibration?min_n=1');
    const fields = r.by_field || {};
    const fieldNames = Object.keys(fields);
    if (fieldNames.length === 0) {
      meta.textContent = '';
      body.innerHTML = '<div class="empty muted">Not enough graded reconciliations yet — needs at least one with tags_correct/tags_wrong populated.</div>';
      return;
    }
    meta.textContent = `${r.total_patterns} pattern${r.total_patterns === 1 ? '' : 's'} tracked`;

    // Render one mini-table per field, in a fixed canonical order so the
    // user's eye lands on the same dimensions in the same place each visit.
    const order = ['direction', 'goat_direction', 'open_type', 'structure',
                   'lunch_behavior', 'afternoon_drive', 'close_near_extreme'];
    const labels = {
      direction: 'Direction', goat_direction: 'GOAT direction',
      open_type: 'Open type', structure: 'Structure',
      lunch_behavior: 'Lunch behavior', afternoon_drive: 'Afternoon drive',
      close_near_extreme: 'Close near extreme',
    };
    const sections = order.filter(k => fields[k]).map(k => {
      const items = fields[k];
      const rows = items.map(it => {
        const tier = it.pct >= 70 ? 'acc-strong'
                   : it.pct >= 40 ? 'acc-ok' : 'acc-weak';
        return `<tr class="${tier}">
          <td class="mono small">${escapeHTML(it.value)}</td>
          <td class="mono small calib-pct">${it.pct}%</td>
          <td class="mono small muted">${it.correct}/${it.total}</td>
        </tr>`;
      }).join('');
      return `<div class="calib-field">
        <div class="calib-field__name">${labels[k] || k}</div>
        <table class="calib-table"><tbody>${rows}</tbody></table>
      </div>`;
    });
    body.innerHTML = `<div class="calib-grid">${sections.join('')}</div>`;
  } catch (e) {
    meta.textContent = '';
    body.innerHTML = `<div class="empty err">${escapeHTML(e.message)}</div>`;
  }
}

// ----------------------------------------------------------------------
// Persistent session status bar — bias, invalidation, P&L, running R.
// Visible on every tab; polled every 30s.
// ----------------------------------------------------------------------
const _SESSION_BAR_POLL_MS = 30_000;
let _sessionBarTimer = null;

function _fmtMoney(n) {
  if (n == null || isNaN(n)) return '—';
  const sign = n < 0 ? '-' : (n > 0 ? '+' : '');
  return `${sign}$${Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function _fmtBias(d) {
  // Compact bias label: "long med" / "short low" / "flat"
  const dir = d.direction;
  const conf = d.direction_confidence;
  if (!dir) return d.bias || '—';
  const dirLabel = dir === 'up' ? 'long' : dir === 'down' ? 'short' : dir;
  return conf ? `${dirLabel} · ${conf}` : dirLabel;
}

async function refreshSessionBar() {
  const bar = document.getElementById('session-bar');
  if (!bar) return;
  let r;
  try {
    r = await api('/api/session/today');
  } catch (e) {
    bar.classList.add('empty');
    document.getElementById('sb-bias-val').textContent = '—';
    document.getElementById('sb-inval-val').textContent = `error: ${e.message}`;
    return;
  }
  const tf = r.today_forecast || {};
  const pos = r.positions || {};
  _renderPivotState(tf);
  const sess = r.session || {};

  // Bias cell — direction + confidence; tints the whole bar
  bar.classList.remove('dir-up', 'dir-down', 'dir-flat', 'pnl-up', 'pnl-down');
  if (tf.exists) {
    bar.classList.remove('empty');
    const dir = tf.direction;
    if (dir === 'up') bar.classList.add('dir-up');
    else if (dir === 'down') bar.classList.add('dir-down');
    else bar.classList.add('dir-flat');
    const stageChip = tf.latest_live_stage
      ? `<span class="session-bar__chip" title="last live forecast stage today">F@${tf.latest_live_stage.slice(0,2)}:${tf.latest_live_stage.slice(2)}</span>`
      : `<span class="session-bar__chip" title="only pre-session, no live update yet">pre</span>`;
    document.getElementById('sb-bias-val').innerHTML = `${escapeHTML(_fmtBias(tf))}${stageChip}`;
    document.getElementById('sb-inval-val').textContent = tf.invalidation || '—';
    document.getElementById('sb-inval-val').title = tf.invalidation || '';
  } else {
    bar.classList.add('empty');
    document.getElementById('sb-bias-val').textContent = '— no forecast today';
    document.getElementById('sb-inval-val').textContent = 'Run pre_session_forecast for today';
    document.getElementById('sb-inval-val').title = '';
  }

  // P&L cell — open positions; null if CDP busy
  if (pos.available) {
    const upnl = pos.unrealized_pnl;
    document.getElementById('sb-pnl-val').textContent =
      `${_fmtMoney(upnl)} · ${pos.open_count} open`;
    if (upnl > 0.01) bar.classList.add('pnl-up');
    else if (upnl < -0.01) bar.classList.add('pnl-down');
  } else {
    document.getElementById('sb-pnl-val').textContent = '— (busy)';
  }

  // Session running-R cell
  const r_sum = sess.realized_r_sum || 0;
  const w = sess.wins || 0;
  const l = sess.losses || 0;
  const rTxt = r_sum >= 0 ? `+${r_sum.toFixed(2)}R` : `${r_sum.toFixed(2)}R`;
  document.getElementById('sb-r-val').textContent =
    sess.total > 0 ? `${rTxt} · ${w}W/${l}L` : '—';

  // Canary cell — independent fetch so a slow canary endpoint doesn't
  // hold up the rest of the strip.
  refreshCanaryCell().catch(() => {});

  // Mirror PnL + R to topbar. Same data, more prominent surface.
  _mirrorTopbarPnlR(pos, sess);
}

function _mirrorTopbarPnlR(pos, sess) {
  const pnlCell = document.getElementById('topbar-pnl');
  const pnlBox = pnlCell?.parentElement;
  const rCell = document.getElementById('topbar-r');
  if (pnlCell && pnlBox) {
    pnlBox.classList.remove('pnl-up', 'pnl-down');
    if (pos?.available) {
      const upnl = pos.unrealized_pnl;
      pnlCell.textContent = pos.open_count > 0
        ? `${_fmtMoney(upnl)} · ${pos.open_count}`
        : 'flat';
      if (upnl > 0.01) pnlBox.classList.add('pnl-up');
      else if (upnl < -0.01) pnlBox.classList.add('pnl-down');
    } else {
      pnlCell.textContent = '—';
    }
  }
  if (rCell) {
    const r_sum = sess?.realized_r_sum || 0;
    const w = sess?.wins || 0;
    const l = sess?.losses || 0;
    const rTxt = r_sum >= 0 ? `+${r_sum.toFixed(2)}` : `${r_sum.toFixed(2)}`;
    rCell.textContent = (sess?.total || 0) > 0 ? `${rTxt} · ${w}/${l}` : '—';
  }
}

// --------------------------------------------------------------------
// Canary cell — pre-committed morning trip-wires from pre-session.
// Polled on the same cadence as the session bar.
// --------------------------------------------------------------------
let _canaryFlyoutOpen = false;
let _canaryLastData = null;

async function refreshCanaryCell() {
  const cell = document.getElementById('sb-canary-cell');
  const today = new Date().toISOString().slice(0, 10);
  let data;
  try {
    data = await api(`/api/canary/MNQ1/${today}`);
  } catch (e) {
    if (cell) cell.classList.add('hidden');
    _renderTopbarCanary(null);
    return;
  }
  if (!data?.available) {
    if (cell) cell.classList.add('hidden');
    _renderTopbarCanary(null);
    return;
  }
  if (cell) cell.classList.remove('hidden');
  _canaryLastData = data;
  if (cell) _renderCanaryCell(data);
  if (_canaryFlyoutOpen) _renderCanaryFlyout(data);
  _renderTopbarCanary(data);
}

function _renderTopbarCanary(data) {
  const box = document.getElementById('topbar-canary');
  if (!box) return;
  box.classList.remove('state-passing', 'state-partial', 'state-failing',
                        'state-pending', 'state-no-canary');
  const stateEl = document.getElementById('topbar-canary-state');
  const actionEl = document.getElementById('topbar-canary-action');
  const dotsEl = document.getElementById('topbar-canary-dots');
  if (!data) {
    box.classList.add('state-no-canary');
    if (stateEl) stateEl.textContent = 'no canary';
    if (actionEl) actionEl.textContent = 'wait';
    if (dotsEl) dotsEl.innerHTML = '';
    return;
  }
  const status = data.status || {};
  const ag = status.aggregate;
  const checks = data.canary?.checks || [];
  const byId = Object.fromEntries((status.results || []).map(r => [r.id, r]));
  const state = ag?.state || 'pending';
  box.classList.add(`state-${state}`);
  if (stateEl) stateEl.textContent = state;
  if (actionEl) {
    actionEl.textContent = ag?.recommended_action
      || data.canary?.[`default_action_if_${state}`]
      || 'wait';
  }
  if (dotsEl) {
    dotsEl.innerHTML = checks.map(c => {
      const r = byId[c.id];
      const cls = !r ? 'pending'
        : r.status === 'pass' ? 'pass'
        : r.status === 'fail' ? 'fail'
        : r.status === 'snoozed' ? 'snoozed'
        : r.status === 'evaluate_failed' ? 'failed'
        : 'pending';
      return `<span class="canary-dot ${cls}" title="${escapeHtml(c.id)}"></span>`;
    }).join('');
  }
}

// Topbar canary click — open the legacy flyout (if rendered) so user
// gets the per-check rows. Falls back to no-op when no canary today.
document.getElementById('topbar-canary')?.addEventListener('click', () => {
  if (!_canaryLastData) return;
  const flyout = document.getElementById('sb-canary-flyout');
  const cell = document.getElementById('sb-canary-cell');
  if (cell) cell.classList.remove('hidden');
  if (flyout) {
    flyout.classList.toggle('hidden');
    _canaryFlyoutOpen = !flyout.classList.contains('hidden');
    if (_canaryFlyoutOpen) _renderCanaryFlyout(_canaryLastData);
  }
});

function _renderCanaryCell(data) {
  const cell = document.getElementById('sb-canary-cell');
  const status = data.status;
  const checks = data.canary?.checks || [];
  const results = (status?.results || []);
  const byId = Object.fromEntries(results.map(r => [r.id, r]));
  const dotsEl = document.getElementById('sb-canary-dots');
  const scoreEl = document.getElementById('sb-canary-score');

  const dotHtml = checks.map(c => {
    const r = byId[c.id];
    const cls = !r ? 'pending'
      : r.status === 'pass' ? 'pass'
      : r.status === 'fail' ? 'fail'
      : r.status === 'snoozed' ? 'snoozed'
      : r.status === 'evaluate_failed' ? 'failed'
      : 'pending';
    const w = c.weight > 1 ? ' canary-dot--strong' : '';
    return `<span class="canary-dot ${cls}${w}" title="${escapeHtml(c.id)} (w=${c.weight})"></span>`;
  }).join('');
  dotsEl.innerHTML = dotHtml;

  cell.classList.remove('state-passing', 'state-partial', 'state-failing', 'state-pending');
  if (status?.aggregate) {
    cell.classList.add(`state-${status.aggregate.state}`);
    const pw = status.aggregate.pass_weight;
    const tw = (status.aggregate.pass_weight + status.aggregate.fail_weight + status.aggregate.pending_weight + status.aggregate.evaluate_failed_weight);
    scoreEl.textContent = tw > 0 ? `${pw}/${tw}` : '—';
  } else {
    scoreEl.textContent = `${checks.length} checks`;
  }
}

function _renderCanaryFlyout(data) {
  const flyout = document.getElementById('sb-canary-flyout');
  const stateEl = document.getElementById('sb-canary-state');
  const actionEl = document.getElementById('sb-canary-action');
  const thesisEl = document.getElementById('sb-canary-thesis');
  const rowsEl = document.getElementById('sb-canary-rows');
  const status = data.status;
  const checks = data.canary?.checks || [];
  const byId = Object.fromEntries((status?.results || []).map(r => [r.id, r]));

  if (status?.aggregate) {
    const ag = status.aggregate;
    stateEl.textContent = ag.state;
    stateEl.className = `canary-flyout__state mono state-${ag.state}`;
    actionEl.innerHTML = `→ <b>${escapeHtml(ag.recommended_action || '')}</b>`;
  } else {
    stateEl.textContent = 'pending';
    stateEl.className = 'canary-flyout__state mono state-pending';
    actionEl.innerHTML = '→ <b>wait</b>';
  }
  thesisEl.textContent = data.canary?.thesis_summary || '';

  rowsEl.innerHTML = checks.map(c => {
    const r = byId[c.id];
    const status = r?.status || 'pending';
    const klass = status === 'not_yet_evaluable' ? 'pending'
      : status === 'evaluate_failed' ? 'failed'
      : status;
    let evidence = '';
    if (r?.evidence) {
      const e = r.evidence;
      if (e.close != null && e.threshold != null) {
        evidence = `close ${e.close.toLocaleString()} ${e.comparison} ${e.threshold.toLocaleString()}`;
      } else if (e.reason) {
        evidence = e.reason;
      } else {
        evidence = JSON.stringify(e);
      }
    }
    const time = c.evaluate_at ? `<span class="muted">@${escapeHtml(c.evaluate_at)} ET</span>` : '';
    const wTag = `<span class="canary-row__weight">w=${c.weight}</span>`;
    const snoozeBtn = (status === 'pass' || status === 'fail')
      ? `<button class="canary-row__snooze" data-canary-snooze="${escapeHtml(c.id)}">snooze</button>`
      : '';
    return `<div class="canary-row ${klass}">
      <div class="canary-row__top">
        <span class="canary-row__id">${escapeHtml(c.id)}</span>
        ${time}
        ${wTag}
        <span class="canary-row__status">${status}</span>
      </div>
      <div class="canary-row__rationale">${escapeHtml(c.label || c.rationale || '')}</div>
      ${evidence ? `<div class="canary-row__evidence">${escapeHtml(evidence)}</div>` : ''}
      ${snoozeBtn ? `<div class="canary-row__actions">${snoozeBtn}</div>` : ''}
    </div>`;
  }).join('') || '<div class="empty">No checks defined.</div>';

  // Wire snooze buttons.
  rowsEl.querySelectorAll('[data-canary-snooze]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const checkId = btn.dataset.canarySnooze;
      const reason = (prompt(`Snooze "${checkId}". Reason (≥5 chars, will be logged):`) ?? '').trim();
      if (!reason || reason.length < 5) return;
      const today = new Date().toISOString().slice(0, 10);
      try {
        await api(`/api/canary/MNQ1/${today}/snooze/${encodeURIComponent(checkId)}`,
                  { method: 'POST', body: { reason } });
        toast(`snoozed ${checkId}`, 'ok');
        refreshCanaryCell();
      } catch (e) { toast(`snooze failed: ${e.message}`, 'err'); }
    });
  });
}

document.getElementById('sb-canary-toggle')?.addEventListener('click', () => {
  const flyout = document.getElementById('sb-canary-flyout');
  _canaryFlyoutOpen = !flyout.classList.toggle('hidden');
  if (_canaryFlyoutOpen && _canaryLastData) _renderCanaryFlyout(_canaryLastData);
});

// Tap the invalidation cell on mobile to toggle full-text vs ellipsised
// view. CSS gates the actual collapse to mobile via html.is-mobile, so
// this is a no-op on desktop where the text already fits inline.
document.querySelector('.session-bar__inval')?.addEventListener('click', (ev) => {
  ev.currentTarget.classList.toggle('expanded');
});
document.getElementById('sb-canary-eval-btn')?.addEventListener('click', async () => {
  const today = new Date().toISOString().slice(0, 10);
  try {
    const r = await api(`/api/canary/MNQ1/${today}/evaluate`, { method: 'POST', body: {} });
    if (r.ok) { toast('canary re-evaluated', 'ok'); refreshCanaryCell(); }
    else toast(`evaluate: ${r.reason || 'see audit'}`, 'err');
  } catch (e) { toast(`evaluate failed: ${e.message}`, 'err'); }
});
// Click outside the flyout closes it.
document.addEventListener('click', (e) => {
  if (!_canaryFlyoutOpen) return;
  const cell = document.getElementById('sb-canary-cell');
  if (cell && !cell.contains(e.target)) {
    document.getElementById('sb-canary-flyout').classList.add('hidden');
    _canaryFlyoutOpen = false;
  }
});

function startSessionBarPoll() {
  refreshSessionBar();
  if (_sessionBarTimer) clearInterval(_sessionBarTimer);
  _sessionBarTimer = setInterval(refreshSessionBar, _SESSION_BAR_POLL_MS);
}

// ----------------------------------------------------------------------
// Pivot Forecast — intraday re-forecast fired when the pre-session's
// invalidation condition has broken. Button is hidden until today has a
// pre-session forecast to pivot from; turns amber once a pivot has fired.
// ----------------------------------------------------------------------
function _renderPivotState(tf) {
  const btn = document.getElementById('sb-pivot-btn');
  const applyBtn = document.getElementById('sb-pivot-apply-btn');
  if (!btn) return;
  const haveForecast = !!tf.exists;
  btn.classList.toggle('hidden', !haveForecast);
  const pivot = tf.pivot;
  // Apply button visibility is strictly gated on having a pivot that
  // produced structured output — otherwise there's nothing to render to Pine.
  const canApply = !!(pivot && pivot.pine_available);
  if (applyBtn) applyBtn.classList.toggle('hidden', !canApply);
  if (pivot && pivot.revised_bias) {
    btn.classList.add('fired');
    btn.querySelector('.session-bar__pivot-lbl').textContent =
      `Re-pivot (${pivot.classification || '—'} ${pivot.called_at_et || ''})`.trim();
    btn.title = `Pivot fired at ${pivot.called_at_et}: ${pivot.classification}. `
              + `Revised bias: ${pivot.revised_bias}. `
              + `Tap to run another pivot if conditions changed again.`;
    // Overlay the pivoted bias on the session bar so the eye sees the
    // current working read, not the dead pre-session bias.
    const biasVal = document.getElementById('sb-bias-val');
    const invalVal = document.getElementById('sb-inval-val');
    if (biasVal && invalVal && pivot.revised_bias) {
      const cls = pivot.classification || '';
      biasVal.innerHTML =
        `${escapeHTML(pivot.revised_bias)} <span class="session-bar__chip" title="pivoted from pre-session">${escapeHTML(cls)}</span>`;
      if (pivot.revised_invalidation) {
        invalVal.textContent = pivot.revised_invalidation;
        invalVal.title = pivot.revised_invalidation;
      }
    }
  } else {
    btn.classList.remove('fired');
    btn.querySelector('.session-bar__pivot-lbl').textContent = 'Pivot';
    btn.title = 'Invalidation fired? Run an intraday pivot re-forecast: '
              + 'REVERSAL / FLAT / SHAKEOUT.';
  }
}

function _openPivotModal() {
  const modal = document.getElementById('pivot-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  const reason = document.getElementById('pivot-reason');
  if (reason) { reason.value = ''; reason.focus(); }
  // Clear-pivot button only visible when a pivot has already fired.
  // Driven off the Pivot button's `.fired` state, which is set by
  // _renderPivotState whenever the session endpoint reports a pivot.
  const clearBtn = document.getElementById('pivot-modal-clear');
  const pivotBtn = document.getElementById('sb-pivot-btn');
  if (clearBtn) {
    clearBtn.classList.toggle('hidden',
      !(pivotBtn && pivotBtn.classList.contains('fired')));
  }
}

function _closePivotModal() {
  document.getElementById('pivot-modal')?.classList.add('hidden');
}

async function _dispatchPivot() {
  const reasonEl = document.getElementById('pivot-reason');
  const reason = (reasonEl?.value || '').trim();
  const goBtn = document.getElementById('pivot-modal-go');
  const sbBtn = document.getElementById('sb-pivot-btn');
  setBusy(goBtn, true, 'Run pivot');
  setBusy(sbBtn, true);
  try {
    const r = await api('/api/forecasts/pivot', {
      method: 'POST',
      body: reason ? { reason } : {},
    });
    _closePivotModal();
    toast(`pivot running — ${r.task_id.slice(0,6)}`, 'ok');
    _pollPivotTask(r.task_id);
  } catch (e) {
    toast(`pivot failed: ${e.message}`, 'err');
    setBusy(goBtn, false, 'Run pivot');
    setBusy(sbBtn, false);
  }
}

async function _pollPivotTask(task_id) {
  const sbBtn = document.getElementById('sb-pivot-btn');
  const poll = async () => {
    try {
      const status = await api(`/api/forecasts/runs/${task_id}`);
      if (status.state === 'done') {
        await refreshSessionBar();
        setBusy(sbBtn, false);
        // Parse-fail warning — the pivot ran but the LLM didn't emit
        // structured JSON, so no Pine can be rendered and the session
        // bar won't show the revised bias overlay.
        const result = status.result || {};
        if (result.parsed_structured === false) {
          toast('pivot ran but LLM output didn\'t parse — check pine/parse_failures/', 'err');
          return;
        }
        // Auto-dispatch apply when Pine is available — saves the user
        // a tap. Small delay lets the toast + session bar animate first.
        toast('pivot complete — applying to chart…', 'ok');
        setTimeout(() => _dispatchPivotApply(), 800);
        return;
      }
      if (status.state === 'failed') {
        toast(`pivot failed: ${status.error || 'unknown'}`, 'err');
        setBusy(sbBtn, false);
        return;
      }
      setTimeout(poll, 2000);
    } catch (e) {
      toast(`pivot poll error: ${e.message}`, 'err');
      setBusy(sbBtn, false);
    }
  };
  poll();
}

async function _dispatchPivotClear() {
  if (!confirm('Clear the most-recent pivot? Session bar reverts to pre-session bias. Files move to forecasts/cleared/ and can be restored manually.')) {
    return;
  }
  const today = _fmtDate(new Date());
  try {
    await api(
      `/api/forecasts/MNQ1/${encodeURIComponent(today)}/pivot`,
      { method: 'DELETE' }
    );
    toast('pivot cleared — session bar reverted', 'ok');
    _closePivotModal();
    await refreshSessionBar();
  } catch (e) {
    toast(`clear failed: ${e.message}`, 'err');
  }
}

document.getElementById('sb-pivot-btn')?.addEventListener('click', _openPivotModal);
document.getElementById('pivot-modal-cancel')?.addEventListener('click', _closePivotModal);
document.getElementById('pivot-modal-clear')?.addEventListener('click', _dispatchPivotClear);
document.getElementById('pivot-modal-go')?.addEventListener('click', _dispatchPivot);
// Backdrop click (anywhere outside the box) closes the modal.
document.getElementById('pivot-modal')?.addEventListener('click', (e) => {
  if (e.target.id === 'pivot-modal') _closePivotModal();
});

// Apply pivot to chart — pushes the generated pivot Pine to TradingView
// as a second indicator (the morning's forecast overlay stays intact).
// `_pivotApplyInFlight` guards against double-tapping: the subprocess
// takes 30-60s and firing two concurrently would drive apply_pine twice.
let _pivotApplyInFlight = false;
async function _dispatchPivotApply() {
  if (_pivotApplyInFlight) {
    toast('apply already in progress — wait for it to finish', 'err');
    return;
  }
  const btn = document.getElementById('sb-pivot-apply-btn');
  if (!btn || btn.classList.contains('hidden')) return;
  const today = _fmtDate(new Date());
  _pivotApplyInFlight = true;
  setBusy(btn, true);
  try {
    const r = await api(
      `/api/forecasts/MNQ1/${encodeURIComponent(today)}/pivot/apply`,
      { method: 'POST', body: {} }
    );
    if (r.ok) {
      toast('pivot applied to chart', 'ok');
    } else {
      toast(`apply failed: ${r.error || 'check stderr'}`, 'err');
    }
  } catch (e) {
    toast(`apply error: ${e.message}`, 'err');
  } finally {
    _pivotApplyInFlight = false;
    setBusy(btn, false);
  }
}
document.getElementById('sb-pivot-apply-btn')?.addEventListener('click', _dispatchPivotApply);

// Trade-tab decision-time lessons — top 3 only, surfaced where the
// human is about to commit a trade. Reuses the Forecasts-tab renderer
// for consistent styling.
async function loadTradeLessons() {
  const meta = document.getElementById('trade-lessons-meta');
  const body = document.getElementById('trade-lessons-body');
  if (!meta || !body) return;
  try {
    const r = await api('/api/forecasts/lessons?n=3');
    _renderLessonsInto(meta, body, r, {
      topN: 3,
      emptyMsg: 'No lessons accumulated yet — run a few reconciliations first.',
    });
  } catch (e) {
    meta.textContent = '';
    body.innerHTML = `<div class="empty err">${escapeHTML(e.message)}</div>`;
  }
}

function renderForecastsList() {
  const list = document.getElementById('forecasts-list');
  if (!_forecastsCache || _forecastsCache.length === 0) {
    list.innerHTML = '<div class="empty">Pick a date in the calendar above to run your first forecast.</div>';
    return;
  }
  list.innerHTML = _forecastsCache.map(d => {
    const key = `${d.symbol}|${d.date}`;
    const sel = key === _forecastsSelectedKey ? ' selected' : '';
    const stages = d.stages || {};
    const stageBadges = ['1000', '1200', '1400'].map(s => {
      const present = stages[s];
      const cls = present ? (present.gate_ok === false ? 'badge-yellow' : 'badge-green') : 'badge-neutral';
      return `<span class="badge ${cls}">${s.slice(0,2)}:${s.slice(2)}</span>`;
    }).join(' ');
    const recon = d.has_reconciliation ? '<span class="badge badge-green">recon ✓</span>' : '<span class="badge badge-neutral">recon —</span>';
    // Accuracy pill — shows best-of-stages score when reconciled. Colored by
    // tier (strong/ok/weak) so the eye finds high-accuracy days at a glance.
    let accPill = '';
    if (d.accuracy && d.accuracy.best_score != null) {
      const tier = _accuracyTier(d.accuracy.best_score, d.accuracy.overall_max);
      const avg = d.accuracy.avg_score != null ? ` · avg ${d.accuracy.avg_score.toFixed(1)}` : '';
      accPill = `<span class="forecast-card__acc acc-pill ${tier}" title="best stage score of the day${avg}">${d.accuracy.best_score}/${d.accuracy.overall_max}</span>`;
    }
    const reconLabel = d.has_reconciliation ? '↻ Re-reconcile' : 'Reconcile';
    const reconTitle = d.has_reconciliation
      ? 'Re-run reconciliation against the completed-day profile (overwrites existing reconciliation file)'
      : 'Grade saved forecast stages against the completed-day profile';
    return `
      <div class="forecast-card${sel}" data-key="${key}" data-symbol="${d.symbol}" data-date="${d.date}">
        <div class="forecast-card__row">
          <span class="forecast-card__date">${d.date}</span>
          <span class="forecast-card__symbol mono small">${d.symbol}</span>
          ${accPill}
        </div>
        <div class="forecast-card__badges">
          ${stageBadges} ${recon}
          <button type="button" class="forecast-card__recon-btn" data-symbol="${d.symbol}" data-date="${d.date}" data-existing="${d.has_reconciliation ? 1 : 0}" title="${reconTitle}">${reconLabel}</button>
        </div>
      </div>
    `;
  }).join('');
  list.querySelectorAll('.forecast-card').forEach(el => {
    el.addEventListener('click', () => selectForecastDay(el.dataset.symbol, el.dataset.date));
  });
  list.querySelectorAll('.forecast-card__recon-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      onForecastReconcileClick(btn.dataset.symbol, btn.dataset.date, btn.dataset.existing === '1');
    });
  });
}

async function onForecastReconcileClick(symbol, date, existing) {
  if (existing && !confirm(`Re-run reconciliation for ${date}? Existing reconciliation file will be overwritten.`)) {
    return;
  }
  // Reconcile requires `profiles/MNQ1_<date>.json` to exist (it's the
  // ground-truth chart-day capture used for grading). Probe first; if
  // missing, kick off a daily-profile run for that single date and
  // wait before triggering reconcile. With `resume:true` this is a
  // fast no-op when the profile exists, so the cost is paid only when
  // there's a real gap to fill — exactly the case that tripped CLI
  // recovery for 2026-05-05 today.
  const key = `${symbol}_${date}`;
  let profileExists = false;
  try {
    const r = await fetch(`/api/profiles/${encodeURIComponent(key)}`, {
      headers: { 'X-UI-Token': localStorage.getItem('ios-ui-token') || '' },
    });
    profileExists = r.ok;
  } catch (e) { /* fall through; treat as missing */ }

  if (!profileExists) {
    toast(`Profile missing — generating ${date} (~60s) before reconciling`, 'ok');
    try {
      await _runProfileAndWait({ dates: [date], symbol, resume: true });
    } catch (e) {
      toast(`profile gen failed: ${e.message} — reconcile not run`, 'err');
      return;
    }
  }
  await _dispatchForecastReconcile({ date, symbol });
}

// Helper: kick a profile run for a list of dates and resolve when the
// task finishes. Throws on task failure. Reuses the same polling
// pattern the Plan tab's Run profile button uses but stays out of the
// shared timer state so a Reconcile chain doesn't collide with a
// user-initiated profile run.
async function _runProfileAndWait(body) {
  const r = await api('/api/profiles/run', { method: 'POST', body });
  const task_id = r.task_id;
  if (!task_id) throw new Error('no task_id in profile run response');
  const t0 = Date.now();
  while (true) {
    if (Date.now() - t0 > 5 * 60 * 1000) throw new Error('profile run timeout (5m)');
    await new Promise(resolve => setTimeout(resolve, 2000));
    const status = await api(`/api/profiles/runs/${task_id}`, { method: 'GET' });
    if (status.state === 'done') return status;
    if (status.state === 'failed') throw new Error(status.error || 'profile run failed');
  }
}

async function _dispatchForecastReconcile(payload) {
  const goEl = document.getElementById('forecast-run-go');
  const statusEl = document.getElementById('forecast-run-status');
  const progressEl = document.getElementById('forecast-run-progress');
  const phaseEl = document.getElementById('forecast-run-phase');
  const eventsEl = document.getElementById('forecast-run-events');

  goEl.disabled = true;
  statusEl.textContent = 'starting reconcile…';
  progressEl.classList.remove('hidden');
  phaseEl.textContent = `Starting reconciliation for ${payload.date}`;
  eventsEl.innerHTML = '';
  _forecastRunSeenEvents = 0;

  let task_id, request_id;
  try {
    const r = await api('/api/forecasts/reconcile', { method: 'POST', body: payload });
    task_id = r.task_id; request_id = r.request_id;
  } catch (e) {
    statusEl.textContent = 'failed to start';
    phaseEl.textContent = `Error: ${e.message}`;
    toast(`reconcile failed: ${e.message}`, 'err');
    goEl.disabled = false;
    return;
  }

  statusEl.textContent = `reconciling (task ${task_id.slice(0, 6)})`;
  _forecastRunPollTimer = setInterval(() => _pollForecastRun(task_id, request_id), 1500);
  _pollForecastRun(task_id, request_id);
}

function _renderAccuracyCard(day) {
  // Renders the reconciliation visual: actual summary + per-stage grade grid.
  // day is the /api/forecasts entry for this date; returns '' if no accuracy.
  if (!day || !day.accuracy || !day.accuracy.grades) return '';
  const acc = day.accuracy;
  const actual = acc.actual_summary || {};
  const max = acc.overall_max || 7;

  // Canonical stage order + display label. Reconciliation JSON uses
  // "pre_session_forecast" key but we show it as "Pre-session".
  const rows = [
    { key: 'pre_session_forecast', label: 'Pre-session' },
    { key: 'F1', label: 'F1 (10:00)' },
    { key: 'F2', label: 'F2 (12:00)' },
    { key: 'F3', label: 'F3 (14:00)' },
  ];
  const fmtNum = v => (v == null || isNaN(v)) ? '—' : Number(v).toLocaleString();
  const pct = actual.net_range_pct_open_to_close;
  const pctStr = (pct == null) ? '' : ` · ${pct >= 0 ? '↑' : '↓'}${Math.abs(pct).toFixed(2)}%`;
  const spanStr = actual.intraday_span_pts != null ? ` · span ${fmtNum(actual.intraday_span_pts)}pts` : '';
  const actualLine = `
    <div class="acc-actual mono small">
      O <b>${fmtNum(actual.open_approx)}</b>  ·  C <b>${fmtNum(actual.close_approx)}</b>  ·  HOD <b>${fmtNum(actual.hod_approx)}</b>  ·  LOD <b>${fmtNum(actual.lod_approx)}</b>${spanStr}${pctStr}
    </div>`;

  const tickOrCross = ok => ok === true ? '<span class="acc-tick">✓</span>' : ok === false ? '<span class="acc-cross">✗</span>' : '<span class="acc-none">—</span>';
  const missCell = (ok, miss) => {
    if (ok === true) return tickOrCross(true);
    if (ok === false) return `${tickOrCross(false)}<span class="acc-miss">${miss != null ? `${miss>0?'':'-'}${Math.abs(miss)}` : ''}</span>`;
    return tickOrCross(ok);
  };
  const dotScore = (score, maxS) => {
    if (score == null) return '—';
    const filled = Math.max(0, Math.min(maxS, score));
    let s = '';
    for (let i = 0; i < maxS; i++) s += i < filled ? '●' : '○';
    return s;
  };

  const tbody = rows.map(r => {
    const g = acc.grades[r.key];
    if (!g) {
      return `<tr class="acc-row acc-row-missing">
        <td class="acc-stage">${r.label}</td>
        <td colspan="5" class="acc-missing muted">no forecast on file</td>
      </tr>`;
    }
    const tier = _accuracyTier(g.overall_score, g.overall_max || max);
    return `<tr class="acc-row ${tier}">
      <td class="acc-stage">${r.label}</td>
      <td class="acc-cell">${tickOrCross(g.direction_hit)}</td>
      <td class="acc-cell">${missCell(g.close_in_band, g.close_miss_pts)}</td>
      <td class="acc-cell">${tickOrCross(g.hod_in_band)}</td>
      <td class="acc-cell">${missCell(g.lod_in_band, g.lod_miss_pts)}</td>
      <td class="acc-score">
        <span class="acc-dots ${tier}">${dotScore(g.overall_score, g.overall_max || max)}</span>
        <span class="acc-num">${g.overall_score}/${g.overall_max || max}</span>
      </td>
    </tr>`;
  }).join('');

  const headerTier = _accuracyTier(acc.best_score, max);
  return `
    <div class="card acc-card">
      <div class="card-head">
        <h2>Accuracy — ${day.date}</h2>
        <div class="card-head__actions">
          <span class="acc-pill ${headerTier}" title="best stage score of the day">best ${acc.best_score}/${max}</span>
          ${acc.avg_score != null ? `<span class="mono small muted">avg ${acc.avg_score.toFixed(1)}/${max}</span>` : ''}
        </div>
      </div>
      ${actualLine}
      <table class="acc-table">
        <thead>
          <tr>
            <th class="acc-stage">Stage</th>
            <th class="acc-cell">Dir</th>
            <th class="acc-cell">Close</th>
            <th class="acc-cell">HOD</th>
            <th class="acc-cell">LOD</th>
            <th class="acc-score">Score</th>
          </tr>
        </thead>
        <tbody>${tbody}</tbody>
      </table>
    </div>
  `;
}

async function selectForecastDay(symbol, date) {
  _forecastsSelectedKey = `${symbol}|${date}`;
  // Keep the calendar selection in lockstep so the Ad-hoc / Pre-session
  // run buttons target the same day shown in the accuracy panel. Without
  // this, the day-card list and the calendar grid drift apart and Ad-hoc
  // always re-runs today.
  _forecastCal.selected = date;
  const [y, m] = date.split('-').map(Number);
  _forecastCal.viewYear = y;
  _forecastCal.viewMonth = m - 1;
  renderForecastCalendar();
  renderForecastsList();
  // Mobile drill-in: switch the layout into detail-only view so the
  // user sees the full forecast chain without a tiny side strip.
  if (_mobileMQ.matches) {
    document.getElementById('forecasts-layout').classList.add('mobile-view-detail');
  }
  const main = document.getElementById('forecasts-main');
  // Preserve the back button — only replace the content after it.
  const backBtn = main.querySelector('.mobile-back-btn');
  main.innerHTML = '';
  if (backBtn) main.appendChild(backBtn);
  main.insertAdjacentHTML('beforeend', '<div class="empty">Loading…</div>');

  // Accuracy visual uses the cached /api/forecasts day entry — no extra fetch.
  const dayEntry = (_forecastsCache || []).find(d => d.symbol === symbol && d.date === date);
  const accuracyHtml = _renderAccuracyCard(dayEntry);

  // Fetch all known stages + recon variants in parallel.
  const stages = ['pre_session', '1000', '1200', '1400', 'reconciliation', 'pre_session_reconciliation'];
  const results = await Promise.all(stages.map(async s => {
    try {
      return { stage: s, ...(await api(`/api/forecasts/${encodeURIComponent(symbol)}/${encodeURIComponent(date)}/${encodeURIComponent(s)}`)) };
    } catch (e) {
      return { stage: s, error: e.message };
    }
  }));

  // Always render the four core stages — pre_session + F1/F2/F3 — even
  // when missing, so the operator can see at-a-glance which stages have
  // captures on file and which don't. Reconciliation variants stay
  // conditional (no card when 404) since their presence depends on the
  // day having ended + a profile existing.
  const _CORE_STAGES = new Set(['pre_session', '1000', '1200', '1400']);
  const _is404 = msg => msg && (msg.includes('404') || msg.includes('not found'));
  const present = results.filter(r => {
    if (!r.error) return true;
    if (_CORE_STAGES.has(r.stage)) return true;  // keep placeholder for core stages
    return !_is404(r.error);                     // optional stages: drop 404
  });

  const titleFor = stage => {
    if (stage === 'pre_session') return 'Pre-Session Forecast';
    if (stage === 'pre_session_reconciliation') return 'Pre-Session Reconciliation';
    if (stage === 'reconciliation') return 'In-Session Reconciliation @ 16:00';
    const idx = ['1000','1200','1400'].indexOf(stage);
    if (idx >= 0) return `F${idx+1} @ ${stage.slice(0,2)}:${stage.slice(2)}`;
    return stage;
  };
  // Hint for missing-stage placeholders — points the user at the right
  // capture surface. pre_session has its own button on the Plan tab;
  // intraday stages run via Ad-hoc (or the live F1/F2/F3 buttons today).
  const _captureHintFor = stage => {
    if (stage === 'pre_session') return 'Tap Pre-session at the top of the Plan tab to capture.';
    if (['1000','1200','1400'].includes(stage)) {
      return 'Tap Ad-hoc at the top of the Plan tab to capture F1/F2/F3 for this day.';
    }
    return '';
  };

  // Stable per-card id so the stage-nav strip can scroll to each one.
  const _stageCardId = stage => `stage-card-${stage.replace(/[^a-z0-9_-]/gi, '')}`;

  const sections = present.map(r => {
    const title = titleFor(r.stage);
    const cardId = _stageCardId(r.stage);
    if (r.error) {
      // 404 → friendly "Not captured yet" placeholder with a hint.
      // Anything else → surface the raw error so transport bugs are
      // visible rather than masked as "missing."
      if (_is404(r.error)) {
        const hint = _captureHintFor(r.stage);
        return `<div id="${cardId}" class="card forecast-stage-card forecast-stage-card--empty">
          <div class="card-head"><h2>${title}</h2>
            <div class="card-head__actions"><span class="mono small muted">no capture on file</span></div>
          </div>
          <div class="empty muted">${hint || 'Not captured yet for this day.'}</div>
        </div>`;
      }
      return `<div id="${cardId}" class="card"><div class="card-head"><h2>${title}</h2></div><div class="empty err">${r.error}</div></div>`;
    }
    const j = r.json || {};
    const metaBits = [];
    if (j.made_at) metaBits.push(`made ${j.made_at}`);
    if (j.gate && j.gate.reason) metaBits.push(`gate: ${j.gate.reason}`);
    const imgUrl = `/api/forecasts/${encodeURIComponent(symbol)}/${encodeURIComponent(date)}/${encodeURIComponent(r.stage)}/screenshot`;
    // Pine + Apply buttons only on pre_session — that's the only stage
    // whose forecast shape maps to the overlay template.
    const pineBtns = r.stage === 'pre_session'
      ? `
        <button class="btn small forecast-pine-btn" data-symbol="${symbol}" data-date="${date}" data-stage="${r.stage}">⬇ Generate Pine overlay</button>
        <button class="btn small forecast-regen-btn" data-symbol="${symbol}" data-date="${date}" data-stage="${r.stage}">↻ Regenerate</button>
        <button class="btn small forecast-apply-btn" data-symbol="${symbol}" data-date="${date}" data-stage="${r.stage}">▶ Apply to chart</button>
      `
      : '';
    const speakBtn = `<button class="btn small forecast-speak-btn" data-symbol="${symbol}" data-date="${date}" data-stage="${r.stage}" title="Read this forecast aloud (Qwen3-TTS, local)">🔊 Speak</button>`;
    return `
      <div id="${cardId}" class="card forecast-stage-card">
        <div class="card-head">
          <h2>${title}</h2>
          <div class="card-head__actions">
            ${speakBtn}
            ${pineBtns}
            <span class="mono small">${metaBits.join('  ')}</span>
          </div>
        </div>
        <div class="compare-pane">
          <div class="compare-img">
            <img src="${imgUrl}" alt="stage screenshot" onerror="this.parentNode.innerHTML='<div class=empty>(no screenshot for this stage)</div>';" />
          </div>
        </div>
        <div class="profile-narrative">${renderProfileMarkdown(r.markdown || j.raw_response || '')}</div>
      </div>
    `;
  });

  // Stage-nav strip — chip per stage with a status dot (filled = has
  // capture, hollow = missing). Click scrolls the page to that card.
  // Sits right under the accuracy panel so the operator sees the full
  // stage chain without scrolling past the first card.
  const _stageNavStrip = (() => {
    if (present.length <= 1) return '';
    const chipFor = r => {
      const t = titleFor(r.stage);
      const has = !r.error;
      const dotClass = has ? 'stage-nav__dot stage-nav__dot--filled' : 'stage-nav__dot';
      return `<a class="stage-nav__chip${has ? '' : ' stage-nav__chip--empty'}"
                 href="#${_stageCardId(r.stage)}">
        <span class="${dotClass}"></span>${t}
      </a>`;
    };
    return `<nav class="stage-nav">${present.map(chipFor).join('')}</nav>`;
  })();

  main.innerHTML =
    `<button type="button" class="mobile-back-btn" data-target="forecasts-layout">‹ Back to list</button>`
    + accuracyHtml + _stageNavStrip
    + `<div class="stage-carousel">${sections.join('')}</div>`;

  // Hook nav chips to scroll the carousel horizontally instead of doing
  // an anchor jump on the page (anchor jumps scroll the page vertically
  // and don't move overflow-scrolled containers — we need scrollIntoView
  // with inline:'start' to align the card to the left edge of the
  // carousel viewport).
  main.querySelectorAll('.stage-nav__chip').forEach(chip => {
    chip.addEventListener('click', ev => {
      ev.preventDefault();
      const href = chip.getAttribute('href') || '';
      const target = href.startsWith('#') ? document.getElementById(href.slice(1)) : null;
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', inline: 'start', block: 'nearest' });
      }
    });
  });

  // Wire Pine-download buttons.
  main.querySelectorAll('.forecast-pine-btn').forEach(btn => {
    btn.addEventListener('click', async ev => {
      ev.preventDefault();
      const { symbol, date, stage } = btn.dataset;
      setBusy(btn, true, '⬇ Generate Pine overlay');
      try {
        const url = `/api/forecasts/${encodeURIComponent(symbol)}/${encodeURIComponent(date)}/${encodeURIComponent(stage)}/pine`;
        const res = await fetch(url, { headers: { 'X-UI-Token': localStorage.getItem('ios-ui-token') || '' } });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        const cd = res.headers.get('content-disposition') || '';
        const m = cd.match(/filename="?([^";]+)"?/i);
        const fname = m ? m[1] : `forecast_overlay_${date}.pine`;
        const objUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = objUrl;
        a.download = fname;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(objUrl);
        toast(`downloaded ${fname}`, 'ok');
      } catch (e) {
        toast(`pine generate failed: ${e.message}`, 'err');
      } finally {
        setBusy(btn, false, '⬇ Generate Pine overlay');
      }
    });
  });

  // Wire Speak buttons — four-state machine on a single button:
  //   idle         "🔊 Speak"           → click triggers synth
  //   synthesizing "Synthesizing… NN%"  → progress bar inside button
  //   ready        "▶ Play"             → click starts playback
  //   playing      "⏸ Stop"             → click stops playback
  //
  // Synth dominates wall-clock time (~10s for a typical pre-session
  // forecast). The first 0–90% of the bar is a time-based estimate
  // since the server can't report intra-synth progress; once the
  // response headers arrive we know X-PCM-Total-Bytes and the last
  // 10% reflects real bytes-received. Audio is buffered into a single
  // AudioBuffer rather than scheduled chunk-by-chunk so the user has
  // an explicit Play gesture (required for autoplay reliability on
  // iOS) and so Stop is straightforward to wire up.
  main.querySelectorAll('.forecast-speak-btn').forEach(btn => {
    const initialHTML = btn.innerHTML;
    let state = 'idle';
    let audioCtx = null;
    let audioBuf = null;
    let source = null;
    let progressTimer = null;

    function setSpeakState(next, htmlOrPct) {
      state = next;
      btn.classList.remove('speak-progressing');
      if (next === 'idle') {
        btn.innerHTML = initialHTML;
        btn.style.removeProperty('--progress');
        btn.disabled = false;
      } else if (next === 'synthesizing' || next === 'loading') {
        const pct = Math.max(0, Math.min(100, Math.round(htmlOrPct || 0)));
        btn.classList.add('speak-progressing');
        btn.style.setProperty('--progress', pct + '%');
        btn.innerHTML = next === 'synthesizing'
          ? `<span class="mono small">Synthesizing… ${pct}%</span>`
          : `<span class="mono small">Loading audio… ${pct}%</span>`;
        btn.disabled = false;  // keep clickable for cancel in a future iteration
        btn.style.pointerEvents = 'none';
      } else if (next === 'ready') {
        btn.innerHTML = '▶ Play';
        btn.style.removeProperty('--progress');
        btn.style.pointerEvents = '';
        btn.disabled = false;
      } else if (next === 'playing') {
        btn.innerHTML = '⏸ Stop';
        btn.style.removeProperty('--progress');
        btn.style.pointerEvents = '';
        btn.disabled = false;
      }
    }

    btn.addEventListener('click', async ev => {
      ev.preventDefault();

      // State-routed click. Synthesizing/loading is non-interactive
      // (pointer-events:none on the button), so this branch never
      // fires in those states — left here for clarity.
      if (state === 'playing') {
        source?.stop();
        return;  // onended swaps state back to 'ready'
      }
      if (state === 'ready') {
        // Start playback. AudioBuffer is already decoded; just wire
        // a new BufferSource (sources are single-shot).
        source = audioCtx.createBufferSource();
        source.buffer = audioBuf;
        source.connect(audioCtx.destination);
        source.onended = () => { setSpeakState('ready'); source = null; };
        source.start();
        setSpeakState('playing');
        return;
      }
      if (state !== 'idle') return;

      // ---- idle → synthesizing → loading → ready ----
      const { symbol, date, stage } = btn.dataset;
      const t0 = Date.now();
      // Rough estimate — pre-session forecasts ~600 chars synth in
      // ~12s on M3 Max. We don't know the script length client-side
      // until the response headers arrive, so use a fixed seed.
      const EXPECTED_SYNTH_MS = 12000;
      setSpeakState('synthesizing', 0);
      progressTimer = setInterval(() => {
        const pct = Math.min(90, ((Date.now() - t0) / EXPECTED_SYNTH_MS) * 90);
        setSpeakState('synthesizing', pct);
      }, 120);

      try {
        const url = `/api/forecasts/${encodeURIComponent(symbol)}/${encodeURIComponent(date)}/${encodeURIComponent(stage)}/speak?stream=1`;
        const res = await fetch(url, { headers: { 'X-UI-Token': localStorage.getItem('ios-ui-token') || '' } });
        clearInterval(progressTimer);
        progressTimer = null;
        if (!res.ok) {
          let msg = `HTTP ${res.status}`;
          try { const j = await res.json(); if (j.detail) msg = j.detail; } catch (_) {}
          throw new Error(msg);
        }
        const sampleRate = parseInt(res.headers.get('X-TTS-Sample-Rate') || '24000');
        const totalBytes = parseInt(res.headers.get('X-PCM-Total-Bytes') || '0');

        // Switch to byte-based progress for the download phase.
        setSpeakState('loading', 0);

        // Drain the body, tracking bytes received against the
        // advertised total for an accurate progress bar.
        const reader = res.body.getReader();
        const parts = [];
        let received = 0;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          parts.push(value);
          received += value.length;
          const pct = totalBytes > 0 ? (received / totalBytes) * 100 : 50;
          setSpeakState('loading', Math.min(99, pct));
        }

        // Concat into one buffer, snap to even length (int16 = 2 bytes).
        const merged = new Uint8Array(received);
        let off = 0;
        for (const p of parts) { merged.set(p, off); off += p.length; }
        const usable = merged.length & ~1;
        const int16 = new Int16Array(merged.buffer, 0, usable / 2);
        const float32 = new Float32Array(int16.length);
        for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

        if (audioCtx) try { audioCtx.close(); } catch (_) {}
        audioCtx = new AudioContext({ sampleRate });
        audioBuf = audioCtx.createBuffer(1, float32.length, sampleRate);
        audioBuf.getChannelData(0).set(float32);

        const synthSec = ((Date.now() - t0) / 1000).toFixed(1);
        const audioSec = (audioBuf.duration).toFixed(1);
        toast(`ready (synth ${synthSec}s · audio ${audioSec}s) — tap ▶ to play`, 'ok');
        setSpeakState('ready');
      } catch (e) {
        if (progressTimer) { clearInterval(progressTimer); progressTimer = null; }
        toast(`speak failed: ${e.message}`, 'err');
        setSpeakState('idle');
      }
    });
  });

  // Wire Regenerate buttons.
  //
  // pre_session stage: rerun the whole pipeline (capture + LLM + save).
  // Routes through _dispatchForecastRun so the user sees the same status
  // bar + audit stream as a fresh start, and so _cdp_busy serializes us
  // against concurrent runs. The card itself doesn't auto-refresh after
  // completion — tap the day again to re-render with the fresh screenshot.
  //
  // Other stages (1000/1200/1400/reconciliation): keep the legacy Pine-
  // only regen for now — those stages don't have a force-rerun endpoint
  // yet, and the Ad-hoc button on the Plan tab is the right escape hatch.
  main.querySelectorAll('.forecast-regen-btn').forEach(btn => {
    btn.addEventListener('click', async ev => {
      ev.preventDefault();
      const { symbol, date, stage } = btn.dataset;
      if (stage === 'pre_session') {
        _dispatchForecastRun({
          kind: 'pre_session',
          endpoint: '/api/forecasts/pre_session',
          body: { date, symbol, force: true },
        });
        return;
      }
      setBusy(btn, true, '↻ Regenerate');
      try {
        const r = await api(`/api/forecasts/${encodeURIComponent(symbol)}/${encodeURIComponent(date)}/${encodeURIComponent(stage)}/regenerate`, { method: 'POST', body: {} });
        toast(`regenerated: ${r.pine_path?.split('/').pop() || 'pine'} (${r.bytes} B)`, 'ok');
      } catch (e) {
        toast(`regenerate failed: ${e.message}`, 'err');
      } finally {
        setBusy(btn, false, '↻ Regenerate');
      }
    });
  });

  // Wire Apply-to-chart buttons. ~30-60s round-trip — disable both pine
  // buttons on the same card during apply to prevent double-fire.
  main.querySelectorAll('.forecast-apply-btn').forEach(btn => {
    btn.addEventListener('click', async ev => {
      ev.preventDefault();
      const { symbol, date, stage } = btn.dataset;
      const card = btn.closest('.forecast-stage-card');
      const pineBtn = card?.querySelector('.forecast-pine-btn');
      // Block re-entry on the SAME button while one apply is in flight.
      // The server now 409s concurrent applies, but client-side de-dupe
      // avoids the round-trip and the resulting confusing 409 toast on
      // a double-tap.
      if (btn.dataset.applying === '1') return;
      btn.dataset.applying = '1';
      setBusy(btn, true, '▶ Apply to chart');
      if (pineBtn) pineBtn.disabled = true;
      toast('Applying to chart… (~30-60s)', 'ok');
      try {
        const r = await api(`/api/forecasts/${encodeURIComponent(symbol)}/${encodeURIComponent(date)}/${encodeURIComponent(stage)}/apply`, { method: 'POST', body: {} });
        if (r.ok) {
          const fname = r.pine_path?.split('/').pop() || 'pine';
          toast(`applied: ${fname}`, 'ok');
        } else {
          // Surface the actual subprocess error so iOS PWA users can
          // diagnose without dev tools. Tail of stderr (or stdout if
          // stderr is empty) is the highest-signal slice. Cap at 200
          // chars so the toast stays usable.
          const tail = (r.stderr_tail && r.stderr_tail.trim())
                     || (r.stdout_tail && r.stdout_tail.trim())
                     || r.error || 'see stdout';
          const msg = tail.split('\n').filter(Boolean).pop() || tail;
          toast(`apply failed: ${msg.slice(0, 200)}`, 'err');
          console.warn('apply stdout tail:', r.stdout_tail);
          console.warn('apply stderr tail:', r.stderr_tail);
        }
      } catch (e) {
        // 409 from the server arrives here with a structured body. Map
        // to a clean "another run in progress" message.
        if (e.status === 409 || /409/.test(e.message || '')) {
          toast('another apply is already running — wait a moment', 'err');
        } else {
          toast(`apply failed: ${e.message}`, 'err');
        }
      } finally {
        setBusy(btn, false, '▶ Apply to chart');
        if (pineBtn) pineBtn.disabled = false;
        btn.dataset.applying = '0';
      }
    });
  });
}

// ----------------------------------------------------------------------
// Onboarding wizard — 4-step first-run flow. Lives inside Setup as the
// `tab-onboarding` section. State is tracked in a module-level object
// so the wizard resumes where the user left off if they switch tabs
// mid-flow. Completion flag persists in localStorage.
// ----------------------------------------------------------------------
const _wizard = {
  initialized: false,
  step: 1,
  checks: { chrome: false, capture: false },
};

function initWizard() {
  if (_wizard.initialized) {
    // Re-entering after leaving: fire the step's auto-probe if applicable.
    _wizardGotoStep(_wizard.step);
    return;
  }
  _wizard.initialized = true;
  _wizardBindHandlers();
  _wizardGotoStep(1);
}

function _wizardBindHandlers() {
  // Step progression via data-wizard-next / data-wizard-prev buttons.
  document.querySelectorAll('#wizard [data-wizard-next]').forEach(btn => {
    btn.addEventListener('click', () => _wizardGotoStep(_wizard.step + 1));
  });
  document.querySelectorAll('#wizard [data-wizard-prev]').forEach(btn => {
    btn.addEventListener('click', () => _wizardGotoStep(_wizard.step - 1));
  });

  // Step 2 — Chrome recheck
  const recheckBtn = $('wizard-chrome-recheck');
  if (recheckBtn) recheckBtn.addEventListener('click', _wizardProbeChrome);

  // Step 2 — Copy command
  const copyBtn = $('wizard-cmd-copy');
  if (copyBtn) copyBtn.addEventListener('click', () => {
    const txt = $('wizard-cmd-text').textContent;
    navigator.clipboard.writeText(txt).then(() => {
      copyBtn.textContent = 'Copied';
      copyBtn.classList.add('copied');
      setTimeout(() => { copyBtn.textContent = 'Copy'; copyBtn.classList.remove('copied'); }, 1800);
    }).catch(() => { toast('copy failed — select manually', 'err'); });
  });

  // Step 3 — Run test capture
  const capBtn = $('wizard-capture-run');
  if (capBtn) capBtn.addEventListener('click', _wizardRunCapture);

  // Step 4 — Finish
  const finishBtn = $('wizard-finish');
  if (finishBtn) finishBtn.addEventListener('click', () => {
    try { localStorage.setItem('onboarding-complete', '1'); } catch (e) {}
    // Route to Today tab — the actual workflow starts here.
    activateGroup('today');
  });
}

function _wizardGotoStep(n) {
  n = Math.max(1, Math.min(4, n));
  _wizard.step = n;

  // Toggle active panel
  document.querySelectorAll('#wizard .wizard-step').forEach(el => {
    el.classList.toggle('active', Number(el.dataset.step) === n);
  });
  // Progress indicator — dots before the current are done, current is active
  document.querySelectorAll('#wizard .wizard-progress__dot').forEach(el => {
    const s = Number(el.dataset.step);
    el.classList.toggle('active', s === n);
    el.classList.toggle('done', s < n);
  });

  // Auto-probes
  if (n === 2) _wizardProbeChrome();
}

async function _wizardProbeChrome() {
  const probe = $('wizard-chrome-probe');
  const help = $('wizard-chrome-help');
  const nextBtn = $('wizard-chrome-next');
  if (!probe) return;

  // Reset to spinner state
  probe.className = 'wizard-probe';
  probe.innerHTML =
    `<span class="wizard-probe__spinner"></span>` +
    `<span class="wizard-probe__lbl">Checking Chrome on port 9222…</span>`;
  if (help) help.classList.add('hidden');
  if (nextBtn) nextBtn.disabled = true;

  try {
    const r = await api('/api/health/browser');
    if (r && r.ok !== false) {
      probe.className = 'wizard-probe wizard-probe--ok';
      probe.innerHTML =
        `<span class="wizard-probe__spinner"></span>` +
        `<span class="wizard-probe__lbl">Chrome connected — CDP on :9222, TradingView attachable.</span>`;
      _wizard.checks.chrome = true;
      if (nextBtn) nextBtn.disabled = false;
      if (help) help.classList.add('hidden');
      return;
    }
    const errMsg = (r && r.err) ? r.err : 'Chrome not reachable on 9222';
    throw new Error(errMsg);
  } catch (e) {
    probe.className = 'wizard-probe wizard-probe--err';
    probe.innerHTML =
      `<span class="wizard-probe__spinner"></span>` +
      `<span class="wizard-probe__lbl">Chrome isn\u2019t reachable on :9222 — ${escapeHTML(e.message || String(e))}</span>`;
    if (help) help.classList.remove('hidden');
    if (nextBtn) nextBtn.disabled = true;
    _wizard.checks.chrome = false;
  }
}

async function _wizardRunCapture() {
  const runBtn = $('wizard-capture-run');
  const probe = $('wizard-capture-probe');
  const shot = $('wizard-capture-shot');
  const img = $('wizard-capture-img');
  const meta = $('wizard-capture-meta');
  const err = $('wizard-capture-err');
  const nextBtn = $('wizard-capture-next');

  if (runBtn) { runBtn.disabled = true; runBtn.textContent = 'Capturing…'; }
  if (probe) probe.classList.remove('hidden');
  if (shot) shot.classList.add('hidden');
  if (err) err.classList.add('hidden');
  if (nextBtn) nextBtn.classList.add('hidden');

  try {
    const r = await api('/api/chart/screenshot', {
      method: 'POST',
      body: { symbol: 'MNQ1!', interval: '1D' },
    });
    if (!r || !r.path) throw new Error('no path returned');
    // Server inlines the PNG as a data: URI so <img> loads work even
    // when the regular /api/chart/image endpoint is auth-gated.
    if (img) img.src = r.data_url || r.url;
    if (meta) meta.textContent = `${r.symbol || 'MNQ1!'} · ${r.interval || '1D'} · ${r.path.split('/').pop()}`;
    if (shot) shot.classList.remove('hidden');
    if (probe) probe.classList.add('hidden');
    if (runBtn) { runBtn.classList.add('hidden'); }
    if (nextBtn) nextBtn.classList.remove('hidden');
    _wizard.checks.capture = true;
  } catch (e) {
    if (probe) probe.classList.add('hidden');
    if (err) {
      err.classList.remove('hidden');
      err.classList.add('wizard-probe--err');
      err.innerHTML =
        `<span class="wizard-probe__spinner"></span>` +
        `<span class="wizard-probe__lbl">Capture failed — ${escapeHTML(e.message || String(e))}</span>`;
    }
    if (runBtn) { runBtn.disabled = false; runBtn.textContent = 'Retry capture'; }
    _wizard.checks.capture = false;
  }
}

// ----------------------------------------------------------------------
// Initial load
// ----------------------------------------------------------------------
refreshChartMeta();
setupCombo('trade-symbol');
setupCombo('alert-symbol');
populateSymbolCombos();  // fire-and-forget — fills all three combos from watchlist
loadTradeLessons();      // Trade is the default tab — surface lessons immediately
startSessionBarPoll();   // persistent session-bar across all tabs

// First-run auto-launch — land in Setup → Wizard when the onboarding
// flag hasn't been set yet. Uses the group activation path so the
// sidebar highlights Setup and the sub-tab bar appears.
if (!_onboardingDone()) {
  // Defer so the initial tab's own hooks finish first (no interleaving).
  setTimeout(() => activateGroup('setup'), 0);
}


// ============================================================================
// UNIFIED TODAY DAY-ARC — single linear timeline of the trading day.
// Pre-session → canary checks ticking through 09:00–12:00 → 10/12/14
// forecasts → pivot if any → profile/grading at 16:00. Reads
// /api/journal/{sym}/{date} + /api/canary/{sym}/{date}; both are pure
// reads so re-rendering on a 30s poll is cheap.
// ============================================================================

let _todayArcTimer = null;
let _todayArcBusy = false;

function _isoToday() {
  // Local ISO date — matches the cron + UI server's date-of-day
  // convention. `toISOString()` returns UTC, which differs across the
  // day-boundary; build the local date manually.
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${dd}`;
}

function _hhmmEt() {
  // Approximate HH:MM in ET — used to gate which stages should be
  // "future" (faded) vs already-due. Browser is on user's local clock;
  // cron runs in ET. Use `toLocaleTimeString` with America/New_York to
  // get the actual ET time on whatever device the user is on.
  try {
    const fmt = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/New_York', hour12: false,
      hour: '2-digit', minute: '2-digit',
    });
    return fmt.format(new Date()).replace(/^24:/, '00:');
  } catch (e) {
    const d = new Date();
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }
}

function _hhmmGE(a, b) {
  // String comparison works for "HH:MM" once both are zero-padded.
  return a >= b;
}

function _arcNodeClass(scoreOrStatus) {
  // Convert axes_score "p/t" or a plain status string to a state class.
  if (!scoreOrStatus) return 'is-pending';
  if (typeof scoreOrStatus === 'string' && scoreOrStatus.includes('/')) {
    const [p, t] = scoreOrStatus.split('/').map(Number);
    if (!t) return 'is-pending';
    const r = p / t;
    if (r >= 0.8) return 'is-pass';
    if (r >= 0.4) return 'is-partial';
    return 'is-fail';
  }
  if (scoreOrStatus === 'pass' || scoreOrStatus === 'passing') return 'is-pass';
  if (scoreOrStatus === 'fail' || scoreOrStatus === 'failing') return 'is-fail';
  if (scoreOrStatus === 'partial') return 'is-partial';
  return 'is-pending';
}

function _arcChip(label, kind) {
  const cls = kind ? ` is-${kind}` : '';
  return `<span class="today-arc__chip${cls}">${escapeHtml(label)}</span>`;
}

function _renderArcPreSession(stage, canary) {
  const grading = stage.grading;
  const cls = grading ? _arcNodeClass(grading.axes_score) : 'is-pending';
  const score = grading?.axes_score
    ? `<span class="today-arc__node-score ${_arcNodeClass(grading.axes_score)}">${escapeHtml(grading.axes_score)}</span>`
    : '<span class="today-arc__node-score">—</span>';
  const bias = stage.tactical_bias?.bias_text
    || stage.predictions?.direction
    || (stage.regime_read ? stage.regime_read.split('.')[0] : '—');
  const inval = stage.tactical_bias?.invalidation || '—';
  const thesis = canary?.canary?.thesis_summary;
  return `<div class="today-arc__node ${cls}">
    <div class="today-arc__node-head">
      <span class="today-arc__node-time">08:30</span>
      <span class="today-arc__node-label">Pre-session</span>
      ${score}
    </div>
    <div class="today-arc__node-body">
      <div><b>Bias</b> ${escapeHtml(String(bias).slice(0, 200))}</div>
      <div><b>Invalidates if</b> <span class="muted">${escapeHtml(String(inval).slice(0, 200))}</span></div>
      ${thesis ? `<div><b>Thesis</b> <i>${escapeHtml(thesis)}</i></div>` : ''}
    </div>
  </div>`;
}

function _renderArcCanary(canary) {
  if (!canary?.available) return '';
  const checks = canary.canary?.checks || [];
  const status = canary.status || {};
  const ag = status.aggregate;
  const byId = Object.fromEntries((status.results || []).map(r => [r.id, r]));
  const stateCls = ag?.state ? _arcNodeClass(ag.state) : 'is-pending';
  const ratioTxt = ag
    ? `${ag.pass_weight}/${ag.pass_weight + ag.fail_weight + ag.pending_weight + ag.evaluate_failed_weight} weight`
    : `${checks.length} checks · pending`;
  const action = ag?.recommended_action || 'wait';
  const rows = checks.map(c => {
    const r = byId[c.id];
    const s = r?.status || 'pending';
    const rowCls = s === 'not_yet_evaluable' ? 'is-pending'
      : s === 'evaluate_failed' ? 'is-failed'
      : s === 'pass' ? 'is-pass'
      : s === 'fail' ? 'is-fail'
      : s === 'snoozed' ? 'is-snoozed'
      : 'is-pending';
    let evidence = '';
    if (r?.evidence) {
      const e = r.evidence;
      if (e.close != null && e.threshold != null) {
        evidence = `${e.close.toLocaleString()} ${e.comparison} ${e.threshold.toLocaleString()}`;
      } else if (e.actual_low != null) {
        evidence = `low ${e.actual_low.toLocaleString()} ${e.comparison} ${e.threshold.toLocaleString()}`;
      } else if (e.actual_high != null) {
        evidence = `high ${e.actual_high.toLocaleString()} ${e.comparison} ${e.threshold.toLocaleString()}`;
      } else if (e.observed) {
        evidence = `observed ${e.observed}`;
      } else if (e.reason) {
        evidence = e.reason;
      }
    }
    const evHtml = evidence
      ? `<span class="today-arc__canary-evidence" title="${escapeHtml(evidence)}">${escapeHtml(evidence)}</span>`
      : '';
    return `<div class="today-arc__canary-row ${rowCls}">
      <span class="today-arc__canary-id">${escapeHtml(c.id)}</span>
      ${c.evaluate_at ? `<span class="today-arc__canary-deadline">@${escapeHtml(c.evaluate_at)} ET</span>` : ''}
      ${evHtml}
      <span class="today-arc__canary-status">${escapeHtml(s)}</span>
    </div>`;
  }).join('');
  return `<div class="today-arc__node ${stateCls}">
    <div class="today-arc__node-head">
      <span class="today-arc__node-time">09:00–12:00</span>
      <span class="today-arc__node-label">Canary · ${escapeHtml(ag?.state || 'pending')}</span>
      <span class="today-arc__node-score ${stateCls}">${escapeHtml(ratioTxt)}</span>
    </div>
    <div class="today-arc__node-body">
      <div><b>Action</b> ${escapeHtml(action)}</div>
      <div class="today-arc__canary-checks">${rows}</div>
      <div class="today-arc__node-actions">
        <button class="today-arc__action-btn" id="today-arc-canary-eval">Re-evaluate now</button>
      </div>
    </div>
  </div>`;
}

function _renderArcLiveStage(stage, timeLbl, hhmm, nowEt) {
  if (!stage) {
    const isFuture = !_hhmmGE(nowEt, hhmm);
    return `<div class="today-arc__node ${isFuture ? 'is-future' : 'is-pending'}">
      <div class="today-arc__node-head">
        <span class="today-arc__node-time">${timeLbl}</span>
        <span class="today-arc__node-label">Live forecast</span>
        <span class="today-arc__node-score">${isFuture ? 'scheduled' : 'not yet run'}</span>
      </div>
    </div>`;
  }
  const grading = stage.grading;
  const cls = grading ? _arcNodeClass(grading.axes_score) : 'is-pending';
  const score = grading?.axes_score
    ? `<span class="today-arc__node-score ${_arcNodeClass(grading.axes_score)}">${escapeHtml(grading.axes_score)}</span>`
    : '<span class="today-arc__node-score">awaiting profile</span>';
  let body = '';
  if (grading?.bands) {
    const chips = grading.bands.map(b => {
      if (b.predicted_lo == null && b.predicted_hi == null) {
        return _arcChip(`${b.label}: n/a`, '');
      }
      if (b.hit === true) {
        const actual = b.actual?.toLocaleString() ?? '?';
        return _arcChip(`${b.label} ${actual}`, 'pass');
      }
      if (b.hit === false) {
        return _arcChip(`${b.label} ${b.side === 'over' ? '↑' : '↓'}${b.miss_pts}pts`, 'fail');
      }
      const lo = b.predicted_lo?.toLocaleString() ?? '?';
      const hi = b.predicted_hi?.toLocaleString() ?? '?';
      return _arcChip(`${b.label} [${lo}, ${hi}]`, '');
    }).join('');
    body = `<div class="today-arc__chips">${chips}</div>`;
  } else if (stage.raw_response) {
    body = `<div class="muted">${escapeHtml(stage.raw_response.slice(0, 220))}…</div>`;
  }
  return `<div class="today-arc__node ${cls}">
    <div class="today-arc__node-head">
      <span class="today-arc__node-time">${timeLbl}</span>
      <span class="today-arc__node-label">${escapeHtml(stage.label || 'Live')}</span>
      ${score}
    </div>
    <div class="today-arc__node-body">${body}</div>
  </div>`;
}

function _renderArcPivot(piv) {
  const grading = piv.grading;
  const cls = grading ? _arcNodeClass(grading.axes_score) : 'is-fail';
  const score = grading?.axes_score
    ? `<span class="today-arc__node-score ${_arcNodeClass(grading.axes_score)}">${escapeHtml(grading.axes_score)}</span>`
    : '<span class="today-arc__node-score is-fail">invalidated</span>';
  const reason = piv.reason || piv.raw_response?.slice(0, 200) || '';
  return `<div class="today-arc__node ${cls}">
    <div class="today-arc__node-head">
      <span class="today-arc__node-time">${escapeHtml(piv.label || 'pivot')}</span>
      <span class="today-arc__node-label">Pivot</span>
      ${score}
    </div>
    <div class="today-arc__node-body">
      ${reason ? `<div class="muted">${escapeHtml(reason)}</div>` : ''}
    </div>
  </div>`;
}

function _renderArcProfile(profileWrap, nowEt) {
  if (profileWrap?.available) {
    const sm = profileWrap.summary || {};
    const tags = profileWrap.tags || {};
    return `<div class="today-arc__node is-pass">
      <div class="today-arc__node-head">
        <span class="today-arc__node-time">16:00</span>
        <span class="today-arc__node-label">Profile · captured</span>
        <span class="today-arc__node-score">${escapeHtml(sm.direction || '—')}</span>
      </div>
      <div class="today-arc__node-body">
        <div class="today-arc__chips">
          ${_arcChip(`open ${sm.open_approx?.toLocaleString() ?? '—'}`)}
          ${_arcChip(`close ${sm.close_approx?.toLocaleString() ?? '—'}`)}
          ${_arcChip(`HOD ${sm.hod_approx?.toLocaleString() ?? '—'}`)}
          ${_arcChip(`LOD ${sm.lod_approx?.toLocaleString() ?? '—'}`)}
          ${tags.structure ? _arcChip(tags.structure) : ''}
        </div>
        ${profileWrap.takeaway ? `<div class="muted"><i>${escapeHtml(profileWrap.takeaway)}</i></div>` : ''}
      </div>
    </div>`;
  }
  const isFuture = !_hhmmGE(nowEt, '16:00');
  return `<div class="today-arc__node ${isFuture ? 'is-future' : 'is-pending'}">
    <div class="today-arc__node-head">
      <span class="today-arc__node-time">16:00</span>
      <span class="today-arc__node-label">Profile</span>
      <span class="today-arc__node-score">${isFuture ? 'after close' : 'not captured'}</span>
    </div>
    <div class="today-arc__node-body">
      <div class="muted">Capture pulls today's chart and seeds tomorrow's pre-session priors.</div>
    </div>
  </div>`;
}

async function renderTodayArc() {
  const body = document.getElementById('today-arc-body');
  if (!body) return;
  if (_todayArcBusy) return;
  _todayArcBusy = true;
  const date = _isoToday();
  const dateLabel = document.getElementById('today-arc-date-label');
  if (dateLabel) dateLabel.textContent = date;
  const rollup = document.getElementById('today-arc-rollup');

  // Fire both fetches in parallel — independent endpoints.
  let journal = null, canary = null;
  try {
    [journal, canary] = await Promise.all([
      api(`/api/journal/MNQ1/${date}`).catch(() => null),
      api(`/api/canary/MNQ1/${date}`).catch(() => null),
    ]);
  } finally { _todayArcBusy = false; }

  if (!journal) {
    body.innerHTML = '<div class="empty">Could not load today\'s arc — server unreachable.</div>';
    if (rollup) rollup.textContent = '—';
    return;
  }

  const stages = journal.stages || [];
  const stageByKey = Object.fromEntries(stages.map(s => [s.key, s]));
  const pre = stageByKey['pre_session'];
  const f10 = stageByKey['1000'];
  const f12 = stageByKey['1200'];
  const f14 = stageByKey['1400'];
  const pivots = stages.filter(s => !['pre_session', '1000', '1200', '1400'].includes(s.key));
  const nowEt = _hhmmEt();

  const out = [];
  if (pre) out.push(_renderArcPreSession(pre, canary));
  else {
    out.push(`<div class="today-arc__node is-pending">
      <div class="today-arc__node-head">
        <span class="today-arc__node-time">08:30</span>
        <span class="today-arc__node-label">Pre-session</span>
        <span class="today-arc__node-score">not run</span>
      </div>
      <div class="today-arc__node-body">
        <div class="muted">Run the pre-session forecast to seed today's bias and canary trip-wires.</div>
      </div>
    </div>`);
  }
  if (canary?.available) out.push(_renderArcCanary(canary));
  out.push(_renderArcLiveStage(f10, '10:00', '10:00', nowEt));
  // Inline any pivot artifacts whose stage name suggests they fired
  // before 12:00. Heuristic: TV stages are "1000"/"1200"/"1400"; pivots
  // are "pivot_HH-MM-SS" or "invalidation_HHMM" — show after the live
  // stage that immediately precedes them in time.
  const pivBefore12 = pivots.filter(p => {
    const m = (p.key || '').match(/(\d{2})[-_]?(\d{2})/);
    if (!m) return false;
    return `${m[1]}:${m[2]}` < '12:00';
  });
  pivBefore12.forEach(p => out.push(_renderArcPivot(p)));
  out.push(_renderArcLiveStage(f12, '12:00', '12:00', nowEt));
  const pivBefore14 = pivots.filter(p => {
    const m = (p.key || '').match(/(\d{2})[-_]?(\d{2})/);
    if (!m) return false;
    const t = `${m[1]}:${m[2]}`;
    return t >= '12:00' && t < '14:00';
  });
  pivBefore14.forEach(p => out.push(_renderArcPivot(p)));
  out.push(_renderArcLiveStage(f14, '14:00', '14:00', nowEt));
  const pivAfter14 = pivots.filter(p => {
    const m = (p.key || '').match(/(\d{2})[-_]?(\d{2})/);
    if (!m) return true;  // no time → show late
    return `${m[1]}:${m[2]}` >= '14:00';
  });
  pivAfter14.forEach(p => out.push(_renderArcPivot(p)));
  out.push(_renderArcProfile(journal.profile, nowEt));

  body.innerHTML = out.join('');

  if (rollup) {
    if (journal.rollup?.score) {
      rollup.classList.remove('muted');
      rollup.textContent = `${journal.rollup.score} axes`;
    } else {
      rollup.classList.add('muted');
      rollup.textContent = `${stages.length} stage${stages.length === 1 ? '' : 's'} · grading pending`;
    }
  }

  // Wire the inline canary re-evaluate button.
  const evalBtn = document.getElementById('today-arc-canary-eval');
  if (evalBtn) {
    evalBtn.addEventListener('click', async () => {
      evalBtn.disabled = true;
      evalBtn.textContent = 'Evaluating…';
      try {
        const r = await api(`/api/canary/MNQ1/${date}/evaluate`, { method: 'POST', body: {} });
        if (r.ok) toast('canary re-evaluated', 'ok');
        else toast(`evaluate: ${r.reason || 'see audit'}`, 'err');
      } catch (e) { toast(`evaluate failed: ${e.message}`, 'err'); }
      finally {
        evalBtn.disabled = false;
        evalBtn.textContent = 'Re-evaluate now';
        renderTodayArc();
        refreshCanaryCell();
      }
    });
  }
}

document.getElementById('today-arc-refresh')?.addEventListener('click', renderTodayArc);

// Auto-poll every 60s while the Today tab is the active one. The
// session-bar's own 30s poll keeps the topbar canary/PnL fresh; the
// timeline body (heavier render) refreshes half as often to stay
// kind to the canary endpoint and the profile endpoint.
function _startTodayArcPoll() {
  if (_todayArcTimer) clearInterval(_todayArcTimer);
  _todayArcTimer = setInterval(() => {
    if (document.getElementById('tab-today')?.classList.contains('hidden')) return;
    renderTodayArc();
  }, 60_000);
}
_startTodayArcPoll();

// ======================================================================
// Coach tab — AI Visual Coach + Sketchpad
// ======================================================================
//
// Three-card tab: capture controls → proposals (after Analyze) → sketchpad.
// Sketchpad JSON is the source of truth (`tradingview/sketchpad/<sym>_<date>.json`);
// the Pine artifact is regenerated on every Apply.
//
// State is mostly DOM-resident — last-proposals lives on the proposals
// card itself (data-attr); sketchpad is fetched fresh on each refresh.

let _coachInitialized = false;
let _coachActiveTask = null;
let _coachPollTimer = null;
let _coachLastProposals = null;  // last full result from /api/coach/analyze
let _coachThreadId = null;       // active chat thread (set after Analyze)
let _coachChatTask = null;       // in-flight chat-turn task_id
let _coachChatPollTimer = null;
let _coachLastSignal = null;     // last proposed signal (initial OR from chat)

function _coachToday() {
  // Local-time YYYY-MM-DD. Matches the date the sketchpad endpoints
  // and the visual_coach forecast loader use.
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function _coachSymbol() {
  return (document.getElementById('coach-symbol')?.value || 'MNQ1!').trim();
}

function _coachEsc(s) {
  // Minimal HTML-escape for label / rationale text. We render visuals
  // via innerHTML so checkbox/button hooks are easy — escaping here
  // keeps any < / > / & / " from breaking the row.
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function _coachVisualSummary(v) {
  // One-line, type-specific summary for the per-row display.
  if (v.type === 'level') {
    const px = Number(v.price).toLocaleString(undefined, { maximumFractionDigits: 2 });
    const al = v.alert_on_cross ? ' · alert' : '';
    return `level @ ${px}${al}`;
  }
  if (v.type === 'vline') return `vline @ ${v.time_et} ET`;
  if (v.type === 'cross_alert') {
    const px = Number(v.price).toLocaleString(undefined, { maximumFractionDigits: 2 });
    const arrow = v.direction === 'above' ? '↑' : '↓';
    return `cross ${arrow} ${px}`;
  }
  return v.type;
}

function _coachConfidenceClass(c) {
  return ({ high: 'coach-conf-high', med: 'coach-conf-med', low: 'coach-conf-low' })[c] || '';
}

// --- Init: bind once -------------------------------------------------
function initCoachTab() {
  if (_coachInitialized) return;
  _coachInitialized = true;

  document.getElementById('coach-analyze-btn')
    ?.addEventListener('click', runCoachAnalyze);
  document.getElementById('coach-proposals-accept-btn')
    ?.addEventListener('click', acceptSelectedProposals);
  document.getElementById('coach-proposals-toggle-all')
    ?.addEventListener('click', toggleAllProposals);
  document.getElementById('coach-sketchpad-clear-btn')
    ?.addEventListener('click', clearSketchpad);
  document.getElementById('coach-sketchpad-apply-btn')
    ?.addEventListener('click', applySketchpad);
  document.getElementById('coach-signal-accept-btn')
    ?.addEventListener('click', acceptSignalLevels);

  // Chat — submit on Send button OR Cmd/Ctrl+Enter in the textarea.
  const chatForm = document.getElementById('coach-chat-form');
  chatForm?.addEventListener('submit', e => { e.preventDefault(); sendCoachChat(); });
  document.getElementById('coach-chat-input')
    ?.addEventListener('keydown', e => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        sendCoachChat();
      }
    });
}

// --- Run analyze -----------------------------------------------------
async function runCoachAnalyze() {
  const btn = document.getElementById('coach-analyze-btn');
  const status = document.getElementById('coach-run-status');
  const symbol = _coachSymbol();
  const tf = document.getElementById('coach-tf')?.value || '5m';
  const pm = (document.getElementById('coach-provider-model')?.value || 'claude_web|opus').split('|');
  const provider = pm[0];
  const model = pm[1];

  if (!symbol) { alert('Symbol required'); return; }

  btn.disabled = true;
  btn.textContent = 'Analyzing…';
  if (status) status.textContent = 'capturing chart…';

  try {
    const r = await api('/api/coach/analyze', {
      method: 'POST',
      body: { symbol, timeframe: tf, provider, model },
    });
    if (!r?.task_id) throw new Error('no task_id');
    _coachActiveTask = r.task_id;
    if (status) status.textContent = `task ${r.task_id} · running…`;
    pollCoachTask(r.task_id);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'Analyze chart';
    if (status) status.textContent = `error: ${e.message || e}`;
  }
}

function pollCoachTask(taskId) {
  if (_coachPollTimer) clearInterval(_coachPollTimer);
  const started = Date.now();
  _coachPollTimer = setInterval(async () => {
    try {
      const t = await api(`/api/coach/task/${taskId}`);
      const elapsed = Math.round((Date.now() - started) / 1000);
      const status = document.getElementById('coach-run-status');
      if (status) status.textContent = `${t.state || '?'} · ${elapsed}s`;

      if (t.state === 'done') {
        clearInterval(_coachPollTimer);
        _coachPollTimer = null;
        _coachActiveTask = null;
        document.getElementById('coach-analyze-btn').disabled = false;
        document.getElementById('coach-analyze-btn').textContent = 'Analyze chart';
        _onCoachAnalyzeDone(t.result);
      } else if (t.state === 'failed' || t.state === 'cancelled') {
        clearInterval(_coachPollTimer);
        _coachPollTimer = null;
        _coachActiveTask = null;
        document.getElementById('coach-analyze-btn').disabled = false;
        document.getElementById('coach-analyze-btn').textContent = 'Analyze chart';
        if (status) status.textContent = `${t.state}: ${t.error || ''}`;
      }
    } catch (e) {
      // Transient — keep polling. Hard fail will surface when the task
      // disappears (404) and we'll stop.
    }
  }, 1500);
}

// --- Render proposals ------------------------------------------------
// `mergeVisuals` mode: when true, append new visuals to the list (used
// for chat-sourced visuals). Default replaces — used for initial Analyze.
function renderCoachProposals(result, { mergeVisuals = false } = {}) {
  if (!result) return;

  const card = document.getElementById('coach-proposals-card');
  const ctx  = document.getElementById('coach-context');
  const list = document.getElementById('coach-proposals');
  const meta = document.getElementById('coach-proposals-meta');

  let visuals = result.visuals || [];
  if (mergeVisuals && _coachLastProposals?.visuals?.length) {
    // Dedupe by id so re-emit doesn't duplicate the same row.
    const seen = new Set(visuals.map(v => v.id));
    const carryover = _coachLastProposals.visuals.filter(v => !seen.has(v.id));
    visuals = [...carryover, ...visuals];
  }

  const merged = { ...result, visuals };
  _coachLastProposals = merged;

  const ctxText = result.context_read || _coachLastProposals?.context_read || '';
  const skip = result.skip_rationale;

  if (ctx) ctx.textContent = ctxText || '(no context)';
  if (meta) {
    const took = result.llm_elapsed_s ? `${result.llm_elapsed_s}s` : '?s';
    meta.textContent = `${visuals.length} proposals · ${result.provider || ''} · ${result.model || ''} · ${took}`;
  }

  card.classList.remove('hidden');

  if (visuals.length === 0) {
    list.innerHTML = `<div class="empty small">${_coachEsc(skip || 'No additive visuals proposed.')}</div>`;
    document.getElementById('coach-proposals-accept-btn').disabled = true;
    return;
  }

  document.getElementById('coach-proposals-accept-btn').disabled = false;
  list.innerHTML = visuals.map(v => `
    <label class="coach-proposal" data-vid="${_coachEsc(v.id)}">
      <input type="checkbox" class="coach-proposal__cb" checked
             data-visual='${_coachEsc(JSON.stringify(v))}'>
      <span class="coach-proposal__chip coach-color-${_coachEsc(v.color)}">${_coachEsc(v.type)}</span>
      <span class="coach-proposal__label">${_coachEsc(v.label)}</span>
      <span class="coach-proposal__summary mono small">${_coachEsc(_coachVisualSummary(v))}</span>
      <span class="coach-proposal__conf small ${_coachConfidenceClass(v.confidence)}">${_coachEsc(v.confidence)}</span>
      <span class="coach-proposal__rationale small muted">${_coachEsc(v.rationale)}</span>
    </label>
  `).join('');
}

// Update the call site after Analyze completes — render the signal
// banner, the proposals list, and open the chat card.
function _onCoachAnalyzeDone(result) {
  renderCoachSignal(result?.signal || null, {
    provider: result?.provider, model: result?.model,
    elapsed: result?.llm_elapsed_s,
  });
  renderCoachProposals(result);
  if (result?.thread_id) {
    _coachThreadId = result.thread_id;
    _hydrateChatCard(result);
  }
}

// --- Signal banner --------------------------------------------------
function renderCoachSignal(signal, extra = {}) {
  const card = document.getElementById('coach-signal-card');
  if (!card) return;
  if (!signal || !signal.side) {
    card.classList.add('hidden');
    return;
  }
  _coachLastSignal = signal;
  card.classList.remove('hidden');

  const side = signal.side;
  card.classList.remove('coach-signal-card--long',
                        'coach-signal-card--short',
                        'coach-signal-card--hold');
  card.classList.add(`coach-signal-card--${side.toLowerCase()}`);

  document.getElementById('coach-signal-side').textContent = side.toUpperCase();

  const lvl = document.getElementById('coach-signal-levels');
  const fmt = n => Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (side === 'Hold' || signal.entry == null || signal.stop == null || signal.tp == null) {
    lvl.innerHTML = `<span class="coach-signal__hold-msg muted">No actionable trade right now</span>`;
    document.getElementById('coach-signal-rr').textContent = '';
    document.getElementById('coach-signal-accept-btn').disabled = true;
  } else {
    lvl.innerHTML = `
      <div class="coach-signal__lvl coach-signal__lvl--entry">
        <span class="coach-signal__lvl-name">ENTRY</span>
        <span class="coach-signal__lvl-px mono">${_coachEsc(fmt(signal.entry))}</span>
      </div>
      <div class="coach-signal__lvl coach-signal__lvl--stop">
        <span class="coach-signal__lvl-name">STOP</span>
        <span class="coach-signal__lvl-px mono">${_coachEsc(fmt(signal.stop))}</span>
      </div>
      <div class="coach-signal__lvl coach-signal__lvl--tp">
        <span class="coach-signal__lvl-name">TP</span>
        <span class="coach-signal__lvl-px mono">${_coachEsc(fmt(signal.tp))}</span>
      </div>
    `;
    const rr = signal.r_r;
    let rrCls = 'coach-signal__rr--low';
    if (rr != null && rr >= 2) rrCls = 'coach-signal__rr--good';
    else if (rr != null && rr >= 1.5) rrCls = 'coach-signal__rr--ok';
    document.getElementById('coach-signal-rr').innerHTML = rr != null
      ? `<span class="coach-signal__rr-val ${rrCls}">${rr}R</span> · risk ${fmt(Math.abs(signal.entry - signal.stop))} · reward ${fmt(Math.abs(signal.tp - signal.entry))}`
      : '';
    document.getElementById('coach-signal-accept-btn').disabled = false;
  }

  document.getElementById('coach-signal-rationale').textContent = signal.rationale || '';

  const meta = document.getElementById('coach-signal-meta');
  const conf = signal.confidence ? `confidence ${signal.confidence}` : '';
  const took = extra.elapsed ? `${extra.elapsed}s` : '';
  const provider = extra.provider ? `${extra.provider} · ${extra.model || ''}` : '';
  meta.textContent = [conf, provider, took].filter(Boolean).join(' · ');
}

// "Accept trade levels" — pull the entry/stop/tp visuals out of the
// proposals list (they were synthesized server-side and prepended)
// and POST them to the sketchpad accept endpoint as one batch.
async function acceptSignalLevels() {
  if (!_coachLastProposals?.visuals) return;
  const tradeVisuals = _coachLastProposals.visuals.filter(v =>
    ['trade_entry', 'trade_stop', 'trade_tp'].includes(v.role)
  );
  if (tradeVisuals.length === 0) {
    alert('No trade-level visuals available — signal may be Hold.');
    return;
  }

  const symbol = _coachLastProposals.symbol || _coachSymbol();
  const date = _coachToday();
  const btn = document.getElementById('coach-signal-accept-btn');
  btn.disabled = true;
  btn.textContent = 'Accepting…';
  try {
    const r = await api(`/api/sketchpad/${encodeURIComponent(symbol)}/${date}/accept`, {
      method: 'POST', body: { visuals: tradeVisuals },
    });
    btn.textContent = `Added ${r.accepted || 0} trade levels — Apply to chart to push`;
    setTimeout(() => {
      btn.textContent = 'Accept trade levels → Sketchpad';
      btn.disabled = false;
    }, 2200);
    refreshSketchpad();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'Accept trade levels → Sketchpad';
    alert(`Accept failed: ${e.message || e}`);
  }
}

function _hydrateChatCard(result) {
  const card = document.getElementById('coach-chat-card');
  const meta = document.getElementById('coach-chat-meta');
  const transcript = document.getElementById('coach-chat-transcript');
  if (!card) return;
  card.classList.remove('hidden');
  if (meta) meta.textContent = `thread ${_coachThreadId} · ${result.provider} · ${result.model}`;

  // Seed the transcript with the analyze context as the first
  // assistant message so the user sees what the LLM "said" first.
  const seed = result.context_read || '';
  transcript.innerHTML = `
    <div class="coach-msg coach-msg--assistant">
      <div class="coach-msg__role mono small">coach</div>
      <div class="coach-msg__body">${_coachEsc(seed) || '(analyzed)'}</div>
    </div>
  `;
  transcript.scrollTop = transcript.scrollHeight;
}

// --- Chat send -------------------------------------------------------
async function sendCoachChat() {
  if (!_coachThreadId) {
    alert('Run Analyze first to start a chat thread.');
    return;
  }
  const inp = document.getElementById('coach-chat-input');
  const send = document.getElementById('coach-chat-send');
  const transcript = document.getElementById('coach-chat-transcript');
  const message = (inp.value || '').trim();
  if (!message) return;

  // Optimistic render of the user message + a pending assistant bubble.
  _appendChatMessage('user', message);
  const pendingId = `coach-pending-${Date.now()}`;
  _appendChatMessage('assistant', '…thinking', { idAttr: pendingId, pending: true });
  inp.value = '';
  send.disabled = true;
  send.textContent = 'Sending…';

  try {
    const r = await api('/api/coach/chat', {
      method: 'POST',
      body: { thread_id: _coachThreadId, message },
    });
    if (!r?.task_id) throw new Error('no task_id');
    _coachChatTask = r.task_id;
    _pollCoachChat(r.task_id, pendingId);
  } catch (e) {
    _replaceChatMessage(pendingId, 'assistant', `error: ${e.message || e}`);
    send.disabled = false;
    send.textContent = 'Send';
  }
}

function _pollCoachChat(taskId, pendingId) {
  if (_coachChatPollTimer) clearInterval(_coachChatPollTimer);
  const started = Date.now();
  _coachChatPollTimer = setInterval(async () => {
    try {
      const t = await api(`/api/coach/chat/task/${taskId}`);
      const elapsed = Math.round((Date.now() - started) / 1000);
      const pendingEl = document.getElementById(pendingId);
      if (pendingEl) {
        const body = pendingEl.querySelector('.coach-msg__body');
        if (body) body.textContent = `…thinking (${elapsed}s)`;
      }

      if (t.state === 'done') {
        clearInterval(_coachChatPollTimer);
        _coachChatPollTimer = null;
        _coachChatTask = null;
        const reply = t.result?.reply || '(empty reply)';
        _replaceChatMessage(pendingId, 'assistant', reply);
        const sendBtn = document.getElementById('coach-chat-send');
        sendBtn.disabled = false;
        sendBtn.textContent = 'Send';

        // Signal updates from chat — re-render the banner. The
        // synthesized trade-level visuals are already in new_visuals
        // (server-side merged) so the proposals merge below picks them
        // up automatically.
        const newSignal = t.result?.new_signal;
        if (newSignal) {
          renderCoachSignal(newSignal, {
            provider: _coachLastProposals?.provider,
            model:    _coachLastProposals?.model,
            elapsed:  t.result?.elapsed_s,
          });
        }

        // New visuals from the chat reply land in the proposals panel.
        const newVisuals = t.result?.new_visuals || [];
        if (newVisuals.length > 0) {
          renderCoachProposals(
            { visuals: newVisuals,
              context_read: _coachLastProposals?.context_read || '',
              provider: _coachLastProposals?.provider,
              model: _coachLastProposals?.model,
              llm_elapsed_s: t.result?.elapsed_s },
            { mergeVisuals: true },
          );
        }
      } else if (t.state === 'failed' || t.state === 'cancelled') {
        clearInterval(_coachChatPollTimer);
        _coachChatPollTimer = null;
        _coachChatTask = null;
        _replaceChatMessage(pendingId, 'assistant', `${t.state}: ${t.error || ''}`);
        const sendBtn = document.getElementById('coach-chat-send');
        sendBtn.disabled = false;
        sendBtn.textContent = 'Send';
      }
    } catch (e) {
      // Transient — keep polling.
    }
  }, 1500);
}

function _appendChatMessage(role, text, { idAttr = '', pending = false } = {}) {
  const transcript = document.getElementById('coach-chat-transcript');
  if (!transcript) return;
  // Drop the "empty state" placeholder on first append.
  const empty = transcript.querySelector('.empty');
  if (empty) empty.remove();

  const cls = role === 'assistant' ? 'coach-msg--assistant' : 'coach-msg--user';
  const pcls = pending ? ' coach-msg--pending' : '';
  const idAttribute = idAttr ? ` id="${idAttr}"` : '';
  transcript.insertAdjacentHTML('beforeend', `
    <div class="coach-msg ${cls}${pcls}"${idAttribute}>
      <div class="coach-msg__role mono small">${role === 'assistant' ? 'coach' : 'you'}</div>
      <div class="coach-msg__body">${_coachEsc(text)}</div>
    </div>
  `);
  transcript.scrollTop = transcript.scrollHeight;
}

function _replaceChatMessage(id, role, text) {
  const el = document.getElementById(id);
  if (!el) return _appendChatMessage(role, text);
  el.classList.remove('coach-msg--pending');
  el.querySelector('.coach-msg__body').textContent = text;
  document.getElementById('coach-chat-transcript').scrollTop = 1e9;
}

function toggleAllProposals() {
  const cbs = document.querySelectorAll('#coach-proposals .coach-proposal__cb');
  const anyOff = Array.from(cbs).some(cb => !cb.checked);
  cbs.forEach(cb => { cb.checked = anyOff; });
}

// --- Accept selected → sketchpad -------------------------------------
async function acceptSelectedProposals() {
  if (!_coachLastProposals) return;
  const cbs = document.querySelectorAll('#coach-proposals .coach-proposal__cb:checked');
  if (cbs.length === 0) { alert('No visuals selected'); return; }

  const visuals = Array.from(cbs).map(cb => {
    try { return JSON.parse(cb.dataset.visual); }
    catch (e) { return null; }
  }).filter(v => v && v.id);

  const symbol = _coachLastProposals.symbol || _coachSymbol();
  const date = _coachToday();
  const btn = document.getElementById('coach-proposals-accept-btn');
  btn.disabled = true;
  btn.textContent = 'Accepting…';

  try {
    const r = await api(`/api/sketchpad/${encodeURIComponent(symbol)}/${date}/accept`, {
      method: 'POST', body: { visuals },
    });
    btn.textContent = `Accepted ${r.accepted || 0} → Apply to chart to push`;
    setTimeout(() => { btn.textContent = 'Accept selected → Sketchpad'; btn.disabled = false; }, 1800);
    refreshSketchpad();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'Accept selected → Sketchpad';
    alert(`Accept failed: ${e.message || e}`);
  }
}

// --- Sketchpad load + render -----------------------------------------
async function refreshSketchpad() {
  const symbol = _coachSymbol();
  const date = _coachToday();
  try {
    const r = await api(`/api/sketchpad/${encodeURIComponent(symbol)}/${date}`);
    renderSketchpad(r);
  } catch (e) {
    // Empty sketchpad on error — non-fatal
    renderSketchpad({ symbol, date, visuals: [], updated_at: null });
  }
}

function renderSketchpad(payload) {
  const list = document.getElementById('coach-sketchpad');
  const meta = document.getElementById('coach-sketchpad-meta');
  const visuals = payload?.visuals || [];

  if (meta) {
    const upd = payload?.updated_at ? new Date(payload.updated_at).toLocaleTimeString() : '—';
    meta.textContent = `${visuals.length} visual${visuals.length === 1 ? '' : 's'} · updated ${upd}`;
  }

  if (visuals.length === 0) {
    list.innerHTML = `<div class="empty small">Empty. Run Analyze and accept visuals to populate.</div>`;
    document.getElementById('coach-sketchpad-clear-btn').disabled = true;
    return;
  }
  document.getElementById('coach-sketchpad-clear-btn').disabled = false;

  list.innerHTML = visuals.map(v => `
    <div class="coach-sketch-row" data-vid="${_coachEsc(v.id)}">
      <span class="coach-proposal__chip coach-color-${_coachEsc(v.color)}">${_coachEsc(v.type)}</span>
      <span class="coach-sketch-row__label">${_coachEsc(v.label)}</span>
      <span class="coach-sketch-row__summary mono small">${_coachEsc(_coachVisualSummary(v))}</span>
      <button type="button" class="icon-btn coach-sketch-row__rm"
              title="Remove this visual" data-vid="${_coachEsc(v.id)}">✕</button>
    </div>
  `).join('');

  list.querySelectorAll('.coach-sketch-row__rm').forEach(btn => {
    btn.addEventListener('click', () => removeSketchpadVisual(btn.dataset.vid));
  });
}

async function removeSketchpadVisual(vid) {
  const symbol = _coachSymbol();
  const date = _coachToday();
  try {
    await api(`/api/sketchpad/${encodeURIComponent(symbol)}/${date}/visual/${vid}`,
              { method: 'DELETE' });
    refreshSketchpad();
  } catch (e) {
    alert(`Remove failed: ${e.message || e}`);
  }
}

async function clearSketchpad() {
  if (!confirm('Clear all visuals from the sketchpad? Apply afterward to scrub the chart indicator.')) return;
  const symbol = _coachSymbol();
  const date = _coachToday();
  try {
    await api(`/api/sketchpad/${encodeURIComponent(symbol)}/${date}/clear`,
              { method: 'POST', body: {} });
    refreshSketchpad();
  } catch (e) {
    alert(`Clear failed: ${e.message || e}`);
  }
}

async function applySketchpad() {
  const symbol = _coachSymbol();
  const date = _coachToday();
  const btn = document.getElementById('coach-sketchpad-apply-btn');
  const status = document.getElementById('coach-apply-status');
  btn.disabled = true;
  btn.textContent = 'Applying…';
  if (status) {
    status.classList.remove('hidden');
    status.textContent = 'rendering Pine + applying to chart (~30-60s)…';
  }
  try {
    const r = await api(`/api/sketchpad/${encodeURIComponent(symbol)}/${date}/apply`,
                        { method: 'POST', body: {} });
    if (status) {
      status.textContent = r.ok
        ? `applied · ${r.n_visuals} visuals · ${r.pine_path?.split('/').pop() || ''}`
        : `apply failed (rc=${r.returncode}): ${(r.stderr_tail || r.error || '').slice(-200)}`;
    }
  } catch (e) {
    if (status) status.textContent = `apply error: ${e.message || e}`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Apply to chart';
  }
}

// ----------------------------------------------------------------------
// Upload card — manual screenshot → any of the four analysis pipelines.
// Sibling to the live Capture flow on the Trade tab. The user picks
// which pipeline (Trade Analyze / Deep / Pre-session / F1 / F2 / F3),
// supplies the metadata that pipeline needs, and uploads a PNG.
// ----------------------------------------------------------------------
(function initUpload() {
  const card = $('upload-card'); if (!card) return;
  const pipelineSel = $('upload-pipeline');
  const symbolEl = $('upload-symbol');
  const tfEl = $('upload-tf'), tfWrap = $('upload-tf-wrap');
  const dateEl = $('upload-date'), dateWrap = $('upload-date-wrap');
  const tfsEl = $('upload-tfs'), tfsWrap = $('upload-tfs-wrap');
  const fileEl = $('upload-file');
  const runBtn = $('upload-run');
  const statusEl = $('upload-status');
  const progress = $('upload-progress');
  const phaseEl = $('upload-phase');
  const eventsEl = $('upload-events');
  const resultEl = $('upload-result');

  // Default Date input to today (ET-resolved). Pre-session/live both
  // need a date; auto-fill so the operator only types if the upload is
  // for a different day.
  dateEl.value = _fmtDate(new Date());

  // Show/hide field rows based on pipeline. Each pipeline needs a
  // different metadata shape — TF for analyze, Date for forecasts,
  // multi-TF list for deep, file-multi for deep too.
  function applyPipeline() {
    const k = pipelineSel.value;
    const isAnalyze = (k === 'analyze');
    const isDeep = (k === 'deep');
    const isForecast = k.startsWith('pre_session') || k.startsWith('live_');
    tfWrap.classList.toggle('hidden', !isAnalyze);
    dateWrap.classList.toggle('hidden', !isForecast);
    tfsWrap.classList.toggle('hidden', !isDeep);
    fileEl.multiple = isDeep;
    fileEl.accept = 'image/*';
    runBtn.textContent = isDeep ? 'Run deep upload' : 'Run';
  }
  pipelineSel.addEventListener('change', applyPipeline);
  applyPipeline();

  let pollTimer = null, seenEvents = 0;

  function streamEvent(ent) {
    const li = document.createElement('li');
    const t = (ent.ts || '').slice(11, 19);
    li.textContent = `${t}  ${ent.event || ''}`;
    if (/parse_fail|\.fail|\.error/.test(ent.event || '')) li.className = 'ev-fail';
    else if (/\.complete|\.done|saved/.test(ent.event || '')) li.className = 'ev-done';
    eventsEl.prepend(li);
  }

  async function poll(taskId, requestId, kind) {
    const taskUrl = (kind === 'analyze' || kind === 'deep')
      ? `/api/analyze/${taskId}`
      : `/api/forecasts/runs/${taskId}`;
    let status, entries = [];
    try {
      [status, entries] = await Promise.all([
        api(taskUrl),
        api(`/api/audit/tail?n=200&request_id=${encodeURIComponent(requestId)}`)
          .then(r => r.entries || []).catch(() => []),
      ]);
    } catch (e) {
      statusEl.textContent = `poll error: ${e.message}`;
      return;
    }
    entries.slice(seenEvents).forEach(streamEvent);
    seenEvents = entries.length;
    const latest = entries[entries.length - 1];
    if (latest) phaseEl.textContent = latest.event;
    if (status.state === 'done' || status.state === 'failed' || status.state === 'cancelled') {
      clearInterval(pollTimer); pollTimer = null;
      runBtn.disabled = false;
      if (status.state === 'done') {
        statusEl.textContent = 'done';
        renderResult(status.result, kind);
      } else {
        statusEl.textContent = status.state;
        phaseEl.textContent = `Error: ${status.error || status.state}`;
      }
    }
  }

  function renderResult(result, kind) {
    if (!result) return;
    resultEl.classList.remove('hidden');
    if (kind === 'analyze' || kind === 'deep') {
      const sig = (result.signal || '—').toString().toUpperCase();
      const conf = result.confidence != null ? `${result.confidence}%` : '—';
      const entry = result.entry ?? '—', stop = result.stop ?? '—', tp = result.tp ?? '—';
      const optTf = kind === 'deep' && result.optimal_tf ? ` · optimal=${result.optimal_tf}` : '';
      resultEl.innerHTML = `
        <div class="upload-result__head">${escapeHTML(sig)} · ${conf}${optTf}</div>
        <div class="upload-result__levels mono small">entry ${entry} · stop ${stop} · tp ${tp}</div>
        <div class="upload-result__rationale small">${escapeHTML(result.rationale || '')}</div>`;
    } else {
      // forecast — show the structured bias + invalidation
      const tb = result.tactical_bias || {};
      const preds = result.predictions || {};
      const dir = preds.direction || result.direction || '—';
      const conf = preds.direction_confidence || '—';
      resultEl.innerHTML = `
        <div class="upload-result__head">${escapeHTML(dir)} · ${escapeHTML(conf)}</div>
        <div class="upload-result__levels small">${escapeHTML(tb.bias || '')}</div>
        <div class="upload-result__rationale small"><b>Invalidation:</b> ${escapeHTML(tb.invalidation || '—')}</div>`;
    }
  }

  runBtn.addEventListener('click', async () => {
    const file = fileEl.files && fileEl.files[0];
    if (!file && pipelineSel.value !== 'deep') {
      statusEl.textContent = 'pick a file first'; return;
    }
    if (pipelineSel.value === 'deep' && (!fileEl.files || fileEl.files.length < 2)) {
      statusEl.textContent = 'deep upload needs ≥2 files'; return;
    }
    runBtn.disabled = true;
    statusEl.textContent = 'uploading…';
    eventsEl.innerHTML = ''; seenEvents = 0;
    progress.classList.remove('hidden');
    resultEl.classList.add('hidden');

    const k = pipelineSel.value;
    const fd = new FormData();
    let url = '', kind = '';
    try {
      if (k === 'analyze') {
        fd.append('file', file);
        fd.append('symbol', symbolEl.value.trim());
        fd.append('timeframe', tfEl.value.trim());
        url = '/api/analyze/upload'; kind = 'analyze';
      } else if (k === 'deep') {
        Array.from(fileEl.files).forEach(f => fd.append('files', f));
        const tfs = tfsEl.value.trim();
        if (!tfs) throw new Error('timeframes required for deep');
        fd.append('timeframes', tfs);
        fd.append('symbol', symbolEl.value.trim());
        url = '/api/analyze/deep/upload'; kind = 'deep';
      } else if (k === 'pre_session') {
        fd.append('file', file);
        fd.append('date', dateEl.value);
        fd.append('symbol', symbolEl.value.trim() || 'MNQ1');
        url = '/api/forecasts/pre_session/upload'; kind = 'forecast';
      } else if (k.startsWith('live_')) {
        const stage = k.replace('live_', '').toUpperCase();
        fd.append('file', file);
        fd.append('stage', stage);
        fd.append('date', dateEl.value);
        fd.append('symbol', symbolEl.value.trim() || 'MNQ1');
        url = '/api/forecasts/live/upload'; kind = 'forecast';
      }
      const headers = { 'X-UI': '1' };
      const tok = localStorage.getItem('ios-ui-token') || '';
      if (tok) headers['X-UI-Token'] = tok;
      const res = await fetch(url, { method: 'POST', headers, body: fd });
      const text = await res.text();
      let data = null;
      try { data = JSON.parse(text); } catch {}
      if (!res.ok) throw new Error((data && (data.detail || data.error)) || `HTTP ${res.status}`);
      const { task_id, request_id } = data;
      statusEl.textContent = `running (task ${task_id.slice(0,6)})`;
      pollTimer = setInterval(() => poll(task_id, request_id, kind), 1500);
      poll(task_id, request_id, kind);
    } catch (e) {
      runBtn.disabled = false;
      statusEl.textContent = `error: ${e.message || e}`;
    }
  });
})();
