import logging

from fastapi import HTTPException, status

from app.services.service_factory import service_factory

logger = logging.getLogger(__name__)


async def get_rate_aggregator():
    """
    Dependency to get the rate aggregator service.
    This ensures we reuse the same service factory instance across all requests.
    """
    try:
        # Get or create the rate aggregator
        if not service_factory.rate_aggregator:
            await service_factory.create_rate_aggregator()

        return service_factory.rate_aggregator
    except Exception as e:
        logger.error(f"Failed to get rate aggregator service: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable"
        )
    

async def get_service_factory():
    """
    Dependency to get the service factory itself.
    Useful for health checks and accessing multiple services.
    """
    try:
        return service_factory
    except Exception as e:
        logger.error(f"Failed to get service factory: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable"
        )