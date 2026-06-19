const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');

let mainWindow;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1024,
    height: 768,
    minWidth: 800,
    minHeight: 600,
    title: "WhatsApp Bot Manager",
    backgroundColor: '#0f172a', // Tailwind slate-900
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false, // For simplicity in this template; in production consider true + preload script
    }
  });

  // Check if we are running in development mode via an env var (e.g. Vite auto-injects, or we can assume it if running dev script)
  const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged;

  if (isDev) {
    // In development mode, load the Vite dev server
    mainWindow.loadURL('http://localhost:3000');
    // mainWindow.webContents.openDevTools();
  } else {
    // In production, load the built static index.html
    mainWindow.loadFile(path.join(__dirname, 'dist', 'index.html'));
  }

  // Handle WhatsApp Bot process signaling (Mocked here for the UI context)
  ipcMain.on('start-bot', (event, args) => {
    console.log("Starting WhatsApp MD bot process...");
    // Here we would typically spawn a node process running Baileys
    // Or require the bot logic and run it in the main process
    
    // Simulate generation of QR code
    setTimeout(() => {
      event.reply('bot-qr', 'mock_qr_code_please_scan_12345');
    }, 2000);

    // Simulate successful connection
    setTimeout(() => {
      event.reply('bot-connected', { user: '18005551234@s.whatsapp.net', pushName: 'Bot Master' });
    }, 10000);
  });

  ipcMain.on('stop-bot', (event, args) => {
    console.log("Stopping bot process...");
    event.reply('bot-disconnected');
  });
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
