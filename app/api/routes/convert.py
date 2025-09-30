from fastapi import APIRouter, Depends, HTTPException, status
from decimal import Decimal
import logging
import time

from app.api.dependencies import get_rate_aggregator
from app.api.models.requests import ConvertRequest
from app.api.models.responses import ConvertResponse, ErrorResponse
from app.services.rate_aggregator import RateAggregatorService
from app.utils.time import adjust_timestamp
from app.monitoring.logger import get_production_logger, LogEvent, EventType, LogLevel

production_logger = get_production_logger()


router = APIRouter(prefix="/api/v1", tags=["conversion"])


@router.post(
    "/convert",
    response_model=ConvertResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
    },
    summary="Convert currency amount",
    description="Convert an amount from one currency to another using real-time exchange rates"
)
async def convert_currency(
    request: ConvertRequest,
    rate_service: RateAggregatorService = Depends(get_rate_aggregator)
):
    """
    Convert currency amount using current exchange rates.
    """
    start_time = time.time()
    try:
        production_logger.log_user_request(
            endpoint="/convert",
            request_data=request.model_dump(),
            success=True, # Will be updated on failure
            response_time_ms=0 # Will be updated
        )

        # Get exchange rate results using rate aggregator
        rate_result = await rate_service.get_exchange_rate(
            request.from_currency,
            request.to_currency
        )

        # Calculate the converted amount
        converted_amount = request.amount * rate_result.rate
        converted_amount = round(converted_amount, 2)

        duration_ms = (time.time() - start_time) * 1000
        production_logger.log_user_request(
            endpoint="/convert",
            request_data=request.model_dump(),
            success=True,
            response_time_ms=duration_ms
        )

        return ConvertResponse(
            from_currency=request.from_currency,
            to_currency=request.to_currency,
            amount=request.amount,
            converted_amount=converted_amount,
            exchange_rate=rate_result.rate,
            confidence_level=rate_result.confidence_level,
            timestamp=adjust_timestamp(rate_result.timestamp)
        )
    except HTTPException:
        raise
    except ValueError as e:
        duration_ms = (time.time() - start_time) * 1000
        production_logger.log_user_request(
            endpoint="/convert",
            request_data=request.model_dump(),
            success=False,
            response_time_ms=duration_ms,
            error_message=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Currency validation failed: {e}"
        )
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        production_logger.log_user_request(
            endpoint="/convert",
            request_data=request.model_dump(),
            success=False,
            response_time_ms=duration_ms,
            error_message=str(e)
        )
        
        # Return generic error to user
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable"
        )
    
@router.get(
    "/convert/{from_currency}/{to_currency}/{amount}",
    response_model=ConvertResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid parameters"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
    },
    summary="Convert currency amount (GET)",
    description="Alternative GET endpoint for currency conversion (useful for simple requests)"
)
async def convert_currency_get(
    from_currency: str,
    to_currency: str, 
    amount: Decimal,
    rate_service: RateAggregatorService = Depends(get_rate_aggregator)
):
    """
    GET version of currency conversion for simple requests
    Example: GET /api/v1/convert/USD/EUR/100
    """
    start_time = time.time()
    try:
        # Validate and create request object
        request = ConvertRequest(
            from_currency=from_currency,
            to_currency=to_currency,
            amount=amount
        )

        # Use the same logic as POST endpoint
        return await convert_currency(request, rate_service)
    except HTTPException:
        raise
    except ValueError as e:        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid currency codes or amount"
        )