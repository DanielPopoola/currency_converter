from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.cache.redis_manager import RedisManager
from app.config.database import DatabaseManager
from app.providers.base import APICallResult, ExchangeRateResponse
from app.services import CircuitBreaker, CurrencyManager
from app.services.circuit_breaker import CircuitBreaker, CircuitBreakerError
from app.services.rate_aggregator import AggregatedRateResult, RateAggregatorService


class TestRateAggregatorHappyPath:
    """Test normal operation - when everything works"""

    @pytest.fixture
    def mock_dependencies(self):
        """Create all the mocked dependencies for RateAggregator"""
        # Mock providers
        mock_primary_provider = AsyncMock()
        mock_secondary_provider = AsyncMock()
        providers = {
            "FixerIO": mock_primary_provider,
            "OpenExchange": mock_secondary_provider
        }

        # Mock circuit breakers
        mock_primary_cb = AsyncMock(spec=CircuitBreaker)
        mock_secondary_cb = AsyncMock(spec=CircuitBreaker)
        circuit_breakers = {
            "FixerIO": mock_primary_cb,
            "OpenExchange": mock_secondary_cb
        }

        # Mock Redis and DB
        mock_redis = AsyncMock(spec=RedisManager)
        mock_db = MagicMock(spec=DatabaseManager)
        mock_currency_manager = AsyncMock(spec=CurrencyManager)
        mock_currency_manager.validate_currencies.return_value = (True, None)

        return {
            "providers": providers,
            "circuit_breakers": circuit_breakers,
            "redis_manager": mock_redis,
            "db_manager": mock_db,
            "currency_manager": mock_currency_manager
        }
    
    @pytest.fixture
    def aggregator(self, mock_dependencies):
        """Create RateAggregator with mocked dependencies"""
        return RateAggregatorService(
            providers=mock_dependencies["providers"],
            circuit_breakers=mock_dependencies["circuit_breakers"],
            redis_manager=mock_dependencies["redis_manager"],
            db_manager=mock_dependencies["db_manager"],
            currency_manager=mock_dependencies["currency_manager"],
            primary_provider="FixerIO"
        )
    
    def create_successful_api_result(self, provider_name: str, rate: str, base: str = "USD", target: str = "EUR"):
        """Helper to create successful APICallResult"""
        exchange_rate = ExchangeRateResponse(
            base_currency=base,
            target_currency=target,
            rate=Decimal(rate),
            timestamp=datetime.now(UTC),
            provider_name=provider_name,
            raw_response={"test": "data"},
            is_successful=True
        )

        return APICallResult(
            provider_name=provider_name,
            endpoint="/latest",
            http_status_code=200,
            response_time_ms=150,
            was_successful=True,
            data=exchange_rate
        )
    
    @pytest.mark.asyncio
    async def test_cache_hit_returns_immediately(self, aggregator, mock_dependencies):
        """Test: Cache hit should return immediately without calling APIs"""
        # Arrange
        mock_redis = mock_dependencies["redis_manager"]
        cached_rate = {
            "rate": Decimal("1.23"),
            "confidence_level": "high",
            "sources_used": ["FixerIO"],
            "is_primary_used": True,
            "timestamp": datetime.now(UTC).isoformat()
        }
        mock_redis.get_cached_rate.return_value = cached_rate

        result = await aggregator.get_exchange_rate("USD", "EUR")

        assert result.cached is True
        assert result.rate == Decimal("1.23")
        assert result.confidence_level == "high"
        assert result.sources_used == ["FixerIO"]
        assert result.is_primary_used is True
        
        # Should not call any APIs
        mock_dependencies["providers"]["FixerIO"].get_exchange_rate.assert_not_called()
        mock_dependencies["providers"]["OpenExchange"].get_exchange_rate.assert_not_called()

    @pytest.mark.asyncio
    async def test_primary_success_only(self, aggregator, mock_dependencies):
        """Test: When only primary succeeds, return primary result"""
        # Arrange
        mock_redis = mock_dependencies["redis_manager"]
        mock_redis.get_cached_rate.return_value = None

        # Primary succeeds
        primary_result = self.create_successful_api_result("FixerIO", "1.23")
        mock_dependencies["circuit_breakers"]["FixerIO"].call.return_value = primary_result

        # Secondary fails
        mock_dependencies["circuit_breakers"]["OpenExchange"].call.side_effect = Exception("API down")

        # Act
        result = await aggregator.get_exchange_rate("USD", "EUR")

        # Assert
        assert result.cached is False
        assert result.rate == Decimal("1.23")
        assert result.confidence_level == "high"
        assert result.sources_used == ["FixerIO"]
        assert result.is_primary_used is True
        
        # Should cache the result
        mock_redis.rate_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_primary_and_secondary_success_returns_average(self, aggregator, mock_dependencies):
        """Test: When both primary and secondary succeed, return average"""
        # Arrange
        mock_redis = mock_dependencies["redis_manager"]
        mock_redis.get_cached_rate.return_value = None

        # Primary succeeds with rate 1.20
        primary_result = self.create_successful_api_result("FixerIO", "1.20")
        mock_dependencies["circuit_breakers"]["FixerIO"].call.return_value = primary_result

        # Secondary succeeds with rate 1.30
        secondary_result = self.create_successful_api_result("OpenExchange", "1.30")
        mock_dependencies["circuit_breakers"]["OpenExchange"].call.return_value = secondary_result

        # Act
        result = await aggregator.get_exchange_rate("USD", "EUR")

        # Assert - should average: (1.20 + 1.30) / 2 = 1.25
        assert result.cached is False
        assert result.rate == Decimal("1.25")
        assert result.confidence_level == "high"
        assert result.sources_used == ["FixerIO", "OpenExchange"]
        assert result.is_primary_used is False  # Using average, not just primary
        
        # Should cache the averaged result
        mock_redis.rate_cache.assert_called_once()


class TestRateAggregatorFailureScenarios:
    """Test what happens when things go wrong"""

    @pytest.fixture
    def aggregator_setup(self):
        """Setup aggregator with mocked dependencies"""
        # Create mocks
        providers = {"FixerIO": AsyncMock(), "OpenExchange": AsyncMock()}
        circuit_breakers = {"FixerIO": AsyncMock(), "OpenExchange": AsyncMock()}
        mock_redis = AsyncMock()
        mock_db = Mock()
        mock_currency_manager = AsyncMock()
        mock_currency_manager.validate_currencies.return_value = (True, None)
        
        aggregator = RateAggregatorService(
            providers=providers,
            circuit_breakers=circuit_breakers,
            redis_manager=mock_redis,
            db_manager=mock_db,
            currency_manager=mock_currency_manager,
            primary_provider="FixerIO"
        )
        
        return aggregator, providers, circuit_breakers, mock_redis, mock_db
    
    def create_failed_api_result(self, provider_name: str, error: str):
        """Helper to create failed APICallResult"""
        return APICallResult(
            provider_name=provider_name,
            endpoint="/latest",
            http_status_code=500,
            response_time_ms=5000,
            was_successful=False,
            error_message=error
        )
    
    @pytest.mark.asyncio
    async def test_primary_fails_secondary_succeeds(self, aggregator_setup):
        """Test: Primary fails, secondary succeeds"""
        # Arrange
        aggregator, _, circuit_breakers, mock_redis, _ = aggregator_setup
        mock_redis.get_cached_rate.return_value = None

        # Primary fails
        circuit_breakers["FixerIO"].call.side_effect = CircuitBreakerError("FixerIO", 5, datetime.now(UTC))

        # Secondary succeeds
        secondary_result = APICallResult(
            provider_name="OpenExchange",
            endpoint="/latest", 
            http_status_code=200,
            response_time_ms=200,
            was_successful=True,
            data=ExchangeRateResponse(
                base_currency="USD",
                target_currency="EUR", 
                rate=Decimal("1.25"),
                timestamp=datetime.now(UTC),
                provider_name="OpenExchange",
                raw_response={},
                is_successful=True
            )
        )
        circuit_breakers["OpenExchange"].call.return_value = secondary_result

        result = await aggregator.get_exchange_rate("USD", "EUR")

        assert result.rate == Decimal("1.25")
        assert result.confidence_level == "medium"  # Lower confidence without primary
        assert result.sources_used == ["OpenExchange"]
        assert result.is_primary_used is False
        assert len(result.warnings) == 1
        assert "Primary provider FixerIO unavailable" in result.warnings[0]

    @pytest.mark.asyncio
    async def test_multiple_secondaries_return_average(self, aggregator_setup):
        """Test: Primary fails, multiple secondaries succeed -> average them"""
        # Arrange
        aggregator, providers, circuit_breakers, mock_redis, _ = aggregator_setup

        # Add a third provider for this test
        providers["CurrencyAPI"] = AsyncMock()
        circuit_breakers["CurrencyAPI"] = AsyncMock()
        aggregator.providers = providers
        aggregator.circuit_breakers = circuit_breakers

        mock_redis.get_cached_rate.return_value = None

        # Primary fails
        circuit_breakers["FixerIO"].call.side_effect = Exception("Primary down")
        
        # Two secondaries succeed with different rates
        secondary1 = APICallResult(
            provider_name="OpenExchange",
            endpoint="/latest",
            http_status_code=200, 
            response_time_ms=150,
            was_successful=True,
            data=ExchangeRateResponse(
                base_currency="USD", target_currency="EUR", rate=Decimal("1.20"),
                timestamp=datetime.now(UTC), provider_name="OpenExchange",
                raw_response={}, is_successful=True
            )
        )
        
        secondary2 = APICallResult(
            provider_name="CurrencyAPI",
            endpoint="/latest",
            http_status_code=200,
            response_time_ms=180,
            was_successful=True, 
            data=ExchangeRateResponse(
                base_currency="USD", target_currency="EUR", rate=Decimal("1.30"),
                timestamp=datetime.now(UTC), provider_name="CurrencyAPI",
                raw_response={}, is_successful=True
            )
        )
        
        circuit_breakers["OpenExchange"].call.return_value = secondary1
        circuit_breakers["CurrencyAPI"].call.return_value = secondary2
        
        result = await aggregator.get_exchange_rate("USD", "EUR")
        
        assert result.rate == Decimal("1.25")
        assert result.confidence_level == "medium"
        assert set(result.sources_used) == {"OpenExchange", "CurrencyAPI"}
        assert result.is_primary_used is False

    @pytest.mark.asyncio
    async def test_all_apis_fail_uses_stale_cache(self, aggregator_setup):
        """Test: All APIs fail -> graceful degradation to stale cache"""

        aggregator, _, circuit_breakers, mock_redis, _ = aggregator_setup

        mock_redis.get_cached_rate.return_value = None
        
        # All APIs fail
        circuit_breakers["FixerIO"].call.side_effect = Exception("Primary down")
        circuit_breakers["OpenExchange"].call.side_effect = Exception("Secondary down")

        stale_data = {
            "rate": Decimal("1.15"),
            "timestamp": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            "sources_used": ["FixerIO"],
            "age_minutes": 120
        }

        # Mock the database query for stale cache
        with patch.object(aggregator, '_check_stale_cache', return_value=stale_data):
            result = await aggregator.get_exchange_rate("USD", "EUR")

            assert result.rate == Decimal("1.15")
            assert result.confidence_level == "low"
            assert result.cached is True
            assert len(result.warnings) == 2
            assert "All API providers unavailable" in result.warnings[0]
            assert "Using stale cache data" in result.warnings[1]

    @pytest.mark.asyncio
    async def test_complete_failure_raises_exception(self, aggregator_setup):
        """Test: No APIs work and no cache -> should raise exception"""
        # Arrange
        aggregator, _, circuit_breakers, mock_redis, _ = aggregator_setup
        
        # No cache at all
        mock_redis.get_cached_rate.return_value = None
        
        # All APIs fail
        circuit_breakers["FixerIO"].call.side_effect = Exception("Down")
        circuit_breakers["OpenExchange"].call.side_effect = Exception("Down")
        
        # No stale cache either
        with patch.object(aggregator, '_check_stale_cache', return_value=None):
            # Act & Assert
            with pytest.raises(Exception, match="No exchange rate data available"):
                await aggregator.get_exchange_rate("USD", "EUR")


class TestRateAggregatorCachingLogic:
    """Test caching behavior"""

    @pytest.fixture
    def cache_test_setup(self):
        """Setup for cache-specific tests"""
        providers = {"FixerIO": AsyncMock()}
        circuit_breakers = {"FixerIO": AsyncMock()}
        mock_redis = AsyncMock()
        mock_db = Mock()
        mock_currency_manager = AsyncMock()
        mock_currency_manager.validate_currencies.return_value = (True, None)

        aggregator = RateAggregatorService(
            providers=providers,
            circuit_breakers=circuit_breakers, 
            redis_manager=mock_redis,
            db_manager=mock_db,
            currency_manager=mock_currency_manager,
            primary_provider="FixerIO"
        )
        
        return aggregator, mock_redis

    @pytest.mark.asyncio
    async def test_cache_miss_calls_apis_then_caches(self, cache_test_setup):
        """Test: Cache miss -> call APIs -> cache the result"""
        # Arrange
        aggregator, mock_redis = cache_test_setup
        
        # No cache initially
        mock_redis.get_cached_rate.return_value = None
        
        # API succeeds
        api_result = APICallResult(
            provider_name="FixerIO",
            endpoint="/latest",
            http_status_code=200,
            response_time_ms=100,
            was_successful=True,
            data=ExchangeRateResponse(
                base_currency="USD", target_currency="EUR", rate=Decimal("1.20"),
                timestamp=datetime.now(UTC), provider_name="FixerIO",
                raw_response={}, is_successful=True
            )
        )
        aggregator.circuit_breakers["FixerIO"].call.return_value = api_result
        
        # Act
        result = await aggregator.get_exchange_rate("USD", "EUR")
        
        # Assert
        assert result.cached is False  # Fresh from API
        assert result.rate == Decimal("1.20")
        
        # Should cache the result
        mock_redis.rate_cache.assert_called_once()
        cache_call = mock_redis.rate_cache.call_args
        assert cache_call[0][0] == "USD"  # base currency
        assert cache_call[0][1] == "EUR"  # target currency
        # Third argument is the cache data dict
        cached_data = cache_call[0][2]
        assert cached_data["rate"] == "1.20"
        assert cached_data["confidence_level"] == "high"
    
    @pytest.mark.asyncio
    async def test_cached_result_not_recached(self, cache_test_setup):
        """Test: Returning cached result shouldn't trigger another cache write"""
        # Arrange  
        aggregator, mock_redis = cache_test_setup
        
        # Cache hit
        cached_data = {
            "rate": Decimal("1.30"),
            "confidence_level": "high", 
            "sources_used": ["FixerIO"],
            "is_primary_used": True,
            "timestamp": datetime.now(UTC).isoformat()
        }
        mock_redis.get_cached_rate.return_value = cached_data
        
        # Act
        result = await aggregator.get_exchange_rate("USD", "EUR")
        
        # Assert
        assert result.cached is True
        assert result.rate == Decimal("1.30")
        
        # Should NOT write to cache again
        mock_redis.rate_cache.assert_not_called()


class TestRateAggregatorEdgeCases:
    """Test edge cases and error conditions"""
    
    @pytest.mark.asyncio
    async def test_invalid_currency_pair_handling(self):
        """Test behavior with invalid currency codes"""
        # This tests your system's input validation
        providers = {"FixerIO": AsyncMock()}
        circuit_breakers = {"FixerIO": AsyncMock()}
        mock_redis = AsyncMock()
        mock_db = Mock()
        mock_currency_manager = AsyncMock()
        mock_currency_manager.validate_currencies.return_value = (True, None)
        
        aggregator = RateAggregatorService(
            providers=providers,
            circuit_breakers=circuit_breakers,
            redis_manager=mock_redis,
            db_manager=mock_db,
            currency_manager=mock_currency_manager
        )
        
        mock_redis.get_cached_rate.return_value = None
        
        # API returns an error for invalid currency
        failed_result = APICallResult(
            provider_name="FixerIO",
            endpoint="/latest",
            http_status_code=400,
            response_time_ms=50,
            was_successful=False,
            error_message="Invalid currency code: XXX"
        )
        circuit_breakers["FixerIO"].call.return_value = failed_result
        
        # Act & Assert - should handle gracefully
        with pytest.raises(Exception):
            await aggregator.get_exchange_rate("XXX", "EUR")
    
    @pytest.mark.asyncio
    async def test_response_time_tracking(self):
        """Test that response times are tracked correctly"""
        providers = {"FixerIO": AsyncMock()}
        circuit_breakers = {"FixerIO": AsyncMock()}
        mock_redis = AsyncMock()
        mock_db = Mock()
        mock_currency_manager = AsyncMock()
        mock_currency_manager.validate_currencies.return_value = (True, None)
        
        aggregator = RateAggregatorService(
            providers=providers,
            circuit_breakers=circuit_breakers,
            redis_manager=mock_redis,
            db_manager=mock_db,
            currency_manager=mock_currency_manager
        )
        
        mock_redis.get_cached_rate.return_value = None
        
        # Mock a slow API response
        slow_result = APICallResult(
            provider_name="FixerIO",
            endpoint="/latest", 
            http_status_code=200,
            response_time_ms=2000,  # 2 seconds
            was_successful=True,
            data=ExchangeRateResponse(
                base_currency="USD", target_currency="EUR", rate=Decimal("1.20"),
                timestamp=datetime.now(UTC), provider_name="FixerIO",
                raw_response={}, is_successful=True
            )
        )
        circuit_breakers["FixerIO"].call.return_value = slow_result
        
        # Act
        start_time = datetime.now(UTC)
        result = await aggregator.get_exchange_rate("USD", "EUR")
        
        # Assert
        assert result.response_time_ms >= 0
        # The total time should include aggregation overhead, not just API time
        assert isinstance(result.response_time_ms, int)


# Integration test that tests the whole flow
class TestRateAggregatorIntegration:
    """Integration tests that verify the complete workflow"""
    
    @pytest.mark.asyncio
    async def test_complete_aggregation_workflow(self):
        """Integration test: Complete happy path with multiple providers"""
        # This test verifies the entire get_exchange_rate method works end-to-end
        
        # Arrange - create realistic mocks
        providers = {
            "FixerIO": AsyncMock(),
            "OpenExchange": AsyncMock(), 
            "CurrencyAPI": AsyncMock()
        }
        circuit_breakers = {name: AsyncMock() for name in providers}
        mock_redis = AsyncMock()
        mock_db = Mock()
        mock_currency_manager = AsyncMock()
        mock_currency_manager.validate_currencies.return_value = (True, None)
        
        aggregator = RateAggregatorService(
            providers=providers,
            circuit_breakers=circuit_breakers,
            redis_manager=mock_redis,
            db_manager=mock_db,
            currency_manager=mock_currency_manager,
            primary_provider="FixerIO"
        )
        
        # No cache initially
        mock_redis.get_cached_rate.return_value = None
        
        # All APIs succeed with different rates
        primary_result = APICallResult(
            provider_name="FixerIO", endpoint="/latest", http_status_code=200,
            response_time_ms=100, was_successful=True,
            data=ExchangeRateResponse(
                base_currency="USD", target_currency="EUR", rate=Decimal("1.20"),
                timestamp=datetime.now(UTC), provider_name="FixerIO",
                raw_response={}, is_successful=True
            )
        )
        
        secondary_results = [
            APICallResult(
                provider_name="OpenExchange", endpoint="/latest", http_status_code=200,
                response_time_ms=120, was_successful=True,
                data=ExchangeRateResponse(
                    base_currency="USD", target_currency="EUR", rate=Decimal("1.22"),
                    timestamp=datetime.now(UTC), provider_name="OpenExchange", 
                    raw_response={}, is_successful=True
                )
            ),
            APICallResult(
                provider_name="CurrencyAPI", endpoint="/latest", http_status_code=200,
                response_time_ms=140, was_successful=True,
                data=ExchangeRateResponse(
                    base_currency="USD", target_currency="EUR", rate=Decimal("1.18"),
                    timestamp=datetime.now(UTC), provider_name="CurrencyAPI",
                    raw_response={}, is_successful=True
                )
            )
        ]
        
        circuit_breakers["FixerIO"].call.return_value = primary_result
        circuit_breakers["OpenExchange"].call.return_value = secondary_results[0]
        circuit_breakers["CurrencyAPI"].call.return_value = secondary_results[1]
        
        # Act
        result = await aggregator.get_exchange_rate("USD", "EUR")
        
        # Assert - should average all three: (1.20 + 1.22 + 1.18) / 3 = 1.20
        assert result.rate == Decimal("1.20")
        assert result.confidence_level == "high"
        assert set(result.sources_used) == {"FixerIO", "OpenExchange", "CurrencyAPI"}
        assert result.is_primary_used is False  # Using average
        assert result.cached is False
        
        # Should cache the aggregated result
        mock_redis.rate_cache.assert_called_once()