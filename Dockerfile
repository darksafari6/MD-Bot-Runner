# Container image for App Host.
#
# Node and Python live in the same image because the host runs JavaScript
# projects: the panel is Python, the apps it supervises are Node.
FROM node:20-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip git tar ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY apphost ./apphost
COPY scripts ./scripts

RUN python3 -m venv /opt/apphost \
 && /opt/apphost/bin/pip install --no-cache-dir --upgrade pip \
 && /opt/apphost/bin/pip install --no-cache-dir . \
 && rm -rf /root/.cache

# Run unprivileged; 10001 matches the compose file.
RUN useradd --uid 10001 --create-home --shell /bin/bash apphost \
 && mkdir -p /data \
 && chown -R apphost:apphost /data /app
USER 10001

ENV APPHOST_HOST=0.0.0.0 \
    APPHOST_PORT=8080 \
    APPHOST_DATA_DIR=/data \
    APPHOST_TOKEN= \
    PATH=/opt/apphost/bin:$PATH \
    NPM_CONFIG_UPDATE_NOTIFIER=false

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

CMD ["apphost", "serve"]
