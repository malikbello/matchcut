# Matchcut API and Studio: one container serving the Studio, its 3D bundle, the match data and the API.
# Built with Docker and pushed to the registry (deploy/deploy.sh describes the release).

# ---------------------------------------------------------------- the Studio's 3D bundle
FROM node:22-slim AS studio
WORKDIR /studio
COPY apps/studio/package.json apps/studio/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY apps/studio/ ./
RUN npm run build

# ---------------------------------------------------------------- the API, from the lockfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS app
# downloads are kept in a build cache: a code change reinstalls from it without the network, and
# a slow connection gets 5 minutes per file (a retry keeps every file that already arrived)
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_HTTP_TIMEOUT=300
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY services services
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --package matchcut-api

FROM python:3.12-slim-bookworm
# ffmpeg: fan cuts are assembled here from pre-rendered pieces (a lossless join and a sound mix)
RUN echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80retries     && apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --create-home matchcut
WORKDIR /app
COPY --from=app /app /app
# the Studio: page, styles, fonts, assets (CC0 and the licensed private library) and the bundle
COPY --from=studio /studio/index.html /studio/studio.js /studio/studio.css /app/apps/studio/
COPY --from=studio /studio/factory.html /studio/factory.js /studio/factory.css /app/apps/studio/
COPY --from=studio /studio/fonts /app/apps/studio/fonts
COPY --from=studio /studio/assets /app/apps/studio/assets
COPY --from=studio /studio/dist /app/apps/studio/dist
# the showcase match: tracking feed, verified cues, play-by-play calls and their voices
COPY out/feeds /app/out/feeds
COPY out/insights /app/out/insights
COPY out/calls /app/out/calls
COPY out/describe /app/out/describe
COPY out/media /app/out/media
ENV PATH="/app/.venv/bin:$PATH" HOST=0.0.0.0 PORT=8080 MATCHCUT_STUDIO_DIR=/app/apps/studio
USER 10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["matchcut-api"]
