# Currency Converter API

A production-ready currency conversion service built with FastAPI that aggregates exchange rates from multiple providers to ensure reliability and accuracy.

## 🎯 Overview

This service provides real-time currency conversion with automatic fallback between multiple exchange rate providers. It implements a clean 4-layer architecture with Redis caching and PostgreSQL persistence for historical data tracking.

### Key Features

- **Multi-Provider Aggregation**: Fetches rates from 3 providers (Fixer.io, OpenExchange, CurrencyAPI) and returns averaged results
- **Automatic Fallback**: If one provider fails, seamlessly falls back to others
- **Smart Caching**: Redis cache with 5-minute TTL to minimize API calls
- **Rate History**: PostgreSQL stores all fetched rates for historical analysis
- **Retry Logic**: Exponential backoff for transient network errors
- **Currency Validation**: Only supports currencies available across ALL providers
- **Type Safety**: Full type hints with Pydantic validation

## 🏗️ Architecture

### Layered Design

The project follows a strict 4-layer architecture where each layer only communicates with the layer directly below it:

```
┌─────────────────────────────────────┐
│   API Layer (FastAPI Routes)       │  ← HTTP endpoints, request/response
├─────────────────────────────────────┤
│   Application Layer (Services)     │  ← Business logic, orchestration
├─────────────────────────────────────┤
│   Domain Layer (Models)            │  ← Core entities, exceptions
├─────────────────────────────────────┤
│   Infrastructure Layer             │  ← External services, database
│   (Providers, Cache, Repository)   │
└─────────────────────────────────────┘
```

### Request Flow

```
1. Client Request
   ↓
2. API Layer validates input (Pydantic)
   ↓
3. Application Service checks currency validity
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

## 📂 Project Structure

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
│       ├── currency_service.py  # Currency validation & initialization
│       ├── rate_service.py      # Rate fetching & aggregation
│       └── conversion_service.py # Amount conversion logic
│
├── domain/
│   ├── models/
│   │   └── currency.py          # Core entities (frozen dataclasses)
│   └── exceptions/
│       └── currency.py          # Domain-specific exceptions
│
├── infrastructure/
│   ├── providers/
│   │   ├── base.py              # Provider protocol (interface)
│   │   ├── fixerio.py           # Fixer.io integration
│   │   ├── openexchange.py      # OpenExchange integration
│   │   └── currencyapi.py       # CurrencyAPI integration
│   ├── cache/
│   │   └── redis_cache.py       # Redis caching service
│   └── persistence/
│       ├── database.py          # SQLAlchemy async session
│       ├── models/
│       │   └── currency.py      # Database tables
│       └── repositories/
│           └── currency.py      # Data access layer
│
├── config/
│   └── settings.py              # Environment configuration
│
└── docker/
    ├── docker-compose.yml       # Container orchestration
    ├── .env.example             # Environment variables template
    └── entrypoint.sh            # Database migration script
```

## 🚀 Getting Started

### Prerequisites

- Docker & Docker Compose
- API keys for currency providers:
  - [Fixer.io](https://fixer.io/) (free tier available)
  - [OpenExchange](https://openexchangerates.org/) (free tier available)
  - [CurrencyAPI](https://currencyapi.com/) (free tier available)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/currency-converter.git
   cd currency-converter
   ```

2. **Configure environment variables**
   ```bash
   cp docker/.env.example docker/.env
   ```

   Edit `docker/.env` and add your API keys:
   ```env
   FIXERIO_API_KEY=your_fixer_key_here
   OPENEXCHANGE_APP_ID=your_openexchange_key_here
   CURRENCYAPI_KEY=your_currencyapi_key_here

   DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/currency_converter
   REDIS_URL=redis://redis:6379/0
   ```

3. **Start the services**
   ```bash
   docker-compose -f docker/docker-compose.yml up --build
   ```

   This will:
   - Start PostgreSQL database
   - Start Redis cache
   - Run database migrations (Alembic)
   - Initialize supported currencies from providers
   - Start the FastAPI server on port 8000

4. **Verify it's running**
   ```bash
   curl http://localhost:8000/docs
   ```
   You should see the Swagger UI documentation.

## 📡 API Endpoints

### Base URL: `http://localhost:8000`

### 1. Convert Currency

Convert an amount from one currency to another.

**Endpoint:** `POST /api/convert`

**Request Body:**
```json
{
  "from_currency": "USD",
  "to_currency": "EUR",
  "amount": 100.00
}
```

**Response:**
```json
{
  "from_currency": "USD",
  "to_currency": "EUR",
  "original_amount": 100.00,
  "converted_amount": 92.50,
  "exchange_rate": 0.925,
  "timestamp": "2025-11-01T14:30:00Z",
  "source": "averaged"
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/api/convert \
  -H "Content-Type: application/json" \
  -d '{"from_currency": "USD", "to_currency": "EUR", "amount": 100}'
```

### 2. Get Exchange Rate

Fetch the current exchange rate between two currencies.

**Endpoint:** `GET /api/rate/{from_currency}/{to_currency}`

**Response:**
```json
{
  "from_currency": "USD",
  "to_currency": "JPY",
  "rate": 149.85,
  "timestamp": "2025-11-01T14:30:00Z",
  "source": "averaged"
}
```

**Example:**
```bash
curl http://localhost:8000/api/rate/USD/JPY
```

### 3. API Documentation

Interactive API documentation is available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 🔧 How It Works

### Multi-Provider Strategy

The service queries **all 3 providers** in parallel for every request:

1. **Parallel Fetch**: Uses `asyncio.gather()` to fetch from all providers simultaneously
2. **Error Tolerance**: If a provider fails, it's excluded from averaging
3. **Rate Averaging**: Takes the mean of all successful responses
4. **Source Tracking**: Records which providers contributed to the final rate

**Example:**
- Fixer.io returns: `1.2500`
- OpenExchange returns: `1.2520`
- CurrencyAPI fails (timeout)
- **Final averaged rate**: `(1.2500 + 1.2520) / 2 = 1.2510`

### Caching Strategy

```python
# On first request: USD/EUR
1. Check Redis cache → MISS
2. Fetch from all providers (parallel)
3. Average the results
4. Store in Redis (TTL: 5 minutes)
5. Store in PostgreSQL (permanent history)
6. Return to client

# Subsequent requests within 5 minutes: USD/EUR
1. Check Redis cache → HIT
2. Return cached rate immediately (no provider calls)
```

### Supported Currencies

At startup, the service:
1. Fetches all supported currencies from each provider
2. Calculates the **intersection** (only currencies ALL providers support)
3. Stores the result in PostgreSQL
4. Caches in Redis (TTL: 24 hours)

This ensures you can only request currency pairs that all providers can serve, preventing partial failures.

## 🛡️ Error Handling

The API uses specific HTTP status codes:

| Status Code | Meaning | Example |
|-------------|---------|---------|
| `200` | Success | Conversion completed |
| `400` | Invalid input | Unsupported currency code |
| `503` | Service unavailable | All providers are down |
| `500` | Internal error | Unexpected server error |

**Example Error Response:**
```json
{
  "detail": "Currency XYZ is not supported"
}
```

## ⚙️ Configuration

All configuration is done via environment variables in `docker/.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `FIXERIO_API_KEY` | Fixer.io API key | Required |
| `OPENEXCHANGE_APP_ID` | OpenExchange app ID | Required |
| `CURRENCYAPI_KEY` | CurrencyAPI key | Required |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://...` |
| `REDIS_URL` | Redis connection string | `redis://redis:6379/0` |

## 🧪 Testing

### Run Tests
```bash
pytest
```

### Test Coverage
```bash
pytest --cov=. --cov-report=html
```

### Manual Testing

Use the provided Swagger UI at http://localhost:8000/docs to test all endpoints interactively.

## 📊 Database Schema

### Tables

**supported_currencies**
```sql
CREATE TABLE supported_currencies (
    code VARCHAR(5) PRIMARY KEY,
    name VARCHAR(100)
);
```

**rate_history**
```sql
CREATE TABLE rate_history (
    id SERIAL PRIMARY KEY,
    from_currency VARCHAR(5) NOT NULL,
    to_currency VARCHAR(5) NOT NULL,
    rate DECIMAL(18, 6) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    source VARCHAR(50) NOT NULL,
    UNIQUE(from_currency, to_currency, timestamp)
);
```

## 🔍 Monitoring & Logs

The application uses structured logging. All logs are output to stdout in JSON format:

```json
{
  "timestamp": "2025-11-01T14:30:00Z",
  "level": "INFO",
  "message": "Cache HIT: USD/EUR"
}
```

### Key Log Events

- `Cache HIT/MISS`: Indicates cache performance
- `Provider {name} failed`: Provider-specific errors
- `All providers failed`: Critical error requiring attention
- `Saved N supported currencies`: Startup initialization

## 🚧 Development

### Local Development (without Docker)

1. Install dependencies:
   ```bash
   poetry add
   ```

2. Start PostgreSQL and Redis locally

3. Run migrations:
   ```bash
   alembic upgrade head
   ```

4. Start the server:
   ```bash
   uvicorn api.main:app --reload
   ```

### Adding a New Provider

1. Create a new file in `infrastructure/providers/`:
   ```python
   # infrastructure/providers/newprovider.py
   class NewProvider:
       @property
       def name(self) -> str:
           return "newprovider"

       async def fetch_rate(self, from_currency: str, to_currency: str) -> Decimal:
           # Implementation

       async def fetch_supported_currencies(self) -> list[dict]:
           # Implementation
   ```

2. Register in `api/dependencies.py`:
   ```python
   deps.providers = {
       'fixerio': FixerIOProvider(...),
       'openexchange': OpenExchangeProvider(...),
       'newprovider': NewProvider(...),  # Add here
   }
   ```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License.

## 🙏 Acknowledgments

- [FastAPI](https://fastapi.tiangolo.com/) for the excellent web framework
- [Fixer.io](https://fixer.io/), [OpenExchange](https://openexchangerates.org/), [CurrencyAPI](https://currencyapi.com/) for providing exchange rate data
