#!/usr/bin/env node
/**
 * One-command development environment:
 *   API  → http://localhost:3001 (tsx watch, real Baileys runtime)
 *   UI   → http://localhost:5173 (Vite dev server, proxies /api to the API)
 *
 * Both bind to 0.0.0.0 so the sandbox/live preview can reach them.
 */
import { spawn } from 'node:child_process';

const children = [];
let shuttingDown = false;

function run(command, args, name) {
  const child = spawn(command, args, { stdio: 'inherit', shell: false });
  child.on('exit', (code) => {
    if (shuttingDown) return;
    console.error(`[dev] ${name} exited with code ${code}`);
    shutdown(code ?? 1);
  });
  children.push(child);
  return child;
}

function shutdown(code) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) child.kill('SIGTERM');
  }
  setTimeout(() => process.exit(code), 300);
}

process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));

run('npx', ['tsx', 'watch', 'server/index.ts'], 'api');
run('npx', ['vite'], 'ui');
