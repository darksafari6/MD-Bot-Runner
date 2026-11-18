# WhatsApp MD Bot Runner Manager — Python runtime
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    WAMANAGER_DATA_DIR=/data

# libmagic: required by the WhatsApp engine. ffmpeg: media messages.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY wamanager ./wamanager
RUN pip install --no-cache-dir .

# Unprivileged runtime user; /data holds WhatsApp credentials.
RUN useradd --system --uid 10001 --home /app wamanager \
    && mkdir -p /data \
    && chown -R wamanager:wamanager /data
USER wamanager

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request,sys; \
url=f\"http://127.0.0.1:{os.environ.get('PORT','8080')}/api/health\"; \
sys.exit(0 if urllib.request.urlopen(url, timeout=4).status == 200 else 1)"

CMD ["wa", "serve"]
