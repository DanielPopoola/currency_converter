from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from api.dependencies import (
	get_conversion_service,
	get_currency_service,
	get_rate_service,
)
from api.schemas import ConversionResponse, ExchangeRateResponse, SupportedCurrenciesResponse
from application.services import (
	ConversionService,
	CurrencyService,
	RateService,
)

router = APIRouter(prefix='/api', tags=['currency'])


@router.get(
	'/convert/{from_currency}/{to_currency}/{amount}',
	response_model=ConversionResponse,
	status_code=status.HTTP_200_OK,
	summary='Convert currency amount',
)
async def convert_currency(
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
	amount: Annotated[
		Decimal,
		Path(
			gt=0,
			decimal_places=2,
		),
	],
	service: Annotated[ConversionService, Depends(get_conversion_service)],
) -> ConversionResponse:
	from_currency = from_currency.upper()
	to_currency = to_currency.upper()
	result = await service.convert(amount, from_currency, to_currency)
	return ConversionResponse(**result)


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


@router.get(
	'/currencies',
	response_model=SupportedCurrenciesResponse,
	status_code=status.HTTP_200_OK,
	summary='List supported currencies',
)
async def get_supported_currencies(
	service: Annotated[CurrencyService, Depends(get_currency_service)],
) -> SupportedCurrenciesResponse:
	currencies = await service.get_supported_currencies()
	return SupportedCurrenciesResponse(currencies=currencies)
