'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('penelope', {
  call: (method, params) => ipcRenderer.invoke('penelope:call', method, params),
  readConfig: (name) => ipcRenderer.invoke('penelope:readConfig', name),
  readAsset: (rel) => ipcRenderer.invoke('penelope:readAsset', rel),
  showWindow: () => ipcRenderer.invoke('penelope:showWindow'),
  hideWindow: () => ipcRenderer.invoke('penelope:hideWindow'),
  on: (channel, handler) => {
    const listener = (_evt, payload) => handler(payload);
    ipcRenderer.on(channel, listener);
    return () => ipcRenderer.removeListener(channel, listener);
  },
});
