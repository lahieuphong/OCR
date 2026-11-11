'use strict';
// Bridge for the local status page. The app window has its own, smaller one (preload-app.js).
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('vietdoc', {
  getStatus: () => ipcRenderer.invoke('vietdoc:get-status'),
  onStatus: (callback) => ipcRenderer.on('vietdoc:status', (_event, status) => callback(status)),
  retry: () => ipcRenderer.send('vietdoc:retry'),
  openLogs: () => ipcRenderer.send('vietdoc:open-logs'),
  quit: () => ipcRenderer.send('vietdoc:quit'),
});
