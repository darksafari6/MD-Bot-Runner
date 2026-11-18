import type { InstanceStatus } from '../../shared/types';

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '—';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m`;
  return `${Math.floor(seconds)}s`;
}

export function formatRelative(timestamp: number | null): string {
  if (!timestamp) return 'never';
  const delta = Math.floor((Date.now() - timestamp) / 1000);
  if (delta < 5) return 'just now';
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

export function formatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export const STATUS_LABEL: Record<InstanceStatus, string> = {
  stopped: 'Stopped',
  starting: 'Starting',
  qr: 'Awaiting scan',
  pairing: 'Awaiting code',
  connected: 'Connected',
  reconnecting: 'Reconnecting',
  logged_out: 'Logged out',
  error: 'Error',
};

export const STATUS_TONE: Record<InstanceStatus, string> = {
  stopped: 'text-slate-400 bg-slate-500/10 border-slate-500/20',
  starting: 'text-amber-300 bg-amber-500/10 border-amber-500/20',
  qr: 'text-amber-300 bg-amber-500/10 border-amber-500/20',
  pairing: 'text-amber-300 bg-amber-500/10 border-amber-500/20',
  connected: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20',
  reconnecting: 'text-sky-300 bg-sky-500/10 border-sky-500/20',
  logged_out: 'text-orange-300 bg-orange-500/10 border-orange-500/20',
  error: 'text-rose-300 bg-rose-500/10 border-rose-500/20',
};

export const STATUS_DOT: Record<InstanceStatus, string> = {
  stopped: 'bg-slate-500',
  starting: 'bg-amber-400 animate-pulse',
  qr: 'bg-amber-400 animate-pulse',
  pairing: 'bg-amber-400 animate-pulse',
  connected: 'bg-emerald-400',
  reconnecting: 'bg-sky-400 animate-pulse',
  logged_out: 'bg-orange-400',
  error: 'bg-rose-500',
};

export function isBusy(status: InstanceStatus): boolean {
  return status === 'starting' || status === 'reconnecting';
}

export function uptimeSeconds(startedAt: number | null): number {
  if (!startedAt) return 0;
  return (Date.now() - startedAt) / 1000;
}
