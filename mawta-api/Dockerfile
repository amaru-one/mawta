# Build: install the locked production dependencies (and the service itself,
# non-editable) into a virtualenv with uv, and fetch the goose CLI so
# migrations can run from the same image (`docker compose run --rm
# --entrypoint /usr/local/bin/goose api up`). goose is a third-party release
# binary; no code of this repo is compiled.
FROM python:3.14-slim AS build
ARG TARGETARCH
ARG GOOSE_VERSION=3.27.3
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN case "${TARGETARCH:-amd64}" in \
      amd64) goose_arch=x86_64 ;; \
      arm64) goose_arch=arm64 ;; \
      *) echo "unsupported arch ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
    && curl -fsSL -o /usr/local/bin/goose \
      "https://github.com/pressly/goose/releases/download/v${GOOSE_VERSION}/goose_linux_${goose_arch}" \
    && chmod +x /usr/local/bin/goose
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# Runtime: the same Python, the virtualenv, ffmpeg (voice notes are transcoded
# on the request path) and the migrations.
FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local/bin/goose /usr/local/bin/goose
COPY --from=build /app/.venv /app/.venv
COPY migrations /app/migrations
WORKDIR /app
# `useradd`, `onboard` and `chatkey` are on PATH too, so
# `docker compose run --rm --entrypoint useradd api ...` keeps working.
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8080
ENTRYPOINT ["mawta-api"]
