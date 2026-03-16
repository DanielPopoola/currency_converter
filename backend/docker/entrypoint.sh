#!/bin/bash
set -e

# entrypoint.sh
# Runs database migrations then hands off to the main process (CMD).
#
# The `depends_on: condition: service_healthy` in docker-compose already
# guarantees Postgres is up before this script runs. The loop below is
# a lightweight extra safety net for edge cases (e.g. local docker restarts).

echo "Waiting for database to be ready..."
until pg_isready -h db -p 5432 -U "${POSTGRES_USER:-postgres}"; do
  echo "  db not ready yet — retrying in 2s..."
  sleep 2
done
echo "Database is ready."

# Apply all pending migrations.
# IMPORTANT: we never run `alembic revision --autogenerate` here.
# Migration *files* are committed to the repo by developers.
# The entrypoint only *applies* them.
echo "Running database migrations..."
alembic upgrade head
echo "Migrations complete."

# Execute whatever command was passed (e.g. uvicorn ...)
exec "$@"
