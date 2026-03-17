# ── Stage 1: Build React frontend ──────────────────────────────────
FROM node:22-slim AS frontend

WORKDIR /build
COPY web/package.json web/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY web/ ./
RUN npm run build

# ── Stage 2: Python API + built frontend ──────────────────────────
FROM python:3.12.8-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates git \
  && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY cli /app/cli
COPY server /app/server
COPY shared /app/shared

RUN python -m pip install --upgrade pip \
  && python -m pip install /app

# Copy React build output into the server's web/dist directory
COPY --from=frontend /build/dist /app/server/deathstar_server/web/dist

RUN useradd -r -s /usr/sbin/nologin deathstar

EXPOSE 8080
USER deathstar

CMD ["uvicorn", "deathstar_server.main:app", "--host", "0.0.0.0", "--port", "8080"]
