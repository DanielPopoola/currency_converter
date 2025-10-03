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
    warnings: list[str] | None = None

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
        1. Validate currencies
        2. Check cache
        3. Fetch from primary and secondary providers
        4. Aggregate results
        5. Update cache and log to DB
        """
        start_time = time.time()

        # Step 1: Validate currencies before expensive operations
        is_valid, error_msg = await self.currency_manager.validate_currencies(base, target)
        if not is_valid:
            raise ValueError(f"Currency validation failed: {error_msg}")

        # Step 2: Check cache first
        cached_rate = await self._check_cache(base, target)
        if cached_rate:
            response_time_ms = int((time.time() - start_time) * 1000)
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

        # Step 3: Fetch from providers
        primary_result = await self._try_provider(self.primary_provider, base, target)
        secondary_results = await self._try_secondary_providers(base, target)
        
        # Step 4: Aggregate results
        all_call_results = ([primary_result] if primary_result else []) + secondary_results
        aggregated_result = await self._aggregate_rates(base, target, all_call_results, start_time)
        
        # Step 5: Update cache and log
        await self._update_cache(aggregated_result)
        await self._log_results_to_db(all_call_results)

        return aggregated_result
    
    async def get_all_rates_for_base(self, base: str) -> dict[str, AggregatedRateResult]:
        """
        Fetch ALL rates for a given base currency.
        Returns a dictionary mapping target currencies to their aggregated results.
        """
        start_time = time.time()
        is_valid, error_msg = await self.currency_manager.validate_currencies(base, base)
        if not is_valid:
            raise ValueError(f"Invalid base currency: {error_msg}")
        
        # Fetch all rates from all providers
        primary_all_rates_task = self._try_provider_all_rates(self.primary_provider, base)
        secondary_all_rates_task = self._try_secondary_providers_all_rates(base)
        primary_rates_dict, secondary_rates_list = await asyncio.gather(primary_all_rates_task, secondary_all_rates_task)

        # Combine all results into a per-target-currency dictionary
        all_rates_by_target = {}
        if primary_rates_dict:
            for target, rate_response in primary_rates_dict.items():
                if target not in all_rates_by_target:
                    all_rates_by_target[target] = []
                all_rates_by_target[target].append(rate_response)

        for provider_rates in secondary_rates_list:
            for target, rate_response in provider_rates.items():
                if target not in all_rates_by_target:
                    all_rates_by_target[target] = []
                all_rates_by_target[target].append(rate_response)

        # Aggregate for each target currency
        aggregated_results = {}
        aggregation_tasks = []
        for target, rate_responses in all_rates_by_target.items():
            task = self._aggregate_rates(base, target, rate_responses, start_time)
            aggregation_tasks.append(task)
        
        aggregated_list = await asyncio.gather(*aggregation_tasks)

        # Update cache and log
        update_tasks = [self._update_cache(res) for res in aggregated_list]
        await asyncio.gather(*update_tasks)
        
        for target, result in zip(all_rates_by_target.keys(), aggregated_list, strict=False):
            aggregated_results[target] = result

        return aggregated_results

    async def _aggregate_rates(
        self,
        base: str,
        target: str,
        results: list[APICallResult | ExchangeRateResponse],
        start_time: float
    ) -> AggregatedRateResult:
        """
        Unified aggregation logic for a single currency pair.
        This method processes results from either get_exchange_rate or get_all_rates.
        """
        response_time_ms = int((time.time() - start_time) * 1000)

        # Standardize input to ExchangeRateResponse
        rate_responses: list[ExchangeRateResponse] = []
        for res in results:
            if isinstance(res, APICallResult) and res.was_successful and res.data:
                rate_responses.append(res.data)
            elif isinstance(res, ExchangeRateResponse) and res.is_successful:
                rate_responses.append(res)

        primary_response = next((r for r in rate_responses if r.provider_name == self.primary_provider), None)
        secondary_responses = [r for r in rate_responses if r.provider_name != self.primary_provider]

        # Scenario 1: Primary succeeded
        if primary_response:
            final_rate = primary_response.rate
            sources_used = [self.primary_provider]
            confidence = "high"
            is_primary_used = True
            
            # If secondaries also succeeded, average them in if deviation is low
            if secondary_responses:
                all_valid_rates = [primary_response.rate] + [r.rate for r in secondary_responses]
                avg_rate = Decimal(sum(all_valid_rates) / len(all_valid_rates))
                max_deviation = max(abs(r - avg_rate) for r in all_valid_rates)

                self.logger.info(
                    "Rate comparison {base}->{target}: Primary={p_rate}, Secondaries={s_rates}, MaxDev={dev:.6f}",
                    base=base, target=target, p_rate=primary_response.rate, 
                    s_rates=[r.rate for r in secondary_responses], dev=max_deviation
                )

                # If deviation is low, use the average and include all sources
                if max_deviation < 1.0:
                    final_rate = avg_rate
                    sources_used.extend(r.provider_name for r in secondary_responses)
                    is_primary_used = False
                    
            return AggregatedRateResult(
                base_currency=base, target_currency=target, rate=final_rate,
                confidence_level=confidence, sources_used=sources_used, is_primary_used=is_primary_used,
                cached=False, timestamp=primary_response.timestamp, response_time_ms=response_time_ms
            )

        # Scenario 2: Primary failed, use secondaries
        elif secondary_responses:
            self.logger.warning(
                "Primary provider {primary} failed, using secondary sources: {secondaries}",
                primary=self.primary_provider,
                secondaries=[r.provider_name for r in secondary_responses]
            )
            rates = [r.rate for r in secondary_responses]
            final_rate = Decimal(sum(rates) / len(rates))
            sources = [r.provider_name for r in secondary_responses]
            warnings = [f"Primary provider {self.primary_provider} unavailable"]
            
            return AggregatedRateResult(
                base_currency=base, target_currency=target, rate=final_rate,
                confidence_level="medium", sources_used=sources, is_primary_used=False,
                cached=False, timestamp=datetime.now(tz=UTC), response_time_ms=response_time_ms,
                warnings=warnings
            )

        # Scenario 3: All failed, try stale cache
        else:
            self.logger.error(f"All providers failed for {base}->{target}, checking stale cache")
            stale_cache = await self._check_stale_cache(base, target)
            if stale_cache:
                warnings = [
                    "All API providers unavailable",
                    f"Using stale cache data (age: {stale_cache.get('age_minutes', 'unknown')} minutes)"
                ]
                return AggregatedRateResult(
                    base_currency=base, target_currency=target, rate=Decimal(stale_cache["rate"]),
                    confidence_level="low", sources_used=stale_cache.get("sources_used", ["cache"]),
                    is_primary_used=False, cached=True, timestamp=datetime.fromisoformat(stale_cache["timestamp"]),
                    response_time_ms=response_time_ms, warnings=warnings
                )
            
            # Absolute worst case
            raise Exception(f"No exchange rate data available for {base}->{target}")

    async def _try_provider(self, provider_name: str, base: str, target: str) -> APICallResult | None:
        """Try a single provider with circuit breaker for a single pair."""
        return await self._execute_provider_call(
            provider_name,
            lambda p: p.get_exchange_rate(base, target)
        )

    async def _try_provider_all_rates(self, provider_name: str, base: str) -> dict[str, ExchangeRateResponse] | None:
        """Try a single provider with circuit breaker for all rates."""
        result = await self._execute_provider_call(
            provider_name,
            lambda p: p.get_all_rates(base)
        )
        if result and result.was_successful and result.data:
            return {
                res.target_currency: res
                for res in result.data if isinstance(res, ExchangeRateResponse)
            }
        return None

    async def _execute_provider_call(self, provider_name: str, api_call_func) -> APICallResult | None:
        """Generic method to execute a provider call with circuit breaker and logging."""
        if provider_name not in self.providers:
            self.logger.error(f"Provider {provider_name} not configured.")
            return None

        provider = self.providers[provider_name]
        circuit_breaker = self.circuit_breakers[provider_name]

        try:
            return await circuit_breaker.call(lambda: api_call_func(provider))
        except CircuitBreakerError as e:
            self.logger.warning(f"Circuit breaker OPEN for {provider_name}. Call blocked. Reason: {e}")
            return None
        except Exception as e:
            self.logger.error(f"API call failed unexpectedly for {provider_name}: {e}")
            return None

    async def _try_secondary_providers(self, base: str, target: str) -> list[APICallResult]:
        """Try all secondary providers concurrently for a single pair."""
        tasks = [
            self._try_provider(name, base, target)
            for name in self.providers if name != self.primary_provider
        ]
        results = await asyncio.gather(*tasks)
        return [res for res in results if res is not None]

    async def _try_secondary_providers_all_rates(self, base: str) -> list[dict[str, ExchangeRateResponse]]:
        """Try all secondary providers concurrently for all rates."""
        tasks = [
            self._try_provider_all_rates(name, base)
            for name in self.providers if name != self.primary_provider
        ]
        results = await asyncio.gather(*tasks)
        return [res for res in results if res is not None]

    async def _check_cache(self, base: str, target: str) -> dict[str, Any] | None:
        """Check Redis cache for fresh data."""
        return await self.redis_manager.get_latest_rate(base, target)
    
    async def _check_stale_cache(self, base: str, target: str) -> dict[str, Any] | None:
        """Check database for the most recent successful rate as a fallback."""
        try:
            with self.db_manager.get_session() as session:
                latest_rate = session.query(ExchangeRate).join(
                    ExchangeRate.currency_pair
                ).filter(
                    ExchangeRate.is_successful,
                    ExchangeRate.currency_pair.has(base_currency=base, target_currency=target)
                ).order_by(ExchangeRate.fetched_at.desc()).first()

                if latest_rate:
                    fetched_at_aware = latest_rate.fetched_at.replace(tzinfo=UTC)
                    age_minutes = int((datetime.now(tz=UTC) - fetched_at_aware).total_seconds() / 60)
                    return {
                        "rate": latest_rate.rate,
                        "timestamp": latest_rate.fetched_at.isoformat(),
                        "sources_used": [latest_rate.provider.name],
                        "age_minutes": age_minutes
                    }
        except Exception as e:
            self.logger.error(f"Failed to get stale cache for {base}->{target}: {e}")
        return None
    
    async def _update_cache(self, result: AggregatedRateResult):
        """Update Redis cache with the aggregated result."""
        if not result.cached:
            cache_data = {
                "rate": str(result.rate),
                "confidence_level": result.confidence_level,
                "sources_used": result.sources_used,
                "is_primary_used": result.is_primary_used,
                "timestamp": result.timestamp.isoformat(),
                "warnings": result.warnings
            }
            await self.redis_manager.set_latest_rate(
                result.base_currency, result.target_currency, cache_data
            )

    async def _log_results_to_db(self, results: list[APICallResult]):
        """Log all API call results to the database."""
        try:
            with self.db_manager.get_session() as session:
                for result in results:
                    if not isinstance(result, APICallResult):
                        continue
                    
                    provider_id = self._get_provider_id(result.provider_name)
                    session.add(APICallLog(
                        provider_id=provider_id,
                        endpoint=result.endpoint,
                        http_status_code=result.http_status_code,
                        response_time_ms=result.response_time_ms,
                        was_successful=result.was_successful,
                        error_message=result.error_message,
                    ))

                    if result.was_successful and result.data:
                        pair = self.db_manager.get_or_create_currency_pair(
                            session, result.data.base_currency, result.data.target_currency
                        )
                        session.add(ExchangeRate(
                            currency_pair_id=pair.id,
                            provider_id=provider_id,
                            rate=result.data.rate,
                            fetched_at=result.data.timestamp,
                            is_successful=True,
                        ))
                session.commit()
        except Exception as e:
            self.logger.error(f"Failed to log results to database: {e}")

    def _get_provider_id(self, provider_name: str) -> int:
        """Get provider ID from the database."""
        try:
            with self.db_manager.get_session() as session:
                provider = session.query(APIProviderModel).filter(APIProviderModel.name == provider_name).first()
                return provider.id if provider else 1
        except Exception:
            return 1
        
    async def get_health_status(self) -> dict[str, Any]:
        """Get health status of all providers and circuit breakers."""
        provider_statuses = {
            name: await cb.get_status()
            for name, cb in self.circuit_breakers.items()
        }
        return {
            "service": "rate_aggregator",
            "status": "healthy" if all(p["status"] == "healthy" for p in provider_statuses.values()) else "unhealthy",
            "providers": provider_statuses,
            "cache_status": await self.redis_manager.health_check()
        }
