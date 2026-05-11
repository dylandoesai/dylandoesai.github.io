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

  mainWindow = new BrowserWindow({
    width,
    height,
    minWidth: 1280,
    minHeight: 800,
    backgroundColor: '#000000',
    show: false,
    fullscreen: true,
    autoHideMenuBar: true,
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: false,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
  mainWindow.once('ready-to-show', () => mainWindow.show());

  globalShortcut.register('CommandOrControl+F', () => {
    if (!mainWindow) return;
    mainWindow.setFullScreen(!mainWindow.isFullScreen());
  });
}

function startPython() {
  py = new PythonBridge({
    cwd: path.join(__dirname, '..'),
    onEvent: (evt) => {
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
