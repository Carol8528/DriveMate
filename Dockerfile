FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM node:22-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    DRIVEMATE_FRONTEND_URL=http://127.0.0.1:7860 \
    DRIVEMATE_FRONTEND_HOST=0.0.0.0 \
    DRIVEMATE_SKIP_FRONTEND_BUILD=1 \
    DRIVEMATE_NO_BROWSER=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python3 -m venv /opt/venv \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=node:node . .
COPY --from=frontend-builder --chown=node:node /build/frontend/dist ./frontend/dist

USER node
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health', timeout=2).read()" || exit 1

CMD ["python", "start_demo.py"]
