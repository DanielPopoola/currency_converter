# Development Guide
## Currency Converter API

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local Setup](#local-setup)
3. [Project Structure](#project-structure)
4. [Running the Application](#running-the-application)
5. [Testing](#testing)
6. [Code Quality](#code-quality)
7. [Adding a New Provider](#adding-a-new-provider)
8. [Adding a New Endpoint](#adding-a-new-endpoint)
9. [Database Migrations](#database-migrations)
10. [CI/CD Pipeline](#cicd-pipeline)
11. [Common Pitfalls](#common-pitfalls)

---

## Prerequisites

- Python 3.12
- Docker & Docker Compose
- `uv` — fast Python package installer (`pip install uv`)
- API keys for all three providers:
  - [Fixer.io](https://fixer.io/) — free tier available (EUR base only)
  - [OpenExchangeRates](https://openexchangerates.org/) — free tier available
  - [CurrencyAPI](https://currencyapi.com/) — free tier available

---

## Local Setup

### 1. Clone and create virtual environment
```bash
git clone https://github.com/yourorg/currency-converter.git
cd currency-converter
python -m venv .venv
source .venv/bin/activate
uv pip install -e .
```

### 2. Configure environment variables
```bash
cp .env.example .env
```

Edit `.env` and fill in your API keys. The `DATABASE_URL` and `REDIS_URL` in `.env` use `localhost` — this is correct for running the API directly on your machine. Docker overrides these two values internally to point at the named services (`db`, `redis`).

### 3. Start infrastructure (Postgres + Redis)
```bash
docker compose -f docker/docker-compose.yml up db redis -d
```

### 4. Run database migrations
```bash
alembic upgrade head
```

### 5. Start the API server
```bash
uvicorn api.main:app --reload
```

API available at `http://localhost:8000`. Swagger UI at `http://localhost:8000/docs`.

---

## Project Structure
```
.
├── api/
│   ├── routes/currency.py       # HTTP endpoints
│   ├── schemas/
│   │   ├── requests.py          # Pydantic input validation
│   │   └── responses.py         # Pydantic response models
│   ├── dependencies.py          # FastAPI Depends() wiring
│   ├── error_handlers.py        # Exception → HTTP status mapping
│   └── main.py                  # App factory, lifespan, startup
│
├── application/services/
│   ├── currency_service.py      # Supported currencies + validation + seeding
│   ├── rate_service.py          # Rate fetching + aggregation
│   └── conversion_service.py   # Conversion orchestration
│
├── domain/
│   ├── models/currency.py       # ExchangeRate, SupportedCurrency, AggregatedRate
│   └── exceptions/currency.py  # InvalidCurrencyError, ProviderError, CacheError
│
├── infrastructure/
│   ├── providers/
│   │   ├── base.py              # ExchangeRateProvider Protocol
│   │   ├── fixerio.py
│   │   ├── openexchange.py
│   │   └── currencyapi.py
│   ├── cache/redis_cache.py
│   └── persistence/
│       ├── database.py
│       ├── models/currency.py   # SQLAlchemy ORM models
│       └── repositories/currency.py
│
├── alembic/                     # Migration scripts
│   ├── versions/
│   │   └── 0001_initial_tables.py
│   └── env.py
│
├── alembic.ini
├── config/settings.py
├── Dockerfile
└── docker/
    ├── docker-compose.yml
    └── entrypoint.sh
```

---

## Running the Application

### Full stack with Docker (recommended)
```bash
docker compose -f docker/docker-compose.yml up --build
```

On first startup: migrations run, currencies are seeded from providers, API starts.
On subsequent startups: migrations are a no-op, currencies are read from DB, API starts.

### Locally (API only, Docker for infra)
```bash
docker compose -f docker/docker-compose.yml up db redis -d
alembic upgrade head
uvicorn api.main:app --reload
```

---

## Testing

### Run all tests
```bash
pytest
```

### Run with coverage
```bash
pytest --cov=. --cov-report=html
open htmlcov/index.html
```

### Test structure
```
tests/
└── unit/
    └── infrastructure/
        ├── cache/test_redis_cache.py
        └── providers/test_fixerio.py
```

### How provider tests work

Providers accept an injected `httpx.AsyncClient`, so tests mock at the HTTP level:
```python
mock_client = AsyncMock(spec=httpx.AsyncClient)
mock_response = Mock()
mock_response.json.return_value = {"success": True, "rates": {"EUR": 0.85}}
mock_response.raise_for_status = Mock()
mock_client.get.return_value = mock_response

provider = FixerIOProvider(api_key='test_key', client=mock_client)
rate = await provider.fetch_rate('USD', 'EUR')
assert rate == Decimal('0.85')
```

### How cache tests work

`RedisCacheService` accepts an injected Redis client:
```python
mock_redis = AsyncMock()
mock_redis.get.return_value = json.dumps({...})
cache = RedisCacheService(redis_client=mock_redis)
result = await cache.get_rate('USD', 'EUR')
```

---

## Code Quality

### Linting & formatting (ruff)
```bash
ruff check .
ruff check . --fix
ruff format .
```

### Pre-commit hooks

Install once:
```bash
pip install pre-commit
pre-commit install
pre-commit install --hook-type commit-msg
```

Hooks enforce: trailing whitespace, ruff lint+format, mypy, bandit, conventional commit messages.

---

## Adding a New Provider

1. Create `infrastructure/providers/yourprovider.py`:
```python
from decimal import Decimal
import httpx
from domain.exceptions.currency import ProviderError

class YourProvider:
    BASE_URL = "https://api.yourprovider.com/v1"

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=10)

    @property
    def name(self) -> str:
        return "yourprovider"

    async def fetch_rate(self, from_currency: str, to_currency: str) -> Decimal:
        # fetch and return Decimal rate
        # raise ProviderError on any failure
        ...

    async def fetch_supported_currencies(self) -> list[dict]:
        # return [{"code": "USD", "name": "US Dollar"}, ...]
        # raise ProviderError on any failure
        ...

    async def close(self) -> None:
        await self._client.aclose()
```

2. Export from `infrastructure/providers/__init__.py`.

3. Add the API key to `config/settings.py`:
```python
YOUR_API_KEY: str = ''
```

4. Register in `api/dependencies.py`:
```python
deps.providers = {
    'fixerio': FixerIOProvider(settings.FIXERIO_API_KEY),
    'openexchange': OpenExchangeProvider(settings.OPENEXCHANGE_APP_ID),
    'currencyapi': CurrencyAPIProvider(settings.CURRENCYAPI_KEY),
    'yourprovider': YourProvider(settings.YOUR_API_KEY),  # ← add here
}
```

`RateService` and `CurrencyService` both receive the full providers dict and will automatically include the new provider in rate aggregation and currency seeding.

5. Write unit tests in `tests/unit/infrastructure/providers/test_yourprovider.py`.

> **Note:** Adding a new provider will expand the intersection of supported currencies on the **next fresh database** (or if you clear the `supported_currencies` table). Existing deployments won't re-seed automatically.

---

## Adding a New Endpoint

1. Add route to `api/routes/currency.py`
2. Add request/response schemas to `api/schemas/`
3. Add method to the relevant service in `application/services/`
4. If new data access is needed, add a method to `infrastructure/persistence/repositories/currency.py`

Chain is always: route → service → repository.

---

## Database Migrations

Alembic manages all schema changes. The `env.py` reads `DATABASE_URL` from the environment, so always ensure it's set before running migration commands.

### Workflow

```bash
# After changing an ORM model in infrastructure/persistence/models/
alembic revision --autogenerate -m "describe what changed"

# Always review the generated file in alembic/versions/ before applying
# Autogenerate is good but not perfect — check it caught everything

alembic upgrade head
```

### Other useful commands
```bash
alembic current        # show current revision in the DB
alembic history        # list all migrations
alembic downgrade -1   # roll back one migration
```

### Rules
- **Never** run `alembic revision --autogenerate` unless you have actually changed a model. It is not a sync command — it generates a diff file. Running it on an unchanged schema produces an empty migration that clutters the history.
- **Never** run `alembic revision --autogenerate` in `entrypoint.sh` or any startup script. The entrypoint only runs `alembic upgrade head` (applies existing migrations). Migration *files* are created by developers and committed to the repo.

---

## CI/CD Pipeline

`.github/workflows/main.yml` runs on every push and pull request to `master`.

### `lint-and-test` job

1. Spins up Postgres 15 and Redis 6 as GitHub Actions services
2. Installs dependencies via `uv pip install --system -e .`
3. Runs `ruff check .`
4. Runs `alembic upgrade head` against the test database
5. Runs `pytest`

### `build-and-push` job (master only)

Runs after `lint-and-test` passes, builds the Docker image and pushes to GitHub Container Registry with two tags: `latest` and the git SHA.

---

## Common Pitfalls

**`Decimal` precision loss** — Always convert float API responses via `str` first: `Decimal(str(float_value))`, never `Decimal(float_value)`. The providers already do this correctly.

**Session lifecycle** — Never hold an `AsyncSession` open longer than a single request. `get_db_session()` manages commit/rollback/close automatically.

**Currency re-seeding** — Supported currencies are only fetched from providers once (when the DB is empty). If you add a provider and want to re-seed, truncate the `supported_currencies` table and restart the app.

**`asyncio_mode = "auto"` in tests** — All test functions run as async automatically. Don't mix sync and async test helpers without being intentional about it.

**Provider free-tier limits** — Fixer.io's free tier only supports EUR as the base currency. Use OpenExchange or CurrencyAPI as primary during local development if you need other base currencies.

**Running autogenerate on an unchanged schema** — This generates an empty migration file. Delete it and do not apply it. See the Migrations section above.
