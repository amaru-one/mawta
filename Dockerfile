# One image for the whole school: the API, the worker, the agents and the director chat (`mawta`),
# the migrations (`alembic upgrade head`, run by the compose service `migrate` before the app
# starts), and the admin commands `onboard` and `useradd`.

# Build: the locked production dependencies and the project itself (non-editable) into a venv.
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# Runtime: the same Python, the venv, ffmpeg (voice notes are transcoded on the request path) and
# what Alembic reads.
FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin mawta \
    && mkdir -p /data/audio && chown mawta /data/audio
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini /app/alembic.ini
COPY migrations /app/migrations
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 STORAGE_DIR=/data/audio
USER mawta
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"]
CMD ["mawta"]
