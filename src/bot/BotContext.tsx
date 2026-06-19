import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

type BotStatus = 'offline' | 'extracting' | 'installing' | 'starting' | 'waiting_qr' | 'online' | 'error';

interface LogEntry {
  id: string;
  timestamp: string;
  message: string;
  type: 'info' | 'warn' | 'error' | 'success';
}

interface BotContextType {
  status: BotStatus;
  qrCode: string | null;
  botInfo: { user?: string; pushName?: string } | null;
  logs: LogEntry[];
  botArchive: File | null;
  setBotArchive: (file: File | null) => void;
  appUrl: string | null;
  startBot: () => void;
  stopBot: () => void;
  clearLogs: () => void;
}

const BotContext = createContext<BotContextType | undefined>(undefined);

// Web-based simulator for the Bot Manager
// When bundled via Electron, this could be swapped out to use `window.require('electron').ipcRenderer`
export function BotProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BotStatus>('offline');
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [botInfo, setBotInfo] = useState<{ user?: string; pushName?: string } | null>(null);
  const [botArchive, setBotArchive] = useState<File | null>(null);
  const [appUrl, setAppUrl] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([
    {
      id: crypto.randomUUID(),
      timestamp: new Date().toLocaleTimeString(),
      message: 'System initialized. Upload your MD bot source code (.zip) to begin.',
      type: 'info',
    }
  ]);

  const addLog = (message: string, type: LogEntry['type'] = 'info') => {
    setLogs(prev => [...prev, {
      id: crypto.randomUUID(),
      timestamp: new Date().toLocaleTimeString(),
      message,
      type
    }]);
  };

  const startBot = () => {
    if (status !== 'offline') return;
    
    if (!botArchive) {
      addLog('No source code archive (.zip) provided. Please upload it first.', 'error');
      return;
    }

    setStatus('extracting');
    addLog(`Extracting ${botArchive.name}...`, 'info');
    setAppUrl(null);

    // Simulate Extraction
    setTimeout(() => {
      addLog('Extraction complete. Installing dependencies...', 'info');
      setStatus('installing');
      
      // Simulate NPM Install
      setTimeout(() => {
        addLog('Dependencies installed.', 'success');
        setStatus('starting');
        addLog('Starting WhatsApp MD bot process...', 'info');
        
        // Simulate Baileys initialization
        setTimeout(() => {
          setStatus('waiting_qr');
          setQrCode('whatsapp://login?data=123mockQrcodeThatWouldUsuallyBeRenderedForWAAuth');
          addLog('QR code generated. Please scan to link device.', 'warn');
          
          // Simulate scanning completed after a few seconds
          setTimeout(() => {
            setQrCode(null);
            setStatus('online');
            setBotInfo({ user: '18005551234@s.whatsapp.net', pushName: 'Manager Bot' });
            setAppUrl('http://localhost:3000'); // Simulate providing a local web interface URL
            addLog('Device linked successfully. Bot is now online.', 'success');
            addLog('Local web interface is now running on port 3000.', 'info');
          }, 6000);
          
        }, 2500);

      }, 3000);

    }, 2000);
  };

  const stopBot = () => {
    setStatus('offline');
    setQrCode(null);
    setBotInfo(null);
    setAppUrl(null);
    addLog('Bot process stopped.', 'warn');
  };

  const clearLogs = () => {
    setLogs([]);
  };

  return (
    <BotContext.Provider value={{ status, qrCode, botInfo, logs, botArchive, setBotArchive, appUrl, startBot, stopBot, clearLogs }}>
      {children}
    </BotContext.Provider>
  );
}

export function useBot() {
  const context = useContext(BotContext);
  if (context === undefined) {
    throw new Error('useBot must be used within a BotProvider');
  }
  return context;
}
