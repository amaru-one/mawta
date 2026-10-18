# Build: install the locked production dependencies (and the service itself,
# non-editable) into a virtualenv with uv.
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# Runtime: the same Python, the virtualenv, a non-root user.
FROM python:3.13-slim
RUN useradd --system --uid 10001 --no-create-home chat
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8001
USER chat
EXPOSE 8001
CMD ["mawta-chat"]
