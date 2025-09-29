import json
import logging
from datetime import datetime, UTC
from enum import Enum
from typing import Any, List, Optional, Dict

from redis import asyncio as redis

logger = logging.getLogger(__name__)


class CircuitBreakerState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class RedisManager:
    """Handles all Redis operations for caching and circuit breaker state"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
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
    
    # Rate caching method
    async def rate_cache(self, base: str, target: str, rate_data: Dict[str, Any]):
        """Cache exchange rate with TTL-only expiry"""
        try:
            cache_key = self._get_rate_cache_key(base, target)

            # Add metadata to cached data
            cache_data = {
                **rate_data,
                "cached_at": datetime.now(tz=UTC).isoformat(),
                "cache_key": cache_key
            }

            # Store with TTL
            result = await self.redis_client.setex(
                cache_key,
                self.RATE_CACHE_TTL,
                json.dumps(cache_data)
            )

            logger.debug(f"Cached rate {base} --> {target}: {cache_key}")
            return result
        
        except Exception as e:
            logger.error(f"Failed to cache rate {base}->{target}: {e}")
            return False
        
    async def get_cached_rate(self, base: str, target: str) -> Dict[str, Any] | None:
        """Retrieve cached rate - TTL handles expiry automatically"""
        try:
            cache_key = self._get_rate_cache_key(base, target)
            cached_data = await self.redis_client.get(cache_key)

            if cached_data:
                rate_data = json.loads(cached_data)
                logger.debug(f"Cache hit for {base}-->{target}")
                return rate_data
            else:
                logger.debug(f"Cache miss for {base} --> {target}")
                return None
            
        except Exception as e:
            logger.error(f"Failed to retrieve cached rate {base}->{target}: {e}")
            return None

    async def set_cache_validation_result(self, cache_key: str, ttl: int, cache_data: Dict[str, Any]) -> bool:
        """Cache currency validation results with specified TTL."""

        try:
            json_data = json.dumps(cache_data)

            result = await self.redis_client.setex(cache_key, ttl, json_data)
            logger.debug(f"Cached validation result: {cache_key} (TTL: {ttl}s)")
            return bool(result)
        except Exception as e:
            logger.error(f"Failed to cache validation result {cache_key}: {e}")
            return False
        
    async def get_cached_currency(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve cached currency validation result"""
        try:
            cached_value = await self.redis_client.get(cache_key)

            if cached_value is None:
                logger.debug(f"Cache miss for validation: {cache_key}")
                return None
            
            validation_data = json.loads(cached_value)
            logger.debug(f"Cache hit for validation: {cache_key}")
            return validation_data
        except json.JSONDecodeError as e:
            # Corrupted data in cache - treat as miss
            logger.warning(f"Corrupted cache data for {cache_key}: {e}")
            return None
        except Exception as e:
            # Any other error - treat as miss
            logger.error(f"Failed to retrieve cached validation {cache_key}: {e}")
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
            logger.error(f"Failed to get circuit breaker state for provider {provider_id}: {e}")
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

            logger.info(f"Circuit breaker {provider_id}: {state.value} (failures: {failure_count})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set circuit breaker state for provider {provider_id}: {e}")
            return False
        
    async def get_failure_count(self, provider_id: int) -> int:
        """Get current failure count for circuit breaker logic"""
        try:
            failures_key = self._get_circuit_breaker_key(provider_id, "failures")
            count = await self.redis_client.get(failures_key)
            return int(count) if count else 0
            
        except Exception as e:
            logger.error(f"Failed to get failure count for provider {provider_id}: {e}")
            return 0
        
    async def increment_failure_count(self, provider_id: int) -> int:
        """Increment failure count and return new count"""
        try:
            failures_key = self._get_circuit_breaker_key(provider_id, "failures")
            new_count = await self.redis_client.incr(failures_key)
            await self.redis_client.expire(failures_key, self.CIRCUIT_BREAKER_TTL)
            
            logger.debug(f"Provider {provider_id} failure count: {new_count}")
            return new_count
        except Exception as e:
            logger.error(f"Failed to increment failure count for provider {provider_id}: {e}")
            return 0
        
    async def reset_failure_count(self, provider_id: int) -> bool:
        """Reset failure count (on successful recovery)"""
        try:
            failures_key = self._get_circuit_breaker_key(provider_id, "failures")
            await self.redis_client.delete(failures_key)
            
            logger.debug(f"Reset failure count for provider {provider_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reset failure count for provider {provider_id}: {e}")
            return False

    async def get_last_failure_time(self, provider_id: int) -> str | None:
        """Get the timestamp of the last recorded failure."""
        try:
            last_failure_key = self._get_circuit_breaker_key(provider_id, "last_failure")
            return await self.redis_client.get(last_failure_key)
        except Exception as e:
            logger.error(f"Failed to get last failure time for provider {provider_id}: {e}")
            return None

    async def get_top_currencies(self) -> List[str]:
        """Retrieve cached list of top currencies."""
        try:
            cached_data = await self.redis_client.get(self.TOP_CURRENCIES_KEY)
            if cached_data:
                return json.loads(cached_data)
            return []
        except Exception as e:
            logger.error(f"Failed to retrieve top currencies from cache: {e}")
            return []

    async def set_top_currencies(self, currencies: List[str], ttl: int = 86400):
        """Cache a list of top currencies with a specified TTL."""
        try:
            await self.redis_client.setex(self.TOP_CURRENCIES_KEY, ttl, json.dumps(currencies))
            logger.info(f"Cached {len(currencies)} top currencies with TTL {ttl}s")
        except Exception as e:
            logger.error(f"Failed to cache top currencies: {e}")


    # Utility methods

    async def health_check(self) -> Dict[str, Any]:
        """Check Redis connection health"""
        try:
            start_time = datetime.now(tz=UTC)
            await self.redis_client.ping()
            response_time = (datetime.now(tz=UTC) - start_time).total_seconds() * 1000
            
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
                logger.info(f"Cleared {deleted} cache keys matching {pattern}")
                return deleted
            return 0
        except Exception as e:
            logger.error(f"Failed to clear cache pattern {pattern}: {e}")
            return 0

    
