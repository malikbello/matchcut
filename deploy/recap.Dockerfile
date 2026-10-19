# Matchcut render job: makes one fan's cut per run (Azure Container Apps Job, queue-triggered).
# Microsoft's Playwright image brings Chromium and its libraries; ffmpeg encodes and mixes; Mesa's
# llvmpipe renders WebGL on CPU (several times faster than SwiftShader on GPU-less servers).

FROM node:22-slim AS studio
WORKDIR /studio
COPY apps/studio/package.json apps/studio/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY apps/studio/ ./
RUN npm run build

FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1-mesa-dri libegl1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY services services
RUN uv sync --locked --no-dev --package matchcut-recap \
    && /app/.venv/bin/python -m playwright install chromium  # the browser build that matches our locked Playwright
COPY --from=studio /studio/index.html /studio/studio.js /studio/studio.css /app/apps/studio/
COPY --from=studio /studio/fonts /app/apps/studio/fonts
COPY --from=studio /studio/assets /app/apps/studio/assets
COPY --from=studio /studio/dist /app/apps/studio/dist
COPY out/feeds /app/out/feeds
COPY out/insights /app/out/insights
COPY out/calls /app/out/calls
COPY out/media /app/out/media
ENV PATH="/app/.venv/bin:$PATH" MATCHCUT_STUDIO_DIR=/app/apps/studio MATCHCUT_CUES_DIR=/app/out/insights \
    MATCHCUT_FEEDS_DIR=/app/out/feeds MATCHCUT_MEDIA_DIR=/app/out/media MATCHCUT_CALLS_DIR=/app/out/calls \
    MATCHCUT_DATA=/app/out
RUN useradd --uid 10001 --create-home matchcut && chown -R matchcut /app
USER 10001
CMD ["matchcut-recap-job"]
