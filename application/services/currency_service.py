import asyncio
import logging

from domain.exceptions.currency import InvalidCurrencyError, ProviderError
from domain.models.currency import SupportedCurrency
from infrastructure.persistence.repositories.currency import CurrencyRepository
from infrastructure.providers.base import ExchangeRateProvider

logger = logging.getLogger(__name__)


class CurrencyService:
	def __init__(self, repository: CurrencyRepository, providers: list[ExchangeRateProvider]):
		self.repository = repository
		self.providers = providers

	async def initialize_supported_currencies(self) -> None:
		logger.info('Initializing supported currencies...')

		provider_tasks = [provider.fetch_supported_currencies() for provider in self.providers]
		results = await asyncio.gather(*provider_tasks, return_exceptions=True)

		all_currencies = []
		for i, result in enumerate(results):
			provider_name = self.providers[i].name
			if isinstance(result, Exception):
				logger.error(f'Failed to fetch currencies from {provider_name}: {result}')
			elif isinstance(result, list):
				all_currencies.append(set(c['code'] for c in result))
				logger.info(f'{provider_name} supports {len(result)} currencies')

		if not all_currencies:
			raise ProviderError('Failed to fetch currencies from any provider')

		supported_codes = set.intersection(*all_currencies)
		currency_models = [SupportedCurrency(code=code, name=None) for code in supported_codes]

		await self.repository.save_supported_currencies(currency_models)
		logger.info(f'Saved {len(supported_codes)} supported currencies.')

	async def get_supported_currencies(self) -> list[str]:
		currencies = await self.repository.get_supported_currencies()
		return [c.code for c in currencies]

	async def validate_currency(self, code: str) -> None:
		supported = await self.get_supported_currencies()
		if code not in supported:
			raise InvalidCurrencyError(f'Currency {code} is not supported')
