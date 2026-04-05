# ── Stage 1: Build React frontend ──────────────────────────────────
FROM node:22-slim AS frontend

WORKDIR /build
COPY web/package.json web/package-lock.json* ./
RUN npm ci --ignore-scripts
ARG CACHEBUST=0
COPY web/ ./
RUN npm run build

# ── Stage 2: Python API + built frontend ──────────────────────────
FROM python:3.12.8-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
     ca-certificates git curl zsh ripgrep fd-find unzip vim ncurses-term \
     postgresql-client \
  && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
     -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
     > /etc/apt/sources.list.d/github-cli.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends gh \
  && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
  && apt-get install -y --no-install-recommends nodejs \
  && COREPACK_ENABLE_AUTO_INSTALL=1 corepack enable \
  && npm install -g @anthropic-ai/claude-code \
  # Set zsh as default shell + configure vim as default editor
  && chsh -s /usr/bin/zsh root \
  && rm -rf /var/lib/apt/lists/*

# Pre-install official Claude plugins
RUN git clone --depth=1 https://github.com/anthropics/claude-plugins-official.git /tmp/claude-plugins-src \
  && mkdir -p /opt/claude-plugins \
  && cp -r /tmp/claude-plugins-src/plugins/security-guidance /opt/claude-plugins/ \
  && cp -r /tmp/claude-plugins-src/plugins/code-review /opt/claude-plugins/ \
  && cp -r /tmp/claude-plugins-src/plugins/pr-review-toolkit /opt/claude-plugins/ \
  && cp -r /tmp/claude-plugins-src/plugins/frontend-design /opt/claude-plugins/ \
  && cp -r /tmp/claude-plugins-src/plugins/feature-dev /opt/claude-plugins/ \
  && rm -rf /tmp/claude-plugins-src

# Install custom DeathStar skill plugins
COPY plugins/deathstar-audit /opt/claude-plugins/deathstar-audit
COPY plugins/deathstar-review /opt/claude-plugins/deathstar-review
COPY plugins/deathstar-plan /opt/claude-plugins/deathstar-plan
COPY plugins/deathstar-docs /opt/claude-plugins/deathstar-docs
COPY plugins/deathstar-code /opt/claude-plugins/deathstar-code

# Cache-bust arg: pass --build-arg CACHEBUST=$(date +%s) to force
# re-copy of code layers while keeping heavy dependency layers cached.
ARG CACHEBUST=0

COPY pyproject.toml README.md alembic.ini /app/
COPY cli /app/cli
COPY server /app/server
COPY shared /app/shared
COPY alembic /app/alembic

RUN python -m pip install --upgrade pip \
  && python -m pip install /app

# Copy React build output into the INSTALLED package location
# (pip install puts it in site-packages, not /app/server/)
COPY --from=frontend /build/dist /tmp/web-dist
RUN PKGDIR=$(python -c "from pathlib import Path; import deathstar_server; print(Path(deathstar_server.__file__).parent / 'web' / 'dist')") \
  && mkdir -p "$PKGDIR" \
  && cp -r /tmp/web-dist/* "$PKGDIR/" \
  && rm -rf /tmp/web-dist

# GIT_ASKPASS script — uses GITHUB_TOKEN env var for HTTPS auth
RUN printf '#!/bin/sh\ncase "$1" in\n  *Username*) echo "x-access-token" ;;\n  *Password*) echo "$GITHUB_TOKEN" ;;\nesac\n' \
      > /usr/local/bin/git-askpass-github \
  && chmod +x /usr/local/bin/git-askpass-github
ENV GIT_ASKPASS=/usr/local/bin/git-askpass-github
ENV GIT_TERMINAL_PROMPT=0

# Trust all repos under /workspace (container runs as root, repos may be cloned by other users)
RUN git config --global --add safe.directory '*' \
  && git config --global core.editor vim

EXPOSE 8080

# Entrypoint runs Alembic migrations (idempotent) before starting the app.
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "deathstar_server.main:app", "--host", "0.0.0.0", "--port", "8080"]
