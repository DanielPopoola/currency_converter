# API Reference

Complete reference for all Currency Converter API endpoints.

**Base URL:** `http://localhost:8000` (development) | configured via deployment environment

**Interactive docs:** `/docs` (Swagger UI) · `/redoc` (ReDoc)

---

## Authentication

The API is currently unauthenticated. All endpoints are publicly accessible. For production deployments exposed to the internet, add API key authentication or an OAuth2 layer before the FastAPI application.

---

## Common Conventions

### Currency Codes

All currency codes follow [ISO 4217](https://en.wikipedia.org/wiki/ISO_4217) (3–5 character uppercase strings). Codes are case-insensitive in path parameters — the API normalises them to uppercase internally.

Only currencies supported by **all three providers simultaneously** are accepted. Use `GET /api/currencies` to retrieve the current supported list.

### Decimal Precision

All monetary amounts and rates in responses are returned as **decimal strings** (not floats) to avoid precision loss during JSON serialisation. Parse them with a `Decimal` type in your client.

```json
{ "rate": "0.925500" }  ✓  (string)
{ "rate": 0.9255 }      ✗  (float — avoid)
```

### Timestamps

All timestamps are ISO 8601 UTC: `2025-11-01T14:30:00`.

---

## Endpoints

### `GET /api/convert/{from_currency}/{to_currency}/{amount}`

Convert an amount from one currency to another using live aggregated rates.

#### Path Parameters

| Parameter | Type | Constraints | Example |
|-----------|------|-------------|---------|
| `from_currency` | string | 3–5 chars, supported currency code | `USD` |
| `to_currency` | string | 3–5 chars, supported currency code, must differ from `from_currency` | `EUR` |
| `amount` | decimal | Greater than 0, max 2 decimal places | `100.00` |

#### Success Response `200 OK`

```json
{
  "from_currency": "USD",
  "to_currency": "EUR",
  "original_amount": "100.00",
  "converted_amount": "92.55",
  "exchange_rate": "0.925500",
  "timestamp": "2025-11-01T14:30:00",
  "source": "averaged"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `from_currency` | string | Source currency code |
| `to_currency` | string | Target currency code |
| `original_amount` | decimal string | The amount submitted in the request |
| `converted_amount` | decimal string | Result of `original_amount × exchange_rate` |
| `exchange_rate` | decimal string | Rate used for conversion |
| `timestamp` | ISO 8601 | When the rate was fetched or last cached |
| `source` | string | `"averaged"` when multiple providers contributed; provider name when only one responded |

#### Error Responses

| Status | Condition | Body |
|--------|-----------|------|
| `400` | `from_currency` or `to_currency` is unsupported | `{"detail": "Currency XYZ is not supported"}` |
| `422` | Invalid path parameters (e.g. amount ≤ 0) | Pydantic validation error detail |
| `503` | All three providers are unreachable | `{"detail": "Exchange rate service unavailable"}` |
| `500` | Unexpected server error | `{"detail": "Internal server error"}` |

#### Example

```bash
curl "http://localhost:8000/api/convert/USD/NGN/500"
```

```json
{
  "from_currency": "USD",
  "to_currency": "NGN",
  "original_amount": "500.00",
  "converted_amount": "816450.000000",
  "exchange_rate": "1632.900000",
  "timestamp": "2025-11-01T14:30:00",
  "source": "averaged"
}
```

---

### `GET /api/rate/{from_currency}/{to_currency}`

Get the current exchange rate between two currencies without performing a conversion.

#### Path Parameters

| Parameter | Type | Constraints | Example |
|-----------|------|-------------|---------|
| `from_currency` | string | 3–5 chars, supported currency code | `GBP` |
| `to_currency` | string | 3–5 chars, supported currency code | `JPY` |

#### Success Response `200 OK`

```json
{
  "from_currency": "GBP",
  "to_currency": "JPY",
  "rate": "190.450000",
  "timestamp": "2025-11-01T14:30:00",
  "source": "averaged"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `from_currency` | string | Source currency code |
| `to_currency` | string | Target currency code |
| `rate` | decimal string | 1 unit of `from_currency` expressed in `to_currency` |
| `timestamp` | ISO 8601 | When the rate was fetched or last cached |
| `source` | string | `"averaged"` or individual provider name |

#### Error Responses

Same as `GET /api/convert` except `422` validation (no `amount` parameter).

#### Example

```bash
curl "http://localhost:8000/api/rate/EUR/CHF"
```

---

### `GET /api/currencies`

List all currency codes currently supported by the service.

A currency is supported only if **all three providers** support it. This list is populated once on first startup and cached in Redis for 24 hours.

#### Success Response `200 OK`

```json
{
  "currencies": ["AUD", "CAD", "CHF", "CNY", "EUR", "GBP", "JPY", "NGN", "NZD", "SEK", "USD"]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `currencies` | `string[]` | Sorted list of ISO 4217 currency codes |

#### Example

```bash
curl "http://localhost:8000/api/currencies"
```

---

### `GET /api/health`

Check the operational status of each configured exchange rate provider. Use this endpoint to monitor upstream dependency health.

Health is determined by issuing a live `fetch_supported_currencies()` call to each provider. This endpoint always attempts real network calls — it does not serve a cached result.

#### Success Response `200 OK`

```json
{
  "providers": [
    {
      "name": "fixerio",
      "status": "operational",
      "error": null
    },
    {
      "name": "openexchange",
      "status": "operational",
      "error": null
    },
    {
      "name": "currencyapi.com",
      "status": "down",
      "error": "TimeoutError"
    }
  ],
  "healthy_providers": 2,
  "total_providers": 3,
  "status": "degraded"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `providers` | `object[]` | Per-provider status objects |
| `providers[].name` | string | Provider identifier |
| `providers[].status` | `"operational"` \| `"down"` | Whether the provider responded successfully |
| `providers[].error` | string \| null | Error class name when down, null when operational |
| `healthy_providers` | integer | Count of providers currently `"operational"` |
| `total_providers` | integer | Total number of configured providers |
| `status` | `"healthy"` \| `"degraded"` | `"healthy"` only when all providers are operational |

> **Note:** A `"degraded"` status does not mean conversions are failing. The service continues to operate as long as at least one provider is reachable.

#### Example

```bash
curl "http://localhost:8000/api/health"
```

---

## Rate & Cache Behaviour

Understanding when the API calls external providers helps predict latency and quota consumption.

### First request for a currency pair

1. Redis cache miss.
2. All three providers are called in parallel.
3. Results are averaged.
4. Rate is stored in Redis (5-minute TTL) and PostgreSQL.
5. Response returned. **Typical latency: 80–300ms** depending on provider response times.

### Subsequent requests within 5 minutes

1. Redis cache hit.
2. No provider calls made.
3. Response returned immediately. **Typical latency: <10ms.**

### After 5 minutes

Cache expires. Next request for the pair triggers provider calls again (path 1 above).

---

## Client Examples

### Python

```python
import httpx
from decimal import Decimal

BASE_URL = "http://localhost:8000"

async def convert(from_currency: str, to_currency: str, amount: Decimal) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/api/convert/{from_currency}/{to_currency}/{amount}"
        )
        response.raise_for_status()
        return response.json()

# Usage
result = await convert("USD", "EUR", Decimal("100.00"))
print(Decimal(result["converted_amount"]))  # e.g. Decimal("92.55")
```

### JavaScript / TypeScript

```typescript
const BASE_URL = "http://localhost:8000";

interface ConvertResult {
  from_currency: string;
  to_currency: string;
  original_amount: string;
  converted_amount: string;
  exchange_rate: string;
  timestamp: string;
  source: string;
}

async function convert(
  from: string,
  to: string,
  amount: number
): Promise<ConvertResult> {
  const response = await fetch(
    `${BASE_URL}/api/convert/${from}/${to}/${amount}`
  );
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}
```

### cURL

```bash
# Convert 1000 USD to JPY
curl "http://localhost:8000/api/convert/USD/JPY/1000"

# Get EUR/GBP rate
curl "http://localhost:8000/api/rate/EUR/GBP"

# List supported currencies
curl "http://localhost:8000/api/currencies"

# Check provider health
curl "http://localhost:8000/api/health"
```
