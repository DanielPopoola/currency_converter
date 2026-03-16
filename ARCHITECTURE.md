# Architecture

## Currency Converter API

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Guiding Principles](#guiding-principles)
3. [Layered Architecture](#layered-architecture)
4. [Layer Deep-Dives](#layer-deep-dives)
   - [API Layer](#api-layer)
   - [Application Layer](#application-layer)
   - [Domain Layer](#domain-layer)
   - [Infrastructure Layer](#infrastructure-layer)
5. [Data Flow](#data-flow)
6. [Provider Strategy](#provider-strategy)
7. [Caching Strategy](#caching-strategy)
8. [Persistence Strategy](#persistence-strategy)
9. [Dependency Injection](#dependency-injection)
10. [Error Handling](#error-handling)
11. [Startup & Shutdown](#startup--shutdown)
12. [Frontend Architecture](#frontend-architecture)
13. [Infrastructure & Deployment](#infrastructure--deployment)
14. [Key Design Decisions](#key-design-decisions)
15. [Known Limitations & Future Work](#known-limitations--future-work)

---

## System Overview

```
                        ┌───────────────────────────────┐
                        │     React / Vite Frontend      │
                        │     (port 5173)                │
                        └──────────────┬────────────────┘
                                       │ HTTP (fetch)
                        ┌──────────────▼────────────────┐
                        │      FastAPI Application       │
                        │      (port 8000)               │
                        │                                │
                        │  Routes → Services → Repos     │
                        └────┬──────────────────┬────────┘
                             │                  │
               ┌─────────────▼──┐      ┌────────▼───────────┐
               │   Redis 7       │      │   PostgreSQL 15     │
               │   (cache)       │      │   (persistence)     │
               │   port 6379     │      │   port 5432         │
               └─────────────────┘      └────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        Fixer.io    OpenExchangeRates   CurrencyAPI
        (external)  (external)          (external)
```

The API is the only component that talks to the outside world. The frontend never calls the exchange rate providers directly.

---

## Guiding Principles

**Simplicity over cleverness.** Each module does one thing. Code is readable before it is optimal.

**Dependency rules flow inward.** The domain layer imports nothing from other project layers. Infrastructure imports from the domain only. Application imports from domain and infrastructure. The API layer imports from the application layer only. This means the business logic (domain + application) can be tested without spinning up a database or HTTP server.

**Explicit over implicit.** All dependencies are injected. There are no global singletons accessed via module-level imports in business logic.

**Fail loudly at boundaries, fail gracefully in aggregation.** A single provider failure is handled silently (averaged out). A complete infrastructure failure produces a clear typed exception that maps to a predictable HTTP status.

---

## Layered Architecture

```
┌────────────────────────────────────────────────────────────┐
│  api/            Layer 1 — HTTP interface                   │
│  Routes, Schemas, Error Handlers, Dependencies              │
├────────────────────────────────────────────────────────────┤
│  application/    Layer 2 — Business logic & orchestration   │
│  CurrencyService, RateService, ConversionService            │
├────────────────────────────────────────────────────────────┤
│  domain/         Layer 3 — Core entities & exceptions       │
│  Frozen dataclasses, typed exceptions (pure Python)         │
├────────────────────────────────────────────────────────────┤
│  infrastructure/ Layer 4 — External systems                 │
│  Providers (httpx), Redis cache, SQLAlchemy + repositories  │
└────────────────────────────────────────────────────────────┘
```

Dependency direction: `api` → `application` → `domain` ← `infrastructure`

The domain layer is the only one without external dependencies. It defines the *language* of the system — what an `ExchangeRate` is, what `ProviderError` means — so that all other layers can speak the same language without coupling to each other.

---

## Layer Deep-Dives

### API Layer

**Location:** `backend/api/`

Responsible for exactly three things: validate HTTP input, call a service, shape the HTTP response. No business logic lives here.

```
api/
├── main.py             App factory, CORS middleware, lifespan handler
├── dependencies.py     Singleton lifecycle + FastAPI Depends() wiring
├── error_handlers.py   Domain exception → HTTP status code mapping
├── routes/
│   └── currency.py     All route handlers (convert, rate, currencies, health)
└── schemas/
    ├── requests.py     Pydantic models for request input validation
    └── responses.py    Pydantic models for response shaping
```

Route handlers are deliberately thin:

```python
@router.get("/convert/{from_currency}/{to_currency}/{amount}")
async def convert_currency(
    from_currency: str, to_currency: str, amount: Decimal,
    service: Annotated[ConversionService, Depends(get_conversion_service)],
) -> ConversionResponse:
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()
    result = await service.convert(amount, from_currency, to_currency)
    return ConversionResponse(**result)
```

The handler does: normalize → delegate → shape. Nothing else.

---

### Application Layer

**Location:** `backend/application/services/`

Contains all orchestration and business rules. Services never touch HTTP request/response objects and never write SQL directly.

#### `CurrencyService`

Owns two responsibilities:

1. **One-time seeding** (`initialize_supported_currencies`): On first startup with an empty database, calls all providers in parallel, takes the intersection of supported codes, and persists them. On subsequent startups this method returns immediately after a single DB read.

2. **Validation** (`validate_currency`): Checks a currency code against the cached/persisted list and raises `InvalidCurrencyError` if not found.

#### `RateService`

Core aggregation logic. The `get_rate` method:

1. Validates both currencies via `CurrencyService`.
2. Checks the Redis cache. Returns immediately on hit.
3. On miss, calls `_aggregate_rates()` which fans out to all providers via `asyncio.gather()`.
4. Averages successful responses. Raises `ProviderError` only if all fail.
5. Persists the result to both Redis and PostgreSQL via the repository.

The `@retry` decorator on `_fetch_from_provider` retries only on `ConnectionError` and `TimeoutError` (transient network faults), not on `ProviderError` (API-level errors like invalid keys, quota exhaustion).

#### `ConversionService`

Thin orchestrator: validates currencies → fetches rate → multiplies → returns a plain `dict` that the API layer shapes into a response.

```
ConversionService
    └── validate_currency(from) ──► CurrencyService
    └── validate_currency(to)   ──► CurrencyService
    └── get_rate(from, to)      ──► RateService
                                       ├── cache.get_rate()       ──► Redis
                                       └── _aggregate_rates()
                                               ├── fixerio.fetch_rate()
                                               ├── openexchange.fetch_rate()
                                               └── currencyapi.fetch_rate()
```

---

### Domain Layer

**Location:** `backend/domain/`

Pure Python. No FastAPI, SQLAlchemy, Redis, or httpx. If this layer imports something, it is a standard library module.

#### Models (`domain/models/currency.py`)

All models are frozen dataclasses — immutable value objects.

```python
@dataclass(frozen=True)
class ExchangeRate:
    from_currency: str
    to_currency: str
    rate: Decimal      # Always Decimal, never float
    timestamp: datetime
    source: str

@dataclass(frozen=True)
class AggregatedRate:
    from_currency: str
    to_currency: str
    rate: Decimal
    timestamp: datetime
    sources: list[str]          # Which providers contributed
    individual_rates: dict[str, Decimal]
```

`Decimal` is used throughout to avoid floating-point precision loss. Rates are always constructed via `Decimal(str(float_value))` — never `Decimal(float_value)`.

#### Exceptions (`domain/exceptions/currency.py`)

```
CurrencyException (base)
├── InvalidCurrencyError   → maps to HTTP 400
├── ProviderError          → maps to HTTP 503
└── CacheError             → caught and re-raised by the repository
```

Typed exceptions make error handling explicit and testable without inspecting string messages.

---

### Infrastructure Layer

**Location:** `backend/infrastructure/`

Everything that talks to the outside world. Each module is independently swappable.

#### Providers (`infrastructure/providers/`)

All three providers implement the same `ExchangeRateProvider` Protocol:

```python
class ExchangeRateProvider(Protocol):
    @property
    def name(self) -> str: ...
    async def fetch_rate(self, from_currency: str, to_currency: str) -> Decimal: ...
    async def fetch_supported_currencies(self) -> list[dict[str, str]]: ...
    async def close(self) -> None: ...
```

Using a `Protocol` (structural subtyping) instead of an abstract base class means:
- Providers don't need to inherit from anything.
- Adding a new provider requires no changes to existing code.
- Tests can pass any object with the right shape without inheritance.

Each provider wraps `httpx.AsyncClient`. The client is constructor-injected, enabling tests to swap in a mock without monkey-patching.

#### Redis Cache (`infrastructure/cache/redis_cache.py`)

Two key namespaces:

| Key | Value | TTL |
|-----|-------|-----|
| `rate:{from}:{to}` | `ExchangeRate` serialised as JSON | 5 minutes |
| `currencies:supported` | `list[str]` serialised as JSON | 24 hours |

`Decimal` is serialised as `str` to preserve precision. `datetime` is ISO 8601. On deserialisation, values are reconstructed via `Decimal(str_value)` and `datetime.fromisoformat()`.

#### Database (`infrastructure/persistence/`)

```
persistence/
├── database.py                 SQLAlchemy async engine + session factory
├── models/currency.py          ORM table definitions (SupportedCurrencyDB, RateHistoryDB)
└── repositories/currency.py   All queries — no raw SQL outside this file
```

`CurrencyRepository` is the single point of contact for database operations. It also holds a reference to `RedisCacheService`, so the cache-then-DB read pattern is encapsulated in one place:

```
get_supported_currencies():
  1. Try Redis → return if hit
  2. Query DB
  3. Warm Redis with DB result
  4. Return
```

Schema:

```sql
supported_currencies (
    code  VARCHAR(5)    PRIMARY KEY,
    name  VARCHAR(100)  NULLABLE
)

rate_history (
    id             SERIAL        PRIMARY KEY,
    from_currency  VARCHAR(5)    NOT NULL,
    to_currency    VARCHAR(5)    NOT NULL,
    rate           DECIMAL(18,6) NOT NULL,
    timestamp      DATETIME      NOT NULL  -- indexed
    source         VARCHAR(50)   NOT NULL,
    UNIQUE (from_currency, to_currency, timestamp)
)
```

---

## Data Flow

### Cache Miss (most expensive path)

```
GET /api/convert/USD/EUR/100
        │
        ▼
   Path params parsed and normalised to uppercase
        │
        ▼
   ConversionService.convert("USD", "EUR", 100)
        │
        ├─► CurrencyService.validate_currency("USD")
        │       └─► CurrencyRepository.get_supported_currencies()
        │               ├─► Redis GET currencies:supported  ──► HIT → return
        │               └─► (MISS) → DB SELECT → Redis SET (24h TTL) → return
        │
        ├─► CurrencyService.validate_currency("EUR")  (same path)
        │
        └─► RateService.get_rate("USD", "EUR")
                │
                ├─► Redis GET rate:USD:EUR  ──► MISS
                │
                └─► _aggregate_rates("USD", "EUR")
                        │
                        ├─► asyncio.gather(
                        │       fixerio.fetch_rate("USD", "EUR"),        → 0.9250
                        │       openexchange.fetch_rate("USD", "EUR"),   → 0.9260
                        │       currencyapi.fetch_rate("USD", "EUR"),    → FAIL
                        │   )
                        │
                        ├─► avg = (0.9250 + 0.9260) / 2 = 0.9255
                        │
                        ├─► Redis SET rate:USD:EUR  (5-min TTL)
                        └─► PostgreSQL INSERT rate_history
        │
        ▼
   converted_amount = 100 × 0.9255 = 92.55
        │
        ▼
   HTTP 200 ConversionResponse
```

### Cache Hit (fast path — zero provider calls)

```
GET /api/convert/USD/EUR/100
        │
        ▼
   ConversionService.convert("USD", "EUR", 100)
        ├─► validate currencies (Redis HIT on currencies:supported)
        └─► RateService.get_rate("USD", "EUR")
                └─► Redis GET rate:USD:EUR  ──► HIT
                        └─► return cached ExchangeRate

   HTTP 200 (no external calls made)
```

---

## Provider Strategy

### Parallel Fetching

All provider calls are issued simultaneously via `asyncio.gather()`. The total latency is bounded by the slowest responding provider, not the sum of all latencies.

```
t=0ms  ──► [Fixer.io, OpenExchangeRates, CurrencyAPI]  (all start together)
t=80ms ──► Fixer.io responds:      0.9250
t=95ms ──► OpenExchangeRates:      0.9260
t=200ms──► CurrencyAPI times out   (FAIL)

Final rate = (0.9250 + 0.9260) / 2 = 0.9255
Total time ≈ 200ms (bounded by the timeout, not 80+95+200=375ms)
```

### Failure Tolerance

| Scenario | Outcome |
|----------|---------|
| 0 providers fail | Average of 3 responses |
| 1 provider fails | Average of 2 responses |
| 2 providers fail | Single provider's rate used directly |
| All 3 providers fail | `ProviderError` raised → HTTP 503 |

### Retry Logic

`tenacity` wraps `_fetch_from_provider` with:

- **3 attempts** maximum
- **Exponential backoff:** 1s → 2s → 4s (capped at 10s)
- **Retry condition:** `ConnectionError` or `TimeoutError` only

`ProviderError` is not retried — it indicates an API-level error (bad key, quota exceeded) that will not resolve with a retry.

---

## Caching Strategy

```
Request arrives
      │
      ▼
Redis cache lookup
      ├── HIT  ──► return immediately (0 external calls)
      │
      └── MISS ──► fetch from providers → average
                        │
                        ├──► Redis SET with TTL
                        └──► PostgreSQL INSERT
                                │
                                ▼
                          return to caller
```

### TTL Rationale

| Data | TTL | Reasoning |
|------|-----|-----------|
| Exchange rates | 5 minutes | Rates shift continuously but not second-to-second; 5 minutes balances freshness with provider quota |
| Supported currencies | 24 hours | Currency lists change rarely (new currencies are added infrequently) |

### Decimal Serialisation

Redis stores only strings. All `Decimal` values are serialised as `str` (e.g. `"0.925500"`) and deserialised via `Decimal(str_value)`. This avoids the precision loss that would occur with `float` → JSON → `Decimal`.

---

## Persistence Strategy

PostgreSQL serves two roles:

1. **Source of truth for supported currencies** — populated once on first startup, read on every subsequent startup.
2. **Audit log for rate history** — every rate returned to a caller is recorded with its timestamp and source.

The `rate_history` table has a composite unique constraint on `(from_currency, to_currency, timestamp)` to prevent duplicate inserts if, for example, a request is retried at the application level.

Three indexes on `rate_history` accelerate common query patterns:

- `idx_from_currency` — filter by source currency
- `idx_to_currency` — filter by target currency
- `idx_timestamp` — range queries for history over time periods

---

## Dependency Injection

### Singleton lifecycle

Created once at startup in `api/dependencies.py`, live for the application lifetime:

```python
class AppDependencies:
    db: Database               # SQLAlchemy engine + session factory
    redis_client: Redis        # Raw Redis client
    redis_cache: RedisCacheService
    providers: dict[str, ExchangeRateProvider]
```

Singletons are initialised in `init_dependencies()` and torn down in `cleanup_dependencies()`, both called from the FastAPI `lifespan` context manager.

### Per-request dependency graph

FastAPI rebuilds this graph on every request via `Depends()`:

```
get_db_session()
      │
      └── get_currency_repository(session, cache)
                │
                ├── get_currency_service(repo, providers)
                │
                ├── get_rate_service(currency_service, repo, providers)
                │
                └── get_conversion_service(rate_service, currency_service)
```

Each node is a function. FastAPI resolves the graph, creates instances, and disposes of them (committing or rolling back the DB session) after the response is sent.

`AsyncSession` is never held open longer than a single request. Commit/rollback/close is managed by the `get_db_session` generator.

---

## Error Handling

Domain exceptions are the language between the application and API layers. The `error_handlers.py` module registers handlers that translate them to HTTP responses:

```
Domain Exception       HTTP Status   Client Body
──────────────────────────────────────────────────────────
InvalidCurrencyError → 400         → {"detail": "Currency XYZ is not supported"}
ProviderError        → 503         → {"detail": "Exchange rate service unavailable"}
Exception (catch-all)→ 500         → {"detail": "Internal server error"}
```

`ProviderError` messages are intentionally swallowed before reaching the client — they may contain provider API keys or internal service details. The original error is logged at `ERROR` level server-side.

The global `Exception` handler in `main.py` catches anything not handled by a typed handler, logs the full traceback, and returns a generic 500 without leaking stack frames.

---

## Startup & Shutdown

```
Docker entrypoint.sh
    ├── poll pg_isready until PostgreSQL accepts connections
    └── alembic upgrade head (creates/migrates tables)
            │
            ▼
FastAPI lifespan() starts
    ├── init_dependencies()
    │       ├── create SQLAlchemy engine
    │       ├── create Redis async client
    │       └── instantiate 3 provider clients (httpx.AsyncClient per provider)
    │
    └── bootstrap()
            └── CurrencyService.initialize_supported_currencies()
                    ├── DB query: any rows in supported_currencies?
                    │
                    ├── YES → log "already initialised", return
                    │         (Redis warmed as side-effect on next read)
                    │
                    └── NO  → asyncio.gather(fetch from all 3 providers)
                                → set intersection of supported codes
                                → INSERT into supported_currencies
                                → return

Application ready ✓

[on SIGTERM / SIGINT]
    lifespan() cleanup
        ├── close Redis connection
        ├── dispose SQLAlchemy engine (closes connection pool)
        └── aclose() all httpx.AsyncClient instances
```

The expensive provider calls at boot happen **exactly once** — when the database is first populated. Every subsequent restart reads from PostgreSQL and is unaffected by provider availability.

---

## Frontend Architecture

The frontend (`frontend/`) is a React 18 + Vite application served via Nginx in production.

### Structure

```
src/
├── app/
│   ├── App.tsx                   Root component, router provider
│   ├── routes.ts                 react-router v7 route definitions
│   ├── components/
│   │   ├── layouts/              DashboardLayout (sidebar, nav)
│   │   └── ui/                   shadcn/ui components + custom components
│   ├── data/currencies.ts        Static currency metadata (codes, names, flags)
│   ├── hooks/
│   │   └── useSupportedCurrencies.ts  Fetches live currency list, falls back to static
│   └── pages/
│       ├── ConversionPage.tsx    Main conversion form + result display
│       ├── RateLookupPage.tsx    Real-time rate display + sparkline
│       └── CurrenciesPage.tsx    Searchable currency list with favourites
└── lib/
    └── api.ts                    Typed fetch wrapper for all backend endpoints
```

### API Client (`src/lib/api.ts`)

All backend calls go through a single `request<T>(path)` utility. Response shapes are typed, and `snake_case` API responses are translated to `camelCase` TypeScript interfaces at the boundary.

### Currency Metadata

`data/currencies.ts` ships with a static catalog of ~20 currencies with names, symbols, and country codes. Country codes are converted to emoji flags via Unicode regional indicator symbols. When the API returns a currency code not in the static catalog, a fallback object is created with the code as both name and symbol.

The `useSupportedCurrencies` hook fetches the live currency list from the API on mount. It initialises with the static catalog so the UI renders immediately, then replaces it with the server's list once the request completes.

---

## Infrastructure & Deployment

### Docker Compose services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `db` | `postgres:15` | 5432 | Primary datastore |
| `redis` | `redis:7-alpine` | 6379 | Rate and currency cache |
| `api` | Built from `backend/Dockerfile` | 8000 | FastAPI application |
| `frontend` | Built from `frontend/Dockerfile` | 5173→80 | React SPA via Nginx |

### Dockerfile strategy (backend)

The backend Dockerfile copies `pyproject.toml` first (before application code) so that Docker's layer cache avoids reinstalling dependencies on every code change:

```dockerfile
COPY pyproject.toml .               # cache layer: only invalidated when deps change
RUN pip install uv && uv pip install --system -e .
COPY . .                             # code changes don't invalidate the dep layer
```

### CI/CD

`.github/workflows/main.yml` runs on every push and PR to `master`:

```
push to master
      │
      ├── backend-lint-and-test (ubuntu-latest)
      │       ├── services: postgres:15, redis:6
      │       ├── uv pip install -e .
      │       ├── ruff check .
      │       ├── alembic upgrade head
      │       └── pytest
      │
      ├── frontend-build (ubuntu-latest)
      │       ├── npm ci
      │       └── npm run build
      │
      └── build-and-push (master only, needs both above)
              ├── docker build backend → ghcr.io/…-backend:{sha,latest}
              └── docker build frontend → ghcr.io/…-frontend:{sha,latest}
```

Images are double-tagged: `latest` for convenience and `{git-sha}` for deterministic rollbacks.

---

## Key Design Decisions

### Why freeze domain models?

`@dataclass(frozen=True)` prevents accidental mutation of rate objects as they pass through layers. An `ExchangeRate` fetched from the cache should be identical to when it was stored. Immutability makes this trivially true.

### Why a Protocol instead of ABC for providers?

Python's `Protocol` enables structural subtyping — any class with the right methods satisfies the interface, regardless of inheritance. This makes third-party integrations easier (no need to subclass) and keeps the domain layer from depending on any specific provider implementation.

### Why `Decimal` instead of `float`?

`float` cannot represent many decimal fractions exactly. `0.1 + 0.2 != 0.3` in floating point arithmetic. For financial calculations, precision is non-negotiable. `Decimal` with string construction (`Decimal(str(value))`) guarantees exact representation.

### Why one-time seeding instead of periodic refresh?

The set of globally available currencies changes very rarely (new currencies are introduced infrequently). Seeding once avoids a recurring startup dependency on provider availability. Operators who add a new provider and want an updated currency list can truncate the table and restart — a deliberate, visible action rather than a silent background process.

### Why separate `primary_provider` and `secondary_providers` in `RateService`?

The constructor signature makes intent explicit: there is one primary source and zero-or-more secondaries. This allows future work to add provider-specific weighting or fallback ordering without changing the aggregation interface.

---

## Known Limitations & Future Work

| Area | Current State | Potential Improvement |
|------|--------------|----------------------|
| **Authentication** | None — API is open | Add API key auth or OAuth2 before internet exposure |
| **Rate limiting** | None | Add per-client rate limiting (e.g. `slowapi`) |
| **Fixer.io free tier** | EUR base only | Upgrade to paid plan for arbitrary base currencies |
| **Rate freshness** | 5-minute TTL | Make TTL configurable; add WebSocket push for high-frequency clients |
| **Historical charts** | Frontend uses mock data | Wire `GET /api/rate/history` endpoint to `rate_history` table |
| **Currency re-seeding** | Manual (truncate + restart) | Add admin endpoint to trigger re-seed |
| **Observability** | Structured logging only | Add OpenTelemetry traces and a metrics endpoint |
| **Provider weighting** | Simple average | Weighted average based on provider reliability metrics |
| **Multi-region** | Single instance | Shard Redis by region; replicate PostgreSQL read-replicas |
