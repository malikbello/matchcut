# Matchcut API and Studio: one container serving the Studio, its 3D bundle, the match data and the API.
# Built in Azure (az acr build), so no local Docker is needed.

# ---------------------------------------------------------------- the Studio's 3D bundle
FROM node:22-slim AS studio
WORKDIR /studio
COPY apps/studio/package.json apps/studio/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY apps/studio/ ./
RUN npm run build

# ---------------------------------------------------------------- the API, from the lockfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY services services
RUN uv sync --locked --no-dev --package matchcut-api

FROM python:3.12-slim-bookworm
RUN useradd --uid 10001 --create-home matchcut
WORKDIR /app
COPY --from=app /app /app
# the Studio: page, styles, fonts, assets (CC0 and the licensed private library) and the bundle
COPY --from=studio /studio/index.html /studio/studio.js /studio/studio.css /app/apps/studio/
COPY --from=studio /studio/fonts /app/apps/studio/fonts
COPY --from=studio /studio/assets /app/apps/studio/assets
COPY --from=studio /studio/dist /app/apps/studio/dist
# the showcase match: tracking feed, verified cues, play-by-play calls and their voices
COPY out/feeds /app/out/feeds
COPY out/insights /app/out/insights
COPY out/calls /app/out/calls
COPY out/media /app/out/media
ENV PATH="/app/.venv/bin:$PATH" HOST=0.0.0.0 PORT=8080 MATCHCUT_STUDIO_DIR=/app/apps/studio
USER 10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["matchcut-api"]
