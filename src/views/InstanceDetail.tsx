import React, { useMemo, useState } from 'react';
import {
  ArrowLeft,
  Clock,
  Gauge,
  LogOut,
  MessageSquare,
  Play,
  RotateCw,
  Square,
  Terminal,
  TriangleAlert,
} from 'lucide-react';
import type { Instance } from '../../shared/types';
import { CommandEditor } from '../components/CommandEditor';
import { ConfigPanel } from '../components/ConfigPanel';
import { ConnectPanel } from '../components/ConnectPanel';
import { InboxPanel } from '../components/InboxPanel';
import { LogConsole } from '../components/LogConsole';
import { Button, Card, StatusPill } from '../components/ui';
import { formatDuration, formatRelative, isBusy, uptimeSeconds } from '../lib/format';
import { useAppStore } from '../state/AppStore';
import { cn } from '../lib/utils';

type Tab = 'overview' | 'inbox' | 'commands' | 'logs';

export function InstanceDetail({ instance, onBack }: { instance: Instance; onBack: () => void }) {
  const { actions, instances } = useAppStore();
  const [tab, setTab] = useState<Tab>('overview');
  const needsLink = instance.status === 'qr' || instance.status === 'pairing';
  const running = !['stopped', 'logged_out', 'error'].includes(instance.status);

  const tabs = useMemo(
    () =>
      [
        { id: 'overview' as const, label: 'Overview', icon: Gauge },
        { id: 'inbox' as const, label: 'Inbox', icon: MessageSquare },
        { id: 'commands' as const, label: 'Commands', icon: Gauge },
        { id: 'logs' as const, label: 'Logs', icon: Terminal },
      ] satisfies Array<{ id: Tab; label: string; icon: typeof Gauge }>,
    [],
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={onBack} aria-label="Back to dashboard">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-semibold text-white">{instance.name}</h1>
              <StatusPill status={instance.status} />
            </div>
            <p className="font-mono text-[11px] text-slate-500">
              {instance.identity?.number ? `+${instance.identity.number}` : instance.id}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {!running ? (
            <Button variant="primary" size="sm" onClick={() => void actions.start(instance.id)}>
              <Play className="h-3.5 w-3.5" /> Start
            </Button>
          ) : (
            <>
              <Button size="sm" onClick={() => void actions.restart(instance.id)}>
                <RotateCw className="h-3.5 w-3.5" /> Restart
              </Button>
              <Button size="sm" onClick={() => void actions.stop(instance.id)}>
                <Square className="h-3.5 w-3.5" /> Stop
              </Button>
            </>
          )}
          <Button
            size="sm"
            variant="danger"
            onClick={() => {
              if (window.confirm(`Unlink the device for "${instance.name}"?`)) {
                void actions.logout(instance.id);
              }
            }}
          >
            <LogOut className="h-3.5 w-3.5" /> Unlink
          </Button>
        </div>
      </div>

      <div className="flex gap-1 border-b border-white/[0.07]">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={cn(
              '-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium transition-colors',
              tab === id
                ? 'border-emerald-400 text-white'
                : 'border-transparent text-slate-500 hover:text-slate-300',
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>

      {tab === 'inbox' ? (
        <InboxPanel instance={instance} />
      ) : tab === 'logs' ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <LogConsole
            instances={instances}
            instanceId={instance.id}
            onInstanceChange={() => setTab('logs')}
          />
        </div>
      ) : tab === 'commands' ? (
        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <CommandEditor instance={instance} />
          <ConfigPanel instance={instance} />
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_1.3fr]">
          <div className="flex flex-col gap-4">
            <Card className="p-4">
              <h2 className="mb-3 text-sm font-semibold text-white">
                {needsLink ? 'Link this bot' : 'Connection'}
              </h2>
              {needsLink ? (
                <ConnectPanel instance={instance} />
              ) : instance.status === 'connected' ? (
                <div className="flex flex-col gap-3">
                  <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
                    <p className="text-[11px] uppercase tracking-wider text-emerald-400/80">
                      Linked device
                    </p>
                    <p className="mt-1 text-sm text-white">
                      {instance.identity?.name ?? 'Unknown device'}
                    </p>
                    <p className="font-mono text-xs text-slate-400">
                      {instance.identity?.number ? `+${instance.identity.number}` : '—'}
                    </p>
                  </div>
                  <Button size="sm" onClick={() => setTab('commands')}>
                    <MessageSquare className="h-3.5 w-3.5" /> Manage commands
                  </Button>
                </div>
              ) : (
                <div className="flex flex-col items-start gap-3">
                  <p className="text-xs text-slate-400">
                    {instance.status === 'logged_out'
                      ? 'This device was unlinked. Start the bot and scan again to reconnect.'
                      : 'This bot is not running.'}
                  </p>
                  {instance.lastError && (
                    <p className="flex items-start gap-2 rounded-lg border border-rose-500/15 bg-rose-500/5 p-2.5 text-[11px] text-rose-300/90">
                      <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                      {instance.lastError}
                    </p>
                  )}
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => void actions.start(instance.id)}
                    loading={isBusy(instance.status)}
                  >
                    <Play className="h-3.5 w-3.5" /> Start and link
                  </Button>
                </div>
              )}
            </Card>

            <Card className="p-4">
              <h2 className="mb-3 text-sm font-semibold text-white">Health</h2>
              <dl className="space-y-2 text-xs">
                <Row
                  label="Uptime"
                  value={
                    instance.stats.startedAt
                      ? formatDuration(uptimeSeconds(instance.stats.startedAt))
                      : '—'
                  }
                />
                <Row label="Last activity" value={formatRelative(instance.stats.lastActivityAt)} />
                <Row label="Commands handled" value={String(instance.stats.commandsHandled)} />
                <Row label="Messages seen" value={String(instance.stats.messagesReceived)} />
                <Row label="Replies sent" value={String(instance.stats.messagesSent)} />
                <Row
                  label="Errors"
                  value={String(instance.stats.errors)}
                  tone={instance.stats.errors > 0 ? 'text-rose-300' : undefined}
                />
                <Row
                  label="Created"
                  value={new Date(instance.createdAt).toLocaleDateString()}
                  icon={<Clock className="h-3 w-3" />}
                />
              </dl>
            </Card>
          </div>

          <div className="flex min-h-[320px] flex-col">
            <LogConsole
              instances={instances}
              instanceId={instance.id}
              onInstanceChange={() => setTab('logs')}
              compact
            />
          </div>
        </div>
      )}
    </div>
  );
}

function Row({
  label,
  value,
  tone,
  icon,
}: {
  label: string;
  value: string;
  tone?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="flex items-center gap-1.5 text-slate-500">
        {icon}
        {label}
      </dt>
      <dd className={cn('font-mono text-slate-300', tone)}>{value}</dd>
    </div>
  );
}
