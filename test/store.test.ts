import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Store, isValidInstanceId, normalizeInstance, slugify } from '../server/store.js';

let dir: string;

beforeEach(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), 'wamanager-store-'));
});

afterEach(async () => {
  await fs.rm(dir, { recursive: true, force: true });
});

describe('slugify', () => {
  it('produces url-safe ids', () => {
    expect(slugify('Support Bot #1')).toBe('support-bot-1');
    expect(slugify('  ')).toBe('bot');
    expect(slugify('Ünïcode Böt')).toBe('unicode-bot');
  });
});

describe('isValidInstanceId', () => {
  it('accepts slugs and rejects traversal attempts', () => {
    expect(isValidInstanceId('support-bot')).toBe(true);
    expect(isValidInstanceId('../etc')).toBe(false);
    expect(isValidInstanceId('a')).toBe(false);
    expect(isValidInstanceId('has space')).toBe(false);
  });
});

describe('normalizeInstance', () => {
  it('fills defaults and sanitises numbers', () => {
    const instance = normalizeInstance({
      id: 'x',
      config: {
        commandPrefix: '  !!extra  ',
        allowedNumbers: ['+92 300-1234567', '123', 'abc'],
      } as never,
    });
    expect(instance.config.commandPrefix).toBe('!!e'.slice(0, 3));
    expect(instance.config.allowedNumbers).toEqual(['923001234567']);
    expect(instance.commands.length).toBeGreaterThan(0);
  });

  it('falls back to default prefix when blank', () => {
    const instance = normalizeInstance({ id: 'x', config: { commandPrefix: '   ' } as never });
    expect(instance.config.commandPrefix).toBe('!');
  });

  it('drops malformed command rules', () => {
    const instance = normalizeInstance({
      id: 'x',
      commands: [
        { name: 'ok', response: 'yes', enabled: true },
        { name: '', response: 'orphan', enabled: true },
        { name: 'empty', response: '', enabled: true },
      ] as never,
    });
    expect(instance.commands.map((rule) => rule.name)).toEqual(['ok']);
  });
});

describe('Store', () => {
  it('creates unique ids for duplicate names', async () => {
    const store = new Store(dir);
    await store.init();
    const first = await store.create('Support Bot');
    const second = await store.create('Support Bot');
    expect(first.id).toBe('support-bot');
    expect(second.id).not.toBe(first.id);
  });

  it('persists across instances', async () => {
    const store = new Store(dir);
    await store.init();
    await store.create('Persisted');
    await store.patchConfig('persisted', { respondToDms: false });

    const reopened = new Store(dir);
    await reopened.init();
    expect(reopened.list()).toHaveLength(1);
    expect(reopened.get('persisted')?.config.respondToDms).toBe(false);
  });

  it('survives corrupted state by backing it up', async () => {
    await fs.writeFile(path.join(dir, 'state.json'), '{not json', 'utf8');
    const store = new Store(dir);
    await store.init();
    expect(store.list()).toEqual([]);
    const files = await fs.readdir(dir);
    expect(files.some((file) => file.includes('corrupt'))).toBe(true);
  });

  it('removes instances', async () => {
    const store = new Store(dir);
    await store.init();
    await store.create('Temp');
    expect(await store.remove('temp')).toBe(true);
    expect(await store.remove('temp')).toBe(false);
    expect(store.list()).toHaveLength(0);
  });

  it('clamps log retention settings', async () => {
    const store = new Store(dir);
    await store.init();
    const settings = await store.updateSettings({ logRetention: 42 });
    expect(settings.logRetention).toBe(42);
  });
});
