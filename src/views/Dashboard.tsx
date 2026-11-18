import React, { useMemo, useState } from 'react';
import {
  Bot,
  CheckCircle2,
  MessageSquare,
  Plus,
  RefreshCw,
  Server,
  TriangleAlert,
} from 'lucide-react';
import type { Instance } from '../../shared/types';
import { InstanceCard } from '../components/InstanceCard';
import { LogConsole } from '../components/LogConsole';
import { Button, Card, EmptyState, inputClass } from '../components/ui';
import { useAppStore } from '../state/AppStore';

export function Dashboard({ onOpen }: { onOpen: (id: string) => void }) {
  const { instances, actions, refresh, loading, version, connectionLost } = useAppStore();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const [logFilter, setLogFilter] = useState<string | 'all'>('all');

  const summary = useMemo(() => {
    const connected = instances.filter((instance) => instance.status === 'connected').length;
    const attention = instances.filter((instance) =>
      ['error', 'logged_out', 'reconnecting'].includes(instance.status),
    ).length;
    const commands = instances.reduce(
      (total, instance) => total + instance.stats.commandsHandled,
      0,
    );
    return { connected, attention, commands };
  }, [instances]);

  const create = async () => {
    if (!name.trim()) return;
    setSaving(true);
    await actions.create(name.trim());
    setSaving(false);
    setName('');
    setCreating(false);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-white">Dashboard</h1>
          <p className="text-xs text-slate-500">
            {version ? `Manager v${version} · ` : ''}
            {instances.length} bot{instances.length === 1 ? '' : 's'} configured
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={() => void refresh()} loading={loading}>
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </Button>
          <Button size="sm" variant="primary" onClick={() => setCreating(true)}>
            <Plus className="h-3.5 w-3.5" /> New bot
          </Button>
        </div>
      </div>

      {connectionLost && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-300">
          <TriangleAlert className="h-4 w-4 shrink-0" />
          Cannot reach the manager API. Is the server running on this host?
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard
          icon={<CheckCircle2 className="h-4 w-4" />}
          label="Connected"
          value={`${summary.connected}/${instances.length}`}
          tone="emerald"
        />
        <StatCard
          icon={<MessageSquare className="h-4 w-4" />}
          label="Commands handled"
          value={summary.commands.toLocaleString()}
          tone="sky"
        />
        <StatCard
          icon={<TriangleAlert className="h-4 w-4" />}
          label="Needs attention"
          value={String(summary.attention)}
          tone={summary.attention > 0 ? 'rose' : 'slate'}
        />
      </div>

      {creating && (
        <Card className="flex flex-wrap items-end gap-2 p-3">
          <label className="flex flex-1 flex-col gap-1">
            <span className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
              Bot name
            </span>
            <input
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void create();
                if (event.key === 'Escape') setCreating(false);
              }}
              placeholder="Support bot"
              className={inputClass}
            />
          </label>
          <Button variant="primary" onClick={create} loading={saving} disabled={!name.trim()}>
            Create
          </Button>
          <Button variant="ghost" onClick={() => setCreating(false)}>
            Cancel
          </Button>
        </Card>
      )}

      {instances.length === 0 ? (
        <Card className="p-4">
          <EmptyState
            icon={<Bot className="h-8 w-8" />}
            title="No bots yet"
            description="Create your first instance, start it, then scan the QR code with WhatsApp → Linked devices."
            action={
              <Button variant="primary" size="sm" onClick={() => setCreating(true)}>
                <Plus className="h-3.5 w-3.5" /> Create your first bot
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {instances.map((instance: Instance) => (
            <InstanceCard
              key={instance.id}
              instance={instance}
              active={false}
              onOpen={() => onOpen(instance.id)}
            />
          ))}
        </div>
      )}

      <div className="flex min-h-[240px] flex-1 flex-col">
        <LogConsole instances={instances} instanceId={logFilter} onInstanceChange={setLogFilter} />
      </div>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone: 'emerald' | 'sky' | 'rose' | 'slate';
}) {
  const tones = {
    emerald: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/20',
    sky: 'text-sky-300 bg-sky-500/10 border-sky-500/20',
    rose: 'text-rose-300 bg-rose-500/10 border-rose-500/20',
    slate: 'text-slate-400 bg-white/5 border-white/10',
  } as const;
  return (
    <Card className="flex items-center gap-3 p-3">
      <div className={`rounded-lg border p-2 ${tones[tone]}`}>{icon}</div>
      <div>
        <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
        <p className="font-mono text-lg leading-tight text-white">{value}</p>
      </div>
    </Card>
  );
}

export function SettingsView() {
  const { settings, actions, version, instances } = useAppStore();
  const [logRetention, setLogRetention] = useState(settings?.logRetention ?? 500);

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <div>
        <h1 className="text-lg font-semibold text-white">Settings</h1>
        <p className="text-xs text-slate-500">Manager-wide preferences.</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="flex flex-col gap-4 p-4">
          <h2 className="text-sm font-semibold text-white">Runtime</h2>
          <label className="flex items-center justify-between gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
            <span className="text-sm text-slate-300">Resume bots after restart</span>
            <input
              type="checkbox"
              checked={settings?.autostartConnectedInstances ?? true}
              onChange={(event) =>
                void actions.updateSettings({ autostartConnectedInstances: event.target.checked })
              }
              className="h-4 w-4 accent-emerald-500"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
              Log lines retained
            </span>
            <div className="flex gap-2">
              <input
                type="number"
                min={50}
                max={5000}
                value={logRetention}
                onChange={(event) => setLogRetention(Number(event.target.value))}
                className={inputClass}
              />
              <Button
                size="sm"
                onClick={() => void actions.updateSettings({ logRetention })}
                disabled={logRetention === settings?.logRetention}
              >
                Save
              </Button>
            </div>
          </label>
          <p className="text-[11px] text-slate-500">
            Limits that require a process restart (MAX_INSTANCES, PORT, API_TOKEN) live in{' '}
            <code className="text-slate-400">.env</code>.
          </p>
        </Card>

        <Card className="flex flex-col gap-3 p-4">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-white">
            <Server className="h-4 w-4 text-slate-500" /> About this manager
          </h2>
          <dl className="space-y-2 text-xs">
            <div className="flex justify-between">
              <dt className="text-slate-500">Version</dt>
              <dd className="font-mono text-slate-300">{version ?? '—'}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">WhatsApp engine</dt>
              <dd className="font-mono text-slate-300">Baileys 6.7.24</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-500">Instances</dt>
              <dd className="font-mono text-slate-300">{instances.length}</dd>
            </div>
          </dl>
          <p className="mt-2 rounded-lg border border-amber-500/15 bg-amber-500/5 p-2.5 text-[11px] text-amber-300/80">
            Unofficial WhatsApp automation can get a number banned. Use a dedicated number and keep
            volumes human-like.
          </p>
        </Card>
      </div>
    </div>
  );
}
