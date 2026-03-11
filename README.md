# Currency Converter API

A production-ready currency conversion service built with FastAPI that aggregates exchange rates from multiple providers to ensure reliability and accuracy.

## Overview

This service provides real-time currency conversion with automatic fallback between multiple exchange rate providers. It implements a clean 4-layer architecture with Redis caching and PostgreSQL persistence for historical data tracking.

### Key Features

- **Multi-Provider Aggregation**: Fetches rates from 3 providers (Fixer.io, OpenExchange, CurrencyAPI) and returns averaged results
- **Automatic Fallback**: If one provider fails, seamlessly falls back to others
- **Smart Caching**: Redis cache with 5-minute TTL to minimize API calls
- **Rate History**: PostgreSQL stores all fetched rates for historical analysis
- **Retry Logic**: Exponential backoff for transient network errors
- **Currency Validation**: Only supports currencies available across ALL providers
- **One-time Seeding**: Supported currencies are fetched from providers once on first startup and persisted — subsequent startups read from the database

## Architecture

### Layered Design

```
┌─────────────────────────────────────┐
│   API Layer (FastAPI Routes)        │  ← HTTP endpoints, request/response
├─────────────────────────────────────┤
│   Application Layer (Services)      │  ← Business logic, orchestration
├─────────────────────────────────────┤
│   Domain Layer (Models)             │  ← Core entities, exceptions
├─────────────────────────────────────┤
│   Infrastructure Layer              │  ← External services, database
│   (Providers, Cache, Repository)    │
└─────────────────────────────────────┘
```

### Request Flow

```
1. Client Request
   ↓
2. API Layer validates input (Pydantic)
   ↓
3. Application Service checks currency validity (Redis → DB)
   ↓
4. Repository checks Redis cache
   ↓
5. If MISS → Fetch from all 3 providers in parallel
   ↓
6. Aggregate (average) the rates
   ↓
7. Cache in Redis (5 min TTL)
   ↓
8. Store in PostgreSQL for history
   ↓
9. Return to client
```

## Project Structure

```
.
├── api/
│   ├── routes/
│   │   └── currency.py          # REST endpoints
│   ├── schemas/
│   │   ├── requests.py          # Request validation
│   │   └── responses.py         # Response models
│   ├── dependencies.py          # Dependency injection setup
│   ├── error_handlers.py        # Global exception handlers
│   └── main.py                  # FastAPI app initialization
│
├── application/
│   └── services/
│       ├── currency_service.py  # Currency validation & seeding
│       ├── rate_service.py      # Rate fetching & aggregation
│       └── conversion_service.py
│
├── domain/
│   ├── models/currency.py       # Core entities (frozen dataclasses)
│   └── exceptions/currency.py  # Domain-specific exceptions
│
├── infrastructure/
│   ├── providers/
│   │   ├── base.py              # Provider protocol (interface)
│   │   ├── fixerio.py
│   │   ├── openexchange.py
│   │   └── currencyapi.py
│   ├── cache/redis_cache.py
│   └── persistence/
│       ├── database.py
│       ├── models/currency.py   # SQLAlchemy ORM models
│       └── repositories/currency.py
│
├── alembic/                     # Database migrations
│   ├── versions/
│   │   └── 0001_initial_tables.py
│   └── env.py
│
├── config/settings.py
├── Dockerfile
└── docker/
    ├── docker-compose.yml
    └── entrypoint.sh
```

## Getting Started

### Prerequisites

- Docker & Docker Compose
- API keys for the three currency providers:
  - [Fixer.io](https://fixer.io/) — free tier only supports EUR as base currency
  - [OpenExchangeRates](https://openexchangerates.org/) — free tier available
  - [CurrencyAPI](https://currencyapi.com/) — free tier available

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/DanielPopoola/currency-converter.git
   cd currency-converter
   ```

2. **Configure environment variables**
   ```bash
   cp .env.example .env
   ```

   Fill in your API keys:
   ```env
   FIXERIO_API_KEY=your_fixer_key_here
   OPENEXCHANGE_APP_ID=your_openexchange_id_here
   CURRENCYAPI_KEY=your_currencyapi_key_here
   ```

3. **Start the services**
   ```bash
   docker compose -f docker/docker-compose.yml up --build
   ```

   On first startup this will:
   - Start PostgreSQL and Redis
   - Run Alembic migrations to create tables
   - Fetch supported currencies from all three providers and persist them
   - Start the API on port 8000

   On every subsequent startup, the persisted currencies are used directly — no provider calls at boot.

4. **Verify**
   ```bash
   curl http://localhost:8000/docs
   ```

## API Endpoints

### GET /api/convert/{from_currency}/{to_currency}/{amount}

Convert an amount from one currency to another.

```bash
curl http://localhost:8000/api/convert/USD/EUR/100
```

```json
{
  "from_currency": "USD",
  "to_currency": "EUR",
  "original_amount": 100.00,
  "converted_amount": 92.55,
  "exchange_rate": 0.9255,
  "timestamp": "2025-11-01T14:30:00Z",
  "source": "averaged"
}
```

### GET /api/rate/{from_currency}/{to_currency}

Get the current exchange rate between two currencies.

```bash
curl http://localhost:8000/api/rate/USD/JPY
```

```json
{
  "from_currency": "USD",
  "to_currency": "JPY",
  "rate": 149.85,
  "timestamp": "2025-11-01T14:30:00Z",
  "source": "averaged"
}
```

### GET /api/currencies

List all supported currency codes.

```bash
curl http://localhost:8000/api/currencies
```

```json
{
  "currencies": ["USD", "EUR", "GBP", "JPY", "NGN", "..."]
}
```

Interactive documentation: http://localhost:8000/docs

## How It Works

### Multi-Provider Strategy

All 3 providers are queried in parallel for every cache miss:

- Fixer.io returns: `0.9250`
- OpenExchangeRates returns: `0.9260`
- CurrencyAPI fails (timeout)
- **Final rate**: `(0.9250 + 0.9260) / 2 = 0.9255`

If one or two providers fail, the average of the remaining responses is used. Only if all three fail does the service return a 503.

### Caching

```
First request for USD/EUR:
  Redis MISS → fetch from providers → cache in Redis (5 min TTL) → store in PostgreSQL

Subsequent requests within 5 minutes:
  Redis HIT → return immediately (zero provider calls)
```

### Supported Currencies

On first startup the service fetches all supported currencies from each provider, takes the intersection (only currencies all providers support), and persists them to PostgreSQL. Every subsequent startup reads from the database instead of calling providers.

## Error Handling

| Status | Meaning |
|--------|---------|
| `200` | Success |
| `400` | Unsupported currency code |
| `503` | All providers are down |
| `500` | Unexpected server error |

## Configuration

All config is via the root `.env` file. Docker reads the same file and overrides only the database and Redis hostnames internally.

| Variable | Description |
|----------|-------------|
| `FIXERIO_API_KEY` | Fixer.io API key |
| `OPENEXCHANGE_APP_ID` | OpenExchangeRates app ID |
| `CURRENCYAPI_KEY` | CurrencyAPI key |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `POSTGRES_USER` | Postgres username (used by Docker) |
| `POSTGRES_PASSWORD` | Postgres password (used by Docker) |
| `POSTGRES_DB` | Postgres database name (used by Docker) |

## Testing

```bash
pytest
pytest --cov=. --cov-report=html
```

## License

MIT
