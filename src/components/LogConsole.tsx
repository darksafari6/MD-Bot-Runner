import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDownToLine, Eraser, Search } from 'lucide-react';
import type { Instance, LogEntry, LogLevel } from '../../shared/types';
import { formatTime } from '../lib/format';
import { useAppStore } from '../state/AppStore';
import { cn } from '../lib/utils';
import { Button, inputClass } from './ui';

const LEVEL_STYLE: Record<LogLevel, { label: string; className: string }> = {
  debug: { label: 'debug', className: 'text-slate-500' },
  info: { label: 'info', className: 'text-sky-400' },
  warn: { label: 'warn', className: 'text-amber-400' },
  error: { label: 'error', className: 'text-rose-400' },
  success: { label: 'ok', className: 'text-emerald-400' },
};

export function LogConsole({
  instances,
  instanceId,
  onInstanceChange,
  compact = false,
}: {
  instances: Instance[];
  instanceId: string | 'all';
  onInstanceChange: (value: string | 'all') => void;
  compact?: boolean;
}) {
  const { logs, clearLogs } = useAppStore();
  const [query, setQuery] = useState('');
  const [level, setLevel] = useState<LogLevel | 'all'>('all');
  const [follow, setFollow] = useState(true);
  const scroller = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return logs.filter((entry) => {
      if (instanceId !== 'all' && entry.instanceId !== instanceId) return false;
      if (level !== 'all' && entry.level !== level) return false;
      if (!needle) return true;
      return (
        entry.message.toLowerCase().includes(needle) || entry.source.toLowerCase().includes(needle)
      );
    });
  }, [logs, instanceId, level, query]);

  useEffect(() => {
    if (!follow) return;
    const node = scroller.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [filtered, follow]);

  const nameOf = (id: string | null) =>
    id ? (instances.find((instance) => instance.id === id)?.name ?? id) : 'manager';

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-white/[0.07] bg-[#0b0b0d]">
      <div className="flex flex-wrap items-center gap-2 border-b border-white/[0.07] bg-[#101013] px-3 py-2">
        <div className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-rose-500/50" />
          <span className="h-2 w-2 rounded-full bg-amber-500/50" />
          <span className="h-2 w-2 rounded-full bg-emerald-500/50" />
        </div>
        <span className="ml-1 text-[10px] font-medium uppercase tracking-widest text-slate-500">
          Console
        </span>

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2 h-3 w-3 -translate-y-1/2 text-slate-600" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filter…"
              aria-label="Filter log lines"
              className={cn(inputClass, 'h-7 w-32 py-1 pl-7 text-xs')}
            />
          </div>

          <select
            value={level}
            onChange={(event) => setLevel(event.target.value as LogLevel | 'all')}
            aria-label="Filter by level"
            className={cn(inputClass, 'h-7 w-24 py-1 text-xs')}
          >
            <option value="all">All levels</option>
            <option value="success">Success</option>
            <option value="info">Info</option>
            <option value="warn">Warn</option>
            <option value="error">Error</option>
            <option value="debug">Debug</option>
          </select>

          <select
            value={instanceId}
            onChange={(event) => onInstanceChange(event.target.value)}
            aria-label="Filter by instance"
            className={cn(inputClass, 'h-7 max-w-[9rem] py-1 text-xs')}
          >
            <option value="all">All bots</option>
            <option value="">Manager only</option>
            {instances.map((instance) => (
              <option key={instance.id} value={instance.id}>
                {instance.name}
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={() => setFollow((value) => !value)}
            title="Auto-scroll to newest line"
            className={cn(
              'rounded-md border p-1.5 transition-colors',
              follow
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                : 'border-white/10 text-slate-500 hover:text-slate-300',
            )}
          >
            <ArrowDownToLine className="h-3.5 w-3.5" />
          </button>

          <Button variant="ghost" size="sm" onClick={() => void clearLogs()}>
            <Eraser className="h-3.5 w-3.5" /> Clear
          </Button>
        </div>
      </div>

      <div
        ref={scroller}
        onScroll={(event) => {
          const node = event.currentTarget;
          const atBottom = node.scrollHeight - node.scrollTop - node.clientHeight < 40;
          if (atBottom !== follow) setFollow(atBottom);
        }}
        className={cn(
          'min-h-0 flex-1 overflow-y-auto px-3 py-2 font-mono text-[11.5px] leading-relaxed',
          compact ? 'max-h-64' : '',
        )}
      >
        {filtered.length === 0 ? (
          <p className="px-1 py-6 text-center text-xs text-slate-600">
            {logs.length === 0
              ? 'No activity yet. Create a bot and press Start.'
              : 'No lines match the current filters.'}
          </p>
        ) : (
          filtered.map((entry) => (
            <LogLine key={entry.id} entry={entry} name={nameOf(entry.instanceId)} />
          ))
        )}
      </div>

      <div className="flex items-center justify-between border-t border-white/[0.07] bg-[#101013] px-3 py-1.5 text-[10px] text-slate-600">
        <span>
          {filtered.length} / {logs.length} lines
        </span>
        <span className="font-mono uppercase tracking-wider">
          {follow ? 'live · following' : 'live · paused'}
        </span>
      </div>
    </div>
  );
}

function LogLine({ entry, name }: { entry: LogEntry; name: string }) {
  const style = LEVEL_STYLE[entry.level];
  return (
    <div className="flex gap-2 rounded px-1 py-[1px] hover:bg-white/[0.03]">
      <span className="shrink-0 select-none text-slate-600">{formatTime(entry.ts)}</span>
      <span className={cn('w-12 shrink-0 select-none font-semibold', style.className)}>
        {style.label}
      </span>
      <span className="shrink-0 select-none text-slate-600">[{name}]</span>
      <span className="break-words whitespace-pre-wrap text-slate-300">{entry.message}</span>
    </div>
  );
}
