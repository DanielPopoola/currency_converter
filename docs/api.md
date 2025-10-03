# API Documentation

This document provides detailed information about the API endpoints for the Currency Converter service.

## Base URL

All REST API endpoints are prefixed with `/api/v1`.

-   **Production/Local:** `http://localhost:8000/api/v1`

## Authentication

The API does not currently require authentication.

## Rate Limiting

There is no rate limiting implemented at the application layer. It is assumed that this would be handled by an upstream service like an API gateway or load balancer in a production environment.

## Error Responses

Errors are returned in a standardized JSON format.

```json
{
    "detail": "Error message describing the issue."
}
```

### Common HTTP Status Codes

| Code | Meaning           | Description                                                  |
| :--- | :---------------- | :----------------------------------------------------------- |
| `200`| OK                | The request was successful.                                  |
| `400`| Bad Request       | The request was malformed or contained invalid parameters.   |
| `422`| Unprocessable Entity | The request was well-formed but contained invalid data (FastAPI's default validation error). |
| `503`| Service Unavailable | The service is temporarily unable to handle the request, likely due to issues with upstream providers. |

---

## 1. WebSocket API

### Real-time Rate Updates

This endpoint provides a real-time stream of exchange rate updates for a pre-configured set of currency pairs.

*   **Endpoint:** `ws://localhost:8000/api/v1/ws/rates`
*   **Description:** Establishes a WebSocket connection to receive live FX price ticks. The updates are sourced from the background `RateIngestorWorker`.

#### Query Parameters

| Parameter | Type   | Description                                                                                                 | Example                               |
| :-------- | :----- | :---------------------------------------------------------------------------------------------------------- | :------------------------------------ |
| `pairs`   | string | (Optional) A comma-separated list of currency pairs to subscribe to (e.g., `BASE/TARGET`). If omitted, the client will receive updates for all pairs tracked by the worker. | `USD/EUR,GBP/JPY`                     |

#### Messages from Server

**1. Connection Established**

Upon a successful connection, the server sends a welcome message.

```json
{
    "type": "connection_established",
    "message": "Connected to real-time rate updates",
    "subscribed_pairs": ["USD/EUR", "GBP/JPY"],
    "timestamp": "2025-10-03T12:00:00.123Z"
}
```

**2. Rate Update**

This is the primary message type, sent whenever the worker publishes a new rate.

```json
{
    "type": "rate_update",
    "pair": "USD/EUR",
    "base_currency": "USD",
    "target_currency": "EUR",
    "rate": "1.0855",
    "confidence_level": "high",
    "sources_used": ["FixerIO", "OpenExchange"],
    "is_primary_used": true,
    "timestamp": "2025-10-03T12:00:05.456Z",
    "cached": false,
    "warnings": []
}
```

---

## 2. REST API

### Convert Currency

Converts a given amount from a source currency to a target currency. This endpoint fetches rates on-demand.

*   **Endpoint:** `POST /convert`
*   **Method:** `POST`

#### Request Body

```json
{
    "from_currency": "USD",
    "to_currency": "EUR",
    "amount": 100.00
}
```

| Field           | Type   | Required | Description                  |
| :-------------- | :----- | :------- | :--------------------------- |
| `from_currency` | string | Yes      | The currency code to convert from (e.g., `USD`). |
| `to_currency`   | string | Yes      | The currency code to convert to (e.g., `EUR`).   |
| `amount`        | float  | Yes      | The amount to be converted.  |

#### Success Response (200 OK)

```json
{
    "from_currency": "USD",
    "to_currency": "EUR",
    "amount": 100.00,
    "converted_amount": 92.15,
    "exchange_rate": 0.9215,
    "confidence_level": "high",
    "timestamp": "2025-10-03T12:01:10.789Z"
}
```

---

### Get Exchange Rate

Retrieves the current exchange rate between two currencies. This endpoint fetches rates on-demand.

*   **Endpoint:** `/rates/{from_currency}/{to_currency}`
*   **Method:** `GET`

#### URL Parameters

| Parameter       | Type   | Description                  |
| :-------------- | :----- | :--------------------------- |
| `from_currency` | string | The currency code to convert from (e.g., `USD`). |
| `to_currency`   | string | The currency code to convert to (e.g., `EUR`).   |

#### Example Request

`GET /api/v1/rates/GBP/JPY`

#### Success Response (200 OK)

```json
{
    "from_currency": "GBP",
    "to_currency": "JPY",
    "exchange_rate": 190.55,
    "confidence_level": "high",
    "timestamp": "2025-10-03T12:02:30.990Z"
}
```

---

### Health Check

Provides a detailed health status of the service and its dependencies.

*   **Endpoint:** `/health`
*   **Method:** `GET`

#### Success Response (200 OK)

The response includes the status of the database, cache (Redis), and the state of the circuit breakers for each external provider.

```json
{
    "status": "healthy",
    "timestamp": "2025-10-03T12:03:00.000Z",
    "services": {
        "database": {
            "status": "healthy",
            "response_time_ms": 15.5
        },
        "cache": {
            "status": "healthy",
            "response_time_ms": 2.1
        },
        "rate_aggregator": {
            "service": "rate_aggregator",
            "providers": {
                "FixerIO": {
                    "state": "CLOSED",
                    "status": "healthy",
                    "failure_count": 0
                },
                "OpenExchange": {
                    "state": "CLOSED",
                    "status": "healthy",
                    "failure_count": 0
                },
                "CurrencyAPI": {
                    "state": "OPEN",
                    "status": "unhealthy",
                    "failure_count": 5
                }
            }
        }
    }
}
```
