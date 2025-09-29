import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, UTC
import time
import logging
from dataclasses import dataclass
from decimal import Decimal

from app.providers.base import APIProvider, APICallResult
from app.services.circuit_breaker import CircuitBreaker, CircuitBreakerError
from app.cache.redis_manager import RedisManager
from app.config.database import DatabaseManager
from app.database.models import APIProvider as APIProviderModel, ExchangeRate, APICallLog
from app.monitoring.logger import get_production_logger, LogEvent, EventType, LogLevel

from app.services.currency_manager import CurrencyManager




@dataclass
class AggregatedRateResult:
    """Final result from aggregation process"""
    base_currency: str
    target_currency: str
    rate: Decimal
    confidence_level: str
    sources_used: List[str]
    is_primary_used: bool
    cached: bool
    timestamp: datetime
    response_time_ms: int
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class RateAggregatorService:
    """Orchestrates multiple API providers with circuit breakers and caching"""

    def __init__(self,
                 providers: Dict[str, APIProvider], # provider_name -> provider_instance
                 circuit_breakers: Dict[str, CircuitBreaker],  # provider_name -> circuit_breaker
                 redis_manager: RedisManager,
                 db_manager: DatabaseManager,
                 currency_manager: CurrencyManager,
                 primary_provider: str = "FixerIO"):
        
        self.providers = providers
        self.circuit_breakers = circuit_breakers
        self.redis_manager = redis_manager
        self.db_manager = db_manager
        self.currency_manager = currency_manager
        self.primary_provider = primary_provider
        self.production_logger = get_production_logger()

    async def get_exchange_rate(self, base: str, target: str) -> AggregatedRateResult:
        """
        Main method: Get exchange rate with specified logic:
        1. Try Primary API
        2. If primary fails, try Secondary APIs  
        3. Calculate average if multiple succeed
        4. Update cache
        5. Return rate
        """
        start_time = time.time()

        # NEW: Validate currencies before expensive operations
        is_valid, error_msg = await self.currency_manager.validate_currencies(base, target)
        duration_ms = (time.time() - start_time) * 1000
        if not is_valid:
            self.production_logger.log_currency_validation(
                from_currency=base,
                to_currency=target,
                validation_result={'valid': False, 'error': error_msg},
                duration_ms=duration_ms
            )
            raise ValueError(f"Currency validation failed: {error_msg}")

        # Step 1: Check cache first (5-minute TTL)
        cached_rate = await self._check_cache(base, target)
        if cached_rate:
            response_time_ms = int((time.time() - start_time) * 1000)
            self.production_logger.log_cache_operation(
                operation="get",
                cache_key=f"rate:{base}:{target}",
                hit=True,
                duration_ms=response_time_ms
            )

            return AggregatedRateResult(
                base_currency=base,
                target_currency=target,
                rate=Decimal(cached_rate["rate"]),
                confidence_level=cached_rate["confidence_level"],
                sources_used=cached_rate["sources_used"],
                is_primary_used=cached_rate["is_primary_used"],
                cached=True,
                timestamp=datetime.fromisoformat(cached_rate["timestamp"]),
                response_time_ms=response_time_ms
            )

        # Step 2: Try primary API first
        primary_result = await self._try_provider(self.primary_provider, base, target)

        # Step 3: Try Secondary APIs (always try them for comparison/logging)
        secondary_results = await self._try_secondary_providers(base, target)
        
        # Step 4: Apply your aggregation logic
        aggregated_result = await self._aggregate_results(
            primary_result, secondary_results, base, target, start_time
        )
        
        # Step 5: Update cache with final result
        await self._update_cache(aggregated_result)

        # Step 6: Log to database
        await self._log_results_to_db(primary_result, secondary_results)

        return aggregated_result
    
    async def _try_provider(self, provider_name: str, base: str, target: str) -> Optional[APICallResult]:
        """Try a single provider with circuit breaker protection"""
        if provider_name not in self.providers:
            self.production_logger.log_event(
                LogEvent(
                    event_type=EventType.RATE_AGGREGATION,
                    level=LogLevel.ERROR,
                    message=f"Provider {provider_name} not found",
                    timestamp=datetime.now(),
                    error_context={'error': 'Provider not configured'}
                )
            )
            return None
        
        provider = self.providers[provider_name]
        circuit_breaker = self.circuit_breakers[provider_name]

        start_time = time.time()

        try:
            # Use circuit breaker to protect API call
            result = await circuit_breaker.call(
                lambda: provider.get_exchange_rate(base, target)
            )

            duration_ms = (time.time() - start_time) * 1000

            # Log successful API call
            self.production_logger.log_api_call(
                provider_name=provider_name,
                endpoint="get_exchange_rate",
                success=True,
                response_time_ms=duration_ms,
                rate_data={"rate": str(result.data.rate), "base": base, "target": target}
            )
            return result
        
        except CircuitBreakerError as e:
            duration_ms = (time.time() - start_time) * 1000
            self.production_logger.log_event(
                LogEvent(
                    event_type=EventType.CIRCUIT_BREAKER,
                    level=LogLevel.WARNING,
                    message=f"Circuit breaker OPEN for {provider_name}, blocking {base} -> target",
                    timestamp=datetime.now(),
                    duration_ms=duration_ms,
                    api_context={
                        'provider': provider_name,
                        'operation': 'request_blocked',
                        'failure_count': e.failure_count
                    },
                    user_context={
                        'base_currency': base,
                        'target_currency': target
                    },
                    error_context={
                        'circuit_state': 'OPEN',
                        'last_failure_time': e.last_failure_time.isoformat()
                    }
                )
            )
            return None
        
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
        
            # Log unexpected API failure
            self.production_logger.log_api_call(
                provider_name=provider_name,
                endpoint="get_exchange_rate",
                success=False,
                response_time_ms=duration_ms,
                error_message=str(e)
            )
            return None

    async def _try_secondary_providers(self, base: str, target: str) -> List[APICallResult]:
        """Try all secondary providers simultaneously for speed"""
        secondary_providers = [name for name in self.providers.keys() if name != self.primary_provider]

        # Call all secondary providers concurrently
        tasks = [
            self._try_provider(provider_name, base, target)
            for provider_name in secondary_providers
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out None results and exceptions
        valid_results = []
        for result in results:
            if isinstance(result, APICallResult) and result is not None:
                valid_results.append(result)
            elif isinstance(result, Exception):
                self.production_logger.log_event(
                    LogEvent(
                        event_type=EventType.API_CALL,
                        level=LogLevel.ERROR,
                        message=f"Secondary provider exception: {result}",
                        timestamp=datetime.now(UTC),
                        error_context={'error': str(result)}
                    )
                )

        return valid_results
    
    async def _aggregate_results(self, 
                                primary_result: Optional[APICallResult],
                                secondary_results: List[APICallResult],
                                base: str, target: str,
                                start_time: float) -> AggregatedRateResult:
        """
        Apply aggregation logic:
        - Use primary if available
        - Log secondary results for comparison
        - Fall back to secondary if primary fails
        - Calculate average if multiple sources available
        """
        response_time_ms = int((time.time() - start_time) * 1000)
        successful_results = [r for r in secondary_results if r.was_successful and r.data and r.data.is_successful]

        # Scenario 1: Primary succeeded
        if primary_result and primary_result.was_successful and primary_result.data.is_successful:
            primary_rate = primary_result.data.rate
            sources_used = [self.primary_provider]
            confidence_level = "high"

            # Log secondary results for comparison
            if successful_results:
                secondary_rates = [r.data.rate for r in successful_results]
                secondary_names = [r.provider_name for r in successful_results]

                # Calculate variance for monitoring
                all_rates = [primary_rate] + secondary_rates
                avg_rate = Decimal(sum(all_rates) / len(all_rates))
                max_deviation = max([abs(rate - avg_rate) for rate in all_rates])

                if primary_rate and max_deviation >= 1.0:
                    avg_rate = primary_rate
                    self.production_logger.log_event(
                        LogEvent(
                            event_type=EventType.RATE_AGGREGATION,
                            level=LogLevel.WARNING,
                            message=f"High deviation ({max_deviation:.4f}) between primary and secondary rates for {base}->{target}, using primary only",
                            timestamp=datetime.now(),
                            api_context={
                                'base_currency': base,
                                'target_currency': target,
                                'primary_rate': str(primary_rate),
                                'secondary_rates': [str(r) for r in secondary_rates],
                                'max_deviation': str(max_deviation)
                            }
                        )
                    )

                self.production_logger.log_event(
                    LogEvent(
                        event_type=EventType.RATE_AGGREGATION,
                        level=LogLevel.INFO,
                        message=f"Rate comparison {base}->{target}: Primary({self.primary_provider}): {primary_rate}, Secondaries({secondary_names}): {secondary_rates}, Max deviation: {max_deviation:.6f}",
                        timestamp=datetime.now(),
                        api_context={
                            'base_currency': base,
                            'target_currency': target,
                            'primary_provider': self.primary_provider,
                            'primary_rate': str(primary_rate),
                            'secondary_providers': secondary_names,
                            'secondary_rates': [str(r) for r in secondary_rates],
                            'max_deviation': str(max_deviation)
                        }
                    )
                )

                # If multiple sources available, use average
                if len(successful_results) >= 1:
                    sources_used.extend(secondary_names)
                    confidence_level = "high"

                    self.production_logger.log_rate_aggregation(
                        base=base,
                        target=target,
                        final_rate=float(avg_rate),
                        confidence_level=confidence_level,
                        sources_used=sources_used,
                        is_primary_used=True,
                        was_cached=False,
                        total_duration_ms=response_time_ms,
                        warnings=[f"High deviation ({max_deviation:.4f}) between rates"]
                    )

                    return AggregatedRateResult(
                        base_currency=base,
                        target_currency=target,
                        rate=avg_rate,
                        confidence_level=confidence_level,
                        sources_used=sources_used,
                        is_primary_used=False,
                        cached=False,
                        timestamp=datetime.now(tz=UTC),
                        response_time_ms=response_time_ms
                    )

            return AggregatedRateResult(
                base_currency=base,
                target_currency=target,
                rate=primary_rate,
                confidence_level=confidence_level,
                sources_used=sources_used,
                is_primary_used=True,
                cached=False,
                timestamp=primary_result.data.timestamp,
                response_time_ms=response_time_ms
            )
        
        # Scenario 2: Primary failed, use secondary APIs
        elif successful_results:
            self.production_logger.log_event(
                LogEvent(
                    event_type=EventType.RATE_AGGREGATION,
                    level=LogLevel.WARNING,
                    message=f"Primary provider {self.primary_provider} failed, using secondary sources",
                    timestamp=datetime.now(),
                    api_context={
                        'primary_provider': self.primary_provider,
                        'successful_secondary_providers': [r.provider_name for r in successful_results]
                    }
                )
            )

            # Calculate average of successful secondary APIs
            rates = [r.data.rate for r in successful_results]
            sources = [r.provider_name for r in successful_results]
            
            if len(rates) == 1:
                final_rate = rates[0]
                confidence_level = "medium"
            else:
                final_rate = Decimal(sum(rates) / len(rates))
                confidence_level = "medium"

            warnings = [f"Primary provider {self.primary_provider} unavailable"]

            return AggregatedRateResult(
                base_currency=base,
                target_currency=target,
                rate=final_rate,
                confidence_level=confidence_level,
                sources_used=sources,
                is_primary_used=False,
                cached=False,
                timestamp=datetime.now(tz=UTC),
                response_time_ms=response_time_ms,
                warnings=warnings
            )
        
        # Scenario 3: All APIs failed - try cache as last resort
        else:
            self.production_logger.log_event(
                LogEvent(
                    event_type=EventType.RATE_AGGREGATION,
                    level=LogLevel.ERROR,
                    message=f"All providers failed for {base}->{target}, checking stale cache",
                    timestamp=datetime.now(),
                    api_context={
                        'base_currency': base,
                        'target_currency': target
                    }
                )
            )

            # Try to get cached data even if expired (graceful degradation)
            stale_cache = await self._check_stale_cache(base, target)

            if stale_cache:
                warnings = [
                    "All API providers unavailable",
                    f"Using stale cache data (age: {stale_cache.get('age_minutes', 'unknown')} minutes)"
                ]

                return AggregatedRateResult(
                    base_currency=base,
                    target_currency=target,
                    rate=stale_cache["rate"],
                    confidence_level="low",  # Stale data
                    sources_used=stale_cache.get("sources_used", ["cache"]),
                    is_primary_used=False,
                    cached=True,
                    timestamp=datetime.fromisoformat(stale_cache["timestamp"]),
                    response_time_ms=response_time_ms,
                    warnings=warnings
                )
            
            # Absolute worst case - no data available
            raise Exception(f"No exchange rate data available for {base}->{target}")

    async def _check_cache(self, base: str, target: str) -> Optional[Dict[str, Any]]:
        """Check Redis cache for fresh data (5-minute TTL)"""
        return await self.redis_manager.get_cached_rate(base, target)
    
    async def _check_stale_cache(self, base: str, target: str) -> Optional[Dict[str, Any]]:
        """Check for any cached data, even if expired (graceful degradation)"""
        try:
            with self.db_manager.get_session() as session:
                # Get most recent successful rate from database
                latest_rate = session.query(ExchangeRate).join(
                    ExchangeRate.currency_pair
                ).filter(
                    ExchangeRate.is_successful == True,
                    ExchangeRate.currency_pair.has(
                        base_currency=base,
                        target_currency=target
                    )
                ).order_by(ExchangeRate.fetched_at.desc()).first()

                if latest_rate:
                    # Ensure fetched_at is timezone-aware for comparison
                    fetched_at_aware = latest_rate.fetched_at.replace(tzinfo=UTC) if latest_rate.fetched_at.tzinfo is None else latest_rate.fetched_at
                    age_minutes = int((datetime.now(tz=UTC) - fetched_at_aware).total_seconds() / 60)
                    return {
                        "rate": latest_rate.rate,
                        "timestamp": latest_rate.fetched_at.isoformat(),
                        "sources_used": [latest_rate.provider.name],
                        "confidence_level": "low",
                        "age_minutes": age_minutes
                    }
        
        except Exception as e:
            self.production_logger.log_cache_operation(
                operation="get_stale",
                cache_key=f"rate:{base}:{target}",
                hit=False,
                duration_ms=0, # Not measured here
                error_message=str(e)
            )
        
        return None
    
    async def _update_cache(self, result: AggregatedRateResult):
        """Update Redis cache with aggregated result"""
        if not result.cached:  # Don't re-cache cached results
            cache_data = {
                "rate": str(result.rate),
                "confidence_level": result.confidence_level,
                "sources_used": result.sources_used,
                "is_primary_used": result.is_primary_used,
                "timestamp": result.timestamp.isoformat(),
                "warnings": result.warnings
            }
            
            await self.redis_manager.rate_cache(
                result.base_currency, 
                result.target_currency, 
                cache_data
            )

    async def _log_results_to_db(self,
                                 primary_result: Optional[APICallResult],
                                 secondary_results: List[APICallResult]):
        """Log all API calls to database"""
        try:
            with self.db_manager.get_session() as session:
                all_results = []
                if primary_result:
                    all_results.append(primary_result)
                all_results.extend(secondary_results)

                for result in all_results:
                    # Log API call performance
                    call_log = APICallLog(
                        provider_id=self._get_provider_id(result.provider_name),
                        endpoint=result.endpoint,
                        http_status_code=result.http_status_code,
                        response_time_ms=result.response_time_ms,
                        was_successful=result.was_successful,
                        error_message=result.error_message,
                        called_at=datetime.now(tz=UTC)
                    )
                    session.add(call_log)

                    # Log exchange rate is successful
                    if result.was_successful and result.data and result.data.is_successful:
                        currency_pair = self.db_manager.get_or_create_currency_pair(
                            session, 
                            result.data.base_currency, 
                            result.data.target_currency
                        )
                        
                        rate_log = ExchangeRate(
                            currency_pair_id=currency_pair.id,
                            provider_id=self._get_provider_id(result.provider_name),
                            rate=result.data.rate,
                            fetched_at=result.data.timestamp,
                            is_successful=True,
                            confidence_level="high" if result.provider_name == self.primary_provider else "medium"
                        )
                        session.add(rate_log)
                
                session.commit()
                
        except Exception as e:
            self.production_logger.log_event(
                LogEvent(
                    event_type=EventType.DATABASE_OPERATION,
                    level=LogLevel.ERROR,
                    message=f"Failed to log results to database: {e}",
                    timestamp=datetime.now(),
                    error_context={'error': str(e)}
                )
            )

    def _get_provider_id(self, provider_name: str):
        try:
            with self.db_manager.get_session() as session:
                provider = session.query(APIProviderModel).filter(
                    APIProviderModel.name == provider_name
                ).first()
                return provider.id if provider else 1  # Fallback
        except:
            return 1
        
    async def get_health_status(self) -> Dict[str, Any]:
        """Get health status of all providers and circuit breakers"""
        status = {
            "service": "rate_aggregator",
            "providers": {},
            "cache_status": await self.redis_manager.health_check()
        }
        
        provider_statuses = {}
        for provider_name, circuit_breaker in self.circuit_breakers.items():
            provider_statuses[provider_name] = await circuit_breaker.get_status()

        status["providers"] = provider_statuses
        status["status"] = "healthy" if all(p["status"] == "healthy" for p in provider_statuses.values()) else "unhealthy"
        
        return status