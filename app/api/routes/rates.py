import time
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_rate_aggregator
from app.api.models.requests import ExchangeRateRequest
from app.api.models.responses import ErrorResponse, ExchangeRateResponse
from app.monitoring.logger import logger
from app.services.rate_aggregator import RateAggregatorService
from app.utils.time import adjust_timestamp

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
    rate_service: Annotated[RateAggregatorService, Depends(get_rate_aggregator)]
):
    """
    Get current exchange rate between two currencies.
    
    This endpoint just returns the rate (e.g., 1 USD = 0.8550 EUR)
    without doing any amount conversion.
    """
    start_time = time.time()
    try:
        logger.info(
            "User request received",
            endpoint="/rates",
            request_data=request.model_dump(),
            event_type="USER_REQUEST",
            timestamp=datetime.now()
        )

        # Get exchange rate using rate aggregator, but no multplication by any amount like in /convert
        rate_result = await rate_service.get_exchange_rate(
            request.from_currency,
            request.to_currency
        )

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "Exchange rate retrieved successfully",
            endpoint="/rates",
            request_data=request.model_dump(),
            success=True,
            response_time_ms=duration_ms,
            event_type="USER_REQUEST",
            timestamp=datetime.now()
        )

        return ExchangeRateResponse(
            from_currency=request.from_currency,
            to_currency=request.to_currency,
            exchange_rate=rate_result.rate,
            confidence_level=rate_result.confidence_level,
            timestamp=adjust_timestamp(rate_result.timestamp)
        )

    except HTTPException:
        raise
    except ValueError as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "Currency validation failed",
            endpoint="/rates",
            request_data=request.model_dump(),
            success=False,
            response_time_ms=duration_ms,
            error_message=str(e),
            event_type="USER_REQUEST",
            timestamp=datetime.now()
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Currency validation failed: {e}"
        ) from e
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "An unexpected error occurred during exchange rate retrieval",
            endpoint="/rates",
            request_data=request.model_dump(),
            success=False,
            response_time_ms=duration_ms,
            error_message=str(e),
            event_type="USER_REQUEST",
            timestamp=datetime.now()
        )
        
        # Return generic error to user
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable" 
        ) from e
    
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
    rate_service: Annotated[RateAggregatorService, Depends(get_rate_aggregator)]
):
    """
    GET version of exchange rate fetching.
    Example: GET /api/v1/rates/USD/EUR
    """
    start_time = time.time()
    try:
        # Validate and create request object
        request = ExchangeRateRequest(
            from_currency=from_currency,
            to_currency=to_currency
        )
        
        return await get_exchange_rate(request, rate_service)
        
    except HTTPException:
        raise
    except ValueError as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "Invalid rate request parameters or currency validation failed: {error_message}",
            endpoint="/rates/{from_currency}/{to_currency}",
            request_data={
                'from_currency': from_currency,
                'to_currency': to_currency
            },
            success=False,
            response_time_ms=duration_ms,
            error_message=f"Invalid rate request parameters or currency validation failed: {e}",
            event_type="USER_REQUEST",
            timestamp=datetime.now()
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid currency codes or currency validation failed: {e}"
        ) from e
    
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "An unexpected error occurred during exchange rate retrieval (GET)",
            endpoint="/rates/{from_currency}/{to_currency}",
            request_data={
                'from_currency': from_currency,
                'to_currency': to_currency
            },
            success=False,
            response_time_ms=duration_ms,
            error_message=str(e),
            event_type="USER_REQUEST",
            timestamp=datetime.now()
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable"
        ) from e