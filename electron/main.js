// 1runOS — Electron main process.
//
// Boots a native window that wraps the FastAPI UI. In dev mode we assume
// the Python server is already running (developer starts it with
// ./run-ui.sh). In packaged/production mode we spawn the server as a
// child process and kill it on window close.
//
// The existing Playwright/CDP stack is unaffected — it attaches to the
// user's real Chrome on localhost:9222 regardless of where the UI is
// loaded from.

const {
  app, BrowserWindow, Menu, Tray, Notification,
  globalShortcut, ipcMain, nativeImage, nativeTheme, screen, shell,
} = require('electron');
const { spawn } = require('child_process');
const path = require('node:path');
const http = require('node:http');

// ------------------------------------------------------------
// Config
// ------------------------------------------------------------
const UI_HOST = '127.0.0.1';
const UI_PORT = 8788;
const UI_URL = `http://${UI_HOST}:${UI_PORT}`;
const IS_DEV = process.env.ONERUN_DEV === '1' || !app.isPackaged;
const STARTUP_TIMEOUT_MS = 30_000;

// When we package the app, the Python tree is shipped under
// Contents/Resources/tradingview (electron-builder's extraResources). In
// dev we reach up one level to the repo root.
const PY_CWD = IS_DEV
  ? path.resolve(__dirname, '..', 'tradingview')
  : path.join(process.resourcesPath, 'tradingview');

// ------------------------------------------------------------
// State
// ------------------------------------------------------------
let mainWindow = null;
let popupWindow = null;
let trayContextMenu = null;
let pyProc = null;
let tray = null;
let _sessionPollTimer = null;
// Tracks the pivot signature last shown in a notification so we only
// notify on actual transitions (no re-fires every 10s while state is
// steady). `null` before the first poll → first observed pivot is
// treated as a fresh event, matching user expectation on app launch.
let _lastPivotKey = null;
// Remember the last good tray title so a transient fetch failure doesn't
// blank the menu-bar badge — stale data beats empty.
let _lastTrayTitle = '1runOS';
const SESSION_POLL_MS = 10_000;
const GLOBAL_SHORTCUT = 'CmdOrCtrl+Alt+Space';

// ------------------------------------------------------------
// Python sidecar
// ------------------------------------------------------------
// In production we own the server lifecycle. In dev we attach to whatever
// is already on UI_PORT — the user typically already has `./run-ui.sh`
// running in a terminal and wants to keep using --reload.
async function ensurePythonServer() {
  if (await isServerUp()) return { mode: 'attached' };

  if (IS_DEV) {
    throw new Error(
      `Dev mode: no Python server on ${UI_URL}. Start it in another ` +
      `terminal: cd tradingview && ./run-ui.sh`
    );
  }

  const venvPy = path.join(PY_CWD, '.venv', 'bin', 'python');
  pyProc = spawn(venvPy, [
    '-m', 'uvicorn',
    'ui_server:app',
    '--host', UI_HOST,
    '--port', String(UI_PORT),
  ], { cwd: PY_CWD, stdio: 'inherit' });

  pyProc.on('exit', (code, signal) => {
    console.log(`[python] exited (code=${code}, signal=${signal})`);
    pyProc = null;
  });

  const up = await waitForServer(STARTUP_TIMEOUT_MS);
  if (!up) throw new Error(`Python server did not come up within ${STARTUP_TIMEOUT_MS}ms`);
  return { mode: 'spawned' };
}

function isServerUp() {
  return new Promise((resolve) => {
    const req = http.get(`${UI_URL}/api/health`, { timeout: 800 }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

async function waitForServer(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isServerUp()) return true;
    await new Promise((r) => setTimeout(r, 300));
  }
  return false;
}

// ------------------------------------------------------------
// Window
// ------------------------------------------------------------
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 640,
    // hiddenInset on macOS = native traffic lights floating over the UI;
    // the top-left 80px stays draggable. On Windows/Linux we keep the
    // default chrome — Windows users expect their title bar.
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    trafficLightPosition: { x: 14, y: 14 },
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#0b0e13' : '#ffffff',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.loadURL(UI_URL);
  mainWindow.once('ready-to-show', () => mainWindow.show());

  // External links open in the user's default browser, not a popup
  // window inside the app (same tradingview.com session the Playwright
  // stack uses, so we don't want a second cookie jar).
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(UI_URL)) {
      shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });

  // Ctrl/Cmd+Shift+I toggles DevTools. Off by default in production.
  if (IS_DEV) mainWindow.webContents.openDevTools({ mode: 'detach' });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ------------------------------------------------------------
// Splash / error
// ------------------------------------------------------------
function showFatalError(message) {
  const win = new BrowserWindow({
    width: 560, height: 320,
    resizable: false, minimizable: false, maximizable: false,
    backgroundColor: '#0b0e13',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
  });
  const html = `
    <html><head><style>
      body{margin:0;padding:40px;background:#0b0e13;color:#e6edf3;font:14px -apple-system,BlinkMacSystemFont,sans-serif;line-height:1.5;-webkit-app-region:drag;}
      h2{font-size:18px;margin:0 0 12px;color:#f06a60;-webkit-app-region:no-drag;}
      pre{background:#14181f;border:1px solid rgba(255,255,255,0.08);border-radius:6px;padding:12px;font-size:12px;overflow:auto;max-height:140px;white-space:pre-wrap;-webkit-app-region:no-drag;}
      p{color:#8892a0;margin-top:18px;-webkit-app-region:no-drag;}
    </style></head><body>
      <h2>1runOS couldn't start</h2>
      <pre>${message.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]))}</pre>
      <p>Start the backend manually, then relaunch:<br><code>cd tradingview &amp;&amp; ./run-ui.sh</code></p>
    </body></html>`;
  win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
}

// ------------------------------------------------------------
// App menu — keyboard-shortcut driven. We intentionally keep this small
// on the first pass; native menu items are a product trust signal but
// not a core UX surface.
// ------------------------------------------------------------
function buildMenu() {
  const isMac = process.platform === 'darwin';
  const template = [
    ...(isMac ? [{
      label: '1runOS',
      submenu: [
        { role: 'about', label: 'About 1runOS' },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit', label: 'Quit 1runOS' },
      ],
    }] : []),
    {
      label: 'File',
      submenu: [
        {
          label: 'Capture chart',
          accelerator: 'CmdOrCtrl+K',
          click: () => mainWindow?.webContents.executeJavaScript(
            `document.getElementById('trade-capture')?.click()`),
        },
        {
          label: 'Analyze (single TF)',
          accelerator: 'CmdOrCtrl+Shift+A',
          click: () => mainWindow?.webContents.executeJavaScript(
            `document.getElementById('trade-analyze')?.click()`),
        },
        {
          label: 'Deep analyze',
          accelerator: 'CmdOrCtrl+Shift+D',
          click: () => mainWindow?.webContents.executeJavaScript(
            `document.getElementById('trade-analyze-deep')?.click()`),
        },
        { type: 'separator' },
        isMac ? { role: 'close' } : { role: 'quit' },
      ],
    },
    { role: 'editMenu' },
    {
      label: 'View',
      submenu: [
        {
          label: 'Today',
          accelerator: 'CmdOrCtrl+1',
          click: () => mainWindow?.webContents.executeJavaScript(
            `document.querySelector('.nav-item[data-tab="today"]')?.click()`),
        },
        {
          label: 'Plan',
          accelerator: 'CmdOrCtrl+2',
          click: () => mainWindow?.webContents.executeJavaScript(
            `document.querySelector('.nav-item[data-tab="plan"]')?.click()`),
        },
        {
          label: 'Journal',
          accelerator: 'CmdOrCtrl+3',
          click: () => mainWindow?.webContents.executeJavaScript(
            `document.querySelector('.nav-item[data-tab="journal"]')?.click()`),
        },
        {
          label: 'Setup',
          accelerator: 'CmdOrCtrl+4',
          click: () => mainWindow?.webContents.executeJavaScript(
            `document.querySelector('.nav-item[data-tab="setup"]')?.click()`),
        },
        { type: 'separator' },
        {
          label: 'Toggle theme',
          accelerator: 'CmdOrCtrl+Shift+T',
          click: () => mainWindow?.webContents.executeJavaScript(
            `document.getElementById('theme-toggle')?.click()`),
        },
        { type: 'separator' },
        { role: 'reload' }, { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' },
        { type: 'separator' }, { role: 'togglefullscreen' },
      ],
    },
    { role: 'windowMenu' },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ------------------------------------------------------------
// Session poll — single /api/session/today fetch every 10s drives the
// dock badge, the menu-bar tray title, and pivot-fired notifications.
// Keeping this in the main process means all three update even if the
// renderer isn't on the Today tab (or if the window is hidden).
// ------------------------------------------------------------
function fetchSessionState() {
  return new Promise((resolve) => {
    const req = http.get(`${UI_URL}/api/session/today`, { timeout: 2000 }, (res) => {
      if (res.statusCode !== 200) { res.resume(); return resolve(null); }
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (c) => { body += c; });
      res.on('end', () => {
        try { resolve(JSON.parse(body)); } catch { resolve(null); }
      });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
  });
}

function _formatDockBadge(data) {
  const pos = data?.positions || {};
  const sess = data?.session || {};
  // Priority 1: live unrealized P&L while a position is open. This is
  // the metric a day trader most wants to see without switching windows.
  if (pos.available && typeof pos.unrealized_pnl === 'number' && (pos.open_count || 0) > 0) {
    const p = pos.unrealized_pnl;
    const sign = p >= 0 ? '+' : '-';
    return `${sign}$${Math.abs(p).toFixed(0)}`;
  }
  // Priority 2: running realized R for the session, once decisions exist.
  if ((sess.total || 0) > 0) {
    const r = Number(sess.realized_r_sum || 0);
    return (r >= 0 ? '+' : '') + r.toFixed(1) + 'R';
  }
  return '';
}

function _formatTrayTitle(data) {
  const tf = data?.today_forecast || {};
  const sess = data?.session || {};
  const pos = data?.positions || {};
  const parts = [];
  if (tf.exists) {
    const dir = tf.direction;
    const glyph = dir === 'up' ? '▲' : dir === 'down' ? '▼' : '▬';
    parts.push(glyph);
  }
  if (pos.available && (pos.open_count || 0) > 0 && typeof pos.unrealized_pnl === 'number') {
    const p = pos.unrealized_pnl;
    parts.push(`${p >= 0 ? '+' : '-'}$${Math.abs(p).toFixed(0)}`);
  } else if ((sess.total || 0) > 0) {
    const r = Number(sess.realized_r_sum || 0);
    parts.push((r >= 0 ? '+' : '') + r.toFixed(1) + 'R');
  }
  return parts.join(' ') || '1runOS';
}

function _pivotKey(tf) {
  // Uniquely identifies a specific pivot firing. called_at_et is stamped
  // once per pivot call, so a key change means a new pivot actually fired.
  const p = tf?.pivot;
  if (!p || !p.revised_bias) return null;
  return `${p.called_at_et || ''}|${p.classification || ''}|${p.revised_bias}`;
}

function _maybeFirePivotNotification(data) {
  const tf = data?.today_forecast || {};
  const key = _pivotKey(tf);
  // First poll after launch: seed the key silently so we don't fire
  // a notification for a pivot that already happened before launch.
  if (_lastPivotKey === null) {
    _lastPivotKey = key || '';
    return;
  }
  if (!key || key === _lastPivotKey) return;
  _lastPivotKey = key;

  const p = tf.pivot || {};
  if (!Notification.isSupported()) return;
  const n = new Notification({
    title: `1runOS — pivot fired (${p.classification || '—'})`,
    body: `${p.revised_bias || 'revised bias'}${p.revised_invalidation ? `\nInvalidates if: ${p.revised_invalidation}` : ''}`,
    silent: false,
    timeoutType: 'default',
  });
  n.on('click', () => {
    if (mainWindow) { mainWindow.show(); mainWindow.focus(); }
  });
  n.show();
}

async function pollSessionState() {
  const data = await fetchSessionState();
  if (!data) return;
  // Dock badge — macOS only; no-op on Windows/Linux.
  if (process.platform === 'darwin' && app.dock) {
    try { app.dock.setBadge(_formatDockBadge(data)); } catch {}
  }
  // Tray title (macOS shows it next to the icon in the menu bar).
  if (tray) {
    const title = _formatTrayTitle(data);
    if (title !== _lastTrayTitle) {
      try { tray.setTitle(title); } catch {}
      _lastTrayTitle = title;
    }
  }
  _maybeFirePivotNotification(data);
}

function startSessionPolling() {
  if (_sessionPollTimer) clearInterval(_sessionPollTimer);
  pollSessionState();
  _sessionPollTimer = setInterval(pollSessionState, SESSION_POLL_MS);
}

function stopSessionPolling() {
  if (_sessionPollTimer) { clearInterval(_sessionPollTimer); _sessionPollTimer = null; }
}

// ------------------------------------------------------------
// Menu-bar tray — macOS shows icon + title in the top-right menu bar,
// visible even when the main window is hidden or minimized. On Windows
// the tray lives in the system notification area; no setTitle there,
// so we use tooltip instead.
// ------------------------------------------------------------
function _buildTrayIcon() {
  // An 18×18 template PNG is the macOS standard. We build it in-memory
  // so no asset file is needed: a filled dark circle, template-flagged
  // so macOS recolors it to match light/dark menu-bar styling.
  const size = 18;
  const buf = Buffer.alloc(size * size * 4);
  const cx = (size - 1) / 2, cy = (size - 1) / 2, r = 6;
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = x - cx, dy = y - cy;
      const d = Math.sqrt(dx * dx + dy * dy);
      const i = (y * size + x) * 4;
      if (d <= r - 0.5) {
        buf[i] = 0; buf[i + 1] = 0; buf[i + 2] = 0; buf[i + 3] = 255;
      } else if (d <= r + 0.5) {
        const a = Math.round(255 * (r + 0.5 - d));  // 1px soft edge
        buf[i] = 0; buf[i + 1] = 0; buf[i + 2] = 0; buf[i + 3] = a;
      }
      // else: leave zeros (transparent)
    }
  }
  const img = nativeImage.createFromBuffer(Buffer.alloc(0));  // placeholder
  // createFromBuffer expects a PNG/JPG buffer; for raw pixels we use
  // createFromBitmap. The pixel order on macOS is BGRA, not RGBA.
  const bgra = Buffer.alloc(buf.length);
  for (let i = 0; i < buf.length; i += 4) {
    bgra[i] = buf[i + 2]; bgra[i + 1] = buf[i + 1];
    bgra[i + 2] = buf[i];  bgra[i + 3] = buf[i + 3];
  }
  const out = nativeImage.createFromBitmap(bgra, { width: size, height: size });
  if (process.platform === 'darwin') out.setTemplateImage(true);
  return out;
}

function createTray() {
  try {
    const icon = _buildTrayIcon();
    tray = new Tray(icon);
  } catch (err) {
    // Bitmap construction can fail on exotic platforms; fall back to an
    // empty image + setTitle. On macOS the title alone keeps the menu
    // entry visible; on Windows the tooltip stands in.
    console.warn('[1runos] tray icon build failed, using empty:', err?.message);
    tray = new Tray(nativeImage.createEmpty());
  }
  tray.setToolTip('1runOS — One run per day');
  if (process.platform === 'darwin') tray.setTitle('1runOS');

  // Build the right-click menu once and retain it — we DON'T call
  // setContextMenu(), because that would swallow left-clicks on macOS
  // and open the menu before our popup can show. Instead we dispatch
  // left-click → popup, right-click → programmatic menu.
  trayContextMenu = Menu.buildFromTemplate([
    {
      label: 'Open 1runOS',
      click: () => {
        if (!mainWindow) createWindow();
        else { mainWindow.show(); mainWindow.focus(); }
      },
    },
    { type: 'separator' },
    {
      label: 'Capture chart',
      accelerator: 'CmdOrCtrl+K',
      click: () => _rendererClick('trade-capture', { focus: true }),
    },
    {
      label: 'Capture + Analyze',
      accelerator: GLOBAL_SHORTCUT,
      click: () => _captureThenAnalyze(),
    },
    { type: 'separator' },
    { role: 'quit', label: 'Quit 1runOS' },
  ]);

  // Left-click → mini-dashboard popup (the primary interaction).
  // Right-click (or ctrl-click on macOS) → traditional context menu.
  tray.on('click', () => togglePopup());
  tray.on('right-click', () => {
    if (popupWindow && popupWindow.isVisible()) popupWindow.hide();
    tray.popUpContextMenu(trayContextMenu);
  });
}

function destroyTray() {
  if (tray && !tray.isDestroyed()) tray.destroy();
  tray = null;
  trayContextMenu = null;
}

// ------------------------------------------------------------
// Mini-dashboard popup — frameless transparent window anchored to the
// tray icon. Shows today's bias, open P&L, session R, and the current
// invalidation condition without forcing the user to bring the main
// window forward. Hides on blur (iOS-style dismiss) or Esc.
// ------------------------------------------------------------
const POPUP_WIDTH = 340;
const POPUP_HEIGHT = 320;

function createPopupWindow() {
  popupWindow = new BrowserWindow({
    width: POPUP_WIDTH,
    height: POPUP_HEIGHT,
    show: false,
    frame: false,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    transparent: true,
    hasShadow: true,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  // Keep the popup out of the app's visible-windows list so it doesn't
  // count for mission-control grouping / window cycling.
  if (process.platform === 'darwin') {
    popupWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  }

  popupWindow.on('blur', () => {
    // Blur fires when the user clicks anywhere outside the popup —
    // dismiss exactly like a macOS menu-bar extra would.
    if (popupWindow && popupWindow.isVisible()) popupWindow.hide();
  });
  popupWindow.on('closed', () => { popupWindow = null; });
}

function _positionPopup() {
  if (!popupWindow || !tray) return 0;
  const trayBounds = tray.getBounds();
  const display = screen.getDisplayMatching(trayBounds) || screen.getPrimaryDisplay();
  const work = display.workArea;

  // Center the popup horizontally on the tray icon.
  let x = Math.round(trayBounds.x + (trayBounds.width / 2) - (POPUP_WIDTH / 2));
  // Clamp so the popup never runs off the right edge of the screen.
  const maxX = work.x + work.width - POPUP_WIDTH - 4;
  const minX = work.x + 4;
  x = Math.max(minX, Math.min(x, maxX));

  // On macOS the menu bar is at the top — popup drops below. On Windows
  // the tray is typically bottom-right — popup pops up.
  const isTop = process.platform === 'darwin';
  const y = isTop
    ? trayBounds.y + trayBounds.height + 2
    : trayBounds.y - POPUP_HEIGHT - 2;

  popupWindow.setPosition(x, y, false);

  // Caret — how far from popup's left edge the tray center sits. The
  // mini page reads `?cx=NN` and horizontally positions its caret so
  // the arrow tip lines up with the tray icon even after clamping.
  const trayCenter = trayBounds.x + trayBounds.width / 2;
  const caretX = Math.max(14, Math.min(POPUP_WIDTH - 14, trayCenter - x));
  return caretX;
}

function showPopup() {
  if (!popupWindow) createPopupWindow();
  const caretX = _positionPopup();
  const url = `${UI_URL}/ui/mini.html?cx=${caretX}`;
  // Reload on every show so a stale DOM after a long hidden stretch
  // doesn't sit with week-old data before the first poll tick. Cheap:
  // the page is ~6KB + a shared style.css hit.
  popupWindow.loadURL(url);
  popupWindow.once('ready-to-show', () => {
    if (popupWindow) { popupWindow.show(); popupWindow.focus(); }
  });
}

function hidePopup() {
  if (popupWindow && popupWindow.isVisible()) popupWindow.hide();
}

function togglePopup() {
  if (popupWindow && popupWindow.isVisible()) hidePopup();
  else showPopup();
}

// ------------------------------------------------------------
// Global shortcut — CmdOrCtrl+Alt+Space from anywhere on the system:
// surface the window and start a fresh Capture→Analyze chain. The
// shortcut survives window minimize/hide so the user can hit it mid-
// TradingView work without tabbing away.
// ------------------------------------------------------------
function _rendererClick(elementId, opts = {}) {
  if (!mainWindow) return;
  if (opts.focus) { mainWindow.show(); mainWindow.focus(); }
  mainWindow.webContents.executeJavaScript(
    `document.getElementById(${JSON.stringify(elementId)})?.click()`,
    true,
  ).catch(() => {});
}

// Capture+Analyze in sequence: click Capture, wait for its busy state
// to clear (the button re-enables), then click Analyze. We poll the
// disabled attribute rather than racing a fixed delay so slow networks
// don't miss the handoff.
async function _captureThenAnalyze() {
  if (!mainWindow) return;
  mainWindow.show();
  mainWindow.focus();
  const js = `
    (async () => {
      const cap = document.getElementById('trade-capture');
      const ana = document.getElementById('trade-analyze');
      if (!cap || !ana) return 'missing buttons';
      cap.click();
      // Wait up to 20s for capture to complete (button's disabled flag
      // clears when the server returns).
      const deadline = Date.now() + 20000;
      await new Promise((resolve) => {
        const tick = () => {
          if (!cap.disabled) return resolve();
          if (Date.now() > deadline) return resolve();
          setTimeout(tick, 200);
        };
        tick();
      });
      ana.click();
      return 'ok';
    })()`;
  try { await mainWindow.webContents.executeJavaScript(js, true); } catch {}
}

function registerGlobalShortcuts() {
  const ok = globalShortcut.register(GLOBAL_SHORTCUT, _captureThenAnalyze);
  if (!ok) console.warn(`[1runos] could not register global shortcut ${GLOBAL_SHORTCUT}`);
}

// ------------------------------------------------------------
// IPC — bridge the mini-dashboard popup's buttons to main-process
// actions. preload.js exposes these as window.oneRun.openMain() etc.
// ------------------------------------------------------------
ipcMain.on('mini:open-main', () => {
  if (!mainWindow) createWindow();
  else { mainWindow.show(); mainWindow.focus(); }
  hidePopup();
});

ipcMain.on('mini:capture', () => {
  // Open the main window (capture needs a live chart surface) and fire
  // the existing Capture button.
  if (!mainWindow) {
    createWindow();
    // Wait for ready before dispatching; loadURL + subsequent click
    // would race otherwise.
    app.once('browser-window-created', (_e, win) => {
      win.webContents.once('did-finish-load', () => _rendererClick('trade-capture'));
    });
  } else {
    mainWindow.show(); mainWindow.focus();
    _rendererClick('trade-capture');
  }
  hidePopup();
});

ipcMain.on('mini:close', () => hidePopup());

// ------------------------------------------------------------
// Lifecycle
// ------------------------------------------------------------
app.whenReady().then(async () => {
  buildMenu();
  try {
    const result = await ensurePythonServer();
    console.log(`[1runos] server ${result.mode} at ${UI_URL}`);
    createWindow();
    createTray();
    registerGlobalShortcuts();
    startSessionPolling();
  } catch (err) {
    console.error('[1runos] fatal:', err);
    showFatalError(err.message ?? String(err));
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

// Keep the app running even with no visible window — the tray lives on,
// notifications still fire, and the global shortcut still surfaces the
// window. macOS users expect this; on Windows we also keep it alive so
// the tray icon persists (matches Slack/Discord behavior).
app.on('window-all-closed', (e) => {
  // Don't quit on window close. User uses tray 'Quit 1runOS' or Cmd+Q.
  e.preventDefault();
});

app.on('before-quit', () => {
  stopSessionPolling();
  try { globalShortcut.unregisterAll(); } catch {}
  destroyTray();
  if (pyProc) {
    try { pyProc.kill('SIGTERM'); } catch {}
    pyProc = null;
  }
});
