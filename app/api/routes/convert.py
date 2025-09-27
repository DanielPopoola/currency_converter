from fastapi import APIRouter, Depends, HTTPException, status
from decimal import Decimal
import logging

from app.api.dependencies import get_rate_aggregator
from app.api.models.requests import ConvertRequest
from app.api.models.responses import ConvertResponse, ErrorResponse
from app.services.rate_aggregator import RateAggregatorService


logger = logging.getLogger(__name__)


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
    try:
        logger.info(f"Converting {request.amount} {request.from_currency} to {request.to_currency}")

        # Get exchange rate results using rate aggregator
        rate_result = await rate_service.get_exchange_rate(
            request.from_currency,
            request.to_currency
        )

        # Calculate the converted amount
        converted_amount = request.amount * rate_result.rate
        converted_amount = round(converted_amount, 2)

        logger.info(
            f"Conversion successful: {request.amount} {request.from_currency} = "
            f"{converted_amount} {request.to_currency} (rate: {rate_result.rate}, "
            f"confidence: {rate_result.confidence_level})"
        )

        return ConvertResponse(
            from_currency=request.from_currency,
            to_currency=request.to_currency,
            amount=request.amount,
            converted_amount=converted_amount,
            exchange_rate=rate_result.rate,
            confidence_level=rate_result.confidence_level,
            timestamp=rate_result.timestamp
        )
    except HTTPException:
        raise

    except Exception as e:
        # Log the real error for debugging
        logger.error(f"Currency conversion failed for {request.from_currency}->{request.to_currency}: {e}")
        
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
    try:
        # Validate and create request object
        request = ConvertRequest(
            from_currency=from_currency,
            to_currency=to_currency,
            amount=amount
        )

        # Use the same logic as POST endpoint
        return await convert_currency(request, rate_service)
    except ValueError as e:
        # Handle validation errors from ConvertRequest
        logger.warning(f"Invalid conversion parameters: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid currency codes or amount"
        )
    except Exception as e:
        logger.error(f"GET conversion failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable"
        )