'use strict';
// The only bridge in the app, for the local status page. The OCR window has no preload at all.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('vietdoc', {
  getStatus: () => ipcRenderer.invoke('vietdoc:get-status'),
  onStatus: (callback) => ipcRenderer.on('vietdoc:status', (_event, status) => callback(status)),
  retry: () => ipcRenderer.send('vietdoc:retry'),
  openLogs: () => ipcRenderer.send('vietdoc:open-logs'),
  quit: () => ipcRenderer.send('vietdoc:quit'),
});
