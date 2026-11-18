import fs from 'node:fs/promises';
import type { Server } from 'node:http';
import os from 'node:os';
import path from 'node:path';
import express from 'express';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { createApi } from '../server/api.js';
import { LogHub } from '../server/logger.js';
import type { BotRuntime } from '../server/runtime.js';
import { Store } from '../server/store.js';

let server: Server;
let baseUrl: string;
let dir: string;

/** The API only needs start/stop/getQr from the runtime for these routes. */
const fakeRuntime = {
  getQr: () => ({ qr: 'qr-payload', pairingCode: null }),
  start: async (id: string) => ({ id, status: 'starting' }),
  stop: async (id: string) => ({ id, status: 'stopped' }),
  liveCount: () => 0,
} as unknown as BotRuntime;

beforeAll(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), 'wamanager-api-'));
  const store = new Store(dir);
  await store.init();
  const app = express();
  app.use('/api', createApi(store, fakeRuntime, new LogHub(200)));

  await new Promise<void>((resolve) => {
    server = app.listen(0, '127.0.0.1', () => resolve());
  });
  const address = server.address();
  baseUrl = `http://127.0.0.1:${typeof address === 'object' && address ? address.port : 0}`;
});

afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
  await fs.rm(dir, { recursive: true, force: true });
});

async function call(pathname: string, init?: RequestInit) {
  const response = await fetch(`${baseUrl}/api${pathname}`, init);
  return { status: response.status, body: (await response.json()) as Record<string, unknown> };
}

describe('API', () => {
  it('serves health without auth', async () => {
    const { status, body } = await call('/health');
    expect(status).toBe(200);
    expect(body.status).toBe('ok');
  });

  it('creates and lists instances', async () => {
    const created = await call('/instances', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'API Bot' }),
    });
    expect(created.status).toBe(201);
    expect((created.body.instance as { id: string }).id).toBe('api-bot');

    const list = await call('/instances');
    expect((list.body.instances as unknown[]).length).toBe(1);
  });

  it('rejects an empty name', async () => {
    const { status, body } = await call('/instances', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: '   ' }),
    });
    expect(status).toBe(400);
    expect(String(body.error)).toMatch(/required/i);
  });

  it('rejects path traversal in ids', async () => {
    const { status } = await call('/instances/..%2f..%2fetc');
    expect(status).toBe(400);
  });

  it('404s unknown instances', async () => {
    const { status } = await call('/instances/does-not-exist');
    expect(status).toBe(404);
  });

  it('validates command names and duplicates', async () => {
    const bad = await call('/instances/api-bot', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ commands: [{ name: 'bad name!', response: 'x' }] }),
    });
    expect(bad.status).toBe(400);

    const duplicate = await call('/instances/api-bot', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        commands: [
          { name: 'hi', response: 'a' },
          { name: 'hi', response: 'b' },
        ],
      }),
    });
    expect(duplicate.status).toBe(400);
  });

  it('saves valid commands', async () => {
    const { status, body } = await call('/instances/api-bot', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ commands: [{ name: 'hours', response: '9 to 5' }] }),
    });
    expect(status).toBe(200);
    const instance = body.instance as { commands: Array<{ name: string }> };
    expect(instance.commands).toEqual([
      { name: 'hours', response: '9 to 5', enabled: true, exact: false },
    ]);
  });

  it('exposes the live QR when starting', async () => {
    const { status, body } = await call('/instances/api-bot/qr');
    expect(status).toBe(200);
    expect(body.qr).toBe('qr-payload');
  });

  it('deletes instances', async () => {
    const { status } = await call('/instances/api-bot', { method: 'DELETE' });
    expect(status).toBe(200);
    const list = await call('/instances');
    expect((list.body.instances as unknown[]).length).toBe(0);
  });

  it('returns 404 for unknown endpoints', async () => {
    const { status } = await call('/nope');
    expect(status).toBe(404);
  });
});
