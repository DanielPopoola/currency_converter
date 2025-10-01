from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from app.cache.redis_manager import CircuitBreakerState, RedisManager
from app.config.database import DatabaseManager
from app.database.models import CircuitBreakerLog
from app.monitoring.logger import logger


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open and blocking calls"""
    def __init__(self, provider_name: str, failure_count: int, last_failure_time: datetime):
        self.provider_name = provider_name
        self.failure_count = failure_count
        self.last_failure_time = last_failure_time
        super().__init__(f"Circuit breaker OPEN for {provider_name} ({failure_count} failures)")


class CircuitBreaker:
    """Circuit Breaker implementation for API Providers"""
    
    def __init__(
            self,
            provider_id: int,
            provider_name: str,
            redis_manager: RedisManager,
            db_manager: DatabaseManager,
            failure_threshold: int = 5,
            recovery_timeout: int = 3600,
            success_threshold: int = 2
    ):
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.redis_manager = redis_manager
        self.db_manager = db_manager
        
        # Circuit breaker configuration
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        # Production Logger
        self.logger = logger.bind(service="CircuitBreaker", provider_name=self.provider_name)

        # Track consecutive successes in HALF_OPEN state
        self._consecutive_successes = 0

        # CircuitBreakerError needs datetime.now() for logs
        self.last_failure_time = datetime.now()


    async def call(self, func: Callable[[], Awaitable[Any]]) -> Any:
        """Execute function with circuit breaker protection"""

        # Check current circuit state
        current_state = await self.redis_manager.get_circuit_breaker_state(self.provider_id)

        if current_state == CircuitBreakerState.OPEN:
            # Check if recovery timeout has passed
            if await self._should_attempt_reset():
                await self._transition_to_half_open()
            else:
                # Still in cooldown period
                failure_count = await self.redis_manager.get_failure_count(self.provider_id)
                raise CircuitBreakerError(
                    self.provider_name,
                    failure_count,
                    datetime.now()
                )
            
        # Execute the function
        try:
            result = await func()
            await self._on_success()
            return result
        except Exception:
            await self._on_failure()
            raise


    async def _on_success(self):
        """Handle successful API call"""
        current_state = await self.redis_manager.get_circuit_breaker_state(self.provider_id)

        if current_state == CircuitBreakerState.HALF_OPEN:
            self._consecutive_successes += 1

            if self._consecutive_successes >= self.success_threshold:
                # Enough successes - close the circuit
                await self._transition_to_closed("recovery_successful")
                self.logger.info(
                    "Circuit breaker state change: {old_state} -> {new_state}",
                    old_state="HALF_OPEN",
                    new_state="CLOSED",
                    failure_count=0,
                    reason=f"recovery_successful after {self._consecutive_successes} successes",
                    event_type="CIRCUIT_BREAKER",
                    timestamp=datetime.now()
                )
            else:
                self.logger.debug(
                    "Circuit breaker HALF_OPEN for {provider_name}: {consecutive_successes}/{success_threshold} successes",
                    provider_name=self.provider_name,
                    consecutive_successes=self._consecutive_successes,
                    success_threshold=self.success_threshold,
                    event_type="CIRCUIT_BREAKER",
                    timestamp=datetime.now()
                )
        
        elif current_state == CircuitBreakerState.CLOSED:
            # Reset failure count on successful call in normal operation
            await self.redis_manager.reset_failure_count(self.provider_id)
            

    async def _on_failure(self):
        """Handle failed API call"""
        current_state = await self.redis_manager.get_circuit_breaker_state(self.provider_id)
        
        # Reset consecutive successes if we were in HALF_OPEN
        if current_state == CircuitBreakerState.HALF_OPEN:
            self._consecutive_successes = 0
            await self._transition_to_open("failure_during_recovery")
            return
        
        # Increment failure count
        failure_count = await self.redis_manager.increment_failure_count(self.provider_id)
        
        # Check if we should open the circuit
        if failure_count >= self.failure_threshold:
            await self._transition_to_open(f"{failure_count}_consecutive_failures")
        else:
            self.logger.warning(
                "API failure for {provider_name}: {failure_count}/{failure_threshold}",
                provider_name=self.provider_name,
                failure_count=failure_count,
                failure_threshold=self.failure_threshold,
                event_type="CIRCUIT_BREAKER",
                timestamp=datetime.now()
            )

    async def _should_attempt_reset(self):
        """Check if enough time has passed to attempt circuit reset"""
        try:
            last_failure_value = await self.redis_manager.get_last_failure_time(self.provider_id)
            
            if not last_failure_value:
                return True
            
            last_failure_time = datetime.fromisoformat(last_failure_value)
            time_since_failure = datetime.now(tz=UTC) - last_failure_time

            # Check if recovery timeout has passed
            has_enough_time_passed = time_since_failure.total_seconds() >= self.recovery_timeout
            
            if has_enough_time_passed:
                self.logger.debug(
                    "Recovery timeout passed for {provider_name}: {time_since_failure_seconds}s >= {recovery_timeout}s",
                    provider_name=self.provider_name,
                    time_since_failure_seconds=time_since_failure.total_seconds(),
                    recovery_timeout=self.recovery_timeout,
                    event_type="CIRCUIT_BREAKER",
                    timestamp=datetime.now()
                )
                return True
            else:
                self.logger.debug(
                    "Still in cooldown for {provider_name}: {time_since_failure_seconds}s < {recovery_timeout}s",
                    provider_name=self.provider_name,
                    time_since_failure_seconds=time_since_failure.total_seconds(),
                    recovery_timeout=self.recovery_timeout,
                    event_type="CIRCUIT_BREAKER",
                    timestamp=datetime.now()
                )
                return False
                
        except Exception as e:
            self.logger.error(
                "Error checking reset timeout for {provider_name}: {error}",
                provider_name=self.provider_name,
                error=str(e),
                event_type="CIRCUIT_BREAKER",
                timestamp=datetime.now()
            )
            # Fail safe - allow reset if we can't determine the time
            return True

    async def _transition_to_closed(self, reason: str):
        """Transition circuit breaker to CLOSED state"""
        await self._transition_state(CircuitBreakerState.CLOSED, reason, 0)
        await self.redis_manager.reset_failure_count(self.provider_id)
        self._consecutive_successes = 0
    
    async def _transition_to_open(self, reason: str):
        """Transition circuit breaker to OPEN state"""
        failure_count = await self.redis_manager.get_failure_count(self.provider_id)
        await self._transition_state(CircuitBreakerState.OPEN, reason, failure_count)
        self._consecutive_successes = 0
    
    async def _transition_to_half_open(self):
        """Transition circuit breaker to HALF_OPEN state"""
        await self._transition_state(CircuitBreakerState.HALF_OPEN, "attempting_recovery", 0)
        self._consecutive_successes = 0

    async def _transition_state(self, new_state: CircuitBreakerState, reason: str, failure_count: int):
        """Handle state transitions with hybrid persistence"""
        current_state = await self.redis_manager.get_circuit_breaker_state(self.provider_id)

        # Update Redis
        await self.redis_manager.set_circuit_breaker_state(self.provider_id, new_state, failure_count, reason)

        # Log to PostgreSQL
        try:
            with self.db_manager.get_session() as session:
                log_entry = CircuitBreakerLog(
                    provider_id=self.provider_id,
                    previous_state=current_state.value if current_state.value else None,
                    new_state=new_state.value,
                    failure_count=failure_count,
                    reason=reason
                )
                session.add(log_entry)
        except Exception as e:
            self.logger.error(
                "Failed to log circuit breaker state change to database: {error}",
                error=str(e),
                event_type="DATABASE_OPERATION",
                timestamp=datetime.now()
            )
        
        self.logger.info(
            "Circuit breaker state change: {old_state} -> {new_state}",
            old_state=current_state.value,
            new_state=new_state.value,
            failure_count=failure_count,
            reason=reason,
            event_type="CIRCUIT_BREAKER",
            timestamp=datetime.now()
        )
    
    async def get_status(self) -> dict:
        """Get current circuit breaker status for monitoring"""
        state = await self.redis_manager.get_circuit_breaker_state(self.provider_id)
        failure_count = await self.redis_manager.get_failure_count(self.provider_id)
        status = "healthy" if state.value == "CLOSED" else "unhealthy"
         
        return {
            "provider_name": self.provider_name,
            "state": state.value,
            "status": status,
            "failure_count": failure_count,
            "failure_threshold": self.failure_threshold,
            "consecutive_successes": self._consecutive_successes,
            "success_threshold": self.success_threshold
        }
    
    async def force_reset(self):
        """Manually reset circuit breaker (for admin/debugging)"""
        await self._transition_to_closed("manual_reset")
        self.logger.warning(
            "Circuit breaker manually closed for {provider_name}: manual reset",
            provider_name=self.provider_name,
            event_type="CIRCUIT_BREAKER",
            timestamp=datetime.now()
        )
    
    async def force_open(self, reason: str = "manual_open"):
        """Manually open circuit breaker (for maintenance)"""  
        await self._transition_to_open(reason)
        self.logger.warning(
            "Circuit breaker manually opened for {provider_name}: {reason}",
            provider_name=self.provider_name,
            reason=reason,
            event_type="CIRCUIT_BREAKER",
            timestamp=datetime.now()
        )