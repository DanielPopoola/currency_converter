from decimal import Decimal

from application.services.currency_service import CurrencyService
from application.services.rate_service import RateService


class ConversionService:
	def __init__(self, rate_service: RateService, currency_service: CurrencyService):
		self.rate_service = rate_service
		self.currency_service = currency_service

	async def convert(self, amount: Decimal, from_currency: str, to_currency: str) -> dict:
		await self.currency_service.validate_currency(from_currency)
		await self.currency_service.validate_currency(to_currency)

		rate = await self.rate_service.get_rate(from_currency, to_currency)

		converted_amount = amount * rate.rate

		return {
			'from_currency': from_currency,
			'to_currency': to_currency,
			'original_amount': amount,
			'converted_amount': converted_amount,
			'exchange_rate': rate.rate,
			'timestamp': rate.timestamp,
			'source': rate.source,
		}
