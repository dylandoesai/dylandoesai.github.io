'use strict';

const { app, BrowserWindow, ipcMain, screen, globalShortcut } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
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

function startPython() {
  py = new PythonBridge({
    cwd: path.join(__dirname, '..'),
    onEvent: (evt) => {
      // Wake events show the window before the renderer hears them
      if (evt && evt.event === 'hotword') {
        showWindow();
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

app.whenReady().then(() => {
  createWindow();
  startPython();
});

app.on('window-all-closed', () => {
  if (py) py.stop();
  globalShortcut.unregisterAll();
  if (process.platform !== 'darwin') app.quit();
});

app.on('will-quit', () => {
  if (py) py.stop();
});
