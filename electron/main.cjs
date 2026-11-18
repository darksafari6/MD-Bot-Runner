/**
 * Desktop wrapper. The renderer is the same React bundle served by the local
 * Node process — Electron only provides the window, tray-less lifecycle and
 * "open external link in the real browser" behaviour.
 *
 * Security posture: contextIsolation ON, nodeIntegration OFF, sandboxed
 * renderer, all navigation confined to the local manager origin.
 */
const { app, BrowserWindow, shell, dialog } = require('electron');
const path = require('node:path');
const { spawn } = require('node:child_process');
const http = require('node:http');

const PORT = Number(process.env.PORT || 3001);
const DEV_URL = process.env.ELECTRON_DEV_URL || null;
const ORIGIN = `http://127.0.0.1:${PORT}`;

let mainWindow = null;
let serverProcess = null;

function startServer() {
  if (DEV_URL) return null;
  const serverEntry = path.join(__dirname, '..', 'dist-server', 'index.js');
  serverProcess = spawn(process.execPath, [serverEntry], {
    env: {
      ...process.env,
      PORT: String(PORT),
      HOST: '127.0.0.1',
      ELECTRON_RUN_AS_NODE: '1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  serverProcess.stdout.on('data', (chunk) => process.stdout.write(`[server] ${chunk}`));
  serverProcess.stderr.on('data', (chunk) => process.stderr.write(`[server] ${chunk}`));
  return serverProcess;
}

/** Poll the health endpoint so the window never loads a dead page. */
function waitForServer(timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const request = http.get(`${ORIGIN}/api/health`, (response) => {
        response.resume();
        resolve(true);
      });
      request.on('error', () => {
        if (Date.now() > deadline) return reject(new Error('Manager server did not start'));
        setTimeout(attempt, 300);
      });
    };
    attempt();
  });
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 900,
    minHeight: 600,
    title: 'WhatsApp MD Bot Runner Manager',
    backgroundColor: '#08080a',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, 'preload.cjs'),
    },
  });

  // External links open in the user's browser, never inside the app shell.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://') || url.startsWith('https://')) void shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    const allowed = DEV_URL ? url.startsWith(new URL(DEV_URL).origin) : url.startsWith(ORIGIN);
    if (!allowed) event.preventDefault();
  });

  const target = DEV_URL || ORIGIN;
  try {
    if (!DEV_URL) await waitForServer();
    await mainWindow.loadURL(target);
  } catch (err) {
    await dialog.showMessageBox({
      type: 'error',
      title: 'Cannot start the manager',
      message: 'The local manager server failed to start.',
      detail: `${err.message}\n\nTry running "npm run build" then "npm run desktop" again.`,
    });
    app.quit();
  }
}

app.whenReady().then(async () => {
  startServer();
  await createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) void createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (serverProcess && !serverProcess.killed) serverProcess.kill('SIGTERM');
});
