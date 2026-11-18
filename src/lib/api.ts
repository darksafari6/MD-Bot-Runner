import type {
  CommandRule,
  HealthPayload,
  Instance,
  InstanceConfig,
  LogEntry,
  ManagerSettings,
} from '../../shared/types';

const TOKEN_KEY = 'wamanager.token';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode — token simply won't persist */
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`/api${path}`, { ...init, headers });
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : null;

  if (!response.ok) {
    const body = payload as { error?: string } | null;
    throw new ApiError(response.status, body?.error ?? `Request failed (${response.status})`);
  }
  return payload as T;
}

/** Unauthenticated probe: tells the UI whether a token is required at all. */
export async function probeAuthRequired(): Promise<boolean> {
  try {
    const response = await fetch('/api/health');
    if (!response.ok) return false;
    const body = (await response.json()) as HealthPayload;
    return Boolean(body.authRequired);
  } catch {
    return false;
  }
}

export const api = {
  health: () => request<HealthPayload>('/health'),

  listInstances: () => request<{ instances: Instance[] }>('/instances').then((r) => r.instances),

  createInstance: (name: string) =>
    request<{ instance: Instance }>('/instances', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }).then((r) => r.instance),

  updateInstance: (
    id: string,
    patch: { name?: string; config?: Partial<InstanceConfig>; commands?: CommandRule[] },
  ) =>
    request<{ instance: Instance }>(`/instances/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }).then((r) => r.instance),

  deleteInstance: (id: string) =>
    request<{ removed: boolean }>(`/instances/${id}`, { method: 'DELETE' }),

  start: (id: string) =>
    request<{ instance: Instance }>(`/instances/${id}/start`, { method: 'POST' }).then(
      (r) => r.instance,
    ),

  stop: (id: string) =>
    request<{ instance: Instance }>(`/instances/${id}/stop`, { method: 'POST' }).then(
      (r) => r.instance,
    ),

  restart: (id: string) =>
    request<{ instance: Instance }>(`/instances/${id}/restart`, { method: 'POST' }).then(
      (r) => r.instance,
    ),

  logout: (id: string) =>
    request<{ instance: Instance }>(`/instances/${id}/logout`, { method: 'POST' }).then(
      (r) => r.instance,
    ),

  getQr: (id: string) =>
    request<{ qr: string | null; pairingCode: string | null; status: string }>(
      `/instances/${id}/qr`,
    ),

  requestPairingCode: (id: string, phoneNumber: string) =>
    request<{ pairingCode: string }>(`/instances/${id}/pairing-code`, {
      method: 'POST',
      body: JSON.stringify({ phoneNumber }),
    }),

  getSettings: () => request<{ settings: ManagerSettings }>('/settings').then((r) => r.settings),

  updateSettings: (patch: Partial<ManagerSettings>) =>
    request<{ settings: ManagerSettings }>('/settings', {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }).then((r) => r.settings),

  getLogs: (limit = 300, instanceId?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (instanceId) params.set('instanceId', instanceId);
    return request<{ logs: LogEntry[] }>(`/logs?${params}`).then((r) => r.logs);
  },

  clearLogs: () => request<{ cleared: boolean }>('/logs/clear', { method: 'POST' }),
};

/** Subscribe to the live log stream (SSE). Returns an unsubscribe function. */
export function subscribeToLogs(
  onEntry: (entry: LogEntry) => void,
  onError?: (error: Error) => void,
): () => void {
  const token = getToken();
  const url = token ? `/api/logs/stream?token=${encodeURIComponent(token)}` : '/api/logs/stream';
  const source = new EventSource(url);

  source.onmessage = (event) => {
    try {
      onEntry(JSON.parse(event.data) as LogEntry);
    } catch {
      /* ignore malformed frames */
    }
  };
  source.onerror = () => {
    // EventSource reconnects on its own; surface it once for UI feedback.
    onError?.(new Error('Live log stream disconnected — retrying'));
  };

  return () => source.close();
}
