# ---- build stage -----------------------------------------------------------
FROM node:22-bookworm-slim AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build && npm prune --omit=dev

# ---- runtime stage ---------------------------------------------------------
FROM node:22-bookworm-slim AS runtime
ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3001 \
    WAMANAGER_DATA_DIR=/data

WORKDIR /app

# Run unprivileged; /data holds WhatsApp credentials, so it must be a volume.
RUN useradd --system --uid 10001 --home /app wamanager \
    && mkdir -p /data && chown -R wamanager:wamanager /data

COPY --from=build --chown=wamanager:wamanager /app/node_modules ./node_modules
COPY --from=build --chown=wamanager:wamanager /app/dist ./dist
COPY --from=build --chown=wamanager:wamanager /app/dist-server ./dist-server
COPY --from=build --chown=wamanager:wamanager /app/package.json ./package.json

USER wamanager
VOLUME ["/data"]
EXPOSE 3001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||3001)+'/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "dist-server/index.js"]
