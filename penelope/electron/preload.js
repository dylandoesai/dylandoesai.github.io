'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('penelope', {
  call: (method, params) => ipcRenderer.invoke('penelope:call', method, params),
  readConfig: (name) => ipcRenderer.invoke('penelope:readConfig', name),
  readAsset: (rel) => ipcRenderer.invoke('penelope:readAsset', rel),
  readAssetBinary: (rel) => ipcRenderer.invoke('penelope:readAssetBinary', rel),
  showWindow: () => ipcRenderer.invoke('penelope:showWindow'),
  hideWindow: () => ipcRenderer.invoke('penelope:hideWindow'),
  // Open a URL or x-apple-…/weather:// URL scheme in the system handler.
  // Used by the clickable panels (revenue / analytics / schedule / weather)
  // to deep-link into the source dashboard or native app.
  openExternal: (url) => ipcRenderer.invoke('penelope:openExternal', url),
  detachPanel: (panelId) => ipcRenderer.invoke('penelope:detachPanel', panelId),
  on: (channel, handler) => {
    const listener = (_evt, payload) => handler(payload);
    ipcRenderer.on(channel, listener);
    return () => ipcRenderer.removeListener(channel, listener);
  },
});
