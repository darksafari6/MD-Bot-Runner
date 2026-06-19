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
  Info 
} from 'lucide-react';
import { cn } from './lib/utils';
import { motion, AnimatePresence } from 'motion/react';

export default function App() {
  return (
    <div className="flex bg-slate-950 text-slate-200 h-screen w-screen overflow-hidden font-sans">
      {/* Sidebar Navigation */}
      <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col items-center py-6 gap-6 shadow-2xl z-10 shrink-0">
        <div className="flex items-center gap-3 px-4 w-full text-slate-100">
          <div className="w-10 h-10 bg-emerald-500 rounded-xl flex items-center justify-center shadow-lg shadow-emerald-500/20">
            <Bot className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="font-bold text-lg tracking-tight leading-tight">Bot Manager</h1>
            <p className="text-xs text-slate-400 font-mono">WA-MD Edition</p>
          </div>
        </div>

        <nav className="w-full px-3 flex flex-col gap-1 mt-4">
          <NavItem icon={<Activity />} label="Dashboard" active />
          <NavItem icon={<Terminal />} label="Console Logs" />
          <NavItem icon={<Settings />} label="Configuration" />
        </nav>

        <div className="mt-auto px-4 w-full">
          <div className="p-4 rounded-xl bg-slate-800/50 border border-slate-700/50 flex flex-col gap-2">
            <p className="text-xs text-slate-400">Environment</p>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse"></span>
              <span className="text-sm font-mono tracking-tight text-slate-300">Electron Desktop</span>
            </div>
            <p className="text-[10px] text-slate-500 font-mono mt-1">v1.0.0 (Baileys Hooked)</p>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col h-full bg-slate-950/50 relative overflow-hidden">
        {/* Header */}
        <header className="h-16 px-8 border-b border-slate-800 bg-slate-900/40 backdrop-blur-md flex items-center justify-between shrink-0">
          <h2 className="text-xl font-semibold text-slate-100 tracking-tight">Active Instance</h2>
          <ServerStatusBadge />
        </header>

        {/* Dashboard Content */}
        <div className="flex-1 overflow-y-auto p-8 flex flex-col xl:flex-row gap-6">
          
          {/* Left Column (Controls & Status) */}
          <div className="flex-1 flex flex-col gap-6 max-w-2xl">
            <ControlPanel />
            <SessionDetails />
          </div>

          {/* Right Column (Terminal / Logs) */}
          <div className="flex-[1.5] w-full min-h-[400px] h-full flex">
            <LogTerminal />
          </div>

        </div>
      </main>
    </div>
  );
}

function NavItem({ icon, label, active = false }: { icon: React.ReactNode, label: string, active?: boolean }) {
  return (
    <button className={cn(
      "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all text-sm font-medium",
      active 
        ? "bg-slate-800 text-slate-100 shadow-sm" 
        : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200"
    )}>
      <span className={cn("w-5 h-5", active ? "text-emerald-400" : "")}>{React.cloneElement(icon as React.ReactElement, { size: '100%', strokeWidth: 2 })}</span>
      {label}
    </button>
  );
}

function ServerStatusBadge() {
  const { status } = useBot();

  const getStatusColor = () => {
    switch(status) {
      case 'online': return 'bg-emerald-500 text-emerald-950 shadow-emerald-500/20';
      case 'offline': return 'bg-slate-500 text-slate-950 shadow-slate-500/20';
      case 'starting':
      case 'waiting_qr': return 'bg-amber-500 text-amber-950 shadow-amber-500/20';
      case 'error': return 'bg-red-500 text-red-950 shadow-red-500/20';
    }
  };

  return (
    <div className={cn("px-3 py-1 rounded-full flex items-center gap-2 text-xs font-bold uppercase tracking-wider shadow-md", getStatusColor())}>
      {status === 'online' && <CheckCircle2 className="w-3.5 h-3.5" />}
      {status === 'offline' && <XOctagon className="w-3.5 h-3.5" />}
      {(status === 'starting' || status === 'waiting_qr') && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
      {status === 'error' && <AlertTriangle className="w-3.5 h-3.5" />}
      {status.replace('_', ' ')}
    </div>
  );
}

function ControlPanel() {
  const { status, startBot, stopBot, qrCode } = useBot();

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl relative overflow-hidden flex flex-col gap-6">
      
      {/* Dynamic Background Gradient */}
      <div className={cn(
        "absolute inset-0 opacity-10 transition-colors duration-1000",
        status === 'online' ? "bg-gradient-to-br from-emerald-500 to-transparent" : 
        status === 'starting' || status === 'waiting_qr' ? "bg-gradient-to-br from-amber-500 to-transparent" :
        "bg-gradient-to-br from-slate-500 to-transparent"
      )} />

      <div className="relative z-10 flex flex-col gap-5">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-lg font-semibold text-slate-100">Bot Lifecycle</h3>
            <p className="text-sm text-slate-400 mt-1">Start or stop the background WhatsApp process.</p>
          </div>
          <div className={cn("w-12 h-12 rounded-full flex items-center justify-center transition-colors", status === 'online' ? "bg-emerald-500/20 text-emerald-400" : "bg-slate-800 text-slate-500")}>
            <Smartphone className="w-6 h-6" />
          </div>
        </div>

        <div className="flex gap-4">
          <button 
            onClick={startBot}
            disabled={status !== 'offline' && status !== 'error'}
            className="flex-1 bg-emerald-500 hover:bg-emerald-400 disabled:bg-slate-800 disabled:text-slate-500 text-emerald-950 font-bold py-3 px-4 rounded-xl flex items-center justify-center gap-2 transition-all shadow-lg hover:shadow-emerald-500/25 active:scale-95 disabled:scale-100 disabled:shadow-none"
          >
            <Play className="w-5 h-5 fill-current" />
            Start Process
          </button>
          
          <button 
            onClick={stopBot}
            disabled={status === 'offline'}
            className="w-16 bg-slate-800 hover:bg-red-500/20 disabled:hover:bg-slate-800 text-slate-300 hover:text-red-400 disabled:text-slate-600 disabled:opacity-50 py-3 rounded-xl flex items-center justify-center transition-all shadow-md active:scale-95 disabled:scale-100"
          >
            <Square className="w-5 h-5 fill-current" />
          </button>
        </div>
      </div>

      <AnimatePresence>
        {status === 'waiting_qr' && qrCode && (
          <motion.div 
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="relative z-10 border-t border-slate-800 pt-6 mt-2 flex flex-col items-center gap-4"
          >
            <p className="text-sm text-amber-400 font-medium animate-pulse text-center">
              Scan this QR code with WhatsApp<br/>(Linked Devices)
            </p>
            <div className="bg-white p-4 rounded-2xl shadow-xl shadow-amber-500/10 scale-100 transition-transform">
              <QRCodeSVG value={qrCode} size={200} level="H" includeMargin={false} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function SessionDetails() {
  const { botInfo, status } = useBot();

  return (
    <div className={cn(
      "bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl transition-all duration-500",
      status === 'online' ? "opacity-100" : "opacity-50"
    )}>
      <h3 className="text-lg font-semibold text-slate-100">Session Details</h3>
      
      <div className="mt-5 space-y-4">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-slate-500 font-medium uppercase tracking-wider">Linked Account Number</span>
          <div className="flex items-center gap-2">
            <code className="text-sm text-slate-300 bg-slate-950 px-2 py-1 rounded border border-slate-800 font-mono">
              {botInfo?.user ? botInfo.user.split('@')[0] : 'Not connected'}
            </code>
          </div>
        </div>
        
        <div className="flex flex-col gap-1">
          <span className="text-xs text-slate-500 font-medium uppercase tracking-wider">Push Name</span>
          <p className="text-slate-300 font-medium">{botInfo?.pushName || 'N/A'}</p>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-xs text-slate-500 font-medium uppercase tracking-wider">Database State</span>
          <div className="flex items-center gap-2 text-sm text-slate-300">
            <span className={cn("w-2 h-2 rounded-full", status === 'online' ? "bg-emerald-500" : "bg-slate-600")} />
            {status === 'online' ? 'Synced (Baileys Store)' : 'Locally Dormant'}
          </div>
        </div>
      </div>
    </div>
  );
}

function LogTerminal() {
  const { logs, clearLogs } = useBot();

  return (
    <div className="flex-1 bg-[#0a0a0f] border border-slate-800/80 rounded-2xl shadow-xl flex flex-col overflow-hidden relative">
      
      {/* Terminal Header */}
      <div className="h-12 bg-slate-900/50 border-b border-slate-800 flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-3">
          <Terminal className="w-4 h-4 text-slate-500" />
          <span className="text-sm font-mono text-slate-400">system.log</span>
        </div>
        <div className="flex items-center gap-2">
          {logs.length > 0 && (
             <button onClick={clearLogs} className="text-slate-500 hover:text-red-400 transition-colors p-1" title="Clear Logs">
               <Trash2 className="w-4 h-4" />
             </button>
          )}
        </div>
      </div>

      {/* Log Entries */}
      <div className="flex-1 overflow-y-auto p-4 font-mono text-[13px] leading-relaxed select-text">
        {logs.map((log) => (
          <motion.div 
            initial={{ opacity: 0, x: -5 }}
            animate={{ opacity: 1, x: 0 }}
            key={log.id} 
            className="flex gap-3 mb-1.5 break-words group hover:bg-slate-800/30 px-2 py-0.5 rounded"
          >
            <span className="text-slate-600 shrink-0 select-none">[{log.timestamp}]</span>
            <LogMessage type={log.type} message={log.message} />
          </motion.div>
        ))}
      </div>
    </div>
  );
}

function LogMessage({ type, message }: { type: LogEntry['type'], message: string }) {
  switch (type) {
    case 'info':
      return <span className="text-slate-300">{message}</span>;
    case 'warn':
      return <span className="text-amber-400 flex items-start flex-col">
        {message}
      </span>;
    case 'error':
      return <span className="text-red-400">{message}</span>;
    case 'success':
      return <span className="text-emerald-400">{message}</span>;
    default:
      return <span className="text-slate-300">{message}</span>;
  }
}

