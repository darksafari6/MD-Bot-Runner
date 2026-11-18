import fs from 'node:fs';
import path from 'node:path';
import express from 'express';
import { createApi } from './api.js';
import { config } from './config.js';
import { LogHub } from './logger.js';
import { BotRuntime } from './runtime.js';
import { Store } from './store.js';

async function main(): Promise<void> {
  const hub = new LogHub(config.logBuffer);
  const store = new Store(config.dataDir);
  await store.init();

  const runtime = new BotRuntime(store, hub, {
    onChange: () => {
      /* store already persisted; SSE log stream carries user-facing updates */
    },
  });

  const app = express();
  app.disable('x-powered-by');
  app.set('trust proxy', true);

  if (config.corsOrigins.length > 0) {
    app.use((req, res, next) => {
      const origin = req.get('origin');
      if (origin && config.corsOrigins.includes(origin)) {
        res.setHeader('Access-Control-Allow-Origin', origin);
        res.setHeader('Vary', 'Origin');
        res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
        res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PATCH, DELETE, OPTIONS');
      }
      if (req.method === 'OPTIONS') {
        res.sendStatus(204);
        return;
      }
      next();
    });
  }

  app.use('/api', createApi(store, runtime, hub));

  const indexFile = path.join(config.staticDir, 'index.html');
  if (fs.existsSync(indexFile)) {
    app.use(
      express.static(config.staticDir, {
        index: false,
        setHeaders: (res, filePath) => {
          if (/\.(js|css|woff2?)$/.test(filePath)) {
            res.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
          }
        },
      }),
    );
    // SPA fallback — every non-API route renders the panel.
    app.get('*', (_req, res) => {
      res.sendFile(indexFile);
    });
  } else {
    app.get('/', (_req, res) => {
      res
        .status(503)
        .type('text/plain')
        .send(
          'UI bundle not found. Run "npm run build" first (or "npm run dev" for hot reload).\n',
        );
    });
  }

  const server = app.listen(config.port, config.host, () => {
    hub.info(`Manager listening on http://${config.host}:${config.port}`);
    hub.info(`Data directory: ${config.dataDir}`);
    if (!config.authRequired) {
      hub.warn(
        'No API_TOKEN set — the control panel is unauthenticated. Bind to 127.0.0.1 or set a token before exposing it.',
      );
    }
  });

  server.on('error', (err: NodeJS.ErrnoException) => {
    if (err.code === 'EADDRINUSE') {
      console.error(`Port ${config.port} is already in use. Set PORT to another value.`);
    } else {
      console.error('Server error:', err);
    }
    process.exit(1);
  });

  if (store.settings.autostartConnectedInstances) {
    const resumable = store
      .list()
      .filter((instance) => ['connected', 'reconnecting', 'starting'].includes(instance.status));
    for (const instance of resumable) {
      hub.info(`Resuming "${instance.name}" after restart`, instance.id);
      await runtime.start(instance.id).catch(() => {});
    }
  }

  let shuttingDown = false;
  const shutdown = async (signal: string) => {
    if (shuttingDown) return;
    shuttingDown = true;
    console.log(`\n${signal} received — closing ${runtime.liveCount()} bot connection(s)…`);
    server.close();
    await runtime.stopAll();
    await store.flush();
    process.exit(0);
  };

  process.on('SIGINT', () => void shutdown('SIGINT'));
  process.on('SIGTERM', () => void shutdown('SIGTERM'));
  process.on('unhandledRejection', (reason) => {
    hub.error(`Unhandled rejection: ${reason instanceof Error ? reason.message : String(reason)}`);
  });
  process.on('uncaughtException', (err) => {
    hub.error(`Uncaught exception: ${err.message}`);
    void shutdown('uncaughtException');
  });
}

main().catch((err) => {
  console.error('Fatal startup error:', err);
  process.exit(1);
});
