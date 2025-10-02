import json
from datetime import datetime


from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query

from app.api.dependencies import get_service_factory
from app.services import ServiceFactory
from app.monitoring.logger import logger, LogLevel


router = APIRouter(prefix="/api/v1", tags=["websockets"])


class ConnectionManager:
    """
    Manages WebSocket connections and broadcasting.
    """
    def __init__(self):
        # Store active connections with their subscription filters
        self.active_connections: dict[WebSocket, set[str]] = {}
        self.logger = logger.bind(service='WebsocketConnectionManager')

    async def connect(self, websocket: WebSocket, currency_pairs: set[str] | None):
        """
        Accept a new WebSocket connection.
        
        Args:
            websocket: The WebSocket connection
            currency_pairs: Optional set of pairs to subscribe to (e.g., {"USD/EUR", "GBP/USD"})
                          If None, subscribes to all pairs
        """
        await websocket.accept()
        self.active_connections[websocket] = currency_pairs or set()

        self.logger.info(f"New WebSocket connection. Total connections: {len(self.active_connections)}")
        self.logger.info(f"Subscribed to: {currency_pairs if currency_pairs else 'ALL pairs'}")

        self.logger.info(
            "Websocket connection established",
            event_type="WEBSOCKET_EVENT",
            timestamp=datetime.now(),
            total_connections=len(self.active_connections),
            subscribed_pairs=list(currency_pairs) if currency_pairs else "all"
        )

    def disconnect(self, websocket: WebSocket):
        """Remove a connection when client disconnects"""
        if websocket in self.active_connections:
            subscriptions = self.active_connections[websocket]
            del self.active_connections[websocket]

            self.logger.info(f"WebSocket disconnected. Remaining connections: {len(self.active_connections)}")
            self.logger.info(
                "Websocket connection closed",
                event_type="WEBSOCKET_EVENT",
                timestamp=datetime.now(),
                remaining_connections=len(self.active_connections)
            )

    async def broadcast(self, message: dict):
        """
        Broadcast a message to all connected clients (with filtering).
        
        Args:
            message: The rate update to broadcast
        """
        pair = message.get("pair")

        # Track how many clients received this message
        sent_count = 0
        failed_connections = []

        for websocket, subscribed_pairs in self.active_connections.items():
            if subscribed_pairs and pair not in subscribed_pairs:
                continue  # Client isn't interested in this pair

            try:
                await websocket.send_json(message)
                sent_count += 1
            except Exception as e:
                self.logger.error(f"Failed to send to client: {e}")
                failed_connections.append(websocket)

        # Clean up failed connections
        for websocket in failed_connections:
            self.disconnect(websocket)

        if sent_count > 0:
            self.logger.debug(f"Broadcasted {pair} to {sent_count} clients")

    def get_stats(self) -> dict:
        """Get statistics about active connections."""
        return {
            "total_connections": len(self.active_connections),
            "connections_by_subscription": {
                "all_pairs": sum(1 for pairs in self.active_connections.values() if not pairs),
                "filtered": sum(1 for pairs in self.active_connections.values() if pairs)
            }
        }
    
# Global connection manager instance
manager = ConnectionManager()

@router.websocket("/ws/rates")
async def websocket_rates_endpoint(
    websocket: WebSocket,
    pairs: str | None = Query(None, description="Comma-separated currency pairs (e.g., 'USD/EUR,GBP/USD')")
):
    """
    WebSocket endpoint for real-time exchange rate updates.
    
    Usage examples:
    - Subscribe to all pairs: ws://localhost:8000/api/v1/ws/rates
    - Subscribe to specific pairs: ws://localhost:8000/api/v1/ws/rates?pairs=USD/EUR,GBP/USD
    
    Message format sent to client:
    {
        "pair": "USD/EUR",
        "base_currency": "USD",
        "target_currency": "EUR",
        "rate": "1.08",
        "confidence_level": "high",
        "sources_used": ["FixerIO", "ExchangeRatesAPI"],
        "timestamp": "2025-10-01T10:00:00Z",
        "cached": false
    }
    """
    # Parse subscription filter
    subscribed_pairs = None
    if pairs:
        subscribed_pairs = {pair.strip() for pair in pairs.split(",")}
        logger.info(f"Client subscribing to specific pairs: {subscribed_pairs}")

    # Accept the connection
    await manager.connect(websocket, subscribed_pairs)

    try:
        from app.services.service_factory import service_factory
        redis_manager = service_factory.get_redis_manager()

        # Send welcome message
        await websocket.send_json({
            "type": "connection_established",
            "message": "Connected to real-time rate updates",
            "subscribed_pairs": list(subscribed_pairs) if subscribed_pairs else "all",
            "timestamp": datetime.now().isoformat()
        })

        # Subscribe to Redis Pub/Sub and forward messages to this WebSocket
        async for rate_update in redis_manager.subscribe_to_rates():
            try:
                pair = rate_update.get("pair")

                # Check if client wants this pair
                if subscribed_pairs and pair not in subscribed_pairs:
                    continue  # Skip pairs client doesn't care about
                
                # Send the update to this specific client
                await websocket.send_json({
                    "type": "rate_update",
                    **rate_update
                })
                
                logger.debug(f"Sent {pair} update to client")
            except WebSocketDisconnect:
                logger.info("Client disconnected during message send")
                break
            except Exception as e:
                logger.error(
                    f"Failed to send rate update",
                    timestamp=datetime.now(),
                    error_msg=str(e)
                )
                break

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(
            f"WebSocket connection error: {e}",
            event_type="WEBSOCKET_EVENT",
            timestamp=datetime.now(),
            error_msg=str(e)
        )
    finally:
        manager.disconnect(websocket)


@router.get(
    "/ws/stats",
    summary="WebSocket connection statistics",
    description="Get statistics about active WebSocket connections"
)
async def websocket_stats():
    """
    Get information about active WebSocket connections.
    Useful for monitoring and debugging.
    """
    stats = manager.get_stats()
    return {
        "timestamp": datetime.now().isoformat(),
        **stats
    }