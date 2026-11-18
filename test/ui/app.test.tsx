// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../../src/App';
import { DEFAULT_COMMANDS, DEFAULT_CONFIG, DEFAULT_STATS, type Instance } from '../../shared/types';

const baseInstance: Instance = {
  id: 'support-bot',
  name: 'Support Bot',
  status: 'connected',
  createdAt: new Date('2026-01-01').toISOString(),
  identity: { id: '923001234567@s.whatsapp.net', name: 'Support', number: '923001234567' },
  config: { ...DEFAULT_CONFIG },
  commands: structuredClone(DEFAULT_COMMANDS),
  stats: {
    ...DEFAULT_STATS,
    startedAt: Date.now() - 60_000,
    commandsHandled: 7,
    messagesReceived: 21,
  },
  lastError: null,
};

function mockApi(instances: Instance[]) {
  const state = [...instances];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { 'Content-Type': 'application/json' },
        });

      if (url.endsWith('/api/health')) {
        return json({
          status: 'ok',
          version: '2.0.0',
          uptimeSeconds: 5,
          node: 'v22',
          library: 'Baileys 6.7.24',
          instances: { total: state.length, connected: 1 },
        });
      }
      if (url.endsWith('/api/settings')) {
        return json({
          settings: {
            autostartConnectedInstances: true,
            logRetention: 500,
            commandPrefixDefault: '!',
          },
        });
      }
      if (url.includes('/api/logs/stream')) {
        return json({});
      }
      if (url.includes('/api/logs')) {
        return json({
          logs: [
            {
              id: 'l1',
              instanceId: 'support-bot',
              ts: Date.now(),
              level: 'success',
              source: 'command',
              message: '«ping» replied to 923001234567',
            },
          ],
        });
      }
      if (url.endsWith('/api/instances') && method === 'GET') {
        return json({ instances: state });
      }
      if (url.endsWith('/api/instances') && method === 'POST') {
        const body = JSON.parse(String(init?.body ?? '{}')) as { name: string };
        const created: Instance = {
          ...baseInstance,
          id: 'new-bot',
          name: body.name,
          status: 'stopped',
          identity: null,
          stats: { ...DEFAULT_STATS },
        };
        state.push(created);
        return json({ instance: created }, 201);
      }
      if (url.includes('/stop')) {
        const updated = { ...state[0], status: 'stopped' as const };
        return json({ instance: updated });
      }
      return json({ error: 'not found' }, 404);
    }),
  );
}

describe('App', () => {
  beforeEach(() => {
    localStorage.clear();
    // The shell restores its route from the URL hash, so tests must start clean.
    window.location.hash = '';
  });

  it('renders the dashboard with instance data', async () => {
    mockApi([baseInstance]);
    render(<App />);

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    // The name appears on the card and in the log filter <select>.
    expect((await screen.findAllByText('Support Bot')).length).toBeGreaterThan(0);
    // "Connected" appears in the status pill and the stat card.
    expect((await screen.findAllByText('Connected')).length).toBeGreaterThan(0);
    expect(await screen.findByText('+923001234567')).toBeInTheDocument();
  });

  it('shows the empty state when no bots exist', async () => {
    mockApi([]);
    render(<App />);
    expect(await screen.findByText('No bots yet')).toBeInTheDocument();
    expect(await screen.findByText('Create your first bot')).toBeInTheDocument();
  });

  it('creates a bot through the form', async () => {
    const user = userEvent.setup();
    mockApi([]);
    render(<App />);

    await user.click(await screen.findByRole('button', { name: /new bot/i }));
    const input = await screen.findByPlaceholderText('Support bot');
    await user.type(input, 'Sales Bot');
    await user.click(screen.getByRole('button', { name: /^create$/i }));

    await waitFor(() => expect(screen.getAllByText('Sales Bot').length).toBeGreaterThan(0));
    expect(await screen.findByText(/Created "Sales Bot"/)).toBeInTheDocument();
  });

  it('opens the instance detail view and lives on the commands tab', async () => {
    const user = userEvent.setup();
    mockApi([baseInstance]);
    render(<App />);

    const names = await screen.findAllByText('Support Bot');
    await user.click(names[0]);
    expect(await screen.findByRole('heading', { name: 'Support Bot' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /overview/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^commands$/i }));
    expect(await screen.findByText('Behaviour')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('pong 🏓')).toBeInTheDocument();
  });

  it('stops a running bot from the card', async () => {
    const user = userEvent.setup();
    mockApi([baseInstance]);
    render(<App />);

    await user.click(await screen.findByRole('button', { name: /stop/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /start/i })).toBeInTheDocument());
  });

  it('renders streamed log lines in the console', async () => {
    mockApi([baseInstance]);
    render(<App />);
    expect(await screen.findByText(/«ping» replied to 923001234567/)).toBeInTheDocument();
  });
});
