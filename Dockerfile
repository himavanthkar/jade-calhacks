# JADE in one container: the React UI built with bun, served by the FastAPI app with its API under /api.
# Needs DATABASE_URL (Postgres 16); seeds itself on first start (deploy/start.sh).

FROM oven/bun:1.2 AS ui
WORKDIR /ui
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/ ./
ENV VITE_API_MODE=http VITE_API_BASE_URL=/api
RUN bun run build

FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.10.7 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
COPY --from=ui /ui/dist ./frontend/dist
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 TPA_HUMANS=inbox
EXPOSE 8000
CMD ["sh", "deploy/start.sh"]
