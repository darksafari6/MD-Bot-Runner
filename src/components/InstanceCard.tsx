import React, { useState } from 'react';
import { ExternalLink, LogOut, MoreVertical, Play, RotateCw, Square, Trash2 } from 'lucide-react';
import type { Instance } from '../../shared/types';
import { formatDuration, formatRelative, isBusy, uptimeSeconds } from '../lib/format';
import { useAppStore } from '../state/AppStore';
import { cn } from '../lib/utils';
import { Button, StatusPill } from './ui';

export function InstanceCard({
  instance,
  active,
  onOpen,
}: {
  instance: Instance;
  active: boolean;
  onOpen: () => void;
}) {
  const { actions, notify } = useAppStore();
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const running = instance.status !== 'stopped' && instance.status !== 'logged_out';
  const connected = instance.status === 'connected';

  return (
    <div
      className={cn(
        'group relative flex flex-col gap-3 rounded-xl border p-4 transition-colors',
        active
          ? 'border-emerald-500/30 bg-[#121416]'
          : 'border-white/[0.07] bg-[#101013] hover:border-white/15',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <button onClick={onOpen} className="min-w-0 flex-1 text-left">
          <p className="truncate text-sm font-semibold text-white">{instance.name}</p>
          <p className="mt-0.5 truncate font-mono text-[11px] text-slate-500">
            {connected
              ? `+${instance.identity?.number ?? 'unknown'}`
              : (instance.identity?.name ?? instance.id)}
          </p>
        </button>
        <StatusPill status={instance.status} />
      </div>

      <div className="grid grid-cols-3 gap-2 text-center">
        <Metric
          label="Uptime"
          value={connected ? formatDuration(uptimeSeconds(instance.stats.startedAt)) : '—'}
        />
        <Metric label="Commands" value={instance.stats.commandsHandled.toLocaleString()} />
        <Metric label="Msgs" value={instance.stats.messagesReceived.toLocaleString()} />
      </div>

      {instance.lastError && (
        <p className="line-clamp-2 rounded-md border border-rose-500/15 bg-rose-500/5 px-2 py-1 text-[11px] text-rose-300/90">
          {instance.lastError}
        </p>
      )}

      <div className="flex items-center gap-1.5">
        {!running ? (
          <Button
            variant="primary"
            size="sm"
            className="flex-1"
            onClick={() => void actions.start(instance.id)}
            loading={isBusy(instance.status)}
          >
            <Play className="h-3.5 w-3.5" /> Start
          </Button>
        ) : (
          <>
            <Button
              size="sm"
              className="flex-1"
              onClick={() => void actions.stop(instance.id)}
              disabled={isBusy(instance.status)}
            >
              <Square className="h-3.5 w-3.5" /> Stop
            </Button>
            <Button
              size="sm"
              title="Restart"
              aria-label="Restart instance"
              onClick={() => void actions.restart(instance.id)}
            >
              <RotateCw className="h-3.5 w-3.5" />
            </Button>
          </>
        )}

        <div className="relative">
          <Button
            size="sm"
            aria-label="More actions"
            onClick={() => setMenuOpen((value) => !value)}
          >
            <MoreVertical className="h-3.5 w-3.5" />
          </Button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 z-20 mt-1 w-48 overflow-hidden rounded-lg border border-white/10 bg-[#16161a] shadow-xl">
                <MenuItem
                  icon={<ExternalLink className="h-3.5 w-3.5" />}
                  label="Open details"
                  onClick={() => {
                    setMenuOpen(false);
                    onOpen();
                  }}
                />
                <MenuItem
                  icon={<RotateCw className="h-3.5 w-3.5" />}
                  label="Restart"
                  onClick={() => {
                    setMenuOpen(false);
                    void actions.restart(instance.id);
                  }}
                />
                <MenuItem
                  icon={<LogOut className="h-3.5 w-3.5" />}
                  label="Unlink device"
                  onClick={() => {
                    setMenuOpen(false);
                    if (
                      window.confirm(
                        `Unlink the WhatsApp device for "${instance.name}"? You will need to scan a new QR code.`,
                      )
                    ) {
                      void actions.logout(instance.id);
                    }
                  }}
                />
                <MenuItem
                  icon={<Trash2 className="h-3.5 w-3.5" />}
                  label={confirmDelete ? 'Click again to delete' : 'Delete bot'}
                  danger
                  onClick={() => {
                    if (!confirmDelete) {
                      setConfirmDelete(true);
                      window.setTimeout(() => setConfirmDelete(false), 3000);
                      return;
                    }
                    setMenuOpen(false);
                    void actions.remove(instance.id);
                    notify(`"${instance.name}" deleted`, 'success');
                  }}
                />
              </div>
            </>
          )}
        </div>
      </div>

      <p className="text-[10px] text-slate-600">
        Active {formatRelative(instance.stats.lastActivityAt)}
      </p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/5 bg-white/[0.02] px-2 py-1.5">
      <p className="text-[10px] uppercase tracking-wider text-slate-600">{label}</p>
      <p className="truncate font-mono text-xs text-slate-300">{value}</p>
    </div>
  );
}

function MenuItem({
  icon,
  label,
  onClick,
  danger,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors hover:bg-white/5',
        danger ? 'text-rose-300' : 'text-slate-300',
      )}
    >
      {icon}
      {label}
    </button>
  );
}
