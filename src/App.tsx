import React, { useEffect, useState } from 'react';
import {
  Activity,
  Bot,
  KeyRound,
  LayoutDashboard,
  Settings as SettingsIcon,
  X,
} from 'lucide-react';
import { Button, inputClass } from './components/ui';
import { Dashboard, SettingsView } from './views/Dashboard';
import { InstanceDetail } from './views/InstanceDetail';
import { AppProvider, useAppStore } from './state/AppStore';
import { cn } from './lib/utils';

type Route = { view: 'dashboard' } | { view: 'settings' } | { view: 'instance'; id: string };

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}

function Shell() {
  const { needsToken, ready } = useAppStore();

  if (needsToken) return <TokenGate />;

  return (
    <div className="flex h-full flex-col bg-[#08080a]">
      <Nav />
      <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        {ready ? <Routes /> : <BootSkeleton />}
      </main>
      <Toasts />
    </div>
  );
}

function Routes() {
  const { instances } = useAppStore();
  const [route, setRoute] = useState<Route>({ view: 'dashboard' });

  // Keep the URL hash in sync so reloads land on the same bot.
  useEffect(() => {
    const syncFromHash = () => {
      const hash = window.location.hash.replace(/^#\/?/, '');
      if (hash.startsWith('bot/')) {
        setRoute({ view: 'instance', id: hash.slice(4) });
      } else if (hash === 'settings') {
        setRoute({ view: 'settings' });
      } else {
        setRoute({ view: 'dashboard' });
      }
    };
    syncFromHash();
    window.addEventListener('hashchange', syncFromHash);
    return () => window.removeEventListener('hashchange', syncFromHash);
  }, []);

  const navigate = (next: Route) => {
    setRoute(next);
    const hash =
      next.view === 'instance'
        ? `#/bot/${next.id}`
        : next.view === 'settings'
          ? '#/settings'
          : '#/';
    if (window.location.hash !== hash) window.history.replaceState(null, '', hash);
  };

  if (route.view === 'instance') {
    const instance = instances.find((candidate) => candidate.id === route.id);
    if (!instance) {
      return (
        <div className="p-6 text-sm text-slate-400">
          That bot no longer exists.{' '}
          <button
            className="text-emerald-400 underline"
            onClick={() => navigate({ view: 'dashboard' })}
          >
            Back to dashboard
          </button>
        </div>
      );
    }
    return <InstanceDetail instance={instance} onBack={() => navigate({ view: 'dashboard' })} />;
  }

  if (route.view === 'settings') return <SettingsView />;

  return <Dashboard onOpen={(id) => navigate({ view: 'instance', id })} />;
}

function Nav() {
  const { instances } = useAppStore();
  const connected = instances.filter((instance) => instance.status === 'connected').length;

  return (
    <header className="flex h-12 shrink-0 items-center justify-between gap-4 border-b border-white/[0.07] bg-[#0d0d0f] px-4">
      <a href="#/" className="flex items-center gap-2.5">
        <div className="flex h-6 w-6 items-center justify-center rounded-md bg-emerald-500 shadow-[0_0_12px_rgba(16,185,129,0.4)]">
          <Bot className="h-3.5 w-3.5 text-black" />
        </div>
        <span className="text-[13px] font-semibold tracking-tight text-slate-200">
          WhatsApp MD <span className="text-emerald-400">Bot Runner</span>
        </span>
      </a>

      <div className="flex items-center gap-3">
        <span className="hidden items-center gap-1.5 rounded-full border border-white/[0.07] bg-black/30 px-2.5 py-1 text-[11px] text-slate-400 sm:flex">
          <Activity className="h-3 w-3 text-emerald-400" />
          {connected} connected
        </span>
        <nav className="flex items-center gap-1">
          <a
            href="#/"
            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-slate-400 transition-colors hover:bg-white/5 hover:text-white"
          >
            <LayoutDashboard className="h-3.5 w-3.5" /> Dashboard
          </a>
          <a
            href="#/settings"
            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-slate-400 transition-colors hover:bg-white/5 hover:text-white"
          >
            <SettingsIcon className="h-3.5 w-3.5" /> Settings
          </a>
        </nav>
      </div>
    </header>
  );
}

function TokenGate() {
  const { login, notify } = useAppStore();
  const [token, setValue] = useState('');
  const [checking, setChecking] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setChecking(true);
    const ok = await login(token);
    setChecking(false);
    if (!ok) notify('Invalid token', 'error');
  };

  return (
    <div className="flex h-full items-center justify-center bg-[#08080a] p-6">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-2xl border border-white/[0.07] bg-[#101013] p-6 shadow-2xl"
      >
        <div className="mb-5 flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
            <KeyRound className="h-4 w-4" />
          </div>
          <div>
            <h1 className="text-sm font-semibold text-white">Manager locked</h1>
            <p className="text-xs text-slate-500">Enter the API token configured in .env</p>
          </div>
        </div>
        <input
          autoFocus
          type="password"
          value={token}
          onChange={(event) => setValue(event.target.value)}
          placeholder="API_TOKEN"
          className={inputClass}
        />
        <Button type="submit" variant="primary" className="mt-3 w-full" loading={checking}>
          Unlock
        </Button>
        <p className="mt-3 text-[11px] text-slate-600">
          The token is stored in this browser only. Leave API_TOKEN unset for loopback-only use.
        </p>
      </form>
    </div>
  );
}

function Toasts() {
  const { toasts, dismissToast } = useAppStore();
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-72 flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={cn(
            'pointer-events-auto flex items-start gap-2 rounded-lg border px-3 py-2 text-xs shadow-lg backdrop-blur',
            toast.tone === 'error'
              ? 'border-rose-500/30 bg-rose-950/80 text-rose-200'
              : toast.tone === 'success'
                ? 'border-emerald-500/30 bg-emerald-950/80 text-emerald-200'
                : 'border-white/10 bg-slate-900/90 text-slate-200',
          )}
        >
          <span className="flex-1">{toast.message}</span>
          <button
            onClick={() => dismissToast(toast.id)}
            aria-label="Dismiss"
            className="text-current opacity-50 hover:opacity-100"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      ))}
    </div>
  );
}

function BootSkeleton() {
  return (
    <div className="flex flex-1 flex-col gap-4 p-6">
      <div className="h-6 w-40 animate-pulse rounded bg-white/5" />
      <div className="grid gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((key) => (
          <div key={key} className="h-16 animate-pulse rounded-xl bg-white/5" />
        ))}
      </div>
      <div className="h-64 animate-pulse rounded-xl bg-white/5" />
    </div>
  );
}
