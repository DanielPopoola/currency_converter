# System Design: Real-Time FX Pricing Engine

This document outlines the proposed architecture for evolving the currency converter into a real-time FX pricing engine suitable for a remittance company.

## Architecture: A Decoupled, Proactive Approach

The core principle is to separate the high-frequency data **ingestion** from the low-latency data **serving**.

### Components

1.  **Rate Ingestion Worker (The "Engine")**
    *   **Role**: A standalone, continuously running background process.
    *   **Logic**:
        *   Runs in an infinite loop (e.g., every 2-5 seconds).
        *   For each currency pair to be tracked (e.g., USD/EUR, NGN/USD), it calls the `RateAggregatorService`.
        *   It takes the final, aggregated rate.
        *   It **publishes** this rate to a Redis Pub/Sub channel (e.g., `rates:broadcast`).
        *   It also **writes** the rate to a simple Redis key (e.g., `latest_rate:USD-EUR`) for quick lookups by the REST API.
    *   **Technology**: An `asyncio` Python script. For production, this could be managed by a process manager like `systemd` or a task queue like Celery.

2.  **Redis (The "Central Nervous System")**
    *   **Role**: Acts as the high-speed messaging bus and cache.
    *   **Functionality Used**:
        *   **Pub/Sub**: To broadcast price "ticks" to any listening services (specifically, the WebSocket handler).
        *   **Key-Value Store**: To store the most recent price for any given currency pair, allowing for instant retrieval.

3.  **FastAPI Application (The "Serving Layer")**
    *   **Role**: Exposes the real-time prices to clients. It no longer performs any data fetching itself.
    *   **It will have two primary ways of serving data**:
        *   **WebSocket Handler**: A **push** mechanism. It subscribes to the Redis Pub/Sub channel and immediately pushes any new rates to all connected clients.
        *   **REST API Endpoint**: A **pull** mechanism. The `GET /rate` endpoint performs a simple, fast lookup from the Redis key-value store.

### Data Flow

```
[External APIs] -> (1. Fetched by) -> [Ingestion Worker]
                                            |
                                            v (Aggregates & Publishes)
                                            |
      +-------------------------------------+
      |                                     v
(Pub/Sub broadcast) --------------> [Redis] <---------- (Key-Value GET)
      ^                               |                      ^
      | (Listens to Pub/Sub)          |                      | (Reads from key)
      |                               v                      |
[FastAPI WebSocket Handler]   [FastAPI REST Endpoint]
      |                                                      |
      v (Pushes to client)                                   v (Returns to client)
      |                                                      |
[Client (Web UI)] <--------------------------------------> [Client (API User)]
```

---

## Project Structure Changes

The following changes will be made to the project structure to accommodate this new design.

```
/home/lisanalgaib/currency_converter/
├───app/
│   ├───__init__.py
│   ├───main.py                     # MODIFIED: To include WebSocket router
│   ├───api/
│   │   ├───__init__.py
│   │   ├───models/
│   │   └───routes/
│   │       ├───__init__.py
│   │       ├───rates.py            # MODIFIED: Logic replaced with Redis lookup
│   │       └───websockets.py       # NEW: Handles WebSocket connections and Redis subscription
│   ├───workers/                    # NEW FOLDER
│   │   ├───__init__.py
│   │   └───rate_ingestor.py        # NEW: The background rate engine logic
│   ├───cache/
│   │   └───redis_manager.py        # MODIFIED: Add Pub/Sub helper methods
│   ├───config/
│   ├───database/
│   ├───providers/
│   ├───services/
│   └───utils/
├───scripts/
│   └───run_worker.sh               # NEW: Script to start the ingestion worker
├───pyproject.toml
├───README.md                       # MODIFIED: Add instructions for running the worker
...
```

### Summary of File Changes:

*   **New Directory `app/workers/`**: Will house all background processes.
    *   `rate_ingestor.py`: The heart of the new ingestion engine.
*   **New File `app/api/routes/websockets.py`**: Dedicated to handling all WebSocket logic.
*   **Modified `app/api/routes/rates.py`**: The existing REST endpoint will be simplified to only perform a fast lookup from Redis.
*   **Modified `app/main.py`**: Will be updated to import and initialize the new WebSocket router.
*   **Modified `app/cache/redis_manager.py`**: Helper functions for Redis Pub/Sub will be added.
*   **New `scripts/run_worker.sh`**: A convenience script to launch the new background process.
