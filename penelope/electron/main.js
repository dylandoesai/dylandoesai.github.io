'use strict';

const { app, BrowserWindow, ipcMain, screen, globalShortcut, powerMonitor } = require('electron');
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

  if (app.dock) app.dock.hide(); // background-only by default

  globalShortcut.register('CommandOrControl+F', () => {
    if (!mainWindow) return;
    mainWindow.setFullScreen(!mainWindow.isFullScreen());
  });
}

function showWindow() {
  if (!mainWindow) return;
  if (app.dock) app.dock.show();
  mainWindow.setFullScreen(true);
  mainWindow.show();
  mainWindow.focus();
}

function hideWindow() {
  if (!mainWindow) return;
  mainWindow.setFullScreen(false);
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

ipcMain.handle('penelope:readConfig', async (_evt, name) => {
  const p = path.join(__dirname, '..', 'config', name);
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, 'utf8'));
});

ipcMain.handle('penelope:readAsset', async (_evt, rel) => {
  const p = path.join(__dirname, '..', rel);
  if (!fs.existsSync(p)) return null;
  return fs.readFileSync(p).toString('base64');
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

app.whenReady().then(() => {
  createWindow();
  startPython();
  wirePowerEvents();
  ensureLoginItem();
  applyPowerProfile();
});

app.on('window-all-closed', () => {
  if (py) py.stop();
  globalShortcut.unregisterAll();
  if (process.platform !== 'darwin') app.quit();
});

app.on('will-quit', () => {
  if (py) py.stop();
});
