/**
 * Minimal, read-only bridge. The UI talks to the local manager over HTTP, so
 * the renderer needs no privileged APIs — only a hint that it is running in
 * the desktop shell.
 */
const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('desktop', {
  isElectron: true,
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
  },
});
