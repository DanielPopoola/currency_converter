import json
import time
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from redis import asyncio as redis

from app.monitoring.logger import logger


class CircuitBreakerState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class RedisManager:
    """Handles all Redis operations for caching and circuit breaker state"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.logger = logger.bind(service="RedisManager")
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self.RATE_CACHE_TTL = 300
        self.CIRCUIT_BREAKER_TTL = 3600

    TOP_CURRENCIES_KEY = "supported_currencies:top"

    def _get_rate_cache_key(self, base: str, target: str) -> str:
        """Generate a simple cache key for an exchange rate."""
        return f"rates:{base}:{target}"
    
    def _get_circuit_breaker_key(self, provider_id: int, suffix: str) -> str:
        """Generate circuit breaker keys"""
        return f"circuit_breaker:{provider_id}:{suffix}"
    
    # Rate caching methods
    async def set_latest_rate(self, base: str, target: str, rate_data: dict[str, Any]) -> bool:
        """
        Store the latest rate in a simple key-value format for fast REST API lookups.
        
        Key format: rates:BASE:TARGET (e.g., rates:USD:EUR)
        
        Args:
            base: Base currency code
            target: Target currency code
            rate_data: Dictionary containing rate information
        
        Returns:
            True if successful, False otherwise
        """
        try:
            key = self._get_rate_cache_key(base, target)
            
            # Add metadata
            cache_data = {
                **rate_data,
                "base_currency": base,
                "target_currency": target,
                "updated_at": datetime.now(tz=UTC).isoformat()
            }
            
            result = await self.redis_client.setex(
                key,
                self.RATE_CACHE_TTL,
                json.dumps(cache_data)
            )
            
            self.logger.info(
                "Cache operation: set_latest_rate",
                operation="set_latest_rate",
                cache_key=key,
                hit=False,
                duration_ms=0,
                timestamp=datetime.now()
            )
            
            return bool(result)
            
        except Exception as e:
            self.logger.error(
                "Cache operation error: set_latest_rate",
                operation="set_latest_rate",
                cache_key=self._get_rate_cache_key(base, target),
                hit=False,
                duration_ms=0,
                error_message=str(e),
                timestamp=datetime.now()
            )
            return False


    async def get_latest_rate(self, base: str, target: str) -> dict[str, Any] | None:
        """
        Retrieve the latest rate from the fast-lookup key.
        Used by REST API for instant responses.
        
        Args:
            base: Base currency code
            target: Target currency code
        
        Returns:
            Dictionary with rate data or None if not found
        """
        start_time = time.time()
        try:
            key = self._get_rate_cache_key(base, target)
            cached_data = await self.redis_client.get(key)
            duration_ms = (time.time() - start_time) * 1000
            
            if cached_data:
                rate_data = json.loads(cached_data)
                
                self.logger.info(
                    "Cache operation: get_latest_rate",
                    operation="get_latest_rate",
                    cache_key=key,
                    hit=True,
                    duration_ms=duration_ms,
                    timestamp=datetime.now()
                )
                
                return rate_data
            else:
                self.logger.info(
                    "Cache operation: get_latest_rate",
                    operation="get_latest_rate",
                    cache_key=key,
                    hit=False,
                    duration_ms=duration_ms,
                    timestamp=datetime.now()
                )
                return None
                
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.error(
                "Cache operation error: get_latest_rate",
                operation="get_latest_rate",
                cache_key=self._get_rate_cache_key(base, target),
                hit=False,
                duration_ms=duration_ms,
                error_message=str(e),
                timestamp=datetime.now()
            )
            return None

    async def set_cache_validation_result(self, cache_key: str, ttl: int, cache_data: dict[str, Any]) -> bool:
        """Cache currency validation results with specified TTL."""

        try:
            json_data = json.dumps(cache_data)

            result = await self.redis_client.setex(cache_key, ttl, json_data)
            self.logger.info(
                "Cache operation: set_validation",
                operation="set_validation",
                cache_key=cache_key,
                hit=False,
                duration_ms=0,
                timestamp=datetime.now()
            )
            return bool(result)
        except Exception as e:
            self.logger.error(
                "Cache operation error: set_validation",
                operation="set_validation",
                cache_key=cache_key,
                hit=False,
                duration_ms=0,
                error_message=str(e),
                timestamp=datetime.now()
            )
            return False
        
    async def get_cached_currency(self, cache_key: str) -> dict[str, Any] | None:
        """Retrieve cached currency validation result"""
        start_time = time.time()
        try:
            cached_value = await self.redis_client.get(cache_key)
            duration_ms = (time.time() - start_time) * 1000

            if cached_value is None:
                self.logger.info(
                    "Cache operation: get_validation",
                    operation="get_validation",
                    cache_key=cache_key,
                    hit=False,
                    duration_ms=duration_ms,
                    timestamp=datetime.now()
                )
                return None
            
            validation_data = json.loads(cached_value)
            self.logger.info(
                "Cache operation: get_validation",
                operation="get_validation",
                cache_key=cache_key,
                hit=True,
                duration_ms=duration_ms,
                timestamp=datetime.now()
            )
            return validation_data
        except json.JSONDecodeError:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.error(
                "Cache operation error: get_validation (JSONDecodeError)",
                operation="get_validation",
                cache_key=cache_key,
                hit=False,
                duration_ms=duration_ms,
                timestamp=datetime.now()
            )
            return None
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.error(
                "Cache operation error: get_validation",
                operation="get_validation",
                cache_key=cache_key,
                hit=False,
                duration_ms=duration_ms,
                error_message=str(e),
                timestamp=datetime.now()
            )
            return None
          
    # Circuit breaker method

    async def get_circuit_breaker_state(self, provider_id: int) -> CircuitBreakerState:
        """Get current circuit breaker state from Redis"""
        try:
            state_key = self._get_circuit_breaker_key(provider_id, "state")
            state_value = await self.redis_client.get(state_key)

            if state_value:
                return CircuitBreakerState(state_value)
            else:
                return CircuitBreakerState.CLOSED
            
        except Exception as e:
            self.logger.error(
                "Failed to get circuit breaker state for provider {provider_id}: {error}",
                provider_id=provider_id,
                error=str(e),
                event_type="CIRCUIT_BREAKER",
                timestamp=datetime.now()
            )
            return CircuitBreakerState.CLOSED
    
    async def set_circuit_breaker_state(self, provider_id: int, state: CircuitBreakerState,
                                        failure_count: int = 0, reason: str = "") -> bool:
        """Update circuit breaker state in Redis (fast) and log to PostgreSQL (persistent)"""
        try:
            state_key = self._get_circuit_breaker_key(provider_id, "state")
            failures_key = self._get_circuit_breaker_key(provider_id, "failures")
            last_failure_key = self._get_circuit_breaker_key(provider_id, "last_failure")

            # Update Redis
            async with self.redis_client.pipeline() as pipeline:
                await pipeline.setex(state_key, self.CIRCUIT_BREAKER_TTL, state.value)
                await pipeline.setex(failures_key, self.CIRCUIT_BREAKER_TTL, failure_count)

                if state == CircuitBreakerState.OPEN:
                    await pipeline.setex(last_failure_key, self.CIRCUIT_BREAKER_TTL, datetime.now(tz=UTC).isoformat())

                await pipeline.execute()

            self.logger.info(
                "Circuit breaker state set",
                provider_name=str(provider_id),
                old_state="",
                new_state=state.value,
                failure_count=failure_count,
                reason=reason,
                event_type="CIRCUIT_BREAKER",
                timestamp=datetime.now()
            )
            return True
            
        except Exception as e:
            self.logger.error(
                "Failed to set circuit breaker state for provider {provider_id}: {error}",
                provider_id=provider_id,
                error=str(e),
                event_type="CIRCUIT_BREAKER",
                timestamp=datetime.now()
            )
            return False
        
    async def get_failure_count(self, provider_id: int) -> int:
        """Get current failure count for circuit breaker logic"""
        try:
            failures_key = self._get_circuit_breaker_key(provider_id, "failures")
            count = await self.redis_client.get(failures_key)
            return int(count) if count else 0
            
        except Exception as e:
            self.logger.error(
                "Failed to get failure count for provider {provider_id}: {error}",
                provider_id=provider_id,
                error=str(e),
                event_type="CIRCUIT_BREAKER",
                timestamp=datetime.now()
            )
            return 0
        
    async def increment_failure_count(self, provider_id: int) -> int:
        """Increment failure count atomically and return the new count."""
        failures_key = self._get_circuit_breaker_key(provider_id, "failures")
        try:
            # Use a pipeline to ensure INCR and EXPIRE are atomic
            async with self.redis_client.pipeline(transaction=True) as pipe:
                pipe.incr(failures_key)
                pipe.expire(failures_key, self.CIRCUIT_BREAKER_TTL)
                results = await pipe.execute()

            # Defensive check of results
            if not results or not isinstance(results, list) or len(results) < 1:
                self.logger.error(
                    "Redis pipeline for increment_failure_count returned unexpected data",
                    provider_id=provider_id,
                    results=str(results),
                    event_type="CIRCUIT_BREAKER"
                )
                return 0

            new_count = results[0]
            if not isinstance(new_count, int):
                self.logger.error(
                    "Redis INCR command did not return an integer",
                    provider_id=provider_id,
                    new_count_type=str(type(new_count)),
                    new_count_value=str(new_count),
                    event_type="CIRCUIT_BREAKER"
                )
                # Attempt to recover if it's a string representation of an int
                try:
                    new_count = int(new_count)
                except (ValueError, TypeError):
                    return 0

            self.logger.debug(
                "Provider failure count incremented",
                provider_id=provider_id,
                new_count=new_count,
                event_type="CIRCUIT_BREAKER",
                timestamp=datetime.now()
            )
            return new_count
        except Exception as e:
            self.logger.error(
                "Failed to increment failure count for provider {provider_id}: {error}",
                provider_id=provider_id,
                error=repr(e),  # Use repr(e) for more detailed error logging
                event_type="CIRCUIT_BREAKER",
                timestamp=datetime.now()
            )
            return 0
        
    async def reset_failure_count(self, provider_id: int) -> bool:
        """Reset failure count (on successful recovery)"""
        try:
            failures_key = self._get_circuit_breaker_key(provider_id, "failures")
            await self.redis_client.delete(failures_key)
            
            self.logger.debug(
                "Reset failure count for provider {provider_id}",
                provider_id=provider_id,
                event_type="CIRCUIT_BREAKER",
                timestamp=datetime.now()
            )            
            return True
        except Exception as e:
            self.logger.error(
                "Failed to reset failure count for provider {provider_id}: {error}",
                provider_id=provider_id,
                error=str(e),
                event_type="CIRCUIT_BREAKER",
                timestamp=datetime.now()
            )
            return False

    async def get_last_failure_time(self, provider_id: int) -> str | None:
        """Get the timestamp of the last recorded failure."""
        try:
            last_failure_key = self._get_circuit_breaker_key(provider_id, "last_failure")
            return await self.redis_client.get(last_failure_key)
        except Exception as e:
            self.logger.error(
                "Failed to get last failure time for provider {provider_id}: {error}",
                provider_id=provider_id,
                error=str(e),
                event_type="CIRCUIT_BREAKER",
                timestamp=datetime.now()
            )
            return None

    async def get_top_currencies(self) -> list[str]:
        """Retrieve cached list of top currencies."""
        try:
            cached_data = await self.redis_client.get(self.TOP_CURRENCIES_KEY)
            if cached_data:
                return json.loads(cached_data)
            return []
        except Exception as e:
            self.logger.error(
                "Failed to get top currencies: {error}",
                error=str(e),
                operation="get_top_currencies",
                cache_key=self.TOP_CURRENCIES_KEY,
                hit=False,
                duration_ms=0,
                event_type="CACHE_OPERATION",
                timestamp=datetime.now()
            )
            return []

    async def set_top_currencies(self, currencies: list[str], ttl: int = 86400):
        """Cache a list of top currencies with a specified TTL."""
        try:
            await self.redis_client.setex(self.TOP_CURRENCIES_KEY, ttl, json.dumps(currencies))
            self.logger.info(
                "Cache operation: set_top_currencies",
                operation="set_top_currencies",
                cache_key=self.TOP_CURRENCIES_KEY,
                hit=False,
                duration_ms=0,
                event_type="CACHE_OPERATION",
                timestamp=datetime.now()
            )
        except Exception as e:
            self.logger.error(
                "Failed to set top currencies: {error}",
                error=str(e),
                operation="set_top_currencies",
                cache_key=self.TOP_CURRENCIES_KEY,
                hit=False,
                duration_ms=0,
                event_type="CACHE_OPERATION",
                timestamp=datetime.now()
            )


    # Pub/Sub methods
    async def publish_rate_update(self, base: str, target: str, rate_data: dict[str, Any]) -> int:
        """
        Publish a rate update to the rates:broadcast channel

        Args:
            base: Base currency code
            target: Target currency code
            rate_data: Dictionary containing rate, timestamp, sources, etc.
    
        Returns:
            Number of subscribers that received the message
        """
        try:
            channel = "rates:broadcast"

            # Prepare message payload
            message = {
                "pair": f"{base}/{target}",
                "base_currency": base,
                "target_currency": target,
                **rate_data
            }

            # Publish to Redis channel
            subscriber_count = await self.redis_client.publish(channel, json.dumps(message))

            self.logger.debug(
                "Published rate update for {pair} to {subscriber_count} subscribers",
                channel=channel,
                pair=f"{base}/{target}",
                subscriber_count=subscriber_count,
                event_type="CACHE_OPERATION",
                timestamp=datetime.now()
            )
            return subscriber_count
        except Exception as e:
            self.logger.error(
                "Failed to publish rate update: {error}",
                error=str(e),
                event_type="CACHE_OPERATION",
                timestamp=datetime.now()
            )
        return 0
    
    async def subscribe_to_rates(self) -> AsyncGenerator[dict[str, Any], None]:
        """
        Subscribe to the rates:broadcast channel and yield incoming messages.
        
        This is an async generator that continuously listens for rate updates.
        Used by WebSocket handlers to receive real-time updates.

        Yields:
            Dictionary containing rate update data
        """
        pubsub = self.redis_client.pubsub()

        try:
            await pubsub.subscribe("rates:broadcast")
            
            self.logger.info(
                "Subscribed to rates:broadcast channel",
                event_type="CACHE_OPERATION",
                timestamp=datetime.now()
            )

            # Listen for messags indefinitely
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        yield data
                    except json.JSONDecodeError as e:
                        self.logger.error(
                            "Failed to parse pubsub message: {error}",
                            error=str(e),
                            raw_message=message,
                            event_type="CACHE_OPERATION",
                            timestamp=datetime.now()
                        )
                    continue
        except Exception as e:
            self.logger.error(
                "Pub/Sub subscription error: {error}",
                error=str(e),
                event_type="CACHE_OPERATION",
                timestamp=datetime.now()
            )   
        finally:
            await pubsub.unsubscribe("rates:broadcast")
            await pubsub.close()


    # Utility methods

    async def health_check(self) -> dict[str, Any]:
        """Check Redis connection health"""
        try:
            start_time = datetime.now()
            await self.redis_client.ping()
            response_time = (datetime.now() - start_time).total_seconds() * 1000
            
            return {
                "status": "healthy",
                "response_time_ms": round(response_time, 2)
            }
        except Exception as e:
            return {
                "status": "unhealthy", 
                "error": str(e)
            }
        
    async def clear_cache_pattern(self, pattern: str):
        """Clear cache keys matching pattern (for debugging)"""
        try:
            keys = await self.redis_client.keys(pattern)
            if keys:
                deleted = await self.redis_client.delete(*keys)
                self.logger.info(
                    "Cache operation: clear_pattern",
                    operation="clear_pattern",
                    cache_key=pattern,
                    hit=False,
                    duration_ms=0,
                    event_type="CACHE_OPERATION",
                    timestamp=datetime.now()
                )
                return deleted
            return 0
        except Exception as e:
            self.logger.error(
                "Failed to clear cache pattern: {error}",
                error=str(e),
                operation="clear_pattern",
                cache_key=pattern,
                hit=False,
                duration_ms=0,
                event_type="CACHE_OPERATION",
                timestamp=datetime.now()
            )
            return 0

    
