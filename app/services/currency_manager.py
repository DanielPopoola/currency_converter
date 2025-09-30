import logging
import time
from typing import Dict, List, Set, Optional, Tuple
from datetime import datetime, UTC, timedelta

from sqlalchemy.orm import sessionmaker
from sqlalchemy import func

from app.providers.base import APIProvider
from app.database.models import SupportedCurrency
from app.cache.redis_manager import RedisManager
from app.config.database import DatabaseManager
from app.monitoring.logger import get_production_logger, LogLevel, LogEvent, EventType



class CurrencyManager:
    def __init__(self, db_manager: DatabaseManager, redis_manager: RedisManager):
        self.db_manager = db_manager
        self.redis_manager = redis_manager
        self.production_logger = get_production_logger()
        self.TOP_CURRENCIES_KEY = "supported_currencies:top"
        self.ALL_CURRENCIES_KEY = "supported_currencies:all"
        self.VALIDATION_CACHE_KEY = "currency_validation:{}"
        
        self.POPULAR_CURRENCIES = [
            "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "NGN", "ZAR"
        ]

        # How often to refresh currencies (e.g., weekly)
        self.REFRESH_INTERVAL_DAYS = 7


    async def populate_supported_currencies(self, providers: Dict[str, APIProvider]) -> List[str]: 
        """Fetch and merge supported currencies from all providers"""
        start_time = time.time()
        all_currencies = set()
        provider_currency_counts = {}

        self.production_logger.log_event(
            LogEvent(
                event_type=EventType.API_CALL,
                level=LogLevel.INFO,
                message=f"Starting currency population from {len(providers)} providers",
                timestamp=datetime.now(),
                api_context={
                    "operation": "populate_currencies",
                    "provider_count": len(providers),
                    "providers": list(providers.keys())
                }
            )
        )
        
        for provider_name, provider in providers.items():
            provider_start = time.time()
            try:
                result = await provider.get_supported_currencies()
                provider_duration = (time.time() - provider_start) * 1000
                if result.was_successful and result.data:
                    currencies = set(result.data)
                    all_currencies.update(currencies)
                    provider_currency_counts[provider_name] = len(currencies)

                    # Log successful provider fetch
                    self.production_logger.log_api_call(
                        provider_name=provider_name,
                        endpoint="get_supported_currencies",
                        success=True,
                        response_time_ms=provider_duration,
                        rate_data={"currency_count": len(currencies)}
                    )
                else:
                    # Log provider failure
                    self.production_logger.log_api_call(
                        provider_name=provider_name,
                        endpoint="get_supported_currencies", 
                        success=False,
                        response_time_ms=provider_duration,
                        error_message=result.error_message or "No currencies returned"
                    )
            except Exception as e:
                provider_duration = (time.time() - provider_start) * 1000
                self.production_logger.log_api_call(
                    provider_name=provider_name,
                    endpoint="get_supported_currencies",
                    success=False,
                    response_time_ms=provider_duration,
                    error_message=str(e)
                )

        total_duration = (time.time() - start_time) * 1000

        try:
            await self._store_currencies_in_db(all_currencies)
            await self._cache_top_currencies()
            # Log successful completion
            self.production_logger.log_event(
                LogEvent(
                    event_type=EventType.API_CALL,
                    level=LogLevel.INFO,
                    message=f"Currency population completed: {len(all_currencies)} total currencies",
                    timestamp=datetime.now(),
                    duration_ms=total_duration,
                    api_context={
                        "operation": "populate_currencies_complete",
                        "total_currencies": len(all_currencies),
                        "provider_breakdown": provider_currency_counts,
                        "successful_providers": len([p for p in provider_currency_counts if provider_currency_counts[p] > 0])
                    },
                    performance_context={
                        "total_duration_ms": total_duration,
                        "database_store_completed": True,
                        "cache_update_completed": True
                    }
                )
            )
            
        except Exception as e:
            self.production_logger.log_event(
                LogEvent(
                    event_type=EventType.API_CALL,
                    level=LogLevel.ERROR,
                    message=f"Failed to store/cache currencies: {str(e)}",
                    timestamp=datetime.now(),
                    duration_ms=total_duration,
                    error_context={"storage_error": str(e)}
                )
            )
        
        return list(all_currencies)
    
    async def should_populate_currencies(self) -> Tuple[bool, str]:
        """Determine if we need to fetch supported currencies from external providers"""
        start_time = time.time()
        log_context = {"check_reason": None, "database_count": 0, "data_age_days": None}

        try:
            Session = sessionmaker(bind=self.db_manager.engine)
            with Session() as session:
                # Check if there are any currencies in the database
                count = session.query(func.count(SupportedCurrency.code)).scalar()
                log_context["database_count"] = count

                if count == 0:
                    reason = "No currencies found in database"
                    log_context["check_reason"] = reason
                    self.production_logger.log_event(
                        LogEvent(
                            event_type=EventType.DATABASE_OPERATION,
                            level=LogLevel.INFO,
                            message=f"Currency population check: {reason}",
                            timestamp=datetime.now(),
                            duration_ms=(time.time() - start_time) * 1000,
                            api_context=log_context,
                        )
                    )
                    return True, reason
                
                last_updated = session.query(
                    func.max(SupportedCurrency.last_updated)
                ).scalar()

                if last_updated is None:
                    reason = "No last_updated timestamp found"
                    log_context["check_reason"] = reason
                    self.production_logger.log_event(
                        LogEvent(
                            event_type=EventType.DATABASE_OPERATION,
                            level=LogLevel.WARNING,
                            message=f"Currency population check: {reason}",
                            timestamp=datetime.now(),
                            duration_ms=(time.time() - start_time) * 1000,
                            api_context=log_context,
                        )
                    )
                    return True, reason
                
                # Check if data is stale
                age = datetime.now(UTC) - last_updated
                log_context["data_age_days"] = age.days
                if age > timedelta(days=self.REFRESH_INTERVAL_DAYS):
                    reason = f"Data is {age.days} days old (threshold: {self.REFRESH_INTERVAL_DAYS} days)"
                    log_context["check_reason"] = reason
                    self.production_logger.log_event(
                        LogEvent(
                            event_type=EventType.DATABASE_OPERATION,
                            level=LogLevel.INFO,
                            message=f"Currency population check: Stale data, refresh needed. Reason: {reason}",
                            timestamp=datetime.now(),
                            duration_ms=(time.time() - start_time) * 1000,
                            api_context=log_context,
                        )
                    )
                    return True, reason

                reason = f"Database has {count} currencies, {age.days} days old. No refresh needed."
                log_context["check_reason"] = reason
                self.production_logger.log_event(
                    LogEvent(
                        event_type=EventType.DATABASE_OPERATION,
                        level=LogLevel.INFO,
                        message=f"Currency population check: No refresh needed. Reason: {reason}",
                        timestamp=datetime.now(),
                        duration_ms=(time.time() - start_time) * 1000,
                        api_context=log_context,
                    )
                )
                return False, reason
            
        except Exception as e:
            reason = f"Database check failed: {e}"
            log_context["check_reason"] = "Exception"
            self.production_logger.log_event(
                LogEvent(
                    event_type=EventType.DATABASE_OPERATION,
                    level=LogLevel.ERROR,
                    message=f"Currency population check failed.",
                    timestamp=datetime.now(),
                    duration_ms=(time.time() - start_time) * 1000,
                    error_context={"error": str(e), "details": log_context},
                )
            )
            return True, reason

    async def populate_if_needed(self, providers: Dict[str, APIProvider]) -> bool:
        """
        Only populate currencies if needed (first time or data is stale).
        
        Returns:
            True if population was performed, False if skipped
        """
        should_populate, reason = await self.should_populate_currencies()
        
        if should_populate:
            self.production_logger.log_event(
                LogEvent(
                    event_type=EventType.SERVICE_LIFECYCLE,
                    level=LogLevel.INFO,
                    message=f"Initiating currency population. Reason: {reason}",
                    timestamp=datetime.now(),
                )
            )
            await self.populate_supported_currencies(providers)
            return True
        else:
            self.production_logger.log_event(
                LogEvent(
                    event_type=EventType.SERVICE_LIFECYCLE,
                    level=LogLevel.INFO,
                    message=f"Skipping currency population. Reason: {reason}",
                    timestamp=datetime.now(),
                )
            )
            return False
        
    async def _store_currencies_in_db(self, currencies: Set[str]):
        """Store supported currencies in the database."""
        Session = sessionmaker(bind=self.db_manager.engine)
        with Session() as session:
            new_currencies_count = 0
            for code in currencies:
                # Check if currency already exists
                existing_currency = session.query(SupportedCurrency).filter_by(code=code).first()
                if not existing_currency:
                    new_currency = SupportedCurrency(code=code)
                    session.add(new_currency)
                    new_currencies_count += 1
            session.commit()
            self.production_logger.log_event(
                LogEvent(
                    event_type=EventType.DATABASE_OPERATION,
                    level=LogLevel.INFO,
                    message=f"Stored {new_currencies_count} new currencies out of {len(currencies)} total unique currencies in the database.",
                    timestamp=datetime.now(),
                    api_context={
                        "new_currencies_added": new_currencies_count,
                        "total_unique_currencies_processed": len(currencies),
                    }
                )
            )

    async def _cache_top_currencies(self):
        """Select top N currencies and cache them in Redis."""
        await self.redis_manager.set_top_currencies(self.POPULAR_CURRENCIES)
        self.production_logger.log_cache_operation(
            operation="set_top_currencies",
            cache_key=self.TOP_CURRENCIES_KEY,
            hit=False,
            duration_ms=0,
        )

    async def validate_currencies(self, base: str, target: str) -> Tuple[bool, Optional[str]]:
        """
        Validate currencies with comprehensive logging and performance tracking
        
        Returns: (is_valid, error_message)
        """
        start_time = time.time()
        validation_result = {
            "valid": False,
            "cache_hit": False,
            "db_lookup_required": False,
            "top_cache_checked": False,
            "database_checked": False,
            "error_details": None
        }
            
        try:
            # Step 1: Check validation cache first (to avoid repeated validations)
            cache_key = self.VALIDATION_CACHE_KEY.format(f"{base}_{target}")
            cache_validation = await self.redis_manager.get_cached_currency(cache_key)

            if cache_validation:
                self.production_logger.log_event(
                    LogEvent(
                        event_type=EventType.CACHE_OPERATION,
                        level=LogLevel.DEBUG,
                        message=f"Validation cache hit for {base}->{target}: {cache_validation}",
                        timestamp=datetime.now()
                    )
                )
                validation_result["cache_hit"] = True
                validation_result["valid"] = cache_validation.get("valid", False)
                duration_ms = (time.time() - start_time) * 1000

                # Log cache hit
                self.production_logger.log_currency_validation(
                    from_currency=base,
                    to_currency=target,
                    validation_result=validation_result,
                    duration_ms=duration_ms,
                )

                if validation_result["valid"]:
                    return True, None
                else:
                    cached_error = cache_validation.get("error_message", "Invalid currencies")
                    return False, cached_error
                
            # Step 2: Check top currencies cache (fast path for popular currencies)
            validation_result["top_cache_checked"] = True
            top_currencies = await self.redis_manager.get_top_currencies()

            if top_currencies:
                if base in top_currencies and target in top_currencies:
                    validation_result["result"] = True
                    validation_result["cache_hit"] = True

                    # Cache this validation result
                    await self._cache_validation_result(base, target, True, None)

                    duration_ms = (time.time() - start_time) * 1000
                    self.production_logger.log_currency_validation(
                        from_currency=base,
                        to_currency=target,
                        validation_result=validation_result,
                        duration_ms=duration_ms
                    )
                    
                    return True, None
                
                # If one or both currencies not in top cache, we need database lookup
                validation_result["db_lookup_required"] = True

            # Step 3: Database lookup for comprehensive validation
            validation_result["database_checked"] = True
            db_start_time = time.time()

            try:
                Session = sessionmaker(bind=self.db_manager.engine)
                with Session() as session:
                    supported = session.query(SupportedCurrency.code).all()
                    supported_set = {currency.code for currency in supported}

                    db_lookup_duration = (time.time() - db_start_time) * 1000
                    validation_result["db_lookup_duration_ms"] = db_lookup_duration

                    unsupported = []
                    if base not in supported_set:
                        unsupported.append(base)
                    if target not in supported_set:
                        unsupported.append(target)

                    if unsupported:
                        error_msg = f"Unsupported currency(ies): {', '.join(unsupported)}"
                        validation_result["valid"] = False
                        validation_result["error_details"] = {
                            "unsupported_currencies": unsupported,
                            "total_supported": len(supported_set)
                        }
                        
                        # Cache negative result (shorter TTL)
                        await self._cache_validation_result(base, target, False, error_msg, ttl=300)

                        duration_ms = (time.time() - start_time) * 1000
                        self.production_logger.log_currency_validation(
                            from_currency=base,
                            to_currency=target,
                            validation_result=validation_result,
                            duration_ms=duration_ms,
                        )
                        
                        self.production_logger.log_event(
                            LogEvent(
                                event_type=EventType.CURRENCY_VALIDATION,
                                level=LogLevel.DEBUG,
                                message=f"Validation failed for {base}->{target}. Unsupported: {unsupported}",
                                timestamp=datetime.now(),
                                api_context={
                                    "base": base,
                                    "target": target,
                                    "unsupported": unsupported,
                                    "supported_set_size": len(supported_set),
                                },
                            )
                        )
                        return False, error_msg

                    # Both currencies are valid
                    validation_result["valid"] = True
                    validation_result["error_details"] = {
                        "total_supported": len(supported_set)
                    }

                    # Cache postive result
                    await self._cache_validation_result(base, target, True, None)

                    duration_ms = (time.time() - start_time) * 1000
                    self.production_logger.log_currency_validation(
                        from_currency=base,
                        to_currency=target,
                        validation_result=validation_result,
                        duration_ms=duration_ms
                    )
                    
                    self.production_logger.log_event(
                        LogEvent(
                            event_type=EventType.CURRENCY_VALIDATION,
                            level=LogLevel.DEBUG,
                            message=f"Validation successful for {base}->{target}",
                            timestamp=datetime.now(),
                            api_context={
                                "base": base,
                                "target": target,
                                "supported_set_size": len(supported_set),
                            },
                        )
                    )
                    return True, None
            except Exception as db_error:
                self.production_logger.log_event(
                    LogEvent(
                        event_type=EventType.DATABASE_OPERATION,
                        level=LogLevel.ERROR,
                        message=f"Database error during currency validation",
                        timestamp=datetime.now(),
                        error_context={
                            "error": str(db_error),
                            "error_type": type(db_error).__name__,
                        },
                    )
                )
                validation_result["error_details"] = {
                    "database_error": str(db_error)
                }
                duration_ms = (time.time() - start_time) * 1000

                self.production_logger.log_currency_validation(
                    from_currency=base,
                    to_currency=target,
                    validation_result=validation_result,
                    duration_ms=duration_ms,
                )

                # Fail open - let API calls proceed and handle errors there
                return True, None
            
        except Exception as e:
            validation_result["error_details"] = {
                "unexpected_error": str(e)
            }
            duration_ms = (time.time() - start_time) * 1000
            
            self.production_logger.log_currency_validation(
                from_currency=base,
                to_currency=target,
                validation_result=validation_result,
                duration_ms=duration_ms,
            )
            
            # Fail open - let API calls proceed
            return True, None
        
    async def _cache_validation_result(self, base: str, target: str, is_valid: bool,
                                       error_message: Optional[str] = None, ttl: int = 900):
        """Cache validation results to avoid repeated database lookups"""
        if not is_valid and error_message is None:
            return 
        
        cache_key = self.VALIDATION_CACHE_KEY.format(f"{base}_{target}")
        cache_data = {
            "valid": is_valid,
            "error_message": error_message,
            "cached_at": datetime.now(UTC).isoformat()
        }
        
        try:
            await self.redis_manager.set_cache_validation_result(cache_key, ttl, cache_data)
            self.production_logger.log_cache_operation(
                operation="set_validation_result",
                cache_key=cache_key,
                hit=False, # This is a write operation
                duration_ms=0, # Not measured here
            )
        except Exception as e:
            self.production_logger.log_cache_operation(
                operation="set_validation_result",
                cache_key=cache_key,
                hit=False,
                duration_ms=0,
                level=LogLevel.ERROR,
                error_message=str(e),
            )