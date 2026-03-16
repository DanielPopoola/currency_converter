# Currency Converter API
## What It Does & How It Works

---

## What Is This?

The Currency Converter API is a web service that answers one simple question: **"How much is X amount of currency A worth in currency B right now?"**

For example: *"How much is 500 US Dollars worth in Nigerian Naira right now?"*

You send a request, it responds with the converted amount and the exchange rate used.

---

## The Problem It Solves

Exchange rates change constantly — sometimes by the minute. Any single source of exchange rate data can have outages, inaccuracies, or go temporarily unavailable. A service that relies on just one source will fail when that source fails, and may give incorrect rates if that source has bad data.

This service solves that by using **three different exchange rate sources at once**:

- **Fixer.io**
- **OpenExchangeRates**
- **CurrencyAPI**

It fetches the rate from all three simultaneously, averages the results, and returns that averaged rate. If one source is having problems, the other two carry on without any disruption to the user.

---

## Core Features

### Multi-Source Rate Aggregation

Rather than trusting a single exchange rate provider, the service asks all three at the same time and averages their responses. This provides a more accurate, balanced rate and means the service keeps working even if one provider goes down.

### Automatic Fallback

If one or even two providers fail at the same moment, the service continues using whoever is available. Only if all three fail simultaneously does the service report that it cannot fulfill the request.

### Smart Caching

Exchange rates don't change every single second. To avoid hammering external providers with thousands of unnecessary requests, the service remembers rates for **5 minutes**. If two users both ask for the USD/EUR rate within the same 5-minute window, only one real external request is made. The second user gets the same answer instantly from memory.

Supported currency lists are cached for **24 hours**, since the set of globally available currencies changes very rarely.

### Permanent History

Every exchange rate the service fetches is saved in a database. This means you can see what the rate was at any point in the past — useful for auditing, reporting, or dispute resolution.

### One-Time Currency Setup

The first time the service starts up on a fresh installation, it contacts all three providers to build a list of supported currencies and saves it to the database. Every time the service restarts after that, it reads that saved list directly — no provider calls needed at boot. This means restarts are faster and don't depend on external services being reachable.

---

## How a Typical Request Works

Here's what happens when someone asks to convert $100 USD to EUR:

1. **The request arrives.** The service checks that "USD" and "EUR" are valid, supported currencies.

2. **Check the memory first.** The service looks in its short-term memory (Redis cache) to see if it already fetched the USD/EUR rate in the last 5 minutes.

3. **Memory hit → instant response.** If found, it multiplies $100 by the remembered rate and replies immediately. No calls to external services.

4. **Memory miss → ask the providers.** If not found, the service asks Fixer.io, OpenExchangeRates, and CurrencyAPI simultaneously.

5. **Average the responses.** For example:
   - Fixer.io says: 0.9250
   - OpenExchangeRates says: 0.9260
   - CurrencyAPI times out (fails)
   - Final rate used: (0.9250 + 0.9260) ÷ 2 = **0.9255**

6. **Save and reply.** The rate is saved in memory (for the next 5 minutes) and permanently in the database. The user receives: *$100 USD = €92.55 EUR at a rate of 0.9255*.

---

## API Endpoints

| Endpoint | What It Does |
|----------|-------------|
| `GET /api/convert/{from}/{to}/{amount}` | Converts an amount from one currency to another |
| `GET /api/rate/{from}/{to}` | Returns the current exchange rate between two currencies |
| `GET /api/currencies` | Lists all supported currency codes |

Interactive documentation is available at `/docs` once the service is running.

---

## Example Responses

**Converting 100 USD to EUR:**
```
GET /api/convert/USD/EUR/100
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

The `source` field tells you the rate came from averaging multiple providers, not a single source.

**When something goes wrong:**
```json
{
  "detail": "Currency XYZ is not supported"
}
```

---

## What Happens When Things Go Wrong

| Scenario | What the Service Does |
|----------|-----------------------|
| One provider is slow | The other two respond; the slow one is excluded from averaging |
| One provider is down | The other two carry on; you get an average of two |
| Two providers are down | The remaining one's rate is used directly |
| All three providers are down | The service returns a 503 error: "Exchange rate service unavailable" |
| You request an unsupported currency | The service returns a 400 error with a clear message |
| Unexpected internal error | The service returns a 500 error without exposing internal details |

---

## Technology Stack (Plain English)

| Technology | What It Is | Why It's Used |
|------------|-----------|---------------|
| **FastAPI** | The web framework | Handles incoming HTTP requests quickly |
| **PostgreSQL** | A relational database | Stores permanent rate history and supported currencies |
| **Redis** | An in-memory store | Fast short-term caching of recent rates |
| **SQLAlchemy** | A database toolkit | Handles all database queries in Python |
| **Alembic** | A migration tool | Manages database schema changes safely |
| **Pydantic** | A data validation library | Ensures all input and output data is the right shape and type |
| **httpx** | An HTTP client | Makes requests to the three exchange rate providers |
| **Docker** | Containerization | Packages the app and its dependencies for consistent deployment |
| **GitHub Actions** | CI/CD | Automatically tests and deploys the code on every change |

---

## Deployment Overview

The service is packaged as a Docker container and deployed via GitHub Actions. Every time code is merged into the main branch, automated tests run, a new Docker image is built and published to the container registry, tagged with both `latest` and the specific code version so you can always roll back if needed.

On first deployment to a new environment, the service automatically sets up the database schema and seeds the supported currencies list. Subsequent deployments are non-destructive — existing data is preserved.

---

## Limitations & Known Constraints

- **Fixer.io free tier** only supports EUR as a base currency. Paid plans unlock all base currencies.

- **Rate freshness**: Rates are cached for 5 minutes. In periods of high market volatility, the actual rate at time of transaction may differ slightly from what was quoted.

- **Supported currencies**: Only currencies supported by all three providers simultaneously are available. If you add a new provider, the currency list will only update on a fresh installation or manual database reset.

- **No authentication**: The API is currently open. In a production deployment exposed to the internet, rate limiting and API key authentication should be added.
