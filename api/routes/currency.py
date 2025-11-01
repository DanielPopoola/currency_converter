from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from api.dependencies import (
	get_conversion_service,
	get_rate_service,
)
from api.schemas import (
	ConversionRequest,
	ConversionResponse,
	ExchangeRateResponse,
)
from application.services import (
	ConversionService,
	RateService,
)

router = APIRouter(prefix='/api', tags=['currency'])


@router.post(
	'/convert',
	response_model=ConversionResponse,
	status_code=status.HTTP_200_OK,
	summary='Convert currency amount',
)
async def convert_currency(
	request: ConversionRequest,
	service: Annotated[ConversionService, Depends(get_conversion_service)],
) -> ConversionResponse:
	result = await service.convert(
		amount=request.amount, from_currency=request.from_currency, to_currency=request.to_currency
	)
	return ConversionResponse.model_validate(result)


@router.get(
	'/rate/{from_currency}/{to_currency}',
	response_model=ExchangeRateResponse,
	status_code=status.HTTP_200_OK,
	summary='Get current exchange rate',
)
async def get_exchange_rate(
	from_currency: Annotated[
		str,
		Path(
			min_length=3,
			max_length=5,
		),
	],
	to_currency: Annotated[
		str,
		Path(
			min_length=3,
			max_length=5,
		),
	],
	service: Annotated[RateService, Depends(get_rate_service)],
) -> ExchangeRateResponse:
	from_currency = from_currency.upper()
	to_currency = to_currency.upper()

	result = await service.get_rate(from_currency=from_currency, to_currency=to_currency)
	return ExchangeRateResponse(
		from_currency=result.from_currency,
		to_currency=result.to_currency,
		rate=result.rate,
		timestamp=result.timestamp,
		source=result.source,
	)
