import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { Instance, LogEntry, ManagerSettings } from '../../shared/types';
import { ApiError, api, getToken, probeAuthRequired, setToken, subscribeToLogs } from '../lib/api';

const MAX_LOG_LINES = 1000;
const POLL_MS = 4000;

interface Toast {
  id: string;
  tone: 'info' | 'success' | 'error';
  message: string;
}

interface AppStoreValue {
  ready: boolean;
  loading: boolean;
  needsToken: boolean;
  connectionLost: boolean;
  instances: Instance[];
  logs: LogEntry[];
  settings: ManagerSettings | null;
  version: string | null;
  toasts: Toast[];
  logFilter: string | 'all';
  setLogFilter: (value: string | 'all') => void;
  login: (token: string) => Promise<boolean>;
  refresh: () => Promise<void>;
  clearLogs: () => Promise<void>;
  notify: (message: string, tone?: Toast['tone']) => void;
  dismissToast: (id: string) => void;
  actions: {
    create: (name: string) => Promise<void>;
    remove: (id: string) => Promise<void>;
    start: (id: string) => Promise<void>;
    stop: (id: string) => Promise<void>;
    restart: (id: string) => Promise<void>;
    logout: (id: string) => Promise<void>;
    saveConfig: (id: string, patch: Parameters<typeof api.updateInstance>[1]) => Promise<void>;
    updateSettings: (patch: Partial<ManagerSettings>) => Promise<void>;
  };
}

const AppStore = createContext<AppStoreValue | undefined>(undefined);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(false);
  const [needsToken, setNeedsToken] = useState(false);
  const [connectionLost, setConnectionLost] = useState(false);
  const [instances, setInstances] = useState<Instance[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [settings, setSettings] = useState<ManagerSettings | null>(null);
  const [version, setVersion] = useState<string | null>(null);
  const [logFilter, setLogFilter] = useState<string | 'all'>('all');
  const [toasts, setToasts] = useState<Toast[]>([]);
  const pollRef = useRef<number | null>(null);

  const notify = useCallback((message: string, tone: Toast['tone'] = 'info') => {
    const id = crypto.randomUUID();
    setToasts((prev) => [...prev.slice(-2), { id, tone, message }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((toast) => toast.id !== id));
    }, 5000);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  const handleError = useCallback(
    (err: unknown) => {
      if (err instanceof ApiError && err.status === 401) {
        setNeedsToken(true);
        return;
      }
      notify(err instanceof Error ? err.message : 'Unexpected error', 'error');
    },
    [notify],
  );

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [health, list, currentSettings] = await Promise.all([
        api.health(),
        api.listInstances(),
        api.getSettings(),
      ]);
      setVersion(health.version);
      setInstances(list);
      setSettings(currentSettings);
      setConnectionLost(false);
      setNeedsToken(false);
    } catch (err) {
      handleError(err);
      setConnectionLost(true);
    } finally {
      setLoading(false);
      setReady(true);
    }
  }, [handleError]);

  const login = useCallback(
    async (token: string) => {
      setToken(token.trim());
      try {
        await api.health();
        setNeedsToken(false);
        await refresh();
        return true;
      } catch {
        setToken(null);
        setNeedsToken(true);
        notify('That token was rejected', 'error');
        return false;
      }
    },
    [notify, refresh],
  );

  // Initial load. If the server requires a token and we have none, show the
  // gate immediately instead of waiting for a failing request.
  useEffect(() => {
    void (async () => {
      if (!getToken() && (await probeAuthRequired())) {
        setNeedsToken(true);
        setReady(true);
        return;
      }
      await refresh();
    })();
  }, [refresh]);

  // Poll for status changes made outside this tab (reconnects, QR expiry…).
  useEffect(() => {
    if (needsToken) return;
    pollRef.current = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      api
        .listInstances()
        .then((list) => {
          setInstances(list);
          setConnectionLost(false);
        })
        .catch(() => setConnectionLost(true));
    }, POLL_MS);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [needsToken]);

  // Seed logs once, then switch to the live stream.
  useEffect(() => {
    if (needsToken) return;
    let cancelled = false;
    api
      .getLogs(300)
      .then((entries) => {
        if (!cancelled) setLogs(entries.slice(-MAX_LOG_LINES));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [needsToken]);

  useEffect(() => {
    if (needsToken) return;
    const unsubscribe = subscribeToLogs((entry) => {
      setLogs((prev) => {
        const next = [...prev, entry];
        return next.length > MAX_LOG_LINES ? next.slice(next.length - MAX_LOG_LINES) : next;
      });
    });
    return unsubscribe;
  }, [needsToken]);

  const replaceInstance = useCallback((instance: Instance) => {
    setInstances((prev) => {
      const index = prev.findIndex((candidate) => candidate.id === instance.id);
      if (index === -1) return [...prev, instance];
      const next = [...prev];
      next[index] = instance;
      return next;
    });
  }, []);

  const run = useCallback(
    async (task: () => Promise<unknown>) => {
      try {
        await task();
      } catch (err) {
        handleError(err);
      }
    },
    [handleError],
  );

  const actions = useMemo<AppStoreValue['actions']>(
    () => ({
      create: (name) =>
        run(async () => {
          const instance = await api.createInstance(name);
          replaceInstance(instance);
          notify(`Created "${instance.name}"`, 'success');
        }),
      remove: (id) =>
        run(async () => {
          await api.deleteInstance(id);
          setInstances((prev) => prev.filter((instance) => instance.id !== id));
          notify('Instance deleted', 'success');
        }),
      start: (id) =>
        run(async () => {
          const instance = await api.start(id);
          replaceInstance(instance);
        }),
      stop: (id) =>
        run(async () => {
          const instance = await api.stop(id);
          replaceInstance(instance);
        }),
      restart: (id) =>
        run(async () => {
          const instance = await api.restart(id);
          replaceInstance(instance);
        }),
      logout: (id) =>
        run(async () => {
          const instance = await api.logout(id);
          replaceInstance(instance);
          notify('Device unlinked and session cleared', 'success');
        }),
      saveConfig: (id, patch) =>
        run(async () => {
          const instance = await api.updateInstance(id, patch);
          replaceInstance(instance);
          notify('Settings saved', 'success');
        }),
      updateSettings: (patch) =>
        run(async () => {
          const next = await api.updateSettings(patch);
          setSettings(next);
        }),
    }),
    [notify, replaceInstance, run],
  );

  const clearLogs = useCallback(async () => {
    await run(async () => {
      await api.clearLogs();
      setLogs([]);
    });
  }, [run]);

  const value: AppStoreValue = {
    ready,
    loading,
    needsToken,
    connectionLost,
    instances,
    logs,
    settings,
    version,
    toasts,
    logFilter,
    setLogFilter,
    login,
    refresh,
    clearLogs,
    notify,
    dismissToast,
    actions,
  };

  return <AppStore.Provider value={value}>{children}</AppStore.Provider>;
}

export function useAppStore(): AppStoreValue {
  const context = useContext(AppStore);
  if (!context) throw new Error('useAppStore must be used inside <AppProvider>');
  return context;
}

export function useInstance(id: string | null): Instance | null {
  const { instances } = useAppStore();
  if (!id) return null;
  return instances.find((instance) => instance.id === id) ?? null;
}
