# Deployment Guide

How to deploy and operate the Currency Converter API in production.

---

## Table of Contents

1. [Overview](#overview)
2. [Docker Images](#docker-images)
3. [CI/CD Pipeline](#cicd-pipeline)
4. [Environment Configuration](#environment-configuration)
5. [Database Migrations in Production](#database-migrations-in-production)
6. [Health Monitoring](#health-monitoring)
7. [Operational Runbook](#operational-runbook)

---

## Overview

The service consists of four components, all containerised:

| Component | Image | Port |
|-----------|-------|------|
| PostgreSQL 15 | `postgres:15` | 5432 |
| Redis 7 | `redis:7-alpine` | 6379 |
| FastAPI Backend | `ghcr.io/danielpopoola/currency-converter-backend` | 8000 |
| React Frontend | `ghcr.io/danielpopoola/currency-converter-frontend` | 80 |

The backend is stateless — only the database and Redis hold state. The frontend is a static SPA served by Nginx.

---

## Docker Images

Images are published to GitHub Container Registry on every merge to `master`.

### Tags

| Tag | Meaning |
|-----|---------|
| `latest` | Most recent successful build from `master` |
| `{git-sha}` | Immutable build for a specific commit (use for rollbacks) |

```bash
# Pull latest
docker pull ghcr.io/danielpopoola/currency-converter-backend:latest
docker pull ghcr.io/danielpopoola/currency-converter-frontend:latest

# Pull a specific version (preferred for production deployments)
docker pull ghcr.io/danielpopoola/currency-converter-backend:abc1234
```

### Frontend build argument

The frontend image requires `VITE_API_URL` at **build time**, not runtime:

```bash
docker build \
  --build-arg VITE_API_URL=https://api.yourdomain.com \
  -t currency-converter-frontend \
  ./frontend
```

If you change the API URL, you must rebuild and redeploy the frontend image.

---

## CI/CD Pipeline

The GitHub Actions workflow (`.github/workflows/main.yml`) runs on every push and pull request to `master`.

### Jobs

#### `backend-lint-and-test`

Runs on every push and PR:

1. Starts Postgres 15 and Redis 6 as service containers.
2. Installs Python 3.12 and `uv`.
3. Installs dependencies via `uv pip install --system -e .`.
4. Runs `ruff check .`.
5. Runs `alembic upgrade head` against the test database.
6. Runs `pytest`.

The test database credentials are hardcoded in the workflow (`user:password@localhost:5432/testdb`) — these are ephemeral CI containers and do not represent production credentials.

#### `frontend-build`

Runs on every push and PR:

1. Installs Node 20.
2. Installs dependencies via `npm ci`.
3. Runs `npm run build`.

Build output is not uploaded as an artifact (the Docker build step handles this).

#### `build-and-push`

Runs **only on pushes to `master`**, after both above jobs pass:

1. Logs into GitHub Container Registry using `GITHUB_TOKEN` (no secrets to configure).
2. Normalises the repository name to lowercase (GHCR requirement).
3. Builds the backend image from `./backend` using `./backend/Dockerfile`.
4. Builds the frontend image from `./frontend` using `./frontend/Dockerfile`.
5. Pushes both images tagged with `{git-sha}` and `latest`.

The matrix strategy runs backend and frontend builds in parallel, halving build time.

### Required secrets

No additional secrets are needed. The workflow uses the auto-provided `GITHUB_TOKEN` for GHCR authentication.

### Permissions

The workflow requires these repository permissions (set in the workflow file):

```yaml
permissions:
  contents: read
  packages: write
```

---

## Environment Configuration

### Required variables

These must be set in production. There are no usable defaults.

| Variable | Description |
|----------|-------------|
| `FIXERIO_API_KEY` | Fixer.io API key |
| `OPENEXCHANGE_APP_ID` | OpenExchangeRates App ID |
| `CURRENCYAPI_KEY` | CurrencyAPI key |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host:5432/dbname` |
| `REDIS_URL` | `redis://host:6379/0` |
| `POSTGRES_USER` | PostgreSQL username (used by the `db` service) |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `POSTGRES_DB` | PostgreSQL database name |

### Recommended production values

```env
DEBUG=false
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
LOG_LEVEL=INFO
LOG_FORMAT=json
```

### Docker Compose environment injection

In `docker/docker-compose.yml`, the `api` service overrides `DATABASE_URL` and `REDIS_URL` to use container hostnames, regardless of what is in `.env`:

```yaml
environment:
  DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}
  REDIS_URL: redis://redis:6379/0
```

This means the `.env` file values for these two variables are only used when running the API directly on the host (outside Docker).

---

## Database Migrations in Production

Migrations are applied automatically on container start via `docker/entrypoint.sh`:

```bash
# entrypoint.sh runs before uvicorn starts
alembic upgrade head   # applies any pending migrations, no-op if up to date
```

This is safe to run on every deployment because `alembic upgrade head` is idempotent when no new migrations exist.

### Rolling back a migration

```bash
# Connect to the running container
docker exec -it currency-converter-api bash

# Roll back one step
alembic downgrade -1

# Check current state
alembic current
```

### Running migrations manually (outside the container)

```bash
export DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/dbname"
cd backend
alembic upgrade head
```

---

## Health Monitoring

### `/api/health` endpoint

Poll this endpoint from your uptime monitor:

```bash
curl https://api.yourdomain.com/api/health
```

Response codes:
- `200` with `{"status": "healthy"}` — all providers operational
- `200` with `{"status": "degraded"}` — one or more providers down (conversions still work)
- `5xx` — the API itself is unavailable

**Recommendation:** Alert on `5xx`. Accept `degraded` as a warning (not a page). Page on `5xx` or `healthy_providers == 0`.

### Container health checks

Both `db` and `redis` services have `healthcheck` blocks in `docker-compose.yml`. The `api` service uses `depends_on: condition: service_healthy` to ensure Postgres and Redis are accepting connections before the API starts.

The entrypoint script adds a second-level poll (`pg_isready` loop) as a safety net for edge cases (e.g. slow Docker bridge network initialisation).

### Key log events

| Log message | Level | Meaning |
|-------------|-------|---------|
| `"Dependencies initialized"` | INFO | Startup successful; DB, Redis, and providers are ready |
| `"Application ready"` | INFO | Bootstrap complete; server is accepting requests |
| `"Cache HIT: {from}/{to}"` | INFO | Redis served the rate (no provider calls) |
| `"Cache MISS: {from}/{to}"` | INFO | Redis miss; calling providers |
| `"Provider {name} failed: {err}"` | ERROR | Individual provider failure (conversions continue) |
| `"Provider error: {exc}"` | ERROR | `ProviderError` returned to client as 503 |
| `"Unhandled exception: {exc}"` | ERROR | Unexpected error; returned as 500 |

---

## Operational Runbook

### A provider is returning errors

1. Check `GET /api/health` — identify which provider is down.
2. Check the provider's status page:
   - Fixer.io: https://status.fixer.io
   - OpenExchangeRates: no public status page
   - CurrencyAPI: https://currencyapi.statuspage.io
3. If the provider is down but the others are operational, conversions continue using the remaining two. No action required.
4. If it's a quota issue (HTTP 429 / API key error), rotate the key and restart the api container.

### The API is returning 503 for all conversions

All three providers are unreachable simultaneously. Check:
1. Outbound internet connectivity from the container.
2. `docker logs currency-converter-api` for error details.
3. Whether all three providers have an active outage simultaneously (rare).

### Redis is unavailable

Currency validation and rate lookups will fall back to the database for every request. Performance degrades (higher latency) but the service remains functional. Address Redis connectivity, then restart the API to restore normal cache operation.

### The database is unavailable

The API will fail to start (migrations cannot run) or fail all requests that touch the DB. Redis may still serve cached rates and currency lists for a short window. Address the database issue and restart the API.

### Re-seeding supported currencies

If you add a new provider and want to expand the supported currency list:

```bash
# 1. Connect to the database
docker exec -it currency-converter-db psql -U postgres -d currency_converter

# 2. Truncate the currencies table
TRUNCATE supported_currencies;
\q

# 3. Restart the API — it will re-seed from all providers on startup
docker restart currency-converter-api
```

### Rolling back to a previous image version

```bash
# Redeploy with a specific tagged image
docker pull ghcr.io/danielpopoola/currency-converter-backend:abc1234
docker stop currency-converter-api
docker run -d \
  --name currency-converter-api \
  --env-file /path/to/.env \
  -p 8000:8000 \
  ghcr.io/danielpopoola/currency-converter-backend:abc1234
```
