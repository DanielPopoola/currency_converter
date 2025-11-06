from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ConversionResponse(BaseModel):
	from_currency: str = Field(..., description='Source currency code')
	to_currency: str = Field(..., description='Target currency code')
	original_amount: Decimal = Field(..., description='Original amount requested')
	converted_amount: Decimal = Field(..., description='Converted amount')
	exchange_rate: Decimal = Field(..., description='Exchange rate used for conversion')
	timestamp: datetime = Field(..., description='When the rate was fetched')
	source: str = Field(..., description='Providers of rates')

	class ConfigDict:
		json_schema_extra = {
			'example': {
				'from_currency': 'USD',
				'to_currency': 'EUR',
				'amount': 100.00,
				'converted_amount': 85.50,
				'exchange_rate': 0.8550,
				'timestamp': '2025-09-27T10:30:00Z',
			}
		}


class ExchangeRateResponse(BaseModel):
	from_currency: str = Field(..., description='Source currency code')
	to_currency: str = Field(..., description='Target currency code')
	rate: Decimal = Field(..., description='Exchange rate used for conversion')
	timestamp: datetime = Field(..., description='When the rate was fetched')
	source: str = Field(..., description='Providers of rates')

	class ConfigDict:
		json_schema_extra = {
			'example': {
				'from_currency': 'USD',
				'to_currency': 'EUR',
				'exchange_rate': 0.8550,
				'timestamp': '2025-09-27T10:30:00Z',
			}
		}


class SupportedCurrenciesResponse(BaseModel):
	currencies: list[str] = Field(description='List of currency codes')

	class ConfigDict:
		json_schema_extra = {'examples': [{'currencies': ['USD', 'EUR', 'GBP', 'JPY']}]}
