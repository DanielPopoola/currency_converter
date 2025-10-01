import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.cache.redis_manager import RedisManager
from app.config.database import DatabaseManager
from app.database.models import APICallLog, ExchangeRate
from app.database.models import APIProvider as APIProviderModel
from app.monitoring.logger import logger
from app.providers.base import APICallResult, APIProvider, ExchangeRateResponse
from app.services.circuit_breaker import CircuitBreaker, CircuitBreakerError
from app.services.currency_manager import CurrencyManager


@dataclass
class AggregatedRateResult:
    """Final result from aggregation process"""
    base_currency: str
    target_currency: str
    rate: Decimal
    confidence_level: str
    sources_used: list[str]
    is_primary_used: bool
    cached: bool
    timestamp: datetime
    response_time_ms: int
    warnings: list[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class RateAggregatorService:
    """Orchestrates multiple API providers with circuit breakers and caching"""

    def __init__(self,
                 providers: dict[str, APIProvider], # provider_name -> provider_instance
                 circuit_breakers: dict[str, CircuitBreaker],  # provider_name -> circuit_breaker
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
        self.logger = logger.bind(service="RateAggregator")

    async def get_exchange_rate(self, base: str, target: str) -> AggregatedRateResult:
        """
        Main method: Get exchange rate with specified logic:
        1. Try Primary API
        2. If primary fails, try Secondary APIs  
        3. Calculate average if multiple succeed
        4. Update cache
        5. Return rate
        """
        print(f"DEBUG: Entering get_exchange_rate for {base}->{target}")
        start_time = time.time()

        # NEW: Validate currencies before expensive operations
        is_valid, error_msg = await self.currency_manager.validate_currencies(base, target)
        duration_ms = (time.time() - start_time) * 1000
        if not is_valid:
            self.logger.error(
                "Invalid currency input",
                from_currency=base,
                to_currency=target,
                validation_result={'valid': False, 'error': error_msg},
                duration_ms=duration_ms,
                timestamp=datetime.now()
            )
            raise ValueError(f"Currency validation failed: {error_msg}")

        # Step 1: Check cache first (5-minute TTL)
        cached_rate = await self._check_cache(base, target)
        if cached_rate:
            response_time_ms = int((time.time() - start_time) * 1000)
            self.logger.info(
                "Fetching rates from cache",
                operation="get",
                cache_key=f"rate:{base}:{target}",
                hit=True,
                duration_ms=response_time_ms,
                timestamp=datetime.now()
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
    
    async def _try_provider(self, provider_name: str, base: str, target: str) -> APICallResult | None:
        """Try a single provider with circuit breaker protection"""
        if provider_name not in self.providers:
            self.logger.error(
                "Provider {provider_name} not found",
                provider_name=provider_name,
                event_type="RATE_AGGREGATION",
                error="Provider not configured",
                timestamp=datetime.now()
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
            self.logger.info(
                "API call successful",
                provider_name=provider_name,
                endpoint="get_exchange_rate",
                success=True,
                response_time_ms=duration_ms,
                rate_data={"rate": str(result.data.rate), "base": base, "target": target},
                timestamp=datetime.now()
            )
            return result
        
        except CircuitBreakerError as e:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.warning(
                "Circuit breaker OPEN for {provider_name}, blocking {base_currency} -> {target_currency}",
                provider_name=provider_name,
                base_currency=base,
                target_currency=target,
                event_type="CIRCUIT_BREAKER",
                duration_ms=duration_ms,
                operation='request_blocked',
                failure_count=e.failure_count,
                circuit_state='OPEN',
                last_failure_time=e.last_failure_time.isoformat(),
                timestamp=datetime.now()
            )
            return None
        
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.error(
                "API call failed unexpectedly for {provider_name} at {endpoint}",
                provider_name=provider_name,
                endpoint="get_exchange_rate",
                success=False,
                response_time_ms=duration_ms,
                error_message=str(e),
                event_type="API_CALL",
                timestamp=datetime.now()
            )
            return None

    async def _try_secondary_providers(self, base: str, target: str) -> list[APICallResult]:
        """Try all secondary providers simultaneously for speed"""
        secondary_providers = [name for name in self.providers if name != self.primary_provider]

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
                self.logger.error(
                    "Secondary provider exception: {error}",
                    error=str(result),
                    event_type="API_CALL",
                    timestamp=datetime.now()
                )

        return valid_results
    
    async def _aggregate_results(self, 
                                primary_result: APICallResult | None,
                                secondary_results: list[APICallResult],
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
                    self.logger.warning(
                        "High deviation ({max_deviation:.4f}) between primary and secondary rates for {base_currency}->{target_currency}, using primary only",
                        base_currency=base,
                        target_currency=target,
                        primary_rate=str(primary_rate),
                        secondary_rates=[str(r) for r in secondary_rates],
                        max_deviation=max_deviation,
                        event_type="RATE_AGGREGATION",
                        timestamp=datetime.now()
                    )

                self.logger.info(
                    "Rate comparison {base_currency}->{target_currency}: Primary({primary_provider}): {primary_rate}, Secondaries({secondary_providers}): {secondary_rates}, Max deviation: {max_deviation:.6f}",
                    base_currency=base,
                    target_currency=target,
                    primary_provider=self.primary_provider,
                    primary_rate=str(primary_rate),
                    secondary_providers=secondary_names,
                    secondary_rates=[str(r) for r in secondary_rates],
                    max_deviation=max_deviation,
                    event_type="RATE_AGGREGATION",
                    timestamp=datetime.now()
                )

                # If multiple sources available, use average
                if len(successful_results) >= 1:
                    sources_used.extend(secondary_names)
                    confidence_level = "high"

                    self.logger.info(
                        "Rate aggregated successfully",
                        base_currency=base,
                        target_currency=target,
                        final_rate=float(avg_rate),
                        confidence_level=confidence_level,
                        sources_used=sources_used,
                        is_primary_used=True,
                        was_cached=False,
                        total_duration_ms=response_time_ms,
                        warnings=[f"High deviation ({max_deviation:.4f}) between rates"],
                        event_type="RATE_AGGREGATION",
                        timestamp=datetime.now()
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
            self.logger.warning(
                "Primary provider {primary_provider} failed, using secondary sources",
                primary_provider=self.primary_provider,
                successful_secondary_providers=[r.provider_name for r in successful_results],
                event_type="RATE_AGGREGATION",
                timestamp=datetime.now()
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
            self.logger.error(
                "All providers failed for {base_currency}->{target_currency}, checking stale cache",
                base_currency=base,
                target_currency=target,
                event_type="RATE_AGGREGATION",
                timestamp=datetime.now()
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

    async def get_all_rates_for_base(self, base: str) -> dict[str, AggregatedRateResult]:
        """
        Fetch ALL rates for a given base currency in one shot.
        Returns a dictionary mapping target currencies to their aggregated results.
        Args:
            base: Base currency (e.g., "USD")
        
        Returns:
            Dict mapping target currency to AggregatedRateResult
            Example: {"EUR": AggregatedRateResult(...), "GBP": AggregatedRateResult(...)}
        """
        start_time = time.time()
        is_valid, error_msg = await self.currency_manager.validate_currencies(base, base)
        if not is_valid:
            raise ValueError(f"Invalid base currency: {error_msg}")
        
        primary_all_rates = await self._try_provider_all_rates(self.primary_provider, base)
        secondary_all_rates = await self._try_secondary_providers_all_rates(base)

        all_targets = set()
        
        if primary_all_rates:
            all_targets.update(primary_all_rates.keys())

        for secondary_result in secondary_all_rates:
            all_targets.update(secondary_result.keys())

        aggregated_results = {}

        for target in all_targets:
            # Aggregate this specific pair
            primary_rate_data = primary_all_rates.get(target) if primary_all_rates else None
            secondary_rate_data = [sr.get(target) for sr in secondary_all_rates if target in sr]
            
            aggregated_result = await self._aggregate_single_pair(
                base, target, primary_rate_data, secondary_rate_data, start_time
            )
            
            # Update cache
            await self._update_cache(aggregated_result)
            
            aggregated_results[target] = aggregated_result

        response_time_ms = int(time.time() - start_time) * 1000

        self.logger.info(
            f"Fetched all rates for base {base}: {len(aggregated_results)} pairs in {response_time_ms}ms",
            event_type="RATE_AGGREGATION",
            timestamp=datetime.now(),
            base_currency=base,
            pairs_count=len(aggregated_results),
            duration_ms=response_time_ms
        )

        return aggregated_results
    
    async def _try_provider_all_rates(self, provider_name: str, base: str) -> dict[str, ExchangeRateResponse] | None:
        """
        Fetch all rates from a single provider.
        Returns dict mapping target currency to ExchangeRateResponse.
        """
        if provider_name not in self.providers:
            return None
        
        provider = self.providers[provider_name]
        circuit_breaker = self.circuit_breakers[provider_name]

        start_time = time.time()
        try:
            result = await circuit_breaker.call(lambda: provider.get_all_rates(base))
            duration_ms = (time.time() - start_time) * 1000
            if result.was_successful and result.data:
                # Convert list of ExchangeRateResponses to dict
                rates_dict = {
                    rate_response.target_currency: rate_response
                    for rate_response in result.data if isinstance(rate_response, ExchangeRateResponse)
                }

                self.logger.info(
                    f"Fetched all rates for {base}",
                    provider_name=provider_name,
                    endpoint="get_all_rates",
                    success=True,
                    response_time_ms=duration_ms,
                    pairs_count=len(rates_dict)
                )
                return rates_dict
            return None
        except CircuitBreakerError:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.warning(
                f"Circuit breaker OPEN for {provider_name}, blocking get_all_rates",
                event_type="CIRCUIT_BREAKER",
                provider_name=provider_name,
                operation="get_all_rates_blocked",
                timestamp=datetime.now(),
                duration_ms=duration_ms,
            )
            return None
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self.logger.error(
                "API call failed unexpectedly: get_all_rates",
                provider_name=provider_name,
                endpoint="get_supported_currencies",
                success=False,
                response_time_ms=duration_ms,
                error_message=str(e),
                event_type="API_CALL",
                timestamp=datetime.now()
            )
            return None

    async def _try_secondary_providers_all_rates(self, base: str) -> list[dict[str, ExchangeRateResponse]]:
        """Try all secondary providers for batch rate fetching."""
        secondary_providers = [name for name in self.providers if name != self.primary_provider]
        
        tasks = [
            self._try_provider_all_rates(provider_name, base)
            for provider_name in secondary_providers
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter valid results
        valid_results = []
        for result in results:
            if isinstance(result, dict) and result:
                valid_results.append(result)
        
        return valid_results

    async def _aggregate_single_pair(
        self,
        base: str,
        target: str,
        primary_rate_data: ExchangeRateResponse | None,
        secondary_rate_data: list[ExchangeRateResponse],
        start_time: float
    ) -> AggregatedRateResult:
        """
        Aggregate rates for a single pair (extracted from _aggregate_results for reuse)
        """
        response_time_ms = int((time.time() - start_time) * 1000)
        
        # Use primary if available
        if primary_rate_data and primary_rate_data.is_successful:
            primary_rate = primary_rate_data.rate
            sources_used = [self.primary_provider]
            confidence_level = "high"
            
            # Compare with secondaries if available
            if secondary_rate_data:
                secondary_rates = [r.rate for r in secondary_rate_data if r.is_successful]
                
                if secondary_rates:
                    all_rates = [primary_rate] + secondary_rates
                    avg_rate = Decimal(sum(all_rates) / len(all_rates))
                    max_deviation = max([abs(rate - avg_rate) for rate in all_rates])
                    
                    if max_deviation >= 1.0:
                        # High deviation, use primary only
                        avg_rate = primary_rate
                    else:
                        # Low deviation, use average
                        sources_used.extend([r.provider_name for r in secondary_rate_data if r.is_successful])
                    
                    return AggregatedRateResult(
                        base_currency=base,
                        target_currency=target,
                        rate=avg_rate,
                        confidence_level=confidence_level,
                        sources_used=sources_used,
                        is_primary_used=True,
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
                timestamp=primary_rate_data.timestamp,
                response_time_ms=response_time_ms
            )
        
        # Fallback to secondaries
        elif secondary_rate_data:
            valid_secondaries = [r for r in secondary_rate_data if r.is_successful]
            
            if valid_secondaries:
                rates = [r.rate for r in valid_secondaries]
                sources = [r.provider_name for r in valid_secondaries]
                
                final_rate = Decimal(sum(rates) / len(rates)) if len(rates) > 1 else rates[0]
                
                return AggregatedRateResult(
                    base_currency=base,
                    target_currency=target,
                    rate=final_rate,
                    confidence_level="medium",
                    sources_used=sources,
                    is_primary_used=False,
                    cached=False,
                    timestamp=datetime.now(tz=UTC),
                    response_time_ms=response_time_ms,
                    warnings=[f"Primary provider {self.primary_provider} unavailable"]
                )
        
        # Last resort: stale cache
        stale_cache = await self._check_stale_cache(base, target)
        if stale_cache:
            return AggregatedRateResult(
                base_currency=base,
                target_currency=target,
                rate=stale_cache["rate"],
                confidence_level="low",
                sources_used=stale_cache.get("sources_used", ["cache"]),
                is_primary_used=False,
                cached=True,
                timestamp=datetime.fromisoformat(stale_cache["timestamp"]),
                response_time_ms=response_time_ms,
                warnings=["All API providers unavailable", f"Using stale cache (age: {stale_cache.get('age_minutes', 'unknown')} minutes)"]
            )
        
        raise Exception(f"No exchange rate data available for {base}->{target}")

    async def _check_cache(self, base: str, target: str) -> dict[str, Any] | None:
        """Check Redis cache for fresh data (5-minute TTL)"""
        return await self.redis_manager.get_latest_rate(base, target)
    
    async def _check_stale_cache(self, base: str, target: str) -> dict[str, Any] | None:
        """Check for any cached data, even if expired (graceful degradation)"""
        try:
            with self.db_manager.get_session() as session:
                # Get most recent successful rate from database
                latest_rate = session.query(ExchangeRate).join(
                    ExchangeRate.currency_pair
                ).filter(
                    ExchangeRate.is_successful,
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
            self.logger.error(
                "Failed to get stale cache for {cache_key}: {error_message}",
                operation="get_stale",
                cache_key=f"rate:{base}:{target}",
                hit=False,
                duration_ms=0,
                error_message=str(e),
                event_type="CACHE_OPERATION",
                timestamp=datetime.now()
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
            
            await self.redis_manager.set_latest_rate(
                result.base_currency, 
                result.target_currency, 
                cache_data
            )

    async def _log_results_to_db(self,
                                 primary_result: APICallResult | None,
                                 secondary_results: list[APICallResult]):
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
            self.logger.error(
                "Failed to log results to database: {error}",
                error=str(e),
                event_type="DATABASE_OPERATION",
                timestamp=datetime.now()
            )

    def _get_provider_id(self, provider_name: str):
        try:
            with self.db_manager.get_session() as session:
                provider = session.query(APIProviderModel).filter(
                    APIProviderModel.name == provider_name
                ).first()
                return provider.id if provider else 1
        except Exception:
            return 1
        
    async def get_health_status(self) -> dict[str, Any]:
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