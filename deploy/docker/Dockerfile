# Stage 1: Build — install dependencies with uv
FROM python:3.11-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency specs first for layer caching
COPY pyproject.toml ./
COPY src/ ./src/
COPY README.md ./

# Install all dependencies into the virtual environment
RUN uv sync --no-dev

# Stage 2: Runtime — minimal image with non-root user
FROM python:3.11-slim AS runtime

# Security: run as non-root
RUN groupadd --gid 1001 purveyor && \
    useradd --uid 1001 --gid purveyor --shell /bin/bash --create-home purveyor

# Install uv for runtime commands
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the virtualenv from builder
COPY --from=builder --chown=purveyor:purveyor /app/.venv ./.venv
COPY --from=builder --chown=purveyor:purveyor /app/src ./src
COPY --from=builder --chown=purveyor:purveyor /app/pyproject.toml ./pyproject.toml
COPY --chown=purveyor:purveyor alembic/ ./alembic/
COPY --chown=purveyor:purveyor alembic.ini ./alembic.ini

# Create data directory for SQLite (local mode)
RUN mkdir -p /app/data && chown purveyor:purveyor /app/data

USER purveyor

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["uv", "run", "purveyor"]
CMD ["serve"]
