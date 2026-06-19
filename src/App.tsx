/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { useBot } from './bot/BotContext';
import { QRCodeSVG } from 'qrcode.react';
import { 
  Bot, 
  Terminal, 
  Activity, 
  Settings, 
  Play, 
  Square, 
  Smartphone, 
  CheckCircle2, 
  XOctagon, 
  Loader2,
  Trash2,
  AlertTriangle,
  Info,
  Upload,
  FileArchive,
  ExternalLink
} from 'lucide-react';
import { cn } from './lib/utils';
import { motion, AnimatePresence } from 'motion/react';

export default function App() {
  return (
    <div className="w-screen h-screen bg-[#050507] text-slate-200 font-sans flex flex-col overflow-hidden">
      {/* Custom Title Bar (Electron Style) */}
      <header className="h-10 bg-[#111114] border-b border-white/5 flex items-center justify-between px-4 shrink-0 select-none">
        <div className="flex items-center gap-3">
          <div className="w-5 h-5 bg-[#25D366] rounded-md flex items-center justify-center shadow-[0_0_10px_rgba(37,211,102,0.4)]">
            <Bot className="w-3 h-3 text-black" />
          </div>
          <span className="text-xs font-bold tracking-widest text-slate-400 uppercase">
            Bot Manager <span className="text-[#25D366]">MD</span>
          </span>
        </div>
        <div className="flex items-center gap-4">
          <ServerStatusBadge />
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar Navigation */}
        <aside className="w-64 bg-[#0d0d0f] border-r border-white/5 flex flex-col shrink-0">
          <div className="p-4">
            <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">Navigation</div>
            <nav className="space-y-1">
              <NavItem icon={<Activity />} label="Dashboard" active />
              <NavItem icon={<Terminal />} label="Console Logs" />
              <NavItem icon={<Settings />} label="Configuration" />
            </nav>
          </div>

          <div className="mt-auto p-4 border-t border-white/5">
            <div className="p-3 bg-white/5 border border-white/10 rounded-md flex flex-col gap-1">
              <p className="text-[10px] text-slate-500 uppercase tracking-widest">Environment</p>
              <div className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse shadow-[0_0_5px_rgba(59,130,246,0.6)]"></span>
                <span className="text-xs font-mono text-slate-300">Electron Desktop</span>
              </div>
            </div>
          </div>
        </aside>

        {/* Main Content Area */}
        <main className="flex-1 flex flex-col bg-[#050507] relative overflow-y-auto px-6 pt-6 gap-6">
          <div className="flex flex-col xl:flex-row gap-6 pb-6 min-h-0 flex-1">
            {/* Left Column (Controls & Status) */}
            <div className="flex-1 flex flex-col gap-6 max-w-2xl">
              <ControlPanel />
              <SessionDetails />
            </div>

            {/* Right Column (Terminal / Logs) */}
            <div className="flex-[1.5] w-full min-h-[400px] flex flex-col">
              <LogTerminal />
            </div>
          </div>
        </main>
      </div>

      {/* Footer */}
      <footer className="h-7 bg-[#0d0d0f] border-t border-white/5 flex items-center justify-between px-4 shrink-0 text-[10px] text-slate-500">
        <div className="flex gap-4">
          <span>ENGINE: <span className="text-slate-300">BAILEYS-MD</span></span>
          <span>UI: <span className="text-slate-300">IMMERSIVE</span></span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-[#25D366]"></span>
          <span className="uppercase tracking-tighter font-medium">SYSTEMS SECURED</span>
        </div>
      </footer>
    </div>
  );
}

function NavItem({ icon, label, active = false }: { icon: React.ReactNode, label: string, active?: boolean }) {
  return (
    <button className={cn(
      "w-full flex items-center gap-3 p-2.5 rounded-lg transition-colors cursor-pointer group",
      active 
        ? "bg-[#25D366]/10 border border-[#25D366]/20" 
        : "hover:bg-white/5 border border-transparent"
    )}>
      <span className={cn("w-4 h-4", active ? "text-[#25D366]" : "text-slate-400 group-hover:text-white transition-colors")}>
        {React.cloneElement(icon as React.ReactElement, { size: '100%', strokeWidth: 2 })}
      </span>
      <span className={cn("text-sm font-medium", active ? "text-white" : "text-slate-400 group-hover:text-white transition-colors")}>
        {label}
      </span>
    </button>
  );
}

function ServerStatusBadge() {
  const { status } = useBot();

  return (
    <div className="flex items-center gap-1.5 text-[10px] bg-black/40 px-2 py-0.5 rounded border border-white/5">
      <div className={cn(
        "w-1.5 h-1.5 rounded-full shadow-[0_0_5px_currentColor]",
        status === 'online' ? 'bg-[#25D366] text-[#25D366]' :
        status === 'offline' ? 'bg-slate-500 text-slate-500' :
        (status === 'starting' || status === 'waiting_qr') ? 'bg-yellow-500 text-yellow-500 animate-pulse' :
        'bg-red-500 text-red-500'
      )}></div>
      <span className="text-slate-400 uppercase">Status:</span>
      <span className="text-white font-mono uppercase">{status.replace('_', ' ')}</span>
    </div>
  );
}

function ControlPanel() {
  const { status, startBot, stopBot, qrCode, botArchive, setBotArchive, appUrl } = useBot();
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setBotArchive(e.target.files[0]);
    }
  };

  return (
    <div className="bg-[#111114] border border-white/5 p-5 rounded-xl flex flex-col gap-6 relative overflow-hidden">
      {/* Dynamic Background Gradient */}
      <div className={cn(
        "absolute inset-0 opacity-10 transition-colors duration-1000",
        status === 'online' ? "bg-[radial-gradient(ellipse_at_top_right,rgba(37,211,102,0.4),transparent_50%)]" : 
        (status !== 'offline' && status !== 'error') ? "bg-[radial-gradient(ellipse_at_top_right,rgba(234,179,8,0.4),transparent_50%)]" :
        "bg-[radial-gradient(ellipse_at_top_right,rgba(100,116,139,0.3),transparent_50%)]"
      )} />

      <div className="relative z-10 flex flex-col gap-5">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">Bot Lifecycle</div>
            <h3 className="text-xl font-semibold text-white">Process Control</h3>
          </div>
          <div className={cn("w-10 h-10 rounded-full flex items-center justify-center transition-colors", status === 'online' ? "bg-[#25D366]/20 text-[#25D366]" : "bg-white/5 text-slate-500")}>
            <Smartphone className="w-5 h-5" />
          </div>
        </div>

        {/* Source Code Archive Upload */}
        <div className="flex flex-col gap-2">
          <span className="text-xs text-slate-400 font-medium tracking-wide">Source Code Repository</span>
          
          <input 
            type="file" 
            accept=".zip" 
            ref={fileInputRef} 
            onChange={handleFileChange} 
            className="hidden" 
          />
          
          <div 
            onClick={() => status === 'offline' && fileInputRef.current?.click()}
            className={cn(
              "flex items-center justify-between p-3 rounded-lg border border-dashed transition-all",
              status !== 'offline' ? "opacity-50 cursor-not-allowed border-white/10 bg-white/5" :
              botArchive ? "border-[#25D366]/30 bg-[#25D366]/5 cursor-pointer hover:bg-[#25D366]/10" : "border-white/20 bg-white/5 cursor-pointer hover:bg-white/10"
            )}
          >
            <div className="flex items-center gap-3 overflow-hidden">
              <div className={cn("w-8 h-8 rounded shrink-0 flex items-center justify-center", botArchive ? "bg-[#25D366]/20 text-[#25D366]" : "bg-white/10 text-slate-400")}>
                <FileArchive className="w-4 h-4" />
              </div>
              <div className="flex flex-col truncate">
                <span className="text-sm font-medium text-slate-200 truncate">
                  {botArchive ? botArchive.name : "Upload MD Bot Source (.zip)"}
                </span>
                <span className="text-[10px] text-slate-500">
                  {botArchive ? `${(botArchive.size / 1024 / 1024).toFixed(2)} MB` : 'Click to browse files'}
                </span>
              </div>
            </div>
            
            {status === 'offline' && (
              <div className="shrink-0 pl-2">
                <Upload className="w-4 h-4 text-slate-400" />
              </div>
            )}
          </div>
        </div>

        <div className="flex gap-4 mt-2">
          <button 
            onClick={startBot}
            disabled={status !== 'offline' && status !== 'error'}
            className="flex-[2] bg-[#25D366]/20 border border-[#25D366]/50 text-[#25D366] py-3 rounded-lg font-bold text-xs hover:bg-[#25D366]/30 uppercase tracking-widest shadow-[0_0_15px_rgba(37,211,102,0.1)] disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
          >
            <Play className="w-4 h-4 fill-current" /> Initialize
          </button>
          
          <button 
            onClick={stopBot}
            disabled={status === 'offline'}
            className="flex-1 bg-red-500/10 border border-red-500/30 text-red-400 py-3 rounded-lg font-bold text-xs hover:bg-red-500/20 uppercase tracking-widest disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
          >
            <Square className="w-4 h-4 fill-current" /> Stop
          </button>
        </div>
      </div>

      <AnimatePresence>
        {status === 'waiting_qr' && qrCode && (
          <motion.div 
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="relative z-10 border-t border-white/10 pt-5 mt-2 flex flex-col items-center gap-4"
          >
            <p className="text-[10px] text-yellow-500 font-bold uppercase tracking-widest animate-pulse text-center">
              Scan QR Code to Link Device
            </p>
            <div className="bg-white p-3 rounded-xl shadow-[0_0_30px_rgba(234,179,8,0.15)]">
              <QRCodeSVG value={qrCode} size={160} level="H" includeMargin={false} />
            </div>
          </motion.div>
        )}
        
        {status === 'online' && appUrl && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="relative z-10 border-t border-white/10 pt-5 mt-2 flex flex-col gap-3"
          >
            <div className="text-[10px] text-[#25D366] uppercase tracking-widest font-bold flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[#25D366] animate-pulse shadow-[0_0_5px_#25D366]"></span>
              Web Interface Active
            </div>
            <a 
              href={appUrl} 
              target="_blank" 
              rel="noopener noreferrer"
              className="flex items-center justify-between p-3 rounded-lg bg-[#25D366]/10 border border-[#25D366]/20 hover:bg-[#25D366]/20 transition-all group"
            >
              <div className="flex flex-col">
                <span className="text-sm font-medium text-white group-hover:text-[#25D366] transition-colors">Open Local App</span>
                <span className="text-xs text-slate-400 font-mono">{appUrl}</span>
              </div>
              <ExternalLink className="w-4 h-4 text-[#25D366]" />
            </a>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function SessionDetails() {
  const { botInfo, status } = useBot();

  return (
    <div className="grid grid-cols-2 gap-4">
      <div className={cn(
        "bg-[#111114] border border-white/5 p-4 rounded-xl transition-all duration-500",
        status === 'online' ? "opacity-100" : "opacity-50"
      )}>
        <div className="text-[10px] text-slate-500 uppercase mb-1">Session Push Name</div>
        <div className="text-xl font-semibold text-white truncate" title={botInfo?.pushName || 'N/A'}>
          {botInfo?.pushName || 'N/A'}
        </div>
      </div>
      
      <div className={cn(
        "bg-[#111114] border border-white/5 p-4 rounded-xl transition-all duration-500",
        status === 'online' ? "opacity-100" : "opacity-50"
      )}>
        <div className="text-[10px] text-slate-500 uppercase mb-1">Linked Account</div>
        <div className="text-xl font-mono text-white truncate" title={botInfo?.user ? botInfo.user.split('@')[0] : 'N/A'}>
          {botInfo?.user ? botInfo.user.split('@')[0] : 'N/A'}
        </div>
      </div>

      <div className={cn(
        "bg-[#111114] border border-white/5 p-4 rounded-xl transition-all duration-500 col-span-2 flex justify-between items-center",
        status === 'online' ? "opacity-100" : "opacity-50"
      )}>
        <div>
          <div className="text-[10px] text-slate-500 uppercase mb-1">Database State</div>
          <div className="flex items-center gap-2 text-sm text-slate-300">
            <span className={cn("w-1.5 h-1.5 rounded-full flex-shrink-0", status === 'online' ? "bg-[#25D366]" : "bg-slate-600")} />
            {status === 'online' ? 'Synced (Baileys Store)' : 'Locally Dormant'}
          </div>
        </div>
        {status === 'online' && (
          <div className="text-[10px] text-[#25D366] uppercase tracking-widest font-bold">
            Active
          </div>
        )}
      </div>
    </div>
  );
}

function LogTerminal() {
  const { logs, clearLogs } = useBot();

  return (
    <div className="flex-[1] min-h-0 bg-[#0a0a0c] border border-white/10 rounded-xl flex flex-col overflow-hidden shadow-2xl relative">
      {/* Terminal Header */}
      <div className="h-10 bg-[#16161a] border-b border-white/10 flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full bg-red-500/50"></div>
            <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/50"></div>
            <div className="w-2.5 h-2.5 rounded-full bg-green-500/50"></div>
          </div>
          <span className="text-[10px] font-mono text-slate-500 ml-2 uppercase tracking-widest">Console Output</span>
        </div>
        <div className="flex items-center gap-2">
          {logs.length > 0 && (
             <button onClick={clearLogs} className="text-[10px] uppercase tracking-widest text-slate-500 hover:text-white transition-colors">
               Clear Logs
             </button>
          )}
        </div>
      </div>

      {/* Log Entries */}
      <div className="flex-1 overflow-y-auto p-4 font-mono text-xs leading-relaxed select-text bg-[radial-gradient(circle_at_50%_0%,rgba(37,211,102,0.05),transparent)]">
        {logs.map((log) => (
          <motion.div 
            initial={{ opacity: 0, x: -5 }}
            animate={{ opacity: 1, x: 0 }}
            key={log.id} 
            className="flex gap-3 mb-1.5 break-words group hover:bg-white/5 px-2 py-0.5 rounded"
          >
            <span className="text-slate-500 shrink-0 select-none">[{log.timestamp}]</span>
            <span className="text-slate-300">
              <LogMessage type={log.type} message={log.message} />
            </span>
          </motion.div>
        ))}
        {logs.length > 0 && <div className="animate-pulse text-[#25D366] mt-4 px-2">_</div>}
      </div>
    </div>
  );
}

function LogMessage({ type, message }: { type: LogEntry['type'], message: string }) {
  switch (type) {
    case 'info':
      return <><span className="text-blue-400">info</span>: {message}</>;
    case 'warn':
      return <><span className="text-yellow-400">warn</span>: {message}</>;
    case 'error':
      return <><span className="text-red-400">error</span>: {message}</>;
    case 'success':
      return <><span className="text-green-400">success</span>: {message}</>;
    default:
      return <>{message}</>;
  }
}

