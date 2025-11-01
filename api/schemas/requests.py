from decimal import Decimal

from pydantic import BaseModel, Field, ValidationInfo, field_validator


class ConversionRequest(BaseModel):
	from_currency: str = Field(..., min_length=3, max_length=5)
	to_currency: str = Field(..., min_length=3, max_length=5)
	amount: Decimal = Field(..., gt=0)

	@field_validator('from_currency', 'to_currency')
	@classmethod
	def uppercase_currency(cls, v: str):
		return v.upper()

	@field_validator('amount')
	@classmethod
	def amount_precision(cls, v: Decimal):
		return round(v, 2)

	@field_validator('to_currency')
	@classmethod
	def currencies_must_be_different(cls, v: str, info: ValidationInfo):
		if info.data and 'from_currency' in info.data and v == info.data['from_currency']:
			raise ValueError('from_currency and to_currency must be different')
		return v

	class ConfigDict:
		json_schema_extra = {
			'example': {'from_currency': 'USD', 'to_currency': 'NGN', 'amount': 100.00}
		}
