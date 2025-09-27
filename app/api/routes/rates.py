from fastapi import APIRouter, Depends, HTTPException, status
import logging


from app.api.dependencies import get_rate_aggregator
from app.api.models.requests import ExchangeRateRequest
from app.api.models.responses import ExchangeRateResponse, ErrorResponse
from app.services.rate_aggregator import RateAggregatorService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["rates"])

@router.post(
    "/rates",
    response_model=ExchangeRateResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
    },
    summary="Get exchange rate",
    description="Get the current exchange rate between two currencies without conversion"
)
async def get_exchange_rate(
    request: ExchangeRateRequest,
    rate_service: RateAggregatorService = Depends(get_rate_aggregator)
):
    """
    Get current exchange rate between two currencies.
    
    This endpoint just returns the rate (e.g., 1 USD = 0.8550 EUR)
    without doing any amount conversion.
    """
    try:
        logger.info(f"Getting exchange rate for {request.from_currency} -> {request.to_currency}")

        # Get exchange rate using rate aggregator, but no multplication by any amount like in /convert
        rate_result = await rate_service.get_exchange_rate(
            request.from_currency,
            request.to_currency
        )

        logger.info(
            f"Rate fetched successfully: 1 {request.from_currency} = {rate_result.rate} {request.to_currency} "
            f"(confidence: {rate_result.confidence_level}, sources: {rate_result.sources_used})"
        )

        return ExchangeRateResponse(
            from_currency=request.from_currency,
            to_currency=request.to_currency,
            exchange_rate=rate_result.rate,
            confidence_level=rate_result.confidence_level,
            timestamp=rate_result.timestamp
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rate fetch failed for {request.from_currency}->{request.to_currency}: {e}")
        
        # Return generic error to user
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable"
        )
    
@router.get(
    "/rates/{from_currency}/{to_currency}",
    response_model=ExchangeRateResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid parameters"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
    },
    summary="Get exchange rate (GET)",
    description="Alternative GET endpoint for getting exchange rates"
)
async def get_exchange_rate_get(
    from_currency: str,
    to_currency: str,
    rate_service: RateAggregatorService = Depends(get_rate_aggregator)
):
    """
    GET version of exchange rate fetching.
    Example: GET /api/v1/rates/USD/EUR
    """
    try:
        # Validate and create request object
        request = ExchangeRateRequest(
            from_currency=from_currency,
            to_currency=to_currency
        )
        
        return await get_exchange_rate(request, rate_service)
        
    except ValueError as e:
        # Handle validation errors from ExchangeRateRequest
        logger.warning(f"Invalid rate request parameters: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid currency codes"
        )
    
    except Exception as e:
        logger.error(f"GET rate fetch failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable"
        )