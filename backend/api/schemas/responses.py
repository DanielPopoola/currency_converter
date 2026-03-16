from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ConversionResponse(BaseModel):
	model_config = ConfigDict(
		json_schema_extra={
			'example': {
				'from_currency': 'USD',
				'to_currency': 'EUR',
				'original_amount': '100.00',
				'converted_amount': '92.55',
				'exchange_rate': '0.9255',
				'timestamp': '2025-11-01T14:30:00Z',
				'source': 'averaged',
			}
		}
	)

	from_currency: str = Field(..., description='Source currency code')
	to_currency: str = Field(..., description='Target currency code')
	original_amount: Decimal = Field(..., description='Original amount requested')
	converted_amount: Decimal = Field(..., description='Converted amount')
	exchange_rate: Decimal = Field(..., description='Exchange rate used for conversion')
	timestamp: datetime = Field(..., description='When the rate was fetched')
	source: str = Field(..., description='Providers of rates')


class ExchangeRateResponse(BaseModel):
	model_config = ConfigDict(
		json_schema_extra={
			'example': {
				'from_currency': 'USD',
				'to_currency': 'JPY',
				'rate': '149.85',
				'timestamp': '2025-11-01T14:30:00Z',
				'source': 'averaged',
			}
		}
	)

	from_currency: str = Field(..., description='Source currency code')
	to_currency: str = Field(..., description='Target currency code')
	rate: Decimal = Field(..., description='Exchange rate between the two currencies')
	timestamp: datetime = Field(..., description='When the rate was fetched')
	source: str = Field(..., description='Providers of rates')


class SupportedCurrenciesResponse(BaseModel):
	model_config = ConfigDict(
		json_schema_extra={
			'example': {
				'currencies': ['USD', 'EUR', 'GBP', 'JPY', 'NGN'],
			}
		}
	)

	currencies: list[str] = Field(..., description='List of supported currency codes')
