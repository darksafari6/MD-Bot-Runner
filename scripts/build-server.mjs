#!/usr/bin/env node
/**
 * Bundles the TypeScript server into a single ESM file for `npm start`.
 * Baileys is left external: it ships native/JSON assets that must stay in
 * node_modules, and bundling it breaks protobuf loading.
 */
import { build } from 'esbuild';

await build({
  entryPoints: ['server/index.ts'],
  outfile: 'dist-server/index.js',
  bundle: true,
  platform: 'node',
  target: 'node20',
  format: 'esm',
  sourcemap: true,
  minify: false,
  packages: 'external',
  banner: {
    js: "import { createRequire as __createRequire } from 'node:module';\nconst require = __createRequire(import.meta.url);",
  },
  logLevel: 'info',
});
