import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_service_factory
from app.api.models.responses import HealthResponse
from app.monitoring.logger import EventType, LogEvent, LogLevel, get_production_logger
from app.services.service_factory import ServiceFactory
from app.utils.time import get_adjusted_timestamp

production_logger = get_production_logger()



router = APIRouter(prefix="/api/v1", tags=["health"])

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="System health check",
    description="Check the health status of all system components"
)
async def health_check(
    service_factory: ServiceFactory = Depends(get_service_factory)
):
    """
    Comprehensive health check of all system components.
    
    Returns:
    - Overall system status (healthy/degraded/unhealthy)
    - Individual service statuses (database, cache, providers)
    - Response times and error counts
    """
    try:
        production_logger.log_event(
            LogEvent(
                event_type=EventType.HEALTH_CHECK,
                level=LogLevel.INFO,
                message="Performing system health check",
                timestamp=datetime.now()
            )
        )
        health_data = {
            "timestamp": get_adjusted_timestamp(),
            "services": {}
        }

        # Check database health
        try:
            db_health = await service_factory.get_db_manager().health_check()
            health_data["services"]["database"] = db_health
        except Exception as e:
            production_logger.log_event(
                LogEvent(
                    event_type=EventType.HEALTH_CHECK,
                    level=LogLevel.ERROR,
                    message=f"Database health check failed: {e}",
                    timestamp=datetime.now(),
                    error_context={'error': str(e)}
                )
            )
            health_data["services"]["database"] = {
                "status": "unhealthy",
                "error": "Connection failed"
            }

        # Check Redis cache health
        try:
            cache_health = await service_factory.get_redis_manager().health_check()
            health_data["services"]["cache"] = cache_health
        except Exception as e:
            production_logger.log_event(
                LogEvent(
                    event_type=EventType.HEALTH_CHECK,
                    level=LogLevel.ERROR,
                    message=f"Cache health check failed: {e}",
                    timestamp=datetime.now(),
                    error_context={'error': str(e)}
                )
            )
            health_data["services"]["cache"] = {
                "status": "unhealthy", 
                "error": "Connection failed"
            }

        # Check rate aggregators and providers health
        try:
            if service_factory.rate_aggregator:
                aggregator_health = await service_factory.get_health_status()
                health_data["services"]["rate_aggregator"] = aggregator_health
            else:
                health_data["services"]["rate_aggregator"] = {
                    "status": "not_initialized"
                }
        except Exception as e:
            production_logger.log_event(
                LogEvent(
                    event_type=EventType.HEALTH_CHECK,
                    level=LogLevel.ERROR,
                    message=f"Rate aggregator health check failed: {e}",
                    timestamp=datetime.now(),
                    error_context={'error': str(e)}
                )
            )
            health_data["services"]["rate_aggregator"] = {
                "status": "unhealthy",
                "error": "Service unavailable"
            }

        # Determine overall system health
        overall_status = _determine_overall_health(health_data["services"])
        health_data["status"] = overall_status
        
        # Log health status
        level = LogLevel.INFO
        if overall_status == "unhealthy":
            level = LogLevel.ERROR
        elif overall_status == "degraded":
            level = LogLevel.WARNING
        
        production_logger.log_event(
            LogEvent(
                event_type=EventType.HEALTH_CHECK,
                level=level,
                message=f"System health check: {overall_status}",
                timestamp=datetime.now(),
                performance_context=health_data
            )
        )
        
        return HealthResponse(**health_data)
    
    except Exception as e:
        production_logger.log_event(
            LogEvent(
                event_type=EventType.HEALTH_CHECK,
                level=LogLevel.CRITICAL,
                message=f"Health check failed: {e}",
                timestamp=datetime.now(),
                error_context={'error': str(e)}
            )
        )
        return {
            "status": "unhealthy",
            "timestamp": get_adjusted_timestamp(),
            "services": {
                "error": "Health check system failure"
            }
        }
    
@router.get(
    "/health/simple",
    summary="Simple health check", 
    description="Quick health check that just returns 200 OK if system is running"
)
async def simple_health_check():
    """
    Minimal health check for load balancers and monitoring systems.
    Just returns 200 OK if the API is responding.
    """
    return {
        "status": "ok",
        "timestamp": get_adjusted_timestamp(),
        "message": "API is responding"
    }

@router.get(
    "/health/providers",
    summary="Provider-specific health check",
    description="Detailed health information about external API providers"
)
async def providers_health_check(
    service_factory: ServiceFactory = Depends(get_service_factory)
):
    """
    Detailed health check focused on external API providers.
    Shows circuit breaker states, failure counts, and response times.
    """
    try:
        if not service_factory.rate_aggregator:
            await service_factory.create_rate_aggregator()

        # Get detailed provider status
        provider_health = {}

        for provider_name, circuit_breaker in service_factory.circuit_breakers.items():
            try:
                cb_status = await circuit_breaker.get_status()
                provider_health[provider_name] = {
                    **cb_status,
                    "is_primary": provider_name == service_factory.rate_aggregator.primary_provider
                }
            except Exception as e:
                production_logger.log_event(
                    LogEvent(
                        event_type=EventType.HEALTH_CHECK,
                        level=LogLevel.ERROR,
                        message=f"Failed to get status for provider {provider_name}: {e}",
                        timestamp=datetime.now(),
                        error_context={'error': str(e)}
                    )
                )
                provider_health[provider_name] = {
                    "status": "error",
                    "error": str(e)
                }
        return {
            "timestamp": get_adjusted_timestamp(),
            "providers": provider_health,
            "primary_provider": service_factory.rate_aggregator.primary_provider if service_factory.rate_aggregator else None
        }
    except Exception as e:
        production_logger.log_event(
            LogEvent(
                event_type=EventType.HEALTH_CHECK,
                level=LogLevel.CRITICAL,
                message=f"Provider health check failed: {e}",
                timestamp=datetime.now(),
                error_context={'error': str(e)}
            )
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to check provider health"
        )
    
def _determine_overall_health(services: dict[str, Any]) -> str:
    """
    Determine overall system health based on individual service statuses.
    
    Logic:
    - healthy: All critical services are healthy
    - degraded: Some non-critical services have issues, but core functionality works
    - unhealthy: Critical services are down
    """
    critical_services = ["database", "rate_aggregator"]

    critical_healthy = True
    has_degraded = False

    for service_name, service_data in services.items():
        service_status = service_data.get("status", "unknown")
        
        if service_name in critical_services:
            if service_status in ["unhealthy", "error", "not_initialized"]:
                critical_healthy = False
        
        if service_status in ["degraded", "unhealthy", "error"]:
            has_degraded = True
    
    # Determine overall status
    if not critical_healthy:
        return "unhealthy"
    elif has_degraded:
        return "degraded" 
    else:
        return "healthy"