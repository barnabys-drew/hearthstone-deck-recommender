const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('overlayAPI', {
  config: () => ipcRenderer.invoke('overlay-config'),
  readJson: (fileName) => ipcRenderer.invoke('read-json', fileName),
  setClickThrough: (value) => ipcRenderer.invoke('set-click-through', value),
  onState: (callback) => ipcRenderer.on('overlay-state', (_event, state) => callback(state)),
});
