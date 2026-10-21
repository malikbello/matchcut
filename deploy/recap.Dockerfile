# Matchcut render job: makes one fan's cut per run (Azure Container Apps Job, queue-triggered).
# Chromium's headless shell draws the Studio in render mode; Mesa's llvmpipe renders its WebGL on
# CPU (several times faster than SwiftShader on GPU-less servers); ffmpeg encodes and mixes.
# Only the one browser we use is installed, which keeps the image small and job start-up fast.

# ---------------------------------------------------------------- the Studio's 3D bundle
FROM node:22-slim AS studio
WORKDIR /studio
COPY apps/studio/package.json apps/studio/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY apps/studio/ ./
RUN npm run build

# ---------------------------------------------------------------- the job, from the lockfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY services services
RUN uv sync --locked --no-dev --package matchcut-recap

FROM python:3.12-slim-bookworm
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright PATH="/app/.venv/bin:$PATH"
# the environment first (it changes only with the lockfile; our own packages are installed
# editable), then the heavy system layer, so code changes never re-download the browser or ffmpeg
COPY --from=app /app/.venv /app/.venv
# ffmpeg and Mesa from Debian; the headless shell and exactly the libraries it needs from Playwright
RUN echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/80retries \
    && apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1-mesa-dri libegl1 \
    && /app/.venv/bin/python -m playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/*
COPY --from=app /app/pyproject.toml /app/uv.lock /app/
COPY --from=app /app/packages /app/packages
COPY --from=app /app/services /app/services
WORKDIR /app
COPY --from=studio /studio/index.html /studio/studio.js /studio/studio.css /app/apps/studio/
COPY --from=studio /studio/fonts /app/apps/studio/fonts
COPY --from=studio /studio/assets /app/apps/studio/assets
COPY --from=studio /studio/dist /app/apps/studio/dist
COPY out/feeds /app/out/feeds
COPY out/insights /app/out/insights
COPY out/calls /app/out/calls
COPY out/media /app/out/media
ENV MATCHCUT_STUDIO_DIR=/app/apps/studio MATCHCUT_CUES_DIR=/app/out/insights \
    MATCHCUT_FEEDS_DIR=/app/out/feeds MATCHCUT_MEDIA_DIR=/app/out/media MATCHCUT_CALLS_DIR=/app/out/calls \
    MATCHCUT_DATA=/app/out
RUN useradd --uid 10001 --create-home matchcut
USER 10001
CMD ["matchcut-recap-job"]
