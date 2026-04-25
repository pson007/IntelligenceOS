// Preload runs in an isolated context with access to Node + DOM. We use
// it to:
//   (1) tag the renderer as "running inside Electron" so CSS can apply
//       native-chrome-aware tweaks (title-bar drag region, top padding
//       under macOS traffic lights) without a runtime feature-detect.
//   (2) expose a minimal, explicit bridge to the main process via
//       contextBridge — keeps nodeIntegration disabled while letting the
//       mini-dashboard popup invoke window actions.
//
// Everything here is additive: the main window uses the `is-electron`
// class on <html> (consistent with `is-mobile`) and ignores the IPC
// channels.
const { contextBridge, ipcRenderer } = require('electron');

// Set classes on <html> so they're available before <body> parses —
// matches the is-mobile placement and lets CSS hit them on the very
// first paint without waiting for DOMContentLoaded.
const root = document.documentElement;
root.classList.add('is-electron');
if (process.platform === 'darwin') root.classList.add('is-mac');
if (process.platform === 'win32') root.classList.add('is-windows');

contextBridge.exposeInMainWorld('oneRun', {
  platform: process.platform,
  isElectron: true,
  // Mini-dashboard bridge (tray popup → main process):
  openMain:     () => ipcRenderer.send('mini:open-main'),
  captureChart: () => ipcRenderer.send('mini:capture'),
  closeMini:    () => ipcRenderer.send('mini:close'),
});
