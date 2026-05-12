'use strict';

const { app, BrowserWindow, ipcMain, screen, globalShortcut, powerMonitor, shell, systemPreferences } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { execSync } = require('node:child_process');
const PythonBridge = require('./python-bridge');

let mainWindow = null;
let py = null;

function createWindow() {
  const display = screen.getPrimaryDisplay();
  const { width, height } = display.workAreaSize;

  // Penelope starts INVISIBLE. The Python sidecar listens for the wake
  // phrase. On wake, we show + fullscreen the window via showWindow().
  // On "Sleep Penelope" we hide it again, back to invisible listening.
  mainWindow = new BrowserWindow({
    width,
    height,
    minWidth: 1280,
    minHeight: 800,
    backgroundColor: '#000000',
    show: false,
    fullscreen: false,
    skipTaskbar: true,
    autoHideMenuBar: true,
    titleBarStyle: 'hiddenInset',
    frame: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: false,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
  // No ready-to-show -> stays invisible until wake.
  // DEV: open DevTools so any renderer crash is visible during shake-out.
  if (process.env.PENELOPE_DEV === '1') {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
    mainWindow.show();
  }

  if (app.dock) app.dock.hide(); // background-only by default

  globalShortcut.register('CommandOrControl+F', () => {
    if (!mainWindow) return;
    mainWindow.setFullScreen(!mainWindow.isFullScreen());
  });
}

function showWindow() {
  if (!mainWindow) return;
  if (app.dock) app.dock.show();
  // Order matters on macOS: show first so the window has an animation
  // surface, then simpleFullScreen (no Space-switch flicker), then
  // promote to actual fullscreen if the user prefers it later. Using
  // simpleFullScreen keeps us on the current Space so the wake feels
  // immediate instead of swiping to a separate desktop.
  mainWindow.show();
  mainWindow.setSimpleFullScreen(true);
  mainWindow.setAlwaysOnTop(true, 'screen-saver');
  mainWindow.focus();
}

function hideWindow() {
  if (!mainWindow) return;
  mainWindow.setSimpleFullScreen(false);
  mainWindow.setAlwaysOnTop(false);
  mainWindow.hide();
  if (app.dock) app.dock.hide();
}

ipcMain.handle('penelope:showWindow', () => { showWindow(); });
ipcMain.handle('penelope:hideWindow', () => { hideWindow(); });

function loadConfig() {
  try {
    return JSON.parse(fs.readFileSync(
      path.join(__dirname, '..', 'config', 'config.json'), 'utf8'));
  } catch { return {}; }
}

function maybeWakeClaudeApp(phrase) {
  // Penelope IS Claude Code under the hood — same brain, no shared
  // session with Claude.app. But Dylan asked for the desktop chat to
  // come alongside on full wake. Opt-in via wake_companion.open_claude_app.
  const cfg = loadConfig();
  const companion = (cfg.wake_companion || {});
  if (phrase === 'papis_home' && companion.open_claude_app) {
    try { execSync('open -a "Claude"'); } catch {}
  }
}

function startPython() {
  py = new PythonBridge({
    cwd: path.join(__dirname, '..'),
    onEvent: (evt) => {
      // Wake events show the window before the renderer hears them
      if (evt && evt.event === 'hotword') {
        showWindow();
        maybeWakeClaudeApp(evt.phrase);
      } else if (evt && evt.event === 'go_sleep') {
        hideWindow();
      }
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('penelope:event', evt);
      }
    },
    onLog: (line) => {
      console.log('[py]', line);
    },
  });
  py.start();
}

ipcMain.handle('penelope:call', async (_evt, method, params) => {
  if (!py) throw new Error('python bridge not ready');
  return py.call(method, params);
});

// In packaged app, config/ and assets/ live next to app.asar (unpacked).
// Resolve from there if present; fall back to dev path.
function resolveProjectFile(rel) {
  if (process.resourcesPath) {
    const unpacked = path.join(process.resourcesPath, 'app.asar.unpacked', rel);
    if (fs.existsSync(unpacked)) return unpacked;
  }
  const dev = path.join(__dirname, '..', rel);
  return fs.existsSync(dev) ? dev : null;
}

ipcMain.handle('penelope:readConfig', async (_evt, name) => {
  const p = resolveProjectFile(path.join('config', name));
  if (!p) return null;
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); }
  catch { return null; }
});

ipcMain.handle('penelope:readAsset', async (_evt, rel) => {
  const p = resolveProjectFile(rel);
  if (!p) return null;
  return fs.readFileSync(p).toString('base64');
});

// Deep-link surface — clickable panels in the renderer go through this
// to open Stripe / Gumroad / YouTube Studio / Calendar.app / Weather.app
// in the system handler. Restricted to http(s) + safe Apple URL schemes
// to keep the renderer from being able to fire arbitrary local commands.
const ALLOWED_SCHEMES = ['https:', 'http:', 'ical:', 'message:',
                         'x-apple-reminderkit:', 'weather:', 'spotify:',
                         'stremio:'];
// Detached panel windows — each panel can pop out into its own
// borderless window that Dylan can drag to another Space, resize,
// fullscreen. Same dark + cyan styling, no chrome.
const _detached = new Map();   // panelId -> BrowserWindow
ipcMain.handle('penelope:detachPanel', async (_evt, panelId) => {
  if (!panelId) return false;
  if (_detached.has(panelId)) {
    try { _detached.get(panelId).focus(); } catch {}
    return true;
  }
  const win = new BrowserWindow({
    width: 720, height: 480,
    minWidth: 320, minHeight: 240,
    backgroundColor: '#000000',
    frame: false,
    titleBarStyle: 'hiddenInset',
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: false,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });
  // index.html reads location.hash to filter to just one panel
  win.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'),
               { hash: `panel=${panelId}` });
  win.once('ready-to-show', () => win.show());
  win.on('closed', () => _detached.delete(panelId));
  _detached.set(panelId, win);
  return true;
});

ipcMain.handle('penelope:openExternal', async (_evt, url) => {
  try {
    const u = new URL(url);
    if (!ALLOWED_SCHEMES.includes(u.protocol)) return false;
    await shell.openExternal(url);
    return true;
  } catch (e) {
    return false;
  }
});

// macOS power-event handling — spec said quit on sleep, relaunch on wake.
// Penelope's hotword listener doesn't run while the Mac is asleep anyway,
// and a fresh launch on wake guarantees clean audio device state.
function isOnBattery() {
  try {
    const out = execSync("pmset -g batt", { encoding: 'utf8' });
    return /Battery Power/i.test(out);
  } catch { return false; }
}

function applyPowerProfile() {
  if (!mainWindow) return;
  const onBatt = isOnBattery();
  // Low-power on battery: throttle the renderer and drop face redraws when hidden.
  mainWindow.webContents.setBackgroundThrottling(onBatt);
  mainWindow.webContents.setFrameRate(onBatt ? 30 : 60);
  if (py && py.call) {
    py.call('set_mode', { mode: onBatt ? 'professional' : 'warm' }).catch(()=>{});
  }
}

function wirePowerEvents() {
  powerMonitor.on('suspend', () => {
    if (py) py.stop();
    if (mainWindow) hideWindow();
  });
  powerMonitor.on('resume', () => {
    if (!py || !py.isRunning) startPython();
    applyPowerProfile();
  });
  powerMonitor.on('on-ac',      applyPowerProfile);
  powerMonitor.on('on-battery', applyPowerProfile);
}

// Auto-launch at login — silent (no dock icon, no window) — spec'd as the default.
function ensureLoginItem() {
  try {
    app.setLoginItemSettings({
      openAtLogin: true,
      openAsHidden: true,
      name: 'Penelope',
    });
  } catch (e) {
    console.warn('[autolaunch] failed:', e.message);
  }
}

async function requestMacPermissions() {
  // Force the mic/camera permission prompts to fire from the main
  // (visible) Electron process so the OS dialog isn't hidden behind
  // the invisible Python child. We don't need the audio here — the
  // sounddevice library in Python will inherit the granted state.
  try {
    if (process.platform === 'darwin' && systemPreferences) {
      const micState = systemPreferences.getMediaAccessStatus('microphone');
      if (micState !== 'granted') {
        await systemPreferences.askForMediaAccess('microphone');
      }
      const camState = systemPreferences.getMediaAccessStatus('camera');
      if (camState !== 'granted') {
        await systemPreferences.askForMediaAccess('camera');
      }
    }
  } catch (e) {
    console.warn('[perms] askForMediaAccess failed:', e?.message);
  }
}

app.whenReady().then(() => {
  createWindow();
  // Start the Python sidecar IMMEDIATELY so the renderer's RPC calls
  // have something on the other end. Ask for mic/camera permissions in
  // parallel — the prompts fire from the visible main process.
  startPython();
  wirePowerEvents();
  ensureLoginItem();
  applyPowerProfile();
  requestMacPermissions().catch(() => {});
});

app.on('window-all-closed', () => {
  if (py) py.stop();
  globalShortcut.unregisterAll();
  if (process.platform !== 'darwin') app.quit();
});

app.on('will-quit', () => {
  if (py) py.stop();
});
