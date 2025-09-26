import json
import logging
from datetime import datetime, UTC
from enum import Enum
from typing import Any

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

    def _get_rate_cache_key(self, base: str, target: str, timestamp_bucket: str | None = None) -> str:
        """Generate cache key for exchange rates with 5-minute bucketing"""
        if not timestamp_bucket:
            # Create 5-minute bucket: 2025-09-18T10:35:00 -> 2025-09-18T10:30:00
            now = datetime.now(tz=UTC)
            bucket_minutes = (now.minute // 5) * 5
            timestamp_bucket = now.replace(minute=bucket_minutes, second=0, microsecond=0).strftime("%Y%m%d%H%M%S")

        return f"rates:{base}:{target}:{timestamp_bucket}"
    
    def _get_circuit_breaker_key(self, provider_id: int, suffix: str) -> str:
        """Generate circuit breaker keys"""
        return f"circuit_breaker:{provider_id}:{suffix}"
    
    # Rate caching method
    async def rate_cache(self, base: str, target: str, rate_data: dict[str, Any]):
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
        
    async def get_cached_rate(self, base: str, target: str) -> dict[str, Any] | None:
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
        
    # Utility methods

    async def health_check(self) -> dict[str, Any]:
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
