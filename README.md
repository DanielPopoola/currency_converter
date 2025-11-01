# Currency Converter API v2: Hybrid Real-Time & On-Demand FX Engine

## Project Overview

This project is a high-performance currency conversion service that operates using a sophisticated **hybrid architecture**. It provides both **proactive, real-time price updates** for a pre-configured set of key currency pairs via WebSockets, and a **reactive, on-demand REST API** for fetching rates and performing conversions for *any* valid currency pair.

This dual approach ensures low-latency, real-time data for high-volume currency pairs while maintaining the flexibility to serve less frequent requests without the overhead of constant polling.

## Core Features

*   **Hybrid Architecture:** Combines a real-time, push-based system for key currencies with a flexible, pull-based system for all others.
*   **Real-time WebSocket Feeds:** A background worker continuously fetches rates for important currencies and broadcasts them to subscribed WebSocket clients.
*   **Comprehensive REST API:** Provides on-demand endpoints (`/convert`, `/rates`) that can serve any currency pair by fetching directly from external providers.
*   **Multi-Provider Aggregation:** Integrates with multiple external FX providers (Fixer.io, OpenExchangeRates, etc.) to ensure data reliability.
*   **Resilience & Fault Tolerance:** Uses a Circuit Breaker pattern to gracefully handle failures from external providers.
*   **High-Performance Caching:** Leverages Redis for caching on-demand API responses, managing circuit breaker states, and as a Pub/Sub message bus for the real-time component.
*   **Structured Logging & Persistence:** Utilizes PostgreSQL for storing historical data and provides structured JSON logs for excellent observability.

## System Architecture

The system is composed of two primary components: a background **Rate Ingestor Worker** and the client-facing **API Server**. They work in tandem to provide the hybrid functionality.

The data flow is best understood as two separate, parallel processes:

### 1. Real-time Data Flow (Proactive Push)

This flow handles the pre-configured, high-volume currency pairs.

```
+------------------------+
| External API Providers |
+------------------------+
           ^
           | 1. Fetches rates for key pairs (e.g., USD, EUR)
           |
+-------------------------+      +--------------------------------+
|   Rate Ingestor Worker  |      |                                |
| (Background Process)    |----->| 2. Publishes to Redis Channel  |
+-------------------------+      |      "rates:broadcast"         |
                                 +--------------------------------+
                                                ^
                                                | 3. Subscribes to channel
                                                |
+-------------------------+      +--------------------------------+
|       API Server        |      |                                |
|  (WebSocket Handler)    |<-----|      Redis Message Bus         |
+-------------------------+      +--------------------------------+
           |
           | 4. Pushes updates to clients
           v
+-------------------------+
|   WebSocket Clients     |
+-------------------------+
```

### 2. On-demand Data Flow (Reactive Pull)

This flow handles requests for any currency pair, especially those not covered by the worker.

```
+------------------------+
| External API Providers |
+------------------------+
           ^
           | 3. Fetches rate if not in cache
           |
+-------------------------+      +--------------------------------+
|       API Server        |      |                                |
| (REST API Endpoints)    |----->| 2. Checks for cached rate      |
| - /rates                |      |                                |
| - /convert              |<-----| 4. Caches new rate             |
+-------------------------+      +--------------------------------+
           ^                                      |
           | 1. Client sends request              |
           |                                      |
           +--------------------------------------+
           | 5. Returns response
           v
+-------------------------+
|      REST Clients       |
+-------------------------+
```

## Data Flow Explained

#### Real-time (Worker & WebSockets)

1.  **Fetch Key Currencies:** The **Rate Ingestor Worker** runs in a continuous loop, calling the `RateAggregatorService` to fetch rates for a specific list of `WORKER_BASE_CURRENCIES` defined in the configuration.
2.  **Publish to Redis:** The worker takes the aggregated result and publishes it to the `rates:broadcast` Pub/Sub channel in Redis.
3.  **Subscribe & Listen:** The **API Server's** WebSocket handler subscribes to this Redis channel.
4.  **Push to Clients:** When a new message appears on the channel, the WebSocket handler immediately pushes the rate update to all connected clients who are subscribed to that currency pair.

#### On-demand (REST API)

1.  **Client Request:** A user sends a request to a REST endpoint, e.g., `GET /api/v1/rates/AUD/CAD`.
2.  **Invoke Aggregator:** The API endpoint calls the `RateAggregatorService` to get the rate for the requested pair (`AUD/CAD`).
3.  **Cache & Fetch Logic:** The `RateAggregatorService` first checks Redis for a recently cached rate for this pair. If a valid entry is not found, it proceeds to fetch the rate from the external API providers.
4.  **Cache & Respond:** The newly fetched rate is cached in Redis (with a TTL) and the response is sent back to the client.

This hybrid model ensures that the REST API is always able to serve any pair, while the WebSocket provides a highly efficient, low-latency stream for the most important ones.

## Technologies Used

*   **Python 3.10+**
*   **FastAPI:** Web framework for building APIs.
*   **Uvicorn:** ASGI server for FastAPI.
*   **SQLAlchemy:** ORM for database interactions.
*   **PostgreSQL:** Primary database for persistent data.
*   **Redis:** In-memory data store for caching, Pub/Sub, and circuit breaker state.
*   **Httpx:** Asynchronous HTTP client.
*   **Alembic:** Database migrations.
*   **Pydantic:** Data validation and settings management.
*   **Docker:** Containerization.

## Setup and Installation

### Prerequisites

*   Docker and Docker Compose
*   API keys for the desired currency providers (e.g., Fixer.io, OpenExchangeRates).

### Running with Docker Compose (Recommended)

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-repo/currency_converter.git
    cd currency_converter
    ```
2.  **Create `.env` file:** In the `docker` directory, copy `docker/.env.example` to `docker/.env` and fill in the required environment variables.
    ```bash
    cp docker/.env.example docker/.env
    # Edit docker/.env with your actual API keys and database/redis connection strings
    ```
3.  **Build and run services:**
    ```bash
    docker-compose -f docker/docker-compose.yml up --build
    ```
    This will start the API server, the rate ingestor worker, PostgreSQL, and Redis.

4.  **Access the API:**
    *   **REST API:** `http://localhost:8000`
    *   **Swagger UI:** `http://localhost:8000/docs`
    *   **WebSocket Endpoint:** `ws://localhost:8000/api/v1/ws/rates`

## API Endpoints

All API endpoints are prefixed with `/api/v1`.

### 1. WebSocket Real-time Rates

*   **Endpoint:** `ws://localhost:8000/api/v1/ws/rates`
*   **Description:** Subscribe to real-time exchange rate updates for key currency pairs tracked by the background worker.
*   **Usage:**
    *   Subscribe to all available real-time pairs: `ws://localhost:8000/api/v1/ws/rates`
    *   Subscribe to specific pairs: `ws://localhost:8000/api/v1/ws/rates?pairs=USD/EUR,GBP/USD`

### 2. Convert Currency

*   **Endpoint:** `POST /api/v1/convert`
*   **Description:** Converts an amount from a source currency to a target currency. Fetches the rate on-demand if not recently cached.

### 3. Get Exchange Rate

*   **Endpoint:** `GET /api/v1/rates/{from_currency}/{to_currency}`
*   **Description:** Retrieves the current exchange rate between any two currencies, fetching on-demand as needed.

### 4. Health Check

*   **Endpoint:** `GET /api/v1/health`
*   **Description:** Provides a comprehensive health status of all system components.

## Configuration

The application is configured using environment variables. See `docker/.env.example` for a full list of options. Key variables include:

| Variable                  | Description                                                              |
| :------------------------ | :----------------------------------------------------------------------- |
| `DATABASE_URL`            | PostgreSQL connection string.                                            |
| `REDIS_URL`               | Redis connection string.                                                 |
| `PRIMARY_PROVIDER`        | Name of the primary currency provider (e.g., `FixerIO`).                 |
| `WORKER_BASE_CURRENCIES`  | Comma-separated list of base currencies for the worker to fetch (e.g., `USD,EUR`). |
| `WORKER_TARGET_CURRENCIES`| Comma-separated list of target currencies (e.g., `JPY,GBP,CAD`).         |
| `WORKER_UPDATE_INTERVAL`  | Interval in seconds for the worker's update cycle.                       |

## Testing

To run tests, ensure you have the development dependencies installed.

```bash
pytest
```
