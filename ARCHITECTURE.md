# Architecture Documentation
## Currency Converter API

---

## Table of Contents
1. [System Overview](#system-overview)
2. [Layered Architecture](#layered-architecture)
3. [Layer Responsibilities](#layer-responsibilities)
4. [Data Flow](#data-flow)
5. [Infrastructure Components](#infrastructure-components)
6. [Provider Strategy](#provider-strategy)
7. [Caching Strategy](#caching-strategy)
8. [Dependency Injection](#dependency-injection)
9. [Error Handling Architecture](#error-handling-architecture)
10. [Startup Sequence](#startup-sequence)

---

## System Overview

The Currency Converter API is a production-ready FastAPI service that aggregates exchange rates from three external providers (Fixer.io, OpenExchangeRates, CurrencyAPI), averages them for accuracy, caches results in Redis, and persists history in PostgreSQL.
```
┌──────────────────────────────────────────────────────┐
│                    Clients / Consumers                │
└─────────────────────────┬────────────────────────────┘
                          │ HTTP
┌─────────────────────────▼────────────────────────────┐
│                  FastAPI Application                  │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  Routes  │  │   Schemas    │  │ Error Handlers │  │
│  └──────────┘  └──────────────┘  └────────────────┘  │
└─────────────────────────┬────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────┐
│               Application Services                    │
│  ┌──────────────┐ ┌────────────┐ ┌────────────────┐  │
│  │CurrencyService│ │RateService │ │ConversionService│ │
│  └──────────────┘ └────────────┘ └────────────────┘  │
└─────────────────────────┬────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────┐
│                   Domain Layer                        │
│   ┌──────────────────┐   ┌──────────────────────┐    │
│   │  Domain Models   │   │  Domain Exceptions   │    │
│   └──────────────────┘   └──────────────────────┘    │
└─────────────────────────┬────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────┐
│               Infrastructure Layer                    │
│  ┌───────────┐  ┌────────────┐  ┌─────────────────┐  │
│  │ Providers │  │Redis Cache │  │  PostgreSQL DB  │  │
│  └───────────┘  └────────────┘  └─────────────────┘  │
└──────────────────────────────────────────────────────┘
```

---

## Layered Architecture

The project follows a strict **4-layer architecture**. Each layer only depends on the layer directly below it.
```
api/              ← Layer 1: HTTP interface
application/      ← Layer 2: Business logic & orchestration
domain/           ← Layer 3: Core entities & exceptions
infrastructure/   ← Layer 4: External systems (DB, cache, APIs)
```

Dependency rules:
- `api/` imports from `application/` only
- `application/` imports from `domain/` and `infrastructure/`
- `domain/` imports nothing from other project layers (pure Python)
- `infrastructure/` imports from `domain/` only

---

## Layer Responsibilities

### Layer 1 — API (`api/`)

| File | Responsibility |
|------|----------------|
| `main.py` | FastAPI app creation, lifespan startup/shutdown |
| `routes/currency.py` | HTTP endpoints, path parameter parsing |
| `schemas/requests.py` | Pydantic input validation |
| `schemas/responses.py` | Pydantic response shaping |
| `dependencies.py` | Dependency injection wiring |
| `error_handlers.py` | Maps domain exceptions to HTTP status codes |

The API layer performs **no business logic**. It validates input, calls a service, shapes a response.

### Layer 2 — Application (`application/services/`)

| Service | Responsibility |
|---------|----------------|
| `CurrencyService` | Managing supported currencies, one-time seeding, validation |
| `RateService` | Fetching, aggregating, and caching exchange rates |
| `ConversionService` | Orchestrating end-to-end currency conversion |

### Layer 3 — Domain (`domain/`)

| Module | Responsibility |
|--------|----------------|
| `models/currency.py` | Frozen dataclasses: `ExchangeRate`, `SupportedCurrency`, `AggregatedRate` |
| `exceptions/currency.py` | Typed exceptions: `InvalidCurrencyError`, `ProviderError`, `CacheError` |

Completely framework-free. No FastAPI, SQLAlchemy, or Redis — just plain Python.

### Layer 4 — Infrastructure (`infrastructure/`)

| Module | Responsibility |
|--------|----------------|
| `providers/` | HTTP clients for each exchange rate API |
| `cache/redis_cache.py` | Redis read/write with TTL management |
| `persistence/database.py` | SQLAlchemy async engine and session factory |
| `persistence/models/` | ORM table definitions |
| `persistence/repositories/` | All database and cache queries |

---

## Data Flow

### Happy Path: Cache Miss
```
GET /api/convert/USD/EUR/100
    │
    ├─ Pydantic validates path params
    ├─ ConversionService.convert() called
    │     ├─ CurrencyService.validate_currency("USD")  → Redis HIT, in list ✓
    │     ├─ CurrencyService.validate_currency("EUR")  → Redis HIT, in list ✓
    │     └─ RateService.get_rate("USD", "EUR")
    │           ├─ Redis get_rate("USD", "EUR")        → MISS
    │           └─ _aggregate_rates()
    │                 ├─ asyncio.gather() — parallel fetch:
    │                 │     FixerIO        → 0.9250  ✓
    │                 │     OpenExchange   → 0.9260  ✓
    │                 │     CurrencyAPI    → FAIL    ✗
    │                 ├─ avg = (0.9250 + 0.9260) / 2 = 0.9255
    │                 ├─ Redis SET rate:USD:EUR  (TTL 5 min)
    │                 └─ PostgreSQL INSERT rate_history
    ├─ converted = 100 × 0.9255 = 92.55
    └─ HTTP 200 ConversionResponse
```

### Happy Path: Cache Hit (within 5 min)

Same as above, but `Redis get_rate("USD", "EUR")` returns HIT. The aggregate step is skipped entirely — zero external API calls.

---

## Infrastructure Components

### Redis Key Schema
```
rate:{from}:{to}       → ExchangeRate as JSON  (TTL: 5 minutes)
currencies:supported   → list[str] as JSON     (TTL: 24 hours)
```

`Decimal` is serialized as `str` to preserve precision. `datetime` is stored as ISO 8601.

### PostgreSQL Schema
```sql
supported_currencies (
    code  VARCHAR(5)   PRIMARY KEY,
    name  VARCHAR(100) NULLABLE
)

rate_history (
    id            SERIAL PRIMARY KEY,
    from_currency VARCHAR(5)    NOT NULL,
    to_currency   VARCHAR(5)    NOT NULL,
    rate          DECIMAL(18,6) NOT NULL,
    timestamp     DATETIME      NOT NULL  [indexed],
    source        VARCHAR(50)   NOT NULL,
    UNIQUE(from_currency, to_currency, timestamp)
)
```

### Provider Interface (Protocol)
```python
class ExchangeRateProvider(Protocol):
    @property
    def name(self) -> str: ...
    async def fetch_rate(self, from_currency, to_currency) -> Decimal: ...
    async def fetch_supported_currencies(self) -> list[dict]: ...
    async def close(self) -> None: ...
```

---

## Provider Strategy

### Parallel Fetching
```
Request → [FixerIO, OpenExchange, CurrencyAPI]  ← simultaneous via asyncio.gather()
              0.925      0.926         FAIL
                └──────────┘
                 avg = 0.9255
```

### Failure Tolerance

| Scenario | Outcome |
|----------|---------|
| 1–2 providers fail | Average of remaining responses |
| All 3 providers fail | `ProviderError` → HTTP 503 |

### Retry Logic (tenacity)

- 3 attempts, exponential backoff: 1s → 2s → 4s (max 10s)
- Only retries `ConnectionError` / `TimeoutError`
- Does **not** retry `ProviderError` (API-level errors like bad keys)

---

## Caching Strategy
```
Request → Redis HIT? → Yes → Return immediately (no API calls)
                   → No  → Fetch from providers → Average
                                                 → SET Redis (5 min TTL)
                                                 → INSERT PostgreSQL
                                                 → Return
```

---

## Dependency Injection
```
Singletons (startup, live for app lifetime):
  deps.db             → Database engine + session factory
  deps.redis_cache    → RedisCacheService
  deps.providers      → {name: ProviderInstance} × 3

Per-request (FastAPI Depends, created fresh):
  get_db_session()           → AsyncSession
  get_currency_repository()  → CurrencyRepository(session, cache)
  get_currency_service()     → CurrencyService(repo, providers)
  get_rate_service()         → RateService(svc, repo, providers)
  get_conversion_service()   → ConversionService(rate_svc, svc)
```

---

## Error Handling Architecture
```
Domain Exception       →  HTTP  →  Client Body
─────────────────────────────────────────────────────────────────
InvalidCurrencyError   →  400   →  {"detail": "Currency XYZ not supported"}
ProviderError          →  503   →  {"detail": "Exchange rate service unavailable"}
Exception (catch-all)  →  500   →  {"detail": "Internal server error"}
```

`ProviderError` messages are swallowed before reaching the client (they may contain internal API details).

---

## Startup Sequence
```
entrypoint.sh
  ├── wait for PostgreSQL to be ready (pg_isready loop)
  └── alembic upgrade head  → creates tables if this is a fresh database

lifespan() starts
  ├── init_dependencies()   → creates DB engine, Redis client, 3 provider clients
  └── bootstrap()
        └── initialize_supported_currencies()
              ├── get_supported_currencies() → DB query
              │
              ├── [DB has data] → log "already initialized", return
              │     └── Redis cache warmed as side effect of DB read
              │
              └── [DB empty — first startup only]
                    ├── asyncio.gather() fetch from all 3 providers
                    ├── set intersection of supported codes
                    ├── INSERT into supported_currencies
                    └── Redis cache warmed on next read

Application ready ✓

[on shutdown]
  └── cleanup_dependencies()  → closes Redis, DB engine, provider clients
```

The expensive provider calls at boot happen **exactly once** — on first startup when the database is empty. Every subsequent restart reads from the database.
