from decimal import Decimal

import httpx

from domain.exceptions.currency import ProviderError


class FixerIOProvider:
	BASE_URL = 'http://data.fixer.io/api'

	def __init__(self, api_key: str, client: httpx.AsyncClient | None = None, timeout: int = 10):
		self.api_key = api_key
		self._client = client or httpx.AsyncClient(timeout=timeout)

	@property
	def name(self) -> str:
		return 'fixerio'

	async def _request(self, endpoint: str, params: dict) -> dict:
		params['access_key'] = self.api_key
		url = f'{self.BASE_URL}/{endpoint}'

		try:
			response = await self._client.get(url, params=params)
			response.raise_for_status()
			data = response.json()

			if not data.get('success', False):
				info = data.get('error', {}).get('info', 'Unknown error')
				raise ProviderError(f'Fixer.io API error: {info}')

			return data

		except httpx.HTTPStatusError as e:
			raise ProviderError(
				f'Fixer.io HTTP error {e.response.status_code}: {e.response.text[:200]}'
			) from e
		except httpx.RequestError as e:
			raise ProviderError(f'Fixer.io request failed: {e.__class__.__name__}') from e
		except Exception as e:
			raise ProviderError(f'Fixer.io response parsing error: {str(e)}') from e

	async def fetch_rate(self, from_currency: str, to_currency: str) -> Decimal:
		data = await self._request('latest', {'base': from_currency, 'symbols': to_currency})
		try:
			return Decimal(str(data['rates'][to_currency]))
		except KeyError as e:
			raise ProviderError(f'Missing rate for {to_currency}') from e

	async def fetch_supported_currencies(self) -> list[dict]:
		data = await self._request('symbols', {})
		return [{'code': code, 'name': name} for code, name in data['symbols'].items()]

	async def close(self) -> None:
		await self._client.aclose()
