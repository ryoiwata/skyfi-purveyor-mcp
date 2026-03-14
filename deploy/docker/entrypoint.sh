#!/bin/bash
set -e

# Run Alembic migrations before starting the server.
# For Postgres this applies any pending migrations; for SQLite the server's
# init_db() handles schema creation at startup so we skip it here.
if [[ "${DATABASE_URL:-}" == postgresql* ]]; then
    echo "Running Alembic migrations..."
    /app/.venv/bin/alembic upgrade head
fi

exec /app/.venv/bin/purveyor "$@"
