'use strict';
// Bridge for the app window: the app menu in the page's own top bar (it replaces the native menu bar).
// Only these actions, no Node and no data: the main process answers only the app's own origin.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('vietdocDesktop', {
  info: () => ipcRenderer.invoke('vietdoc-app:info'),
  openStatus: () => ipcRenderer.invoke('vietdoc-app:open-status'),
  openLogs: () => ipcRenderer.invoke('vietdoc-app:open-logs'),
  checkUpdates: () => ipcRenderer.invoke('vietdoc-app:check-updates'),
  zoom: (step) => ipcRenderer.invoke('vietdoc-app:zoom', step),
  quit: () => ipcRenderer.invoke('vietdoc-app:quit'),
});
