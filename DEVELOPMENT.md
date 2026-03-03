# Development Guide
## Currency Converter API

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local Setup](#local-setup)
3. [Project Structure](#project-structure)
4. [Configuration](#configuration)
5. [Running the Application](#running-the-application)
6. [Testing](#testing)
7. [Code Quality](#code-quality)
8. [Adding a New Provider](#adding-a-new-provider)
9. [Adding a New Endpoint](#adding-a-new-endpoint)
10. [Database Migrations](#database-migrations)
11. [CI/CD Pipeline](#cicd-pipeline)
12. [Common Pitfalls](#common-pitfalls)

---

## Prerequisites

- Python 3.12
- Docker & Docker Compose (for local infrastructure)
- API keys for all three providers:
  - [Fixer.io](https://fixer.io/) — free tier available
  - [OpenExchangeRates](https://openexchangerates.org/) — free tier available
  - [CurrencyAPI](https://currencyapi.com/) — free tier available

---

## Local Setup

### 1. Clone and create virtual environment
```bash
git clone https://github.com/yourorg/currency-converter.git
cd currency-converter
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment variables
```bash
cp .env.example .env
```

Edit `.env` and fill in your API keys:
```env
FIXERIO_API_KEY=your_key_here
OPENEXCHANGE_APP_ID=your_id_here
CURRENCYAPI_KEY=your_key_here

DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/currency_converter
REDIS_URL=redis://localhost:6379/0
```

### 3. Start infrastructure (Postgres + Redis)
```bash
docker-compose -f docker/docker-compose.yml up -d
```

### 4. Run database migrations
```bash
alembic upgrade head
```

### 5. Start the API server
```bash
uvicorn api.main:app --reload
```

API is now available at `http://localhost:8000`. Swagger UI at `http://localhost:8000/docs`.

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
│   ├── currency_service.py      # Supported currencies + validation
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
├── config/settings.py           # Pydantic Settings (env vars)
├── tests/
└── docker/
```

---

## Configuration

All config lives in `config/settings.py` using `pydantic-settings`. Values are read from environment variables or a `.env` file.
```python
class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    FIXERIO_API_KEY: str
    OPENEXCHANGE_APP_ID: str
    CURRENCYAPI_KEY: str
    APP_NAME: str = "Currency Converter API"
    DEBUG: bool = True

    model_config = SettingsConfigDict(env_file='.env', case_sensitive=False, extra='ignore')
```

`get_settings()` is decorated with `@lru_cache` so the settings object is only created once per process.

> Never hardcode secrets. Always use the `.env` file locally and proper secret injection in production.

---

## Running the Application

### With Docker Compose (recommended for full stack)
```bash
docker-compose -f docker/docker-compose.yml up --build
```

This starts Postgres, Redis, runs migrations via `entrypoint.sh`, and starts the API.

### Locally (API only, with Docker infra)
```bash
# Start only infra
docker-compose -f docker/docker-compose.yml up -d db redis

# Run API locally
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
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
        ├── cache/test_redis_cache.py       # RedisCacheService unit tests
        └── providers/test_fixerio.py       # FixerIOProvider unit tests
```

### How provider tests work

Providers accept an injected `httpx.AsyncClient`, so tests mock at the HTTP level without making real network calls:
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

`RedisCacheService` accepts an injected Redis client, so tests mock at the Redis level:
```python
mock_redis = AsyncMock()
mock_redis.get.return_value = json.dumps({...})
cache = RedisCacheService(redis_client=mock_redis)
result = await cache.get_rate('USD', 'EUR')
```

### pytest configuration

`pyproject.toml` sets `asyncio_mode = "auto"` so all async test functions run without needing `@pytest.mark.asyncio` (though it's still used for clarity in existing tests).

---

## Code Quality

### Linting & formatting (ruff)
```bash
ruff check .          # lint
ruff check . --fix    # auto-fix
ruff format .         # format
```

### Type checking (mypy)
```bash
mypy --config-file=pyproject.toml --package=api --package=application --package=domain --package=infrastructure
```

### Pre-commit hooks

Install once:
```bash
pip install pre-commit
pre-commit install
pre-commit install --hook-type commit-msg   # for commitizen
```

Hooks run automatically on `git commit` and enforce: trailing whitespace, ruff lint+format, mypy, bandit security scan, and conventional commit message format.

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

    async def fetch_supported_currencies(self) -> list[dict]:
        # return [{"code": "USD", "name": "US Dollar"}, ...]
        # raise ProviderError on any failure

    async def close(self) -> None:
        await self._client.aclose()
```

2. Export from `infrastructure/providers/__init__.py`:
```python
from .yourprovider import YourProvider
```

3. Register in `api/dependencies.py`:
```python
deps.providers = {
    'fixerio': FixerIOProvider(settings.FIXERIO_API_KEY),
    'openexchange': OpenExchangeProvider(settings.OPENEXCHANGE_APP_ID),
    'currencyapi': CurrencyAPIProvider(settings.CURRENCYAPI_KEY),
    'yourprovider': YourProvider(settings.YOUR_API_KEY),   # ← add here
}
```

4. Add the key to `config/settings.py`:
```python
YOUR_API_KEY: str = ''
```

5. Write unit tests in `tests/unit/infrastructure/providers/test_yourprovider.py` following the existing pattern.

That's it. `RateService` picks up the new provider automatically from the `providers` dict.

---

## Adding a New Endpoint

1. Add the route to `api/routes/currency.py`:
```python
@router.get('/history/{from_currency}/{to_currency}', response_model=RateHistoryResponse)
async def get_rate_history(
    from_currency: Annotated[str, Path(min_length=3, max_length=5)],
    to_currency: Annotated[str, Path(min_length=3, max_length=5)],
    service: Annotated[RateService, Depends(get_rate_service)],
) -> RateHistoryResponse:
    ...
```

2. Add request/response schemas to `api/schemas/`.

3. Add service method to the appropriate service in `application/services/`.

4. If the service needs new data access, add a method to `infrastructure/persistence/repositories/currency.py`.

Follow the existing chain: route → service → repository.

---

## Database Migrations

This project uses Alembic for schema migrations.
```bash
# Create a new migration after changing ORM models
alembic revision --autogenerate -m "describe your change"

# Apply all pending migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

> The `entrypoint.sh` script runs `alembic upgrade head` automatically on container startup.

---

## CI/CD Pipeline

`.github/workflows/main.yml` runs on every push and pull request to `master`.

### `lint-and-test` job

1. Spins up Postgres and Redis as GitHub Actions services
2. Installs Python dependencies
3. Runs `ruff check .` — fails fast on lint errors
4. Runs `alembic upgrade head` on the test database
5. Runs `pytest`

### `build-and-push` job (master only)

1. Runs after `lint-and-test` passes
2. Builds the Docker image
3. Pushes to GitHub Container Registry (GHCR) with two tags:
   - `ghcr.io/org/repo:latest`
   - `ghcr.io/org/repo:{git-sha}`

> Pull requests only run `lint-and-test`. The Docker push only happens on merges to `master`.

---

## Common Pitfalls

**`Decimal` precision loss** — Always convert float API responses to `Decimal` via `str` first: `Decimal(str(float_value))`, never `Decimal(float_value)`. The providers already do this correctly.

**Session lifecycle** — Never hold an `AsyncSession` open longer than a single request. The `get_db_session()` dependency manages commit/rollback/close automatically.

**Cache invalidation** — There is no explicit cache invalidation. Rates expire after 5 minutes naturally. If you need to force-refresh a rate, delete the key manually: `redis-cli DEL rate:USD:EUR`.

**Bootstrap failure** — If providers are unreachable at startup (e.g., bad API keys), the app will raise `ProviderError` and exit. Check your `.env` keys first.

**`asyncio_mode = "auto"` in tests** — All test functions in this project are run as async automatically. Don't mix sync and async test helpers without being intentional about it.

**Provider free-tier limits** — Fixer.io's free tier only supports EUR as the base currency. If you're testing with other base currencies locally, use OpenExchange or CurrencyAPI as your primary during development.
