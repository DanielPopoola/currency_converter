#!/bin/bash

# Wait for the database to be ready
# This is a simple loop, a more robust solution would use a tool like wait-for-it.sh
until pg_isready -h db -p 5432 -U postgres; do
  echo "Waiting for database..."
  sleep 2
done

alembic revision --autogenerate -m "init tables"
# Run Alembic migrations
alembic upgrade head

# Start the application
exec "$@"
