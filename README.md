# Currency Converter API

A production-ready currency conversion service built with FastAPI. Aggregates live exchange rates from three independent providers, averages them for accuracy, caches results in Redis, and persists rate history in PostgreSQL.

[![CI/CD](https://github.com/DanielPopoola/currency-converter/actions/workflows/main.yml/badge.svg)](https://github.com/DanielPopoola/currency-converter/actions/workflows/main.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.116-green)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [Development](#development)
- [Testing](#testing)
- [Deployment](#deployment)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

The Currency Converter API solves a fundamental reliability problem with exchange rate data: any single provider can go down, return stale data, or produce inaccurate rates. This service queries **three providers simultaneously** (Fixer.io, OpenExchangeRates, CurrencyAPI), averages their responses, and falls back gracefully if one or two fail.

The result is a conversion service that is more accurate, more resilient, and faster to respond (thanks to Redis caching) than anything built on a single provider.

**Frontend:** A React/Vite dashboard is included at `frontend/`, served at port `5173` via Docker.

---

## Features

| Feature | Detail |
|---------|--------|
| **Multi-provider aggregation** | Fetches rates from 3 providers in parallel via `asyncio.gather()` and averages results |
| **Automatic failover** | 1–2 provider failures are transparent to callers; only all-3-fail triggers a 503 |
| **Redis caching** | Rates cached for 5 minutes, supported currency list for 24 hours |
| **Rate history** | Every fetched rate is persisted to PostgreSQL for auditing and analysis |
| **One-time currency seeding** | Currencies are fetched from providers once on first boot, then served from the DB |
| **Retry with backoff** | `tenacity` retries transient network errors with exponential backoff (max 3 attempts) |
| **Provider health endpoint** | `GET /api/health` reports real-time status of each upstream provider |
| **Layered architecture** | Strict 4-layer separation: API → Application → Domain → Infrastructure |
| **Async throughout** | `asyncpg` + SQLAlchemy async, `httpx` async client, Redis async client |
| **Containerised** | Multi-service Docker Compose for local development and production parity |
| **CI/CD** | GitHub Actions pipeline: lint → test → build → push to GHCR |

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- API keys for the three currency providers:
  - [Fixer.io](https://fixer.io/) — free tier supports EUR as base currency only
  - [OpenExchangeRates](https://openexchangerates.org/) — free tier available
  - [CurrencyAPI](https://currencyapi.com/) — free tier available

### 1. Clone and configure

```bash
git clone https://github.com/DanielPopoola/currency-converter.git
cd currency-converter
cp backend/.env.example backend/.env
```

Edit `backend/.env` and fill in your API keys:

```env
FIXERIO_API_KEY=your_fixer_key_here
OPENEXCHANGE_APP_ID=your_openexchange_id_here
CURRENCYAPI_KEY=your_currencyapi_key_here
```

### 2. Start the full stack

```bash
docker compose -f backend/docker/docker-compose.yml up --build
```

On first run this will:
- Start PostgreSQL 15 and Redis 7
- Run Alembic migrations to create database tables
- Fetch and seed supported currencies from all three providers
- Start the API on **http://localhost:8000**
- Build and serve the React frontend on **http://localhost:5173**

Subsequent starts skip the provider seed step — currencies are loaded from the database.

### 3. Verify

```bash
# API health
curl http://localhost:8000/api/health

# Swagger UI
open http://localhost:8000/docs

# Frontend
open http://localhost:5173
```

---

## API Reference

All endpoints are prefixed with `/api`. Interactive documentation is available at `/docs` (Swagger UI) and `/redoc` (ReDoc).

### `GET /api/convert/{from_currency}/{to_currency}/{amount}`

Convert an amount between two currencies.

**Path parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `from_currency` | string | ISO 4217 source currency code (e.g. `USD`) |
| `to_currency` | string | ISO 4217 target currency code (e.g. `EUR`) |
| `amount` | decimal | Positive amount to convert (2 decimal places max) |

**Example**

```bash
curl http://localhost:8000/api/convert/USD/EUR/100
```

```json
{
  "from_currency": "USD",
  "to_currency": "EUR",
  "original_amount": "100.00",
  "converted_amount": "92.55",
  "exchange_rate": "0.9255",
  "timestamp": "2025-11-01T14:30:00Z",
  "source": "averaged"
}
```

---

### `GET /api/rate/{from_currency}/{to_currency}`

Get the current exchange rate between two currencies without performing a conversion.

```bash
curl http://localhost:8000/api/rate/USD/JPY
```

```json
{
  "from_currency": "USD",
  "to_currency": "JPY",
  "rate": "149.8500",
  "timestamp": "2025-11-01T14:30:00Z",
  "source": "averaged"
}
```

---

### `GET /api/currencies`

List all supported currency codes.

```bash
curl http://localhost:8000/api/currencies
```

```json
{
  "currencies": ["AUD", "CAD", "CHF", "CNY", "EUR", "GBP", "JPY", "NGN", "NZD", "SEK", "USD"]
}
```

---

### `GET /api/health`

Get the operational status of each configured exchange rate provider.

```bash
curl http://localhost:8000/api/health
```

```json
{
  "providers": [
    { "name": "fixerio", "status": "operational", "error": null },
    { "name": "openexchange", "status": "operational", "error": null },
    { "name": "currencyapi.com", "status": "down", "error": "TimeoutError" }
  ],
  "healthy_providers": 2,
  "total_providers": 3,
  "status": "degraded"
}
```

---

### Error Responses

| HTTP Status | Condition |
|-------------|-----------|
| `400 Bad Request` | Unsupported or invalid currency code |
| `503 Service Unavailable` | All exchange rate providers are unreachable |
| `500 Internal Server Error` | Unexpected server error (details not exposed to client) |

```json
{ "detail": "Currency XYZ is not supported" }
```

---

## Configuration

All configuration is loaded via environment variables. Copy `backend/.env.example` to `backend/.env` and adjust as needed. Docker Compose reads the same file but overrides `DATABASE_URL` and `REDIS_URL` internally to use container hostnames.

| Variable | Default | Description |
|----------|---------|-------------|
| `FIXERIO_API_KEY` | `""` | Fixer.io API key |
| `OPENEXCHANGE_APP_ID` | `""` | OpenExchangeRates App ID |
| `CURRENCYAPI_KEY` | `""` | CurrencyAPI key |
| `DATABASE_URL` | SQLite (dev) | PostgreSQL async connection string |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection string |
| `APP_NAME` | `Currency Converter API` | Application name (shown in docs) |
| `DEBUG` | `true` | Enables debug mode |
| `CORS_ORIGINS` | localhost origins | Comma-separated list of allowed CORS origins |
| `POSTGRES_USER` | `postgres` | PostgreSQL username (Docker only) |
| `POSTGRES_PASSWORD` | `postgres` | PostgreSQL password (Docker only) |
| `POSTGRES_DB` | `currency_converter` | PostgreSQL database name (Docker only) |

---

## Project Structure

```
.
├── backend/
│   ├── api/                        # Layer 1: HTTP interface
│   │   ├── routes/currency.py      # All REST endpoints
│   │   ├── schemas/                # Pydantic request/response models
│   │   ├── dependencies.py         # FastAPI Depends() wiring & singletons
│   │   ├── error_handlers.py       # Domain exception → HTTP status mapping
│   │   └── main.py                 # App factory, CORS, lifespan
│   │
│   ├── application/services/       # Layer 2: Business logic
│   │   ├── currency_service.py     # Currency validation & one-time seeding
│   │   ├── rate_service.py         # Rate aggregation & provider orchestration
│   │   └── conversion_service.py  # End-to-end conversion orchestration
│   │
│   ├── domain/                     # Layer 3: Core entities (framework-free)
│   │   ├── models/currency.py      # Frozen dataclasses: ExchangeRate, etc.
│   │   └── exceptions/currency.py  # Typed domain exceptions
│   │
│   ├── infrastructure/             # Layer 4: External systems
│   │   ├── providers/              # httpx clients for each rate provider
│   │   ├── cache/redis_cache.py    # Redis read/write with TTL
│   │   └── persistence/            # SQLAlchemy engine, ORM models, repositories
│   │
│   ├── alembic/                    # Database migrations
│   ├── config/settings.py          # Pydantic-settings configuration
│   ├── docker/                     # Compose file & entrypoint script
│   ├── tests/                      # Pytest test suite
│   └── pyproject.toml
│
└── frontend/
    ├── src/
    │   ├── app/
    │   │   ├── components/         # React UI components
    │   │   ├── data/currencies.ts  # Currency metadata & flag helpers
    │   │   ├── hooks/              # Custom React hooks
    │   │   └── pages/              # Page-level components
    │   └── lib/api.ts              # Typed API client
    └── package.json
```

---

## Development

### Local setup (API only, Docker for infra)

```bash
# 1. Start Postgres and Redis
docker compose -f backend/docker/docker-compose.yml up db redis -d

# 2. Create and activate a virtual environment
cd backend
python -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install uv
uv pip install -e .

# 4. Copy and configure environment
cp .env.example .env
# Fill in FIXERIO_API_KEY, OPENEXCHANGE_APP_ID, CURRENCYAPI_KEY

# 5. Run migrations
alembic upgrade head

# 6. Start the API with hot-reload
uvicorn api.main:app --reload
```

API: http://localhost:8000 | Swagger: http://localhost:8000/docs

### Frontend development

```bash
cd frontend
npm install
npm run dev
```

Frontend: http://localhost:5173

### Code quality

```bash
# Linting (ruff)
cd backend
ruff check .
ruff check . --fix   # auto-fix where possible
ruff format .

# Install pre-commit hooks (run once)
pip install pre-commit
pre-commit install
pre-commit install --hook-type commit-msg
```

Pre-commit hooks enforce: trailing whitespace, ruff lint + format, bandit security scan, and conventional commit message format.

### Database migrations

```bash
# After modifying an ORM model in infrastructure/persistence/models/
alembic revision --autogenerate -m "describe your change"

# Always review the generated file in alembic/versions/ before applying
alembic upgrade head

# Other useful commands
alembic current       # show applied revision
alembic history       # list all migrations
alembic downgrade -1  # roll back one step
```

> **Never** run `alembic revision --autogenerate` inside an entrypoint script or on an unchanged schema. Migration files are authored by developers and committed to the repository. The entrypoint only ever runs `alembic upgrade head`.

---

## Testing

```bash
cd backend

# Run all tests
pytest

# With coverage report
pytest --cov=. --cov-report=html
open htmlcov/index.html

# Run a specific test file
pytest tests/unit/infrastructure/providers/test_fixerio.py -v
```

### Test philosophy

Tests mock at the HTTP boundary — each provider accepts an injected `httpx.AsyncClient`, making it trivial to simulate any response or failure without hitting the real APIs. The Redis cache service similarly accepts an injected client.

```python
# Provider test example
mock_client = AsyncMock(spec=httpx.AsyncClient)
mock_response = Mock()
mock_response.json.return_value = {"success": True, "rates": {"EUR": 0.85}}
mock_response.raise_for_status = Mock()
mock_client.get.return_value = mock_response

provider = FixerIOProvider(api_key="test_key", client=mock_client)
rate = await provider.fetch_rate("USD", "EUR")
assert rate == Decimal("0.85")
```

All tests are async via `asyncio_mode = "auto"` in `pyproject.toml` — no manual `@pytest.mark.asyncio` decorators needed.

---

## Deployment

### CI/CD Pipeline

Every push to `master` triggers the GitHub Actions workflow (`.github/workflows/main.yml`):

1. **`backend-lint-and-test`** — Spins up Postgres 15 + Redis 6, installs dependencies via `uv`, runs `ruff check`, applies migrations, runs `pytest`.
2. **`frontend-build`** — Installs Node 20 dependencies, runs `npm run build`.
3. **`build-and-push`** (master only, after both above pass) — Builds Docker images for `backend` and `frontend`, pushes to GitHub Container Registry tagged with both `latest` and the commit SHA.

### Docker images

```bash
# Pull latest images
docker pull ghcr.io/danielpopoola/currency-converter-backend:latest
docker pull ghcr.io/danielpopoola/currency-converter-frontend:latest
```

### Adding a new exchange rate provider

1. Create `infrastructure/providers/yourprovider.py` implementing the `ExchangeRateProvider` protocol.
2. Export it from `infrastructure/providers/__init__.py`.
3. Add your API key to `config/settings.py` and `.env.example`.
4. Register the instance in `api/dependencies.py` under `deps.providers`.
5. Write unit tests in `tests/unit/infrastructure/providers/test_yourprovider.py`.

`RateService` and `CurrencyService` discover providers from the dict automatically — no other changes needed.

> **Note:** A new provider expands the supported currency intersection only on a fresh database or after manually truncating the `supported_currencies` table and restarting.

---

## Contributing

1. Fork the repository and create a feature branch: `git checkout -b feat/your-feature`
2. Make your changes, ensuring tests pass and `ruff check .` is clean.
3. Commit using [Conventional Commits](https://www.conventionalcommits.org/): `git commit -m "feat: add CoinGecko provider"`
4. Open a pull request against `master`.

---

## License

MIT — see [LICENSE](LICENSE) for details.
