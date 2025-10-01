from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.cache.redis_manager import CircuitBreakerState, RedisManager
from app.config.database import DatabaseManager
from app.services.circuit_breaker import CircuitBreaker, CircuitBreakerError


class TestCircuitBreakerBasicBehavior:
    """Test fundamental circuit breaker behavior - CLOSED state"""

    @pytest.fixture
    def mock_redis_manager(self):
        """Create a mock redis manager for testing"""
        mock_redis = AsyncMock(spec=RedisManager)
        # Default: circuit is CLOSED (healthy state)
        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.CLOSED
        mock_redis.get_failure_count.return_value = 0
        return mock_redis
    
    @pytest.fixture
    def mock_db_manager(self):
        """Create a mock database manager"""
        return Mock(spec=DatabaseManager)
    
    @pytest.fixture
    def circuit_breaker(self, mock_redis_manager, mock_db_manager):
        """Create circuit breaker with mocked dependencies"""
        return CircuitBreaker(
            provider_id=1,
            provider_name="TestProvider",
            redis_manager=mock_redis_manager,
            db_manager=mock_db_manager,
            failure_threshold=3,
            recovery_timeout=60,
            success_threshold=2
        )
    
    @pytest.fixture
    def recovery_setup(self):
        """Setup circuit breaker for recovery testing"""
        mock_redis = AsyncMock(spec=RedisManager)
        mock_db = Mock(spec=DatabaseManager)

        cb = CircuitBreaker(
            provider_id=1,
            provider_name="RecoveryTest",
            redis_manager=mock_redis,
            db_manager=mock_db,
            success_threshold=2
        )

        return cb, mock_redis, mock_db
    
    @pytest.mark.asyncio
    async def test_consecutive_success_counting_in_half_open(self, recovery_setup):
        """Test: Verify consecutive successes are counted correctly in HALF_OPEN"""
        # This test specifically checks the internal counter logic
        cb, mock_redis, _ = recovery_setup
        
        # Start in HALF_OPEN state
        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.HALF_OPEN
        
        async def successful_api_call():
            return "Success!"
        
        # Act: Make 1 successful call (not enough to close yet)
        await cb.call(successful_api_call)
        
        # Assert: Should increment counter but NOT close circuit yet
        assert cb._consecutive_successes == 1  # Check internal state
        
        # No transition to CLOSED should happen yet
        calls = mock_redis.set_circuit_breaker_state.call_args_list
        closed_calls = [call for call in calls if call[0][1] == CircuitBreakerState.CLOSED]
        assert len(closed_calls) == 0, "Circuit should not close after only 1 success"
        
        # Act: Make 2nd successful call (should close circuit)
        await cb.call(successful_api_call)
        
        # Assert: Should close circuit now
        calls = mock_redis.set_circuit_breaker_state.call_args_list
        closed_calls = [call for call in calls if call[0][1] == CircuitBreakerState.CLOSED]
        assert len(closed_calls) == 1, "Circuit should close after 2 successes"
        
        # Counter should reset after closing
        assert cb._consecutive_successes == 0
    
    @pytest.mark.asyncio
    async def test_successfull_call_when_closed(self, circuit_breaker, mock_redis_manager):
        """Test: When circuit is CLOSED, successful calls should work normally"""
        # Arrange
        async def mock_api_call():
            return {"rate": Decimal("1.23"), "status": "success"}
        
        # Act
        result = await circuit_breaker.call(mock_api_call)

        # Assert
        assert result['status'] == "success"
        # Should reset failure count on success
        mock_redis_manager.reset_failure_count.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_failure_increments_count_but_stays_closed(self, circuit_breaker, mock_redis_manager):
        """Test: Single failure should increment count but keep circuit CLOSED"""
        # Arrange
        async def failing_api_call():
            raise Exception("API is down!")
        
        mock_redis_manager.increment_failure_count.return_value = 1

        # Act & Assert
        with pytest.raises(Exception, match="API is down!"):
            await circuit_breaker.call(failing_api_call)

        # Should increment failure count
        mock_redis_manager.increment_failure_count.assert_called_once_with(1)
        # Should NOT transition to OPEN yet (threshold is 3)
        mock_redis_manager.set_circuit_breaker_state.assert_not_called()


class TestCircuitBreakerFailureThreshold:
    """Test circuit breaker opening after hitting failure threshold"""

    @pytest.fixture
    def circuit_breaker_setup(self):
        """Setup circuit breaker with mocks"""
        mock_redis = AsyncMock(spec=RedisManager)
        mock_db = Mock(spec=DatabaseManager)

        cb = CircuitBreaker(
            provider_id=1,
            provider_name="TestProvider", 
            redis_manager=mock_redis,
            db_manager=mock_db,
            failure_threshold=3
        )

        return cb, mock_redis, mock_db
    
    @pytest.mark.asyncio
    async def test_circuit_opens_after_failure_threshold(self, circuit_breaker_setup):
        """Test: Circuit should OPEN after hitting failure threshold"""
        # Arrange
        cb, mock_redis, _ = circuit_breaker_setup

        # Circuit starts CLOSED
        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.CLOSED
        # This will be the 3rd failure (hitting threshold)
        mock_redis.increment_failure_count.return_value = 3

        async def failing_api_call():
            raise Exception("API failure!")
        
        # Act
        with pytest.raises(Exception):
            await cb.call(failing_api_call)

        # Assert: should transition to OPEN state
        mock_redis.set_circuit_breaker_state.assert_called_once()
        call_args = mock_redis.set_circuit_breaker_state.call_args
        assert call_args[0][1] == CircuitBreakerState.OPEN

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_calls_when_open(self, circuit_breaker_setup):
        """Test: When circuit is OPEN, should block all calls immediately"""
        # Arrange
        cb, mock_redis, _ = circuit_breaker_setup

        # Circuit is OPEN
        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.OPEN
        mock_redis.get_failure_count.return_value = 5

        # Mock that recovery timeout hasn't passed yet
        with patch.object(cb, '_should_attempt_reset', return_value=False):
            async def api_call():
                return "This should never be called!"
            
            # Act & Assert
            with pytest.raises(CircuitBreakerError) as exc_info:
                await cb.call(api_call)

            assert "Circuit breaker OPEN" in str(exc_info.value)
            assert "TestProvider" in str(exc_info.value)


class TestCircuitBreakerRecovery:
    """Test circuit breaker recovery logic (HALF_OPEN -> CLOSED)"""

    @pytest.fixture
    def recovery_setup(self):
        """Setup circuit breaker for recovery testing"""
        mock_redis = AsyncMock(spec=RedisManager)
        mock_db = Mock(spec=DatabaseManager)

        cb = CircuitBreaker(
            provider_id=1,
            provider_name="RecoveryTest",
            redis_manager=mock_redis,
            db_manager=mock_db,
            success_threshold=2
        )

        return cb, mock_redis, mock_db

    @pytest.mark.asyncio
    async def test_recovery_timeout_triggers_half_open(self, recovery_setup):
        """Test: After timeout, OPEN circuit should try HALF_OPEN"""
        # Arrange
        cb, mock_redis, _ = recovery_setup

        # Circuit is OPEN but timeout has passed
        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.OPEN

        with patch.object(cb, '_should_attempt_reset', return_value=True):
            async def successful_api_call():
                return "Success!"
            
            # Act
            result = await cb.call(successful_api_call)

            assert result == "Success!"
            # Should transition state to HALF_OPEN first
            calls = mock_redis.set_circuit_breaker_state.call_args_list
            assert any(call[0][1] == CircuitBreakerState.HALF_OPEN for call in calls)

    @pytest.mark.asyncio
    async def test_successful_recovery_closes_circuit(self, recovery_setup):
        """Test: Enough successes in HALF_OPEN should close circuit"""
        # Arrange
        cb, mock_redis, _ = recovery_setup
        
        # Start in HALF_OPEN state
        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.HALF_OPEN
        
        async def successful_api_call():
            return "Success!"
        
        # Act: Make 2 successful calls (meets success_threshold)
        await cb.call(successful_api_call)  # 1st success
        await cb.call(successful_api_call)  # 2nd success - should close circuit
        
        # Assert: Should transition to CLOSED
        calls = mock_redis.set_circuit_breaker_state.call_args_list
        # Last call should be transitioning to CLOSED
        final_call = calls[-1]
        assert final_call[0][1] == CircuitBreakerState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_during_recovery_reopens_circuit(self, recovery_setup):
        """Test: Failure during HALF_OPEN should immediately go back to OPEN"""
        # Arrange
        cb, mock_redis, _ = recovery_setup

        # Start in HALF_OPEN state
        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.HALF_OPEN
        mock_redis.get_failure_count.return_value = 0

        # Set a consecutive success to verify it gets reset
        cb._consecutive_successes = 1
        
        async def failing_api_call():
            raise Exception("Still broken!")

        # Act
        with pytest.raises(Exception, match="Still broken!"):
            await cb.call(failing_api_call)

        # Assert: Should go back to OPEN immediately
        mock_redis.set_circuit_breaker_state.assert_called_with(
            1, # provider_id
            CircuitBreakerState.OPEN,
            0, # failure_count (gets reset when transitioning states)
            "failure_during_recovery"
        )

        assert cb._consecutive_successes == 0
        
        # Assert: Should NOT increment failure count (different from normal failures)
        mock_redis.increment_failure_count.assert_not_called()

    @pytest.mark.asyncio
    async def test_specific_failure_handling(self, recovery_setup):
        """Integration test: Verify different failure handling by state"""
        # This test verifies the state machine handles failures correctly
        cb, mock_redis, _ = recovery_setup
        
        async def failing_call():
            raise Exception("Failure!")

        # Scenario 1: Failure in CLOSED state (should count)
        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.CLOSED
        mock_redis.increment_failure_count.return_value = 1
        
        with pytest.raises(Exception):
            await cb.call(failing_call)
        
        mock_redis.increment_failure_count.assert_called_with(1)
        assert mock_redis.set_circuit_breaker_state.call_count == 0  # No state change yet
        
        # Reset mocks for next scenario
        mock_redis.reset_mock()
        
        # Scenario 2: Failure in HALF_OPEN state (should immediately open)
        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.HALF_OPEN
        mock_redis.get_failure_count.return_value = 0
        cb._consecutive_successes = 1
        
        with pytest.raises(Exception):
            await cb.call(failing_call)
        
        # Should transition to OPEN immediately, no failure counting
        mock_redis.set_circuit_breaker_state.assert_called_once()
        mock_redis.increment_failure_count.assert_not_called()
        assert cb._consecutive_successes == 0


class TestCircuitBreakerTimeLogic:
    """Test time-based logic from recovery timeouts"""

    @pytest.mark.asyncio
    async def test_should_attempt_reset_logic(self):
        """Test the timeout logic for when to attempt reset"""
        # Arrange
        mock_redis = AsyncMock(spec=RedisManager)
        mock_db = Mock(spec=DatabaseManager)
        
        cb = CircuitBreaker(
            provider_id=1,
            provider_name="TimeTest",
            redis_manager=mock_redis,
            db_manager=mock_db,
            recovery_timeout=60  # 1 minute timeout
        )
        
        # Mock the public method on RedisManager
        past_time = datetime.now(tz=UTC) - timedelta(seconds=30)
        mock_redis.get_last_failure_time.return_value = past_time.isoformat()
        
        # Act
        should_reset = await cb._should_attempt_reset()
        
        # Assert: 30 seconds < 60 seconds, so should NOT reset yet
        assert should_reset is False
        
        # Test with old enough failure time
        old_time = datetime.now(tz=UTC) - timedelta(seconds=70)
        mock_redis.get_last_failure_time.return_value = old_time.isoformat()
        
        should_reset = await cb._should_attempt_reset()
        assert should_reset is True


class TestCircuitBreakerMonitoring:
    """Test monitoring and status methods"""

    @pytest.mark.asyncio
    async def test_get_status_returns_correct_info(self):
        # Arrange
        mock_redis = AsyncMock(spec=RedisManager)
        mock_db = Mock(spec=DatabaseManager)

        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.OPEN
        mock_redis.get_failure_count.return_value = 5
        
        cb = CircuitBreaker(
            provider_id=1,
            provider_name="MonitorTest",
            redis_manager=mock_redis,
            db_manager=mock_db,
            failure_threshold=3,
            success_threshold=2
        )

        # Act
        status = await cb.get_status()

        # Assert
        expected_keys = [
            "provider_name", "state", "failure_count", 
            "failure_threshold", "success_threshold", "consecutive_successes"
        ]

        for key in expected_keys:
            assert key in status

        assert status["provider_name"] == "MonitorTest"
        assert status["state"] == "OPEN"
        assert status["failure_count"] == 5

    @pytest.mark.asyncio
    async def test_force_reset_transitions_to_closed(self):
        """Test manual reset functionality"""
        # Arrange
        mock_redis = AsyncMock(spec=RedisManager)
        mock_db = Mock(spec=DatabaseManager)
        
        cb = CircuitBreaker(
            provider_id=1,
            provider_name="ResetTest", 
            redis_manager=mock_redis,
            db_manager=mock_db
        )
        
        # Act
        await cb.force_reset()
        
        # Assert
        mock_redis.set_circuit_breaker_state.assert_called()
        call_args = mock_redis.set_circuit_breaker_state.call_args
        assert call_args[0][1] == CircuitBreakerState.CLOSED


class TestCircuitBreakerStateFlowComplete:
    """Test the complete state flow: CLOSED -> OPEN -> HALF_OPEN -> CLOSED"""

    @pytest.fixture
    def flow_test_setup(self):
        """Setup for testing complete state flow"""
        mock_redis = AsyncMock(spec=RedisManager)
        # Use MagicMock to automatically handle the context manager protocol for the DB logger
        mock_db = MagicMock(spec=DatabaseManager)

        cb = CircuitBreaker(
            provider_id=1,
            provider_name="FlowTest",
            redis_manager=mock_redis,
            db_manager=mock_db,
            failure_threshold=2,  # Open after 2 failures
            success_threshold=1   # Close after 1 success in HALF_OPEN
        )

        return cb, mock_redis, mock_db


    @pytest.mark.asyncio
    async def test_complete_circuit_breaker_state_flow(self, flow_test_setup):
        """Integration test: CLOSED -> OPEN -> HALF_OPEN -> CLOSED"""
        cb, mock_redis, _ = flow_test_setup

        # PHASE 1: Start CLOSED, accumulate failures to OPEN
        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.CLOSED

        async def failing_api_call():
            raise Exception("API down!")
        
        # First failure - should stay CLOSED
        mock_redis.increment_failure_count.return_value = 1
        with pytest.raises(Exception):
            await cb.call(failing_api_call)
        assert mock_redis.set_circuit_breaker_state.call_count == 0

        # Second failure - should transition to OPEN
        mock_redis.increment_failure_count.return_value = 2  # Hits threshold
        with pytest.raises(Exception):
            await cb.call(failing_api_call)
        
        open_calls = [call for call in mock_redis.set_circuit_breaker_state.call_args_list
                      if call.args[1] == CircuitBreakerState.OPEN]
        assert len(open_calls) == 1, "Should transition to OPEN after threshold failures"

        # PHASE 2: OPEN -> HALF_OPEN -> CLOSED
        mock_redis.reset_mock()

        # Make the mock stateful for this phase by returning values in sequence.
        # The list needs to be long enough for all calls, including logging.
        mock_redis.get_circuit_breaker_state.side_effect = [
            CircuitBreakerState.OPEN,       # 1. In .call() to check if open
            CircuitBreakerState.OPEN,       # 2. In _transition_state (logging prev state)
            CircuitBreakerState.HALF_OPEN,  # 3. In _on_success() to check for recovery
            CircuitBreakerState.HALF_OPEN   # 4. In _transition_state (logging prev state)
        ]

        async def recovery_call():
            return "API is back!"
        
        # Mock that timeout has passed, allowing a recovery attempt
        with patch.object(cb, "_should_attempt_reset", return_value=True):
            result = await cb.call(recovery_call)
            assert result == "API is back!"

            # Verify the state transitions happened correctly
            calls = mock_redis.set_circuit_breaker_state.call_args_list
            
            half_open_calls = [call for call in calls if call.args[1] == CircuitBreakerState.HALF_OPEN]
            closed_calls = [call for call in calls if call.args[1] == CircuitBreakerState.CLOSED]
            
            assert len(half_open_calls) >= 1, "Should transition to HALF_OPEN"
            assert len(closed_calls) >= 1, "Should transition to CLOSED after successful recovery"

    @pytest.mark.asyncio
    async def test_failed_recovery_goes_back_to_open(self, flow_test_setup):
        """Test: OPEN -> HALF_OPEN -> (failure) -> OPEN"""
        cb, mock_redis, _ = flow_test_setup
        
        # Start: Circuit is OPEN, timeout has passed
        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.OPEN
        mock_redis.increment_failure_count.return_value = 2
        
        async def still_failing():
            raise Exception("Still broken!")
        
        with patch.object(cb, '_should_attempt_reset', return_value=True):
            # First call after timeout should:
            # 1. Transition to HALF_OPEN
            # 2. Try the call
            # 3. Call fails -> transition back to OPEN
            
            with pytest.raises(Exception, match="Still broken!"):
                await cb.call(still_failing)
            
            calls = mock_redis.set_circuit_breaker_state.call_args_list
            
            # Should see: HALF_OPEN transition + OPEN transition
            half_open_calls = [call for call in calls if call[0][1] == CircuitBreakerState.HALF_OPEN]
            open_calls = [call for call in calls if call[0][1] == CircuitBreakerState.OPEN]
            
            assert len(half_open_calls) >= 1, "Should transition to HALF_OPEN on timeout"
            assert len(open_calls) >= 1, "Should go back to OPEN when recovery call fails"


# Integration-style test (tests multiple components together)
class TestCircuitBreakerIntegration:
    """Test circuit breaker with more realistic scenarios"""

    @pytest.mark.asyncio
    async def test_full_failure_and_recovery_cycle(self):
        """Integration test: Complete failure -> recovery cycle"""
        # This test verifies the entire state machine works correctly
        mock_redis = AsyncMock(spec=RedisManager)
        mock_db = MagicMock(spec=DatabaseManager)

        cb = CircuitBreaker(
            provider_id=1,
            provider_name="IntegrationTest",
            redis_manager=mock_redis,
            db_manager=mock_db,
            failure_threshold=2,
            success_threshold=1
        )

        # Step 1: Circuit starts CLOSED
        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.CLOSED

        # Step 2: First failure - should stay CLOSED
        mock_redis.increment_failure_count.return_value = 1
        async def fail_once():
            raise Exception("First failure")

        with pytest.raises(Exception):
            await cb.call(fail_once)

        # Step 3: Second failure - should OPEN circuit  
        mock_redis.increment_failure_count.return_value = 2
        with pytest.raises(Exception):
            await cb.call(fail_once)
        
        # Verify circuit opened
        calls = mock_redis.set_circuit_breaker_state.call_args_list
        assert any(call[0][1] == CircuitBreakerState.OPEN for call in calls)
        
        # Step 4: After timeout, should allow one call (HALF_OPEN)
        mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.OPEN
        
        with patch.object(cb, '_should_attempt_reset', return_value=True):
            mock_redis.get_circuit_breaker_state.return_value = CircuitBreakerState.HALF_OPEN
            
            async def success():
                return "API is back!"
            
            result = await cb.call(success)
            assert result == "API is back!"
            
            # Should close circuit after successful recovery
            final_calls = mock_redis.set_circuit_breaker_state.call_args_list
            assert any(call[0][1] == CircuitBreakerState.CLOSED for call in final_calls)