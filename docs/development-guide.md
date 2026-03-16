# Development Guide

Everything you need to set up a local environment, understand project conventions, run tests, and contribute new features.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local Setup](#local-setup)
3. [Running the Application](#running-the-application)
4. [Environment Variables](#environment-variables)
5. [Code Quality](#code-quality)
6. [Testing](#testing)
7. [Database Migrations](#database-migrations)
8. [Adding a New Provider](#adding-a-new-provider)
9. [Adding a New Endpoint](#adding-a-new-endpoint)
10. [Commit Conventions](#commit-conventions)
11. [Common Pitfalls](#common-pitfalls)

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12 | Backend runtime |
| Docker | Any recent | Infrastructure (Postgres, Redis) and full-stack runs |
| Docker Compose | v2+ | Multi-service orchestration |
| Node.js | 20+ | Frontend development |
| `uv` | Any | Fast Python package installer (`pip install uv`) |

API keys required (free tiers available):

- [Fixer.io](https://fixer.io/) — note: free tier only supports EUR as base currency
- [OpenExchangeRates](https://openexchangerates.org/)
- [CurrencyAPI](https://currencyapi.com/)

---

## Local Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/DanielPopoola/currency-converter.git
cd currency-converter/backend

python -m venv .venv
source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\activate           # Windows
```

### 2. Install dependencies

```bash
pip install uv
uv pip install -e .
```

The `-e` flag installs in editable mode so local code changes take effect without reinstalling.

### 3. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in at minimum:

```env
FIXERIO_API_KEY=your_fixer_key_here
OPENEXCHANGE_APP_ID=your_openexchange_id_here
CURRENCYAPI_KEY=your_currencyapi_key_here
```

The `DATABASE_URL` and `REDIS_URL` in `.env` use `localhost` — correct when running the API directly on your machine. Docker Compose overrides these to use container hostnames internally.

### 4. Start infrastructure

```bash
docker compose -f docker/docker-compose.yml up db redis -d
```

### 5. Run migrations

```bash
alembic upgrade head
```

### 6. Install pre-commit hooks

```bash
pip install pre-commit
pre-commit install
pre-commit install --hook-type commit-msg
```

---

## Running the Application

### API with hot-reload (recommended for backend work)

```bash
# From backend/
uvicorn api.main:app --reload
```

- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Frontend dev server

```bash
# From frontend/
npm install
npm run dev
```

- Frontend: http://localhost:5173

The frontend reads `VITE_API_URL` from environment (defaults to `http://localhost:8000`).

### Full stack via Docker Compose

```bash
docker compose -f backend/docker/docker-compose.yml up --build
```

Runs all four services (db, redis, api, frontend) together. Best for integration testing or demos.

---

## Environment Variables

All variables are loaded via `config/settings.py` using `pydantic-settings`. Unknown variables are silently ignored (via `extra='ignore'`).

| Variable | Default | Notes |
|----------|---------|-------|
| `FIXERIO_API_KEY` | `""` | Required in production |
| `OPENEXCHANGE_APP_ID` | `""` | Required in production |
| `CURRENCYAPI_KEY` | `""` | Required in production |
| `DATABASE_URL` | SQLite | Use `postgresql+asyncpg://...` for Postgres |
| `REDIS_URL` | `redis://localhost:6379` | |
| `APP_NAME` | `Currency Converter API` | Shown in Swagger UI title |
| `DEBUG` | `true` | Disables certain production guards |
| `CORS_ORIGINS` | localhost ports | Comma-separated list |

---

## Code Quality

### Linting and formatting (ruff)

```bash
# Check for issues
ruff check .

# Auto-fix issues where possible
ruff check . --fix

# Format code
ruff format .
```

Ruff is configured in `pyproject.toml`. It enforces: PEP 8 (E/W), pyflakes (F), pyupgrade (UP), bugbear (B), simplify (SIM), and isort (I).

### Security scanning (bandit)

Bandit runs automatically via pre-commit. To run manually:

```bash
bandit -r . -c pyproject.toml -x tests
```

### Pre-commit hooks

After running `pre-commit install`, the following hooks run on every `git commit`:

| Hook | What it checks |
|------|---------------|
| `trailing-whitespace` | No trailing spaces |
| `end-of-file-fixer` | Files end with a newline |
| `check-yaml` | Valid YAML |
| `check-json` | Valid JSON |
| `check-toml` | Valid TOML |
| `check-merge-conflict` | No unresolved merge conflict markers |
| `debug-statements` | No `pdb`/`breakpoint()` left in code |
| `ruff` | Lint + auto-fix |
| `ruff-format` | Auto-format |
| `bandit` | Security scan |
| `commitizen` | Conventional commit message format |

To run all hooks manually against staged files:

```bash
pre-commit run
```

To run against all files (not just staged):

```bash
pre-commit run --all-files
```

---

## Testing

### Run the test suite

```bash
# From backend/
pytest

# With verbose output
pytest -v

# Stop on first failure
pytest -x

# With coverage report
pytest --cov=. --cov-report=html
open htmlcov/index.html

# Run a specific file or test
pytest tests/unit/infrastructure/providers/test_fixerio.py
pytest tests/unit/infrastructure/providers/test_fixerio.py::test_fetch_rate_success_returns_decimal
```

### Test structure

```
tests/
└── unit/
    └── infrastructure/
        ├── cache/
        │   └── test_redis_cache.py      # RedisCacheService tests
        └── providers/
            └── test_fixerio.py          # FixerIOProvider tests
```

### How tests are structured

All tests are async (`asyncio_mode = "auto"` in `pyproject.toml`). No `@pytest.mark.asyncio` decorators needed.

**Provider tests** inject a mock `httpx.AsyncClient`:

```python
async def test_fetch_rate_success_returns_decimal():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_response = Mock()
    mock_response.json.return_value = {
        "success": True,
        "rates": {"EUR": 0.85}
    }
    mock_response.raise_for_status = Mock()
    mock_client.get.return_value = mock_response

    provider = FixerIOProvider(api_key="test_key", client=mock_client)
    rate = await provider.fetch_rate("USD", "EUR")

    assert rate == Decimal("0.85")
    assert isinstance(rate, Decimal)
```

**Cache tests** inject a mock Redis client:

```python
async def test_get_rate_cache_hit_returns_exchange_rate():
    mock_redis = AsyncMock()
    cached_data = json.dumps({
        "from_currency": "USD", "to_currency": "EUR",
        "rate": "0.85", "timestamp": "2025-11-05T10:30:00", "source": "fixerio"
    })
    mock_redis.get.return_value = cached_data

    cache = RedisCacheService(redis_client=mock_redis)
    result = await cache.get_rate("USD", "EUR")

    assert result.rate == Decimal("0.85")
```

### Writing new tests

When adding a new feature:

1. Create a test file mirroring the source path under `tests/unit/`.
2. Mock at the infrastructure boundary (HTTP clients, Redis client), never at the service layer.
3. Test happy paths, error paths, and edge cases (empty responses, malformed JSON, network timeouts).
4. Assert on types as well as values — `assert isinstance(rate, Decimal)` prevents silent float regressions.

---

## Database Migrations

Alembic manages all schema changes. Migration files are committed to the repository — they are **never** generated at runtime.

### Workflow

```bash
# 1. Modify an ORM model in infrastructure/persistence/models/currency.py
# 2. Generate a migration file
alembic revision --autogenerate -m "add index_on_source_to_rate_history"

# 3. Review the generated file in alembic/versions/
#    Autogenerate is good but not perfect — always check it captured your intent

# 4. Apply the migration
alembic upgrade head
```

### Useful commands

```bash
alembic current          # show which revision is applied to the DB
alembic history          # list all migrations in order
alembic downgrade -1     # roll back the most recent migration
alembic downgrade base   # roll back all migrations (destructive!)
```

### Rules

- **Never** run `alembic revision --autogenerate` on an unchanged schema. It generates an empty migration file that pollutes the history.
- **Never** run `alembic revision --autogenerate` inside `entrypoint.sh` or any startup script. The entrypoint only applies migrations (`alembic upgrade head`). Files are authored by developers.
- **Always** review generated files before applying them.

---

## Adding a New Provider

Follow these steps to integrate a fourth exchange rate provider.

### 1. Create the provider class

Create `infrastructure/providers/yourprovider.py`:

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
        # Make an HTTP request, parse the response, return Decimal
        # Raise ProviderError on any failure
        ...

    async def fetch_supported_currencies(self) -> list[dict]:
        # Return [{"code": "USD", "name": "US Dollar"}, ...]
        # Raise ProviderError on any failure
        ...

    async def close(self) -> None:
        await self._client.aclose()
```

Key requirements:
- Always construct `Decimal` from strings: `Decimal(str(float_value))`, never `Decimal(float_value)`.
- Raise `ProviderError` (from `domain.exceptions.currency`) on all failures.
- Accept an optional injected `httpx.AsyncClient` for testability.

### 2. Export the provider

In `infrastructure/providers/__init__.py`:

```python
from .yourprovider import YourProvider
```

### 3. Add the API key to settings

In `config/settings.py`:

```python
YOUR_API_KEY: str = ""
```

Add it to `backend/.env.example`:

```env
YOUR_API_KEY=your_key_here
```

### 4. Register the provider

In `api/dependencies.py`, add to `deps.providers`:

```python
deps.providers = {
    "fixerio": FixerIOProvider(settings.FIXERIO_API_KEY),
    "openexchange": OpenExchangeProvider(settings.OPENEXCHANGE_APP_ID),
    "currencyapi": CurrencyAPIProvider(settings.CURRENCYAPI_KEY),
    "yourprovider": YourProvider(settings.YOUR_API_KEY),  # ← add here
}
```

`RateService` and `CurrencyService` both receive the full providers dict and will automatically include the new provider in aggregation and currency seeding.

### 5. Write tests

Create `tests/unit/infrastructure/providers/test_yourprovider.py`. Cover:

- Successful rate fetch returns correct `Decimal`
- API error response raises `ProviderError`
- Missing rate in response raises `ProviderError`
- HTTP 4xx/5xx raises `ProviderError`
- Network timeout raises `ProviderError`
- `fetch_supported_currencies` returns correct format

### Note on currency re-seeding

Adding a provider only expands the supported currency intersection on a **fresh database** (empty `supported_currencies` table). Existing deployments retain their current list. To trigger a re-seed, truncate the `supported_currencies` table and restart the API.

---

## Adding a New Endpoint

The chain is always: **route → service → repository**. No layer is skipped.

### 1. Define response schema

In `api/schemas/responses.py`:

```python
class RateHistoryResponse(BaseModel):
    from_currency: str
    to_currency: str
    rates: list[HistoricalRateItem]
```

### 2. Add service method

In the appropriate service in `application/services/`:

```python
async def get_rate_history(
    self, from_currency: str, to_currency: str, since: datetime
) -> list[ExchangeRate]:
    await self.currency_service.validate_currency(from_currency)
    await self.currency_service.validate_currency(to_currency)
    return await self.repository.get_rate_history(from_currency, to_currency, since)
```

### 3. Add repository method (if new DB access needed)

In `infrastructure/persistence/repositories/currency.py`:

```python
async def get_rate_history(
    self, from_currency: str, to_currency: str,
    since: datetime, limit: int = 100
) -> list[ExchangeRate]:
    stmt = (
        select(RateHistoryDB)
        .filter(
            RateHistoryDB.from_currency == from_currency,
            RateHistoryDB.to_currency == to_currency,
            RateHistoryDB.timestamp >= since,
        )
        .order_by(RateHistoryDB.timestamp.desc())
        .limit(limit)
    )
    result = await self.db_session.execute(stmt)
    return [
        ExchangeRate(
            from_currency=r.from_currency,
            to_currency=r.to_currency,
            rate=r.rate,
            timestamp=r.timestamp,
            source=r.source or "unknown",
        )
        for r in result.scalars().all()
    ]
```

### 4. Add the route

In `api/routes/currency.py`:

```python
@router.get(
    "/rate/{from_currency}/{to_currency}/history",
    response_model=RateHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get rate history for a currency pair",
)
async def get_rate_history(
    from_currency: str,
    to_currency: str,
    service: Annotated[RateService, Depends(get_rate_service)],
) -> RateHistoryResponse:
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()
    rates = await service.get_rate_history(from_currency, to_currency)
    return RateHistoryResponse(from_currency=from_currency, to_currency=to_currency, rates=rates)
```

---

## Commit Conventions

This project uses [Conventional Commits](https://www.conventionalcommits.org/). The `commitizen` pre-commit hook enforces this format:

```
<type>(<optional scope>): <description>

[optional body]
```

Common types:

| Type | When to use |
|------|-------------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `docs` | Documentation only changes |
| `chore` | Build process, dependency updates, tooling |
| `ci` | CI/CD pipeline changes |

Examples:

```
feat(providers): add CoinGecko exchange rate provider
fix(cache): handle malformed JSON from Redis without crashing
test(rate_service): add test for all-providers-fail scenario
docs: update API reference with history endpoint
```

---

## Common Pitfalls

**`Decimal` precision loss**
Always construct from a string: `Decimal(str(api_float_value))`. Never `Decimal(0.85)` — floating-point representation errors will silently corrupt rate calculations.

**Holding sessions too long**
Never store an `AsyncSession` in an instance variable. Sessions are per-request resources managed by `get_db_session()`. Holding one open across multiple requests causes connection pool exhaustion.

**Running autogenerate on unchanged schema**
`alembic revision --autogenerate` generates a diff between your models and the live DB. If nothing changed, it creates an empty migration file. Delete it and don't apply it.

**Provider free-tier limits**
Fixer.io's free tier supports only EUR as the base currency. If you need arbitrary base currencies locally, use OpenExchangeRates or CurrencyAPI as your primary test provider.

**Forgetting `asyncio_mode = "auto"`**
The project uses `pytest-asyncio` in auto mode. All test functions are implicitly async. Adding `@pytest.mark.asyncio` is harmless but unnecessary. Mixing sync test helpers that block the event loop will cause intermittent test hangs.

**Currency re-seeding after adding a provider**
Supported currencies are only fetched from providers once (when `supported_currencies` is empty). After adding a new provider, truncate the table and restart to pick up the new intersection.
